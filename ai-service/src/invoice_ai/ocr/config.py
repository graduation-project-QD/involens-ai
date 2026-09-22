"""Frozen PaddleOCR v1 configuration loader."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


OCR_VERSION = "t10_paddleocr_v1"


@dataclass(frozen=True)
class OcrConfig:
    schema_version: str
    ocr_version: str
    cache_version: str
    config_sha256: str
    language: str
    api_variant: str
    device: str
    paddlepaddle_version: str
    paddleocr_version: str
    paddlex_version: str
    cpu_threads: int
    enable_mkldnn: bool
    use_doc_orientation_classify: bool
    use_doc_unwarping: bool
    use_textline_orientation: bool
    text_rec_score_thresh: float
    require_utf8_runtime: bool
    detection_model_name: str
    recognition_model_name: str
    vertical_overlap_ratio: float
    score_semantics: str


def load_ocr_config(path: Path) -> OcrConfig:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("ocr_version") != OCR_VERSION:
        raise ValueError("Unsupported OCR version")
    engine = payload["engine"]
    models = payload["models"]
    order = payload["reading_order"]
    if payload.get("language") != "vi":
        raise ValueError("T10 v1 must use Vietnamese OCR semantics")
    expected = {
        "api_variant": "paddleocr_3_predict",
        "device": "cpu",
        "paddlepaddle_version": "3.3.0",
        "paddleocr_version": "3.7.0",
        "paddlex_version": "3.7.2",
    }
    for key, value in expected.items():
        if engine.get(key) != value:
            raise ValueError(f"T10 engine.{key} must remain {value}")
    if any(engine.get(key) for key in ("use_doc_orientation_classify", "use_doc_unwarping", "use_textline_orientation")):
        raise ValueError("T10 cannot enable implicit geometry transforms")
    if float(engine["text_rec_score_thresh"]) != 0.0:
        raise ValueError("T10 must preserve low-score OCR lines")
    if int(engine.get("cpu_threads", 0)) != 1:
        raise ValueError("T10 engine.cpu_threads must remain 1")
    if models.get("text_detection_model_name") != "PP-OCRv5_mobile_det":
        raise ValueError("Unexpected PaddleOCR detection model")
    if models.get("text_recognition_model_name") != "latin_PP-OCRv5_mobile_rec":
        raise ValueError("Unexpected PaddleOCR recognition model")
    overlap = float(order["vertical_overlap_ratio"])
    if not 0 < overlap <= 1:
        raise ValueError("reading_order.vertical_overlap_ratio must be within (0,1]")
    return OcrConfig(
        schema_version=str(payload["schema_version"]),
        ocr_version=str(payload["ocr_version"]),
        cache_version=str(payload["cache_version"]),
        config_sha256=hashlib.sha256(raw).hexdigest(),
        language=str(payload["language"]),
        api_variant=str(engine["api_variant"]),
        device=str(engine["device"]),
        paddlepaddle_version=str(engine["paddlepaddle_version"]),
        paddleocr_version=str(engine["paddleocr_version"]),
        paddlex_version=str(engine["paddlex_version"]),
        cpu_threads=int(engine["cpu_threads"]),
        enable_mkldnn=bool(engine["enable_mkldnn"]),
        use_doc_orientation_classify=bool(engine["use_doc_orientation_classify"]),
        use_doc_unwarping=bool(engine["use_doc_unwarping"]),
        use_textline_orientation=bool(engine["use_textline_orientation"]),
        text_rec_score_thresh=float(engine["text_rec_score_thresh"]),
        require_utf8_runtime=bool(engine["require_utf8_runtime"]),
        detection_model_name=str(models["text_detection_model_name"]),
        recognition_model_name=str(models["text_recognition_model_name"]),
        vertical_overlap_ratio=overlap,
        score_semantics=str(payload["score_semantics"]["description"]),
    )
