"""End-to-end inference for one receipt image, in memory, with the models loaded once.

Steps (each reuses the function that produced the evaluated test results, so outputs match them):

1. B4 orientation: ``OrientationModels.estimate`` on the decoded image → clockwise angle.
2. Upright image: ``build_upright.rotate_image``; a rotated page is re-encoded as JPEG q95 4:4:4, exactly
   as the evaluated upright images were stored (an unrotated page keeps its original bytes).
3. Detection: L960 pass → background crop rectangle → ``C1920_b0.2_t0.15`` (CPU, as in evaluation).
4. Crops (``rectified_crop``) read by the fine-tuned VietOCR; implausible readings are dropped
   (``plausible_text``) and lines are put in reading order.
5. Words and 0–1000 boxes: ``bio.align_document`` on a document without regions (character-width split).
6. LayoutXLM: ``encode_document`` windows, ``run_predict`` + ``documents`` (window merge).
7. B11: ``postprocess_document`` → ``PostprocessResult.to_contract(document_id)`` for the backend.

Errors are raised as ``PipelineError`` with a code (``IMAGE_DECODE_FAILED``, ``NO_TEXT_FOUND``,
``PROCESSING_FAILED``) that the worker maps to a ``status: 1`` result message.

Usage (batch over a folder, writes one backend message per image)::

    python -m invoice_ai.inference.pipeline --weights ../weights --paddlex-home ../paddlex \
        --images ../data/test_images --out ../runs/inference_test
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from invoice_ai.datasets.build_upright import JPEG_OPTIONS, rotate_image
from invoice_ai.kie.bio import OcrLineInput, align_document
from invoice_ai.kie.data import LabeledDocument
from invoice_ai.kie.geometry import bbox, order_rows
from invoice_ai.kie.postprocess import DocumentPrediction, PostprocessResult, postprocess_document
from invoice_ai.ocr.crops import rectified_crop
from invoice_ai.ocr.det_crops import DETECTION_CONFIG, plausible_text
from invoice_ai.ocr.detection_tuning import CROP_SOURCE, config_by_name, create_detector, crop_rectangle, detect

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "inference_pipeline_v1"
MAX_TOKENS = 512
WINDOW_OVERLAP = 128
MIN_CROP_SIDE = 4  # det_crops skips smaller crops
VIETOCR_BATCH = 32
LAYOUTXLM_BATCH = 16


class PipelineError(Exception):
    """A document that cannot be processed; ``code`` is reported to the backend in the failure message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PipelineResult:
    """B11 result of one document, the tagged words it came from, and what the steps observed."""

    result: PostprocessResult
    document: DocumentPrediction
    rotation_cw: float
    detected_boxes: int
    ocr_lines: int
    timings: dict[str, float] = field(default_factory=dict)

    def to_contract(self, document_id: str) -> dict[str, Any]:
        """Backend success message; ``rotation_applied`` and ``processing_ms`` are filled from this run."""
        message = self.result.to_contract(document_id, processing_ms=round(1000 * sum(self.timings.values())))
        message["data"]["image"]["rotation_applied"] = round(self.rotation_cw, 2)
        message["data"]["meta"]["pipeline_version"] = PIPELINE_VERSION
        return message


def decode_image(image_bytes: bytes) -> tuple[np.ndarray, bytes]:
    """Decodes the upload as RGB, applying an EXIF orientation tag if present.

    Returns the RGB pixels and the bytes that stand for the unrotated page (the original bytes, or a
    lossless PNG when EXIF had to be applied, so later steps never see a different orientation).
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            if image.getexif().get(274) not in (None, 1):
                logger.info("Applying EXIF orientation tag before B4")
                transposed = ImageOps.exif_transpose(image).convert("RGB")
                buffer = io.BytesIO()
                transposed.save(buffer, format="PNG")
                return np.asarray(transposed), buffer.getvalue()
            return np.asarray(image.convert("RGB")), image_bytes
    except (UnidentifiedImageError, OSError) as error:
        logger.warning("Image could not be decoded (%s)", type(error).__name__)
        raise PipelineError("IMAGE_DECODE_FAILED", "Không đọc được ảnh hóa đơn") from error


def upright_page(rgb: np.ndarray, page_bytes: bytes, angle_cw: float) -> bytes:
    """Encoded upright page: original bytes at 0°, otherwise the rotated pixels as JPEG q95 4:4:4 (as in B3/B4)."""
    from PIL import Image

    if angle_cw % 360 == 0:
        return page_bytes
    rotated, _ = rotate_image(rgb, angle_cw)
    buffer = io.BytesIO()
    Image.fromarray(rotated).save(buffer, format="JPEG", **JPEG_OPTIONS)
    return buffer.getvalue()


def reading_order_lines(boxes: Sequence[Sequence[Sequence[float]]], texts: Sequence[str], probs: Sequence[float]) -> list[OcrLineInput]:
    """Keeps readable boxes (non-empty, plausible for the box size) and orders them top-to-bottom, left-to-right."""
    kept = []
    for quad, text, prob in zip(boxes, texts, probs):
        polygon = [tuple(p) for p in quad]
        if not plausible_text(text, polygon):
            text = ""
        if text.strip():
            kept.append((polygon, text, prob))
    if not kept:
        return []
    order = [i for row in order_rows([bbox(polygon) for polygon, _, _ in kept]) for i in row]
    return [OcrLineInput(kept[i][1], tuple((float(x), float(y)) for x, y in kept[i][0]), kept[i][2]) for i in order]


class InvoicePipeline:
    """Loads every model once (B4 + detectors on CPU, VietOCR and LayoutXLM on ``device``) and processes images."""

    def __init__(
        self,
        weights_dir: Path,
        paddlex_home: Path,
        device: str | None = None,
        cpu_threads: int = 6,
        tokenizer: str = "microsoft/layoutxlm-base",
    ) -> None:
        import torch
        from transformers import LayoutLMv2ForTokenClassification, LayoutXLMTokenizerFast

        from invoice_ai.ocr.vietocr_finetune import load_predictor
        from invoice_ai.preprocessing.orientation import OrientationModels

        logger.info("Loading inference models. weights=%s, paddlex=%s", weights_dir, paddlex_home)
        start = time.perf_counter()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.orientation = OrientationModels(paddlex_home, cpu_threads=cpu_threads)
        self.crop_config, self.main_config = config_by_name(CROP_SOURCE), config_by_name(DETECTION_CONFIG)
        self.crop_detector = create_detector(self.crop_config, paddlex_home, cpu_threads)
        self.main_detector = create_detector(self.main_config, paddlex_home, cpu_threads)
        self.recognizer = load_predictor(Path(weights_dir) / "ft_vgg_transformer_20000.pth", "cuda:0" if self.device == "cuda" else "cpu")
        self.tokenizer = LayoutXLMTokenizerFast.from_pretrained(tokenizer)
        self.model = LayoutLMv2ForTokenClassification.from_pretrained(str(Path(weights_dir) / "layoutxlm_e2")).to(self.device).eval()
        use_bf16 = self.device == "cuda" and torch.cuda.is_bf16_supported()  # same autocast as train_layoutxlm.setup
        self.amp = (lambda: torch.autocast("cuda", dtype=torch.bfloat16)) if use_bf16 else _no_autocast
        logger.info("Inference models loaded. device=%s, seconds=%.1f", self.device, time.perf_counter() - start)

    def process(self, image_bytes: bytes, img_id: str = "document") -> PipelineResult:
        """Runs steps 1–7 on one image and returns the B11 result with step timings."""
        logger.info("Processing document. img_id=%s, bytes=%d", img_id, len(image_bytes))
        timings: dict[str, float] = {}
        try:
            clock = time.perf_counter()
            rgb, page_bytes = decode_image(image_bytes)
            # B4 was evaluated on the file decoded by OpenCV (orientation.read_bgr).
            page_bgr = cv2.imdecode(np.frombuffer(page_bytes, np.uint8), cv2.IMREAD_COLOR)
            angle = float(self.orientation.estimate(page_bgr).total_cw)
            upright_bytes = upright_page(rgb, page_bytes, angle)
            upright = cv2.imdecode(np.frombuffer(upright_bytes, np.uint8), cv2.IMREAD_COLOR)
            timings["orientation"] = time.perf_counter() - clock
            logger.info("Orientation decided. img_id=%s, rotation_cw=%.2f", img_id, angle)

            clock = time.perf_counter()
            height, width = upright.shape[:2]
            crop_pass = detect(self.crop_detector, upright)
            boxes = detect(self.main_detector, upright, crop_rectangle(self.main_config, crop_pass, width, height))["boxes"]
            timings["detection"] = time.perf_counter() - clock

            clock = time.perf_counter()
            lines = self.read_lines(upright, boxes)
            timings["recognition"] = time.perf_counter() - clock
            if not lines:
                logger.warning("No readable text. img_id=%s, boxes=%d", img_id, len(boxes))
                raise PipelineError("NO_TEXT_FOUND", "Không tìm thấy chữ trên ảnh hóa đơn")

            clock = time.perf_counter()
            document = self.tag_words(img_id, upright_bytes, lines, width, height)
            timings["layoutxlm"] = time.perf_counter() - clock

            clock = time.perf_counter()
            result = postprocess_document(document)
            timings["postprocess"] = time.perf_counter() - clock
        except PipelineError:
            raise
        except Exception as error:
            logger.error("Document processing failed. img_id=%s", img_id, exc_info=True)
            raise PipelineError("PROCESSING_FAILED", "Lỗi khi trích xuất hóa đơn") from error
        logger.info("Document processed. img_id=%s, words=%d, line_items=%d, needs_review=%s, seconds=%.2f",
                    img_id, len(document.words), len(result.line_items), result.needs_review, sum(timings.values()))
        return PipelineResult(result, document, angle, len(boxes), len(lines), {k: round(v, 3) for k, v in timings.items()})

    def read_lines(self, upright: np.ndarray, boxes: Sequence[Sequence[Sequence[float]]]) -> list[OcrLineInput]:
        """Crops every detector box, reads it with VietOCR in batches and returns the readable lines in reading order."""
        from PIL import Image

        kept_boxes, crops = [], []
        for quad in boxes:
            crop = rectified_crop(upright, [tuple(p) for p in quad])
            if crop is None or min(crop.shape[:2]) < MIN_CROP_SIDE:
                continue
            kept_boxes.append(quad)
            crops.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
        texts: list[str] = []
        probs: list[float] = []
        for start in range(0, len(crops), VIETOCR_BATCH):
            batch_texts, batch_probs = self.recognizer.predict_batch(crops[start : start + VIETOCR_BATCH], return_prob=True)
            texts.extend(batch_texts)
            probs.extend(round(float(p), 5) for p in batch_probs)
        logger.debug("Recognized crops. boxes=%d, crops=%d", len(boxes), len(crops))
        return reading_order_lines(kept_boxes, texts, probs)

    def tag_words(self, img_id: str, upright_bytes: bytes, lines: list[OcrLineInput], width: int, height: int) -> DocumentPrediction:
        """Splits lines into words (0–1000 boxes) and tags them with LayoutXLM, merging overlapping windows."""
        from PIL import Image

        from invoice_ai.kie.tokenize_layoutxlm import encode_document, model_image
        from invoice_ai.kie.train_layoutxlm import SampleDataset, documents, image_tensor, run_predict

        page = LabeledDocument(img_id, "inference", Path(img_id), width, height, 0, ())
        record = align_document(page, lines, ocr_frame="upright").to_dict()
        samples = encode_document(self.tokenizer, record, MAX_TOKENS, WINDOW_OVERLAP)
        for sample in samples:
            sample["image"] = img_id
        with Image.open(io.BytesIO(upright_bytes)) as image:
            tensor = image_tensor(model_image(image))
        dataset = SampleDataset(Path("."), samples, images={img_id: tensor})
        predicted = documents(samples, run_predict(self.model, dataset, LAYOUTXLM_BATCH, self.device, self.amp))[img_id]
        return DocumentPrediction(img_id, record["words"], record["boxes"], record["line_index"], predicted["pred"],
                                  predicted["score"], width, height)


def _no_autocast() -> Any:
    import contextlib

    return contextlib.nullcontext()


def run_folder(args: argparse.Namespace) -> None:
    """Processes every image of a folder: one backend message per image (``messages/``), plus ``words.jsonl`` and
    ``predictions.jsonl`` in the formats ``evaluate_e2e`` reads, and ``timings.jsonl``."""
    pipeline = InvoicePipeline(args.weights, args.paddlex_home, args.device, args.cpu_threads, args.tokenizer)
    (args.out / "messages").mkdir(parents=True, exist_ok=True)
    images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    logger.info("Batch inference started. images=%d", len(images))
    with (args.out / "words.jsonl").open("w", encoding="utf-8") as words, \
            (args.out / "predictions.jsonl").open("w", encoding="utf-8") as predictions, \
            (args.out / "timings.jsonl").open("w", encoding="utf-8") as times:
        for path in images:
            target = args.out / "messages" / f"{path.stem}.json"
            try:
                outcome = pipeline.process(path.read_bytes(), path.name)
            except PipelineError as error:
                message = {"status": 1, "error": {"code": error.code, "message": error.message, "retryable": False}, "data": {"id": path.stem}}
                target.write_text(json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8")
                continue
            target.write_text(json.dumps(outcome.to_contract(path.stem), ensure_ascii=False, indent=2), encoding="utf-8")
            doc = outcome.document
            words.write(json.dumps({"img_id": doc.img_id, "width": doc.width, "height": doc.height, "words": list(doc.words),
                                    "boxes": [list(b) for b in doc.boxes], "line_index": list(doc.line_index),
                                    "rotation_cw": outcome.rotation_cw}, ensure_ascii=False) + "\n")
            predictions.write(json.dumps({"img_id": doc.img_id, "pred": list(doc.tags), "score": list(doc.scores or [])}, ensure_ascii=False) + "\n")
            times.write(json.dumps({"img_id": doc.img_id, **outcome.timings, "boxes": outcome.detected_boxes, "lines": outcome.ocr_lines}) + "\n")
    logger.info("Batch inference completed. out=%s", args.out)


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", type=Path, required=True, help="folder with ft_vgg_transformer_20000.pth and layoutxlm_e2/")
    parser.add_argument("--paddlex-home", type=Path, required=True, help="folder holding official_models/ (PaddleOCR)")
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default=None, help="cuda or cpu (default: cuda when available)")
    parser.add_argument("--cpu-threads", type=int, default=6)
    parser.add_argument("--tokenizer", default="microsoft/layoutxlm-base")
    run_folder(parser.parse_args(argv))


if __name__ == "__main__":
    main()
