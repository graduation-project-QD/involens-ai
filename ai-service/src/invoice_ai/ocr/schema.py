"""Canonical OCR records shared by baseline, LayoutXLM and inference."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


class OcrError(RuntimeError):
    """OCR execution or engine output violates the frozen T10 contract."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class OcrRuntimeIdentity:
    paddlepaddle_version: str
    paddleocr_version: str
    paddlex_version: str
    detection_model_name: str
    recognition_model_name: str
    model_manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OCRLine:
    line_id: str
    engine_index: int
    reading_order: int
    text: str
    polygon_px: tuple[tuple[float, float], ...]
    bbox_xyxy_px: tuple[float, float, float, float]
    recognition_score: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "engine_index": self.engine_index,
            "reading_order": self.reading_order,
            "text": self.text,
            "polygon_px": [list(point) for point in self.polygon_px],
            "bbox_xyxy_px": list(self.bbox_xyxy_px),
            "recognition_score": self.recognition_score,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OCRLine":
        score = payload.get("recognition_score")
        return cls(
            line_id=str(payload["line_id"]),
            engine_index=int(payload["engine_index"]),
            reading_order=int(payload["reading_order"]),
            text=str(payload["text"]),
            polygon_px=tuple((float(point[0]), float(point[1])) for point in payload["polygon_px"]),
            bbox_xyxy_px=tuple(float(value) for value in payload["bbox_xyxy_px"]),  # type: ignore[arg-type]
            recognition_score=float(score) if score is not None else None,
        )


@dataclass(frozen=True)
class OCRPage:
    ocr_version: str
    status: str
    source_sha256: str
    pixel_sha256: str
    preprocessing_version: str
    width: int
    height: int
    lines: tuple[OCRLine, ...]
    latency_ms: float
    score_semantics: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in {"OK", "EMPTY"}:
            raise ValueError("OCRPage status must be OK or EMPTY")
        if self.status == "OK" and not self.lines:
            raise ValueError("OK OCRPage must contain lines")
        if self.status == "EMPTY" and self.lines:
            raise ValueError("EMPTY OCRPage cannot contain lines")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("OCR latency must be finite and non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ocr_version": self.ocr_version,
            "status": self.status,
            "source_sha256": self.source_sha256,
            "pixel_sha256": self.pixel_sha256,
            "preprocessing_version": self.preprocessing_version,
            "width": self.width,
            "height": self.height,
            "line_count": len(self.lines),
            "lines": [line.to_dict() for line in self.lines],
            "latency_ms": self.latency_ms,
            "score_semantics": self.score_semantics,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OCRPage":
        return cls(
            ocr_version=str(payload["ocr_version"]),
            status=str(payload["status"]),
            source_sha256=str(payload["source_sha256"]),
            pixel_sha256=str(payload["pixel_sha256"]),
            preprocessing_version=str(payload["preprocessing_version"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            lines=tuple(OCRLine.from_dict(item) for item in payload["lines"]),
            latency_ms=float(payload["latency_ms"]),
            score_semantics=str(payload["score_semantics"]),
            warnings=tuple(str(item) for item in payload.get("warnings", [])),
        )
