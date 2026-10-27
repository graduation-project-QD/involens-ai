"""Recognition-only CER on GT crops, per label (B5 reference for PaddleOCR rec; B7 reuses it for VietOCR).

Corpus CER = total edit distance / total GT characters after ``normalize_ocr_text`` (NFC, collapsed
whitespace, case and diacritics kept). Also reports CER without diacritics to show how much of the
error is lost tone/vowel marks.

    PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.ocr.recognition_eval paddle \
        --dataset ../dataset_hoadon/dataset_upright_v1 --split val --paddlex-home ../.cache/paddlex \
        --models latin_PP-OCRv5_mobile_rec PP-OCRv6_medium_rec --report ../experiments/reports/detection_v1_2026-10-11
"""

from __future__ import annotations

import argparse
import json
import os
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Sequence

from invoice_ai.kie.data import load_split
from invoice_ai.kie.labels import SEMANTIC_LABELS
from invoice_ai.ocr.crops import CROP_VERSION, edit_distance, normalize_ocr_text, rectified_crop


def strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def gt_crops(dataset: Path, split: str) -> list[dict[str, Any]]:
    from invoice_ai.preprocessing.orientation import read_bgr

    items = []
    for document in load_split(dataset, split):
        if document.rotation_cw % 360:
            raise ValueError("recognition evaluation expects the upright dataset (rotation 0)")
        image = read_bgr(document.image_path)
        for region in document.regions:
            crop = rectified_crop(image, region.polygon)
            if crop is not None and region.text.strip():
                items.append({"img_id": document.img_id, "label": region.label, "text": region.text, "crop": crop})
    return items


def score(items: Sequence[dict[str, Any]], predictions: Sequence[str]) -> dict[str, Any]:
    totals: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"chars": 0, "edits": 0, "edits_no_marks": 0, "exact": 0, "n": 0})
    for item, prediction in zip(items, predictions):
        reference, hypothesis = normalize_ocr_text(item["text"]), normalize_ocr_text(prediction)
        for key in (item["label"], "ALL"):
            t = totals[key]
            t["chars"] += len(reference)
            t["edits"] += edit_distance(reference, hypothesis)
            t["edits_no_marks"] += edit_distance(strip_marks(reference), strip_marks(hypothesis))
            t["exact"] += reference == hypothesis
            t["n"] += 1
    result = {}
    for key in list(SEMANTIC_LABELS) + ["ALL"]:
        t = totals[key]
        if t["n"]:
            result[key] = {
                "regions": t["n"],
                "cer": round(t["edits"] / t["chars"], 4),
                "cer_without_diacritics": round(t["edits_no_marks"] / t["chars"], 4),
                "exact_rate": round(t["exact"] / t["n"], 4),
            }
    return result


def evaluate_recognizer(items: Sequence[dict[str, Any]], recognize: Callable[[list[Any]], list[str]], batch: int = 32) -> tuple[dict[str, Any], float]:
    predictions: list[str] = []
    start = time.perf_counter()
    for i in range(0, len(items), batch):
        predictions.extend(recognize([it["crop"] for it in items[i : i + batch]]))
    return score(items, predictions), (time.perf_counter() - start) / max(1, len(items))


def paddle(args: argparse.Namespace) -> None:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(args.paddlex_home))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import TextRecognition

    items = gt_crops(args.dataset, args.split)
    report: dict[str, Any] = {"split": args.split, "crop_version": CROP_VERSION, "crops": len(items), "models": {}}
    for name in args.models:
        model = TextRecognition(
            model_name=name, model_dir=str(Path(args.paddlex_home) / "official_models" / name), device="cpu", cpu_threads=args.cpu_threads, enable_mkldnn=False
        )

        def recognize(crops: list[Any]) -> list[str]:
            return [str(r["rec_text"]) for r in model.predict(crops, batch_size=1)]

        metrics, seconds = evaluate_recognizer(items, recognize)
        report["models"][f"paddle/{name}"] = {"seconds_per_crop": round(seconds, 4), "by_label": metrics}
        print(name, json.dumps(metrics["ALL"]), f"{seconds:.3f}s/crop", flush=True)
    args.report.mkdir(parents=True, exist_ok=True)
    (args.report / f"recognition_reference_{args.split}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("paddle")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--split", default="val")
    p.add_argument("--paddlex-home", type=Path, required=True)
    p.add_argument("--models", nargs="+", default=["latin_PP-OCRv5_mobile_rec"])
    p.add_argument("--cpu-threads", type=int, default=10)
    p.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    paddle(args)


if __name__ == "__main__":
    main()
