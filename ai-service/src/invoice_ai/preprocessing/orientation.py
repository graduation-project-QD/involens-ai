"""B4: automatic page orientation (0/90/180/270) and small-angle deskew.

Stages, all returning angles in the labeler convention (degrees clockwise to make the page upright):

1. ``PP-LCNet_x1_0_doc_ori`` classifies the coarse orientation. Its label is the counter-clockwise
   rotation of the page, so ``coarse_cw = (360 - label) % 360``.
2. ``PP-OCRv5_mobile_det`` runs on the coarse-rotated page; the length-weighted median angle of long,
   thin text boxes is the residual skew. Rotating by ``-skew`` levels the text.
3. Flip check: on this dataset the classifier's only errors are 180° flips (small receipts on busy
   backgrounds). The longest text lines are recognised as-is and rotated by 180°; if the rotated
   reading is clearly more confident, 180° is added.

Model inference (``OrientationModels.observe``) is separated from the decision (``decide``) so the
decision rule can be tuned on cached observations without re-running the models.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

ORIENTATION_VERSION = "orientation_v1"
RIGHT_ANGLE_OPS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


@dataclass(frozen=True)
class DeskewParams:
    # Defaults chosen on train only (2026-10-10 sweep, experiments/reports/orientation_v1_2026-10-10).
    min_aspect: float = 2.0  # box length / thickness
    min_length_px: float = 30.0
    min_boxes: int = 3
    max_abs_skew: float = 20.0
    min_abs_skew: float = 1.0  # below this the page is left untouched
    flip_margin: float | None = 0.1  # None disables the recognition flip check


@dataclass(frozen=True)
class Observation:
    coarse_label: int  # classifier label (counter-clockwise degrees)
    coarse_score: float
    boxes: tuple[tuple[tuple[float, float], ...], ...]  # det quads on the coarse-rotated page
    box_scores: tuple[float, ...]
    # Recognition scores of the longest lines as-is / rotated 180° (one pair per line), if checked.
    flip_pairs: tuple[tuple[float, float], ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "coarse_label": self.coarse_label,
            "coarse_score": self.coarse_score,
            "boxes": [[[round(x, 1), round(y, 1)] for x, y in quad] for quad in self.boxes],
            "box_scores": [round(s, 4) for s in self.box_scores],
        }
        if self.flip_pairs is not None:
            payload["flip_pairs"] = [[round(a, 4), round(b, 4)] for a, b in self.flip_pairs]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Observation":
        pairs = payload.get("flip_pairs")
        return cls(
            int(payload["coarse_label"]),
            float(payload["coarse_score"]),
            tuple(tuple((float(x), float(y)) for x, y in quad) for quad in payload["boxes"]),
            tuple(float(s) for s in payload["box_scores"]),
            tuple((float(a), float(b)) for a, b in pairs) if pairs is not None else None,
        )


@dataclass(frozen=True)
class OrientationResult:
    coarse_cw: int
    coarse_score: float
    skew_deg: float  # measured text tilt after the coarse rotation, clockwise positive
    total_cw: float  # rotation_to_upright estimate in [0, 360)
    boxes_used: int
    flipped: bool = False  # 180° added by the recognition flip check
    orientation_version: str = ORIENTATION_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rotate_right_angle(image: np.ndarray, angle_cw: int) -> np.ndarray:
    angle = angle_cw % 360
    return image if angle == 0 else cv2.rotate(image, RIGHT_ANGLE_OPS[angle])


def text_skew(boxes: Sequence[Sequence[tuple[float, float]]], params: DeskewParams = DeskewParams()) -> tuple[float, int]:
    """Length-weighted median tilt of long text boxes (degrees, clockwise positive in image coordinates)."""
    angles: list[tuple[float, float]] = []
    for quad in boxes:
        (_, _), (w, h), angle = cv2.minAreaRect(np.asarray(quad, dtype=np.float32))
        length, thickness = max(w, h), min(w, h)
        if thickness <= 0 or length < params.min_length_px or length / thickness < params.min_aspect:
            continue
        # Direction of the long side, folded into (-90, 90].
        theta = angle if w >= h else angle - 90.0
        while theta <= -90.0:
            theta += 180.0
        while theta > 90.0:
            theta -= 180.0
        if abs(theta) <= 45.0:  # vertical boxes are not horizontal text lines
            angles.append((theta, length))
    if len(angles) < params.min_boxes:
        return 0.0, len(angles)
    angles.sort()
    half, cumulative = sum(w for _, w in angles) / 2, 0.0
    for theta, weight in angles:
        cumulative += weight
        if cumulative >= half:
            return theta, len(angles)
    return angles[-1][0], len(angles)


def flip_gain(pairs: Sequence[tuple[float, float]]) -> float:
    """Mean recognition-score gain from rotating the lines by 180° (positive: rotated reads better)."""
    return sum(b - a for a, b in pairs) / len(pairs) if pairs else 0.0


def decide(observation: Observation, params: DeskewParams = DeskewParams()) -> OrientationResult:
    coarse_cw = (360 - observation.coarse_label) % 360
    flipped = bool(
        params.flip_margin is not None and observation.flip_pairs and flip_gain(observation.flip_pairs) > params.flip_margin
    )
    if flipped:
        coarse_cw = (coarse_cw + 180) % 360
    skew, used = text_skew(observation.boxes, params)  # a 180° turn does not change a line's tilt
    if abs(skew) > params.max_abs_skew or abs(skew) < params.min_abs_skew:
        skew = 0.0
    total = (coarse_cw - skew) % 360.0
    return OrientationResult(coarse_cw, observation.coarse_score, round(skew, 2), round(total, 2), used, flipped)


def angular_error(predicted: float, truth: float) -> float:
    difference = (predicted - truth) % 360.0
    return min(difference, 360.0 - difference)


def longest_line_crops(
    image: np.ndarray,
    boxes: Sequence[Sequence[tuple[float, float]]],
    limit: int,
    min_aspect: float = 3.0,
    max_aspect: float = 12.0,
) -> list[np.ndarray]:
    """Rectified crops of the ``limit`` longest horizontal-ish text lines.

    Each crop keeps at most ``max_aspect`` x its height from the left, which is enough text for the
    flip check and keeps recognition cheap on CPU.
    """
    candidates = []
    for quad in boxes:
        rect = cv2.minAreaRect(np.asarray(quad, dtype=np.float32))
        (_, _), (w, h), _ = rect
        length, thickness = max(w, h), min(w, h)
        if thickness >= 4 and length / thickness >= min_aspect:
            candidates.append((length, rect))
    crops = []
    for _, rect in sorted(candidates, key=lambda c: -c[0])[:limit]:
        points = cv2.boxPoints(rect)
        by_x = points[np.argsort(points[:, 0])]
        left = by_x[:2][np.argsort(by_x[:2, 1])]
        right = by_x[2:][np.argsort(by_x[2:, 1])]
        source = np.array([left[0], right[0], right[1], left[1]], dtype=np.float32)
        width = int(round(float(np.linalg.norm(source[1] - source[0]))))
        height = int(round(float(np.linalg.norm(source[3] - source[0]))))
        if width < 8 or height < 4:
            continue
        target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
        crop = cv2.warpPerspective(image, cv2.getPerspectiveTransform(source, target), (width, height))
        crops.append(crop[:, : int(max_aspect * height)])
    return crops


def read_bgr(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode {path}")
    return image


class OrientationModels:
    """Loads the PaddleOCR models once. Needs the T10 OCR environment (PaddleOCR 3.7 / Paddle 3.3)."""

    def __init__(
        self,
        paddlex_home: Path,
        cpu_threads: int = 6,
        detection_model: str = "PP-OCRv5_mobile_det",
        recognition_model: str = "latin_PP-OCRv5_mobile_rec",
        flip_lines: int = 3,
    ) -> None:
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddlex_home))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import DocImgOrientationClassification, TextDetection, TextRecognition

        models = Path(paddlex_home) / "official_models"
        self.classifier = DocImgOrientationClassification(
            model_name="PP-LCNet_x1_0_doc_ori", device="cpu", cpu_threads=cpu_threads, enable_mkldnn=True
        )
        # oneDNN cannot run the PIR detection/recognition graphs on this Paddle build (same finding as T05).
        self.detector = TextDetection(
            model_name=detection_model, model_dir=str(models / detection_model), device="cpu", cpu_threads=cpu_threads, enable_mkldnn=False
        )
        self.recognizer = TextRecognition(
            model_name=recognition_model, model_dir=str(models / recognition_model), device="cpu", cpu_threads=cpu_threads, enable_mkldnn=False
        )
        self.flip_lines = flip_lines

    def flip_pairs(self, upright: np.ndarray, boxes: Sequence[Sequence[tuple[float, float]]]) -> tuple[tuple[float, float], ...]:
        crops = longest_line_crops(upright, boxes, self.flip_lines)
        if not crops:
            return ()
        batch = crops + [cv2.rotate(c, cv2.ROTATE_180) for c in crops]
        scores = [float(r["rec_score"]) for r in self.recognizer.predict(batch)]
        return tuple(zip(scores[: len(crops)], scores[len(crops) :]))

    def observe(self, image_bgr: np.ndarray) -> Observation:
        result = list(self.classifier.predict(image_bgr))[0]
        label, score = int(result["label_names"][0]), float(result["scores"][0])
        upright = rotate_right_angle(image_bgr, (360 - label) % 360)
        detection = list(self.detector.predict(upright))[0]
        boxes = tuple(tuple((float(x), float(y)) for x, y in quad) for quad in np.asarray(detection["dt_polys"]).tolist())
        scores = tuple(float(s) for s in detection["dt_scores"])
        return Observation(label, score, boxes, scores, self.flip_pairs(upright, boxes))

    def estimate(self, image_bgr: np.ndarray, params: DeskewParams = DeskewParams()) -> OrientationResult:
        """Pipeline entry point: ``total_cw`` is the clockwise rotation that makes the page upright."""
        return decide(self.observe(image_bgr), params)

    def add_flip_check(self, image_bgr: np.ndarray, observation: Observation) -> Observation:
        """Complete an older observation (without ``flip_pairs``) without re-running the detector."""
        upright = rotate_right_angle(image_bgr, (360 - observation.coarse_label) % 360)
        return Observation(
            observation.coarse_label, observation.coarse_score, observation.boxes, observation.box_scores, self.flip_pairs(upright, observation.boxes)
        )
