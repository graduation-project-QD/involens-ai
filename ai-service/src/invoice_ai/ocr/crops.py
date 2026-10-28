"""Text-line crops for recognition (GT regions for VietOCR training/evaluation, detection boxes at inference)."""

from __future__ import annotations

import unicodedata
from typing import Sequence

import cv2
import numpy as np

CROP_VERSION = "line_crop_v1"


def rectified_crop(image: np.ndarray, polygon: Sequence[tuple[float, float]], pad_y: float = 0.15, pad_x: float = 0.03) -> np.ndarray | None:
    """Perspective-rectified crop of a text line, read left to right, with relative padding.

    The polygon's minimum-area rectangle is used, so 4-point quads and hand-drawn polygons behave the
    same. ``pad_y`` (fraction of the line height, each side) keeps Vietnamese diacritics above/below.
    """
    points = np.asarray(polygon, dtype=np.float32)
    if len(points) < 3:
        return None
    (cx, cy), (w, h), angle = cv2.minAreaRect(points)
    if w < h:  # make the long side horizontal
        w, h, angle = h, w, angle - 90.0
    if w < 2 or h < 2:
        return None
    w, h = w * (1 + 2 * pad_x), h * (1 + 2 * pad_y)
    box = cv2.boxPoints(((cx, cy), (w, h), angle))
    by_x = box[np.argsort(box[:, 0])]
    left = by_x[:2][np.argsort(by_x[:2, 1])]
    right = by_x[2:][np.argsort(by_x[2:, 1])]
    source = np.array([left[0], right[0], right[1], left[1]], dtype=np.float32)
    width, height = int(round(w)), int(round(h))
    target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    return cv2.warpPerspective(
        image, cv2.getPerspectiveTransform(source, target), (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def normalize_ocr_text(text: str) -> str:
    """OCR scoring text: Unicode NFC and collapsed whitespace; case and diacritics are kept."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def edit_distance(reference: str, hypothesis: str) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref_char in enumerate(reference, 1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_char != hyp_char)))
        previous = current
    return previous[-1]
