"""T08 train-only, deterministic augmentation composed after T07."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter

from .core import IDENTITY, Matrix, PageImage, TransformChain, TransformStep

AUGMENTATION_VERSION = "t08_augmentation_v1"


class AugmentationError(ValueError):
    """Augmentation request violates the frozen train-only policy."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class AugmentationConfig:
    schema_version: str
    augmentation_version: str
    config_sha256: str
    enabled: bool
    seed: int
    allowed_splits: tuple[str, ...]
    mode: str
    operation_order: tuple[str, ...]
    rotation_enabled: bool
    rotation_probability: float
    rotation_degrees: tuple[float, float]
    rotation_expand_canvas: bool
    rotation_fill_rgb: tuple[int, int, int]
    brightness_enabled: bool
    brightness_probability: float
    brightness_factor: tuple[float, float]
    blur_enabled: bool
    blur_probability: float
    blur_radius: tuple[float, float]
    rerun_ocr: bool
    claim_ocr_robustness: bool
    baseline_cache_must_remain_separate: bool
    activation_gate: str


@dataclass
class AugmentedPageImage:
    image: Image.Image
    transform: TransformChain
    source_sha256: str
    document_id: str
    split: str
    derived_seed: int
    augmentation_version: str
    config_sha256: str
    mode: str
    status: str
    operations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def pixel_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.image.mode.encode("ascii"))
        digest.update(f"{self.image.width}x{self.image.height}".encode("ascii"))
        digest.update(self.image.tobytes())
        return digest.hexdigest()

    @property
    def cache_namespace(self) -> str:
        return hashlib.sha256(
            f"{self.source_sha256}:{self.augmentation_version}:{self.config_sha256}:{self.derived_seed}".encode("utf-8")
        ).hexdigest()

    def to_manifest(self) -> dict[str, Any]:
        return {
            "augmentation_version": self.augmentation_version,
            "config_sha256": self.config_sha256,
            "document_id": self.document_id,
            "split": self.split,
            "derived_seed": self.derived_seed,
            "mode": self.mode,
            "status": self.status,
            "operations": self.operations,
            "warnings": self.warnings,
            "source_sha256": self.source_sha256,
            "pixel_sha256": self.pixel_sha256,
            "cache_namespace": self.cache_namespace,
            "transform": self.transform.to_dict(),
        }


def _pair(payload: dict[str, Any], key: str) -> tuple[float, float]:
    values = payload[key]
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError(f"{key} must contain [minimum, maximum]")
    result = (float(values[0]), float(values[1]))
    if not all(math.isfinite(value) for value in result) or result[0] > result[1]:
        raise ValueError(f"{key} range is invalid")
    return result


def _probability(value: Any, key: str) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"{key} must be within [0,1]")
    return result


def load_augmentation_config(path: Path) -> AugmentationConfig:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("augmentation_version") != AUGMENTATION_VERSION:
        raise ValueError("Unsupported augmentation version")
    if payload.get("allowed_splits") != ["train"]:
        raise ValueError("T08 augmentation must be train-only")
    if payload.get("operation_order") != ["rotation", "brightness", "blur"]:
        raise ValueError("T08 operation order is frozen")
    rotation = payload["rotation"]
    brightness = payload["brightness"]
    blur = payload["blur"]
    ocr_policy = payload["ocr_policy"]
    degrees = _pair(rotation, "degrees")
    if degrees[0] < -3 or degrees[1] > 3:
        raise ValueError("T08 rotation must remain within ±3 degrees")
    if not rotation.get("expand_canvas"):
        raise ValueError("T08 rotation must expand the canvas to avoid entity crop")
    if rotation.get("resample") != "BICUBIC":
        raise ValueError("T08 rotation resampling must be BICUBIC")
    fill = tuple(rotation["fill_rgb"])
    if len(fill) != 3 or any(not isinstance(value, int) or not 0 <= value <= 255 for value in fill):
        raise ValueError("rotation.fill_rgb must contain three bytes")
    if ocr_policy.get("rerun_ocr") or ocr_policy.get("claim_ocr_robustness"):
        raise ValueError("T08 v1 cannot enable OCR claims before the T10 ablation")
    return AugmentationConfig(
        schema_version=payload["schema_version"],
        augmentation_version=payload["augmentation_version"],
        config_sha256=hashlib.sha256(raw).hexdigest(),
        enabled=bool(payload["enabled"]),
        seed=int(payload["seed"]),
        allowed_splits=tuple(payload["allowed_splits"]),
        mode=payload["mode"],
        operation_order=tuple(payload["operation_order"]),
        rotation_enabled=bool(rotation["enabled"]),
        rotation_probability=_probability(rotation["probability"], "rotation.probability"),
        rotation_degrees=degrees,
        rotation_expand_canvas=bool(rotation["expand_canvas"]),
        rotation_fill_rgb=fill,  # type: ignore[arg-type]
        brightness_enabled=bool(brightness["enabled"]),
        brightness_probability=_probability(brightness["probability"], "brightness.probability"),
        brightness_factor=_pair(brightness, "factor"),
        blur_enabled=bool(blur["enabled"]),
        blur_probability=_probability(blur["probability"], "blur.probability"),
        blur_radius=_pair(blur, "radius"),
        rerun_ocr=bool(ocr_policy["rerun_ocr"]),
        claim_ocr_robustness=bool(ocr_policy["claim_ocr_robustness"]),
        baseline_cache_must_remain_separate=bool(ocr_policy["baseline_cache_must_remain_separate"]),
        activation_gate=ocr_policy["activation_gate"],
    )


def _inverse_affine(matrix: Matrix) -> Matrix:
    a, b, c, d, e, f, g, h, i = matrix
    if (g, h, i) != (0, 0, 1):
        raise ValueError("T08 only supports affine transforms")
    determinant = a * e - b * d
    if abs(determinant) < 1e-15:
        raise ValueError("Augmentation transform is singular")
    return (
        e / determinant,
        -b / determinant,
        (b * f - e * c) / determinant,
        -d / determinant,
        a / determinant,
        (d * c - a * f) / determinant,
        0,
        0,
        1,
    )


def _apply(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    return (
        matrix[0] * x + matrix[1] * y + matrix[2],
        matrix[3] * x + matrix[4] * y + matrix[5],
    )


def _rotation_step(size: tuple[int, int], clockwise_degrees: float) -> TransformStep:
    width, height = size
    radians = math.radians(clockwise_degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    center_x = width / 2
    center_y = height / 2
    centered: Matrix = (
        cosine,
        -sine,
        center_x - cosine * center_x + sine * center_y,
        sine,
        cosine,
        center_y - sine * center_x - cosine * center_y,
        0,
        0,
        1,
    )
    corners = [_apply(centered, x, y) for x, y in ((0, 0), (width, 0), (width, height), (0, height))]
    min_x = min(point[0] for point in corners)
    min_y = min(point[1] for point in corners)
    max_x = max(point[0] for point in corners)
    max_y = max(point[1] for point in corners)
    output_size = (max(1, math.ceil(max_x - min_x)), max(1, math.ceil(max_y - min_y)))
    forward: Matrix = (
        centered[0], centered[1], centered[2] - min_x,
        centered[3], centered[4], centered[5] - min_y,
        0, 0, 1,
    )
    return TransformStep(
        name="augmentation_rotation",
        input_size=size,
        output_size=output_size,
        forward_matrix=forward,
        inverse_matrix=_inverse_affine(forward),
        parameters={"clockwise_degrees": clockwise_degrees, "expand_canvas": True},
    )


def _derived_seed(config: AugmentationConfig, document_id: str, source_sha256: str) -> int:
    digest = hashlib.sha256(
        f"{config.seed}:{document_id}:{source_sha256}:{config.augmentation_version}:{config.config_sha256}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def augment_page(
    page: PageImage,
    config: AugmentationConfig,
    *,
    document_id: str,
    split: str,
    allow_disabled_preview: bool = False,
) -> AugmentedPageImage:
    if split not in config.allowed_splits:
        raise AugmentationError("SPLIT_NOT_ALLOWED", "Augmentation is restricted to train", split=split)
    seed = _derived_seed(config, document_id, page.source_sha256)
    if not config.enabled and not allow_disabled_preview:
        return AugmentedPageImage(
            image=page.image.copy(),
            transform=page.transform,
            source_sha256=page.source_sha256,
            document_id=document_id,
            split=split,
            derived_seed=seed,
            augmentation_version=config.augmentation_version,
            config_sha256=config.config_sha256,
            mode=config.mode,
            status="SKIPPED_DISABLED",
            operations=[],
            warnings=["AUGMENTATION_DISABLED_PENDING_T10_T18_ABLATION"],
        )

    rng = random.Random(seed)
    image = page.image.copy()
    steps = list(page.transform.steps)
    operations: list[dict[str, Any]] = []

    rotation_applied = config.rotation_enabled and rng.random() < config.rotation_probability
    if rotation_applied:
        angle = rng.uniform(*config.rotation_degrees)
        step = _rotation_step(image.size, angle)
        inverse = step.inverse_matrix
        image = image.transform(
            step.output_size,
            Image.Transform.AFFINE,
            inverse[:6],
            resample=Image.Resampling.BICUBIC,
            fillcolor=config.rotation_fill_rgb,
        )
        steps.append(step)
        operations.append({"name": "rotation", "applied": True, "clockwise_degrees": angle})
    else:
        operations.append({"name": "rotation", "applied": False})

    brightness_applied = config.brightness_enabled and rng.random() < config.brightness_probability
    if brightness_applied:
        factor = rng.uniform(*config.brightness_factor)
        image = ImageEnhance.Brightness(image).enhance(factor)
        steps.append(TransformStep(
            name="augmentation_brightness",
            input_size=image.size,
            output_size=image.size,
            forward_matrix=IDENTITY,
            inverse_matrix=IDENTITY,
            parameters={"factor": factor},
        ))
        operations.append({"name": "brightness", "applied": True, "factor": factor})
    else:
        operations.append({"name": "brightness", "applied": False})

    blur_applied = config.blur_enabled and rng.random() < config.blur_probability
    if blur_applied:
        radius = rng.uniform(*config.blur_radius)
        image = image.filter(ImageFilter.GaussianBlur(radius=radius))
        steps.append(TransformStep(
            name="augmentation_blur",
            input_size=image.size,
            output_size=image.size,
            forward_matrix=IDENTITY,
            inverse_matrix=IDENTITY,
            parameters={"radius": radius},
        ))
        operations.append({"name": "blur", "applied": True, "radius": radius})
    else:
        operations.append({"name": "blur", "applied": False})

    return AugmentedPageImage(
        image=image,
        transform=TransformChain.from_steps(page.transform.source_size, steps),
        source_sha256=page.source_sha256,
        document_id=document_id,
        split=split,
        derived_seed=seed,
        augmentation_version=config.augmentation_version,
        config_sha256=config.config_sha256,
        mode=config.mode,
        status="PREVIEW_ONLY_DISABLED_CONFIG" if not config.enabled else "APPLIED",
        operations=operations,
        warnings=["OCR_NOT_RERUN_GT_VIEW_ONLY", "NO_OCR_ROBUSTNESS_CLAIM"],
    )
