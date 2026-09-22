"""PaddleOCR 3 adapter and deterministic canonical reading order."""

from __future__ import annotations

import importlib.metadata
import locale
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from invoice_ai.preprocessing import PageImage

from .config import OcrConfig
from .schema import OCRLine, OCRPage, OcrError, OcrRuntimeIdentity


def jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class OcrEngine(Protocol):
    def predict(self, page: PageImage) -> Any: ...


class PaddleOcrEngine:
    def __init__(self, config: OcrConfig, cache_root: Path) -> None:
        preferred = locale.getpreferredencoding(False).lower().replace("-", "")
        if config.require_utf8_runtime and sys.flags.utf8_mode != 1 and preferred not in {"utf8", "utf_8"}:
            raise OcrError(
                "OCR_UTF8_RUNTIME_REQUIRED",
                "PaddleOCR must start in UTF-8 mode to preserve Vietnamese characters",
                preferred_encoding=preferred,
                remedy="Set PYTHONUTF8=1 before starting Python",
            )
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_root))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        try:
            import numpy as np
            from paddleocr import PaddleOCR
        except Exception as error:
            raise OcrError("OCR_RUNTIME_UNAVAILABLE", "PaddleOCR runtime cannot be imported", error_type=type(error).__name__) from error
        actual_versions = {
            "paddlepaddle": importlib.metadata.version("paddlepaddle"),
            "paddleocr": importlib.metadata.version("paddleocr"),
            "paddlex": importlib.metadata.version("paddlex"),
        }
        expected_versions = {
            "paddlepaddle": config.paddlepaddle_version,
            "paddleocr": config.paddleocr_version,
            "paddlex": config.paddlex_version,
        }
        if actual_versions != expected_versions:
            raise OcrError("OCR_RUNTIME_VERSION_MISMATCH", "Installed OCR packages differ from T10 config", expected=expected_versions, actual=actual_versions)
        official = cache_root / "official_models"
        detection_dir = official / config.detection_model_name
        recognition_dir = official / config.recognition_model_name
        if not detection_dir.is_dir() or not recognition_dir.is_dir():
            raise OcrError("OCR_MODEL_MISSING", "Frozen PaddleOCR models are not present in the configured cache")
        self._np = np
        self._engine = PaddleOCR(
            text_detection_model_name=config.detection_model_name,
            text_detection_model_dir=str(detection_dir),
            text_recognition_model_name=config.recognition_model_name,
            text_recognition_model_dir=str(recognition_dir),
            device=config.device,
            cpu_threads=config.cpu_threads,
            enable_mkldnn=config.enable_mkldnn,
            use_doc_orientation_classify=config.use_doc_orientation_classify,
            use_doc_unwarping=config.use_doc_unwarping,
            use_textline_orientation=config.use_textline_orientation,
            text_rec_score_thresh=config.text_rec_score_thresh,
        )

    def predict(self, page: PageImage) -> Any:
        raw_results = list(self._engine.predict(input=self._np.asarray(page.image)))
        payloads: list[Any] = []
        for result in raw_results:
            payload = getattr(result, "json", result)
            if callable(payload):
                payload = payload()
            payloads.append(jsonable(payload))
        return payloads


@dataclass
class _Candidate:
    engine_index: int
    text: str
    polygon: tuple[tuple[float, float], ...]
    bbox: tuple[float, float, float, float]
    score: float | None


def _v3_nodes(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("rec_texts"), list):
            found.append(value)
        for item in value.values():
            found.extend(_v3_nodes(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_v3_nodes(item))
    return found


def _legacy_candidates(value: Any) -> list[tuple[Any, Any, Any]]:
    found: list[tuple[Any, Any, Any]] = []
    pages = value if isinstance(value, list) else []
    for page in pages:
        if not isinstance(page, list):
            continue
        for line in page:
            if isinstance(line, list) and len(line) == 2 and isinstance(line[1], (list, tuple)):
                recognition = line[1]
                text = recognition[0] if recognition else ""
                score = recognition[1] if len(recognition) > 1 else None
                found.append((line[0], text, score))
    return found


def _polygon(value: Any, size: tuple[int, int]) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        raise OcrError("OCR_OUTPUT_SCHEMA_ERROR", "OCR polygon must contain at least four points")
    points: list[tuple[float, float]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise OcrError("OCR_OUTPUT_SCHEMA_ERROR", "OCR polygon point must contain x and y")
        x, y = float(item[0]), float(item[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise OcrError("OCR_OUTPUT_SCHEMA_ERROR", "OCR polygon contains non-finite coordinates")
        if not -1e-5 <= x <= size[0] + 1e-5 or not -1e-5 <= y <= size[1] + 1e-5:
            raise OcrError("OCR_OUTPUT_OUT_OF_BOUNDS", "OCR polygon lies outside PageImage", point=[x, y], size=list(size))
        points.append((min(max(x, 0.0), float(size[0])), min(max(y, 0.0), float(size[1]))))
    return tuple(points)


def _bbox(polygon: tuple[tuple[float, float], ...]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    result = (min(xs), min(ys), max(xs), max(ys))
    if result[0] >= result[2] or result[1] >= result[3]:
        raise OcrError("OCR_OUTPUT_SCHEMA_ERROR", "OCR polygon has zero-area bounding box")
    return result


def _score(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise OcrError("OCR_OUTPUT_SCHEMA_ERROR", "Recognition score must be finite within [0,1]", score=value)
    return result


def _parse_candidates(raw: Any, size: tuple[int, int]) -> tuple[list[_Candidate], int]:
    candidates: list[_Candidate] = []
    empty_text_detections = 0
    nodes = _v3_nodes(raw)
    engine_index = 0
    if nodes:
        for node in nodes:
            texts = node["rec_texts"]
            polygons = node.get("dt_polys")
            if polygons is None:
                polygons = node.get("rec_polys")
            scores = node.get("rec_scores")
            if not isinstance(polygons, list) or len(polygons) != len(texts):
                raise OcrError("OCR_OUTPUT_SCHEMA_ERROR", "PaddleOCR text and polygon counts differ")
            if scores is not None and (not isinstance(scores, list) or len(scores) != len(texts)):
                raise OcrError("OCR_OUTPUT_SCHEMA_ERROR", "PaddleOCR text and score counts differ")
            for offset, text_value in enumerate(texts):
                text = str(text_value)
                if "\ufffd" in text:
                    raise OcrError("OCR_UNICODE_REPLACEMENT_DETECTED", "OCR text contains a Unicode replacement character")
                if not text.strip():
                    empty_text_detections += 1
                    engine_index += 1
                    continue
                polygon = _polygon(polygons[offset], size)
                candidates.append(_Candidate(engine_index, text, polygon, _bbox(polygon), _score(scores[offset] if scores is not None else None)))
                engine_index += 1
        return candidates, empty_text_detections
    for polygon_value, text_value, score_value in _legacy_candidates(raw):
        text = str(text_value)
        if "\ufffd" in text:
            raise OcrError("OCR_UNICODE_REPLACEMENT_DETECTED", "OCR text contains a Unicode replacement character")
        if not text.strip():
            empty_text_detections += 1
            engine_index += 1
            continue
        polygon = _polygon(polygon_value, size)
        candidates.append(_Candidate(engine_index, text, polygon, _bbox(polygon), _score(score_value)))
        engine_index += 1
    return candidates, empty_text_detections


def _reading_order(candidates: list[_Candidate], overlap_threshold: float) -> list[_Candidate]:
    rows: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: ((item.bbox[1] + item.bbox[3]) / 2, item.bbox[0], item.engine_index)):
        height = candidate.bbox[3] - candidate.bbox[1]
        best_index: int | None = None
        best_overlap = -1.0
        for index, row in enumerate(rows):
            overlap = max(0.0, min(candidate.bbox[3], row["bottom"]) - max(candidate.bbox[1], row["top"]))
            ratio = overlap / min(height, row["bottom"] - row["top"])
            if ratio >= overlap_threshold and ratio > best_overlap:
                best_index, best_overlap = index, ratio
        if best_index is None:
            rows.append({"top": candidate.bbox[1], "bottom": candidate.bbox[3], "items": [candidate]})
        else:
            row = rows[best_index]
            row["top"] = min(row["top"], candidate.bbox[1])
            row["bottom"] = max(row["bottom"], candidate.bbox[3])
            row["items"].append(candidate)
    ordered: list[_Candidate] = []
    for row in sorted(rows, key=lambda item: (item["top"], min(value.bbox[0] for value in item["items"]))):
        ordered.extend(sorted(row["items"], key=lambda item: (item.bbox[0], item.bbox[1], item.engine_index)))
    return ordered


def canonicalize_engine_output(
    raw: Any,
    page: PageImage,
    config: OcrConfig,
    *,
    latency_ms: float,
) -> OCRPage:
    candidates, empty_text_detections = _parse_candidates(raw, page.image.size)
    ordered = _reading_order(candidates, config.vertical_overlap_ratio)
    warnings: list[str] = []
    if empty_text_detections:
        warnings.append(f"EMPTY_TEXT_DETECTIONS:{empty_text_detections}")
    if any(candidate.score is None for candidate in ordered):
        warnings.append("NULL_RECOGNITION_SCORE_PRESENT")
    lines = tuple(
        OCRLine(
            line_id=f"ocr_line_{candidate.engine_index:04d}",
            engine_index=candidate.engine_index,
            reading_order=index,
            text=candidate.text,
            polygon_px=candidate.polygon,
            bbox_xyxy_px=candidate.bbox,
            recognition_score=candidate.score,
        )
        for index, candidate in enumerate(ordered)
    )
    return OCRPage(
        ocr_version=config.ocr_version,
        status="OK" if lines else "EMPTY",
        source_sha256=page.source_sha256,
        pixel_sha256=page.pixel_sha256,
        preprocessing_version=page.pipeline_version,
        width=page.image.width,
        height=page.image.height,
        lines=lines,
        latency_ms=latency_ms,
        score_semantics=config.score_semantics,
        warnings=tuple(warnings),
    )


def extract_ocr(
    page: PageImage,
    config: OcrConfig,
    identity: OcrRuntimeIdentity,
    engine: OcrEngine,
) -> tuple[OCRPage, Any]:
    del identity  # Included in cache identity; engine output parsing is model-agnostic.
    started = time.perf_counter()
    try:
        raw = jsonable(engine.predict(page))
    except OcrError:
        raise
    except Exception as error:
        raise OcrError("OCR_ENGINE_FAILURE", "PaddleOCR inference failed", error_type=type(error).__name__) from error
    latency_ms = (time.perf_counter() - started) * 1000
    return canonicalize_engine_output(raw, page, config, latency_ms=latency_ms), raw
