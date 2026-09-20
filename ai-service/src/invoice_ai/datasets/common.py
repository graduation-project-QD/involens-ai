"""Shared, side-effect-free helpers for dataset conversion."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image


class AnnotationError(ValueError):
    """Raised when a source annotation cannot be represented safely."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_metadata(path: Path) -> tuple[int, int, str]:
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
    except Exception as exc:  # Pillow exposes several decoder exception classes.
        raise AnnotationError("IMAGE_DECODE_ERROR", str(exc), path=str(path)) from exc
    return width, height, sha256_file(path)


def read_utf8_strict(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AnnotationError(
            "NON_UTF8_ANNOTATION",
            f"Annotation is not valid UTF-8: {path}",
            path=str(path),
            byte_start=exc.start,
            byte_end=exc.end,
        ) from exc


def read_json_object(path: Path) -> dict[str, Any]:
    text = read_utf8_strict(path)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnnotationError("INVALID_JSON", str(exc), path=str(path)) from exc
    if not isinstance(value, dict):
        raise AnnotationError("INVALID_JSON_ROOT", "Expected a JSON object", path=str(path))
    return value


def polygon_bbox(polygon: list[float], width: int, height: int) -> tuple[list[list[float]], list[float]]:
    if len(polygon) < 6 or len(polygon) % 2:
        raise AnnotationError("INVALID_POLYGON", "Polygon must contain at least three points")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in polygon):
        raise AnnotationError("NONFINITE_COORDINATE", "Polygon contains a non-finite coordinate")
    points = [[float(polygon[index]), float(polygon[index + 1])] for index in range(0, len(polygon), 2)]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    if min(xs) < 0 or min(ys) < 0 or max(xs) > width or max(ys) > height:
        raise AnnotationError(
            "POLYGON_OUT_OF_IMAGE",
            "Polygon extends outside the source image",
            polygon=polygon,
            image_size=[width, height],
        )
    twice_area = abs(
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
    )
    if twice_area == 0:
        raise AnnotationError("DEGENERATE_POLYGON", "Polygon has zero area", polygon=polygon)
    return points, [min(xs), min(ys), max(xs), max(ys)]
