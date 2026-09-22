"""T07 deterministic image preprocessing and reversible transform bookkeeping."""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageOps, UnidentifiedImageError

PREPROCESSING_VERSION = "t07_preprocess_v1"
Matrix = tuple[float, float, float, float, float, float, float, float, float]
Point = tuple[float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


class PreprocessingError(ValueError):
    """Input cannot be decoded or transformed under the frozen v1 policy."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _matrix_multiply(left: Matrix, right: Matrix) -> Matrix:
    return tuple(
        sum(left[row * 3 + inner] * right[inner * 3 + column] for inner in range(3))
        for row in range(3)
        for column in range(3)
    )  # type: ignore[return-value]


def _matrix_inverse(matrix: Matrix) -> Matrix:
    a, b, c, d, e, f, g, h, i = matrix
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) < 1e-15:
        raise ValueError("Transform matrix is singular")
    cofactors = (
        e * i - f * h, c * h - b * i, b * f - c * e,
        f * g - d * i, a * i - c * g, c * d - a * f,
        d * h - e * g, b * g - a * h, a * e - b * d,
    )
    return tuple(value / determinant for value in cofactors)  # type: ignore[return-value]


def _apply_matrix(matrix: Matrix, point: Point) -> Point:
    x, y = point
    denominator = matrix[6] * x + matrix[7] * y + matrix[8]
    if abs(denominator) < 1e-15:
        raise ValueError("Point maps to infinity")
    return (
        (matrix[0] * x + matrix[1] * y + matrix[2]) / denominator,
        (matrix[3] * x + matrix[4] * y + matrix[5]) / denominator,
    )


def _within(point: Point, size: tuple[int, int], tolerance: float = 1e-7) -> bool:
    return -tolerance <= point[0] <= size[0] + tolerance and -tolerance <= point[1] <= size[1] + tolerance


@dataclass(frozen=True)
class TransformStep:
    name: str
    input_size: tuple[int, int]
    output_size: tuple[int, int]
    forward_matrix: Matrix
    inverse_matrix: Matrix
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransformChain:
    source_size: tuple[int, int]
    output_size: tuple[int, int]
    steps: tuple[TransformStep, ...]
    forward_matrix: Matrix
    inverse_matrix: Matrix

    @classmethod
    def from_steps(cls, source_size: tuple[int, int], steps: Sequence[TransformStep]) -> "TransformChain":
        forward = IDENTITY
        current_size = source_size
        for step in steps:
            if step.input_size != current_size:
                raise ValueError("Transform steps do not form a continuous coordinate chain")
            forward = _matrix_multiply(step.forward_matrix, forward)
            current_size = step.output_size
        return cls(source_size, current_size, tuple(steps), forward, _matrix_inverse(forward))

    def map_points(self, points: Iterable[Sequence[float]], *, inverse: bool = False) -> list[list[float]]:
        source_bounds = self.output_size if inverse else self.source_size
        target_bounds = self.source_size if inverse else self.output_size
        matrix = self.inverse_matrix if inverse else self.forward_matrix
        result: list[list[float]] = []
        for value in points:
            if len(value) != 2 or not all(isinstance(item, (int, float)) and math.isfinite(item) for item in value):
                raise PreprocessingError("INVALID_POINT", "Each point must contain two finite numbers", point=list(value))
            point = (float(value[0]), float(value[1]))
            if not _within(point, source_bounds):
                raise PreprocessingError("POINT_OUT_OF_BOUNDS", "Point lies outside the input coordinate frame", point=point, bounds=source_bounds)
            mapped = _apply_matrix(matrix, point)
            if not _within(mapped, target_bounds, tolerance=1e-5):
                raise PreprocessingError("TRANSFORM_OUT_OF_BOUNDS", "Mapped point lies outside the output frame", point=mapped, bounds=target_bounds)
            result.append([mapped[0], mapped[1]])
        return result

    def map_bbox(self, bbox_xyxy: Sequence[float], *, inverse: bool = False) -> list[float]:
        if len(bbox_xyxy) != 4:
            raise PreprocessingError("INVALID_BBOX", "bbox must be [x0, y0, x1, y1]")
        x0, y0, x1, y1 = (float(value) for value in bbox_xyxy)
        if not (x0 < x1 and y0 < y1):
            raise PreprocessingError("INVALID_BBOX", "bbox must have positive width and height", bbox=list(bbox_xyxy))
        corners = self.map_points(((x0, y0), (x1, y0), (x1, y1), (x0, y1)), inverse=inverse)
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        return [min(xs), min(ys), max(xs), max(ys)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_size": list(self.source_size),
            "output_size": list(self.output_size),
            "forward_matrix": list(self.forward_matrix),
            "inverse_matrix": list(self.inverse_matrix),
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class PreprocessingConfig:
    schema_version: str
    pipeline_version: str
    max_decode_bytes: int
    max_decode_pixels: int
    request_max_bytes: int
    request_max_pixels: int
    apply_exif_orientation: bool
    output_mode: str
    alpha_background_rgb: tuple[int, int, int]
    resize_enabled: bool
    max_long_edge: int
    allow_upscale: bool
    resample: str
    orientation_detection_enabled: bool
    deskew_enabled: bool
    contrast_enabled: bool


@dataclass
class PageImage:
    image: Image.Image
    source_bytes: bytes
    source_sha256: str
    source_format: str
    source_mode: str
    transform: TransformChain
    warnings: list[str]
    pipeline_version: str = PREPROCESSING_VERSION

    @property
    def pixel_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.image.mode.encode("ascii"))
        digest.update(f"{self.image.width}x{self.image.height}".encode("ascii"))
        digest.update(self.image.tobytes())
        return digest.hexdigest()

    def to_manifest(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "source_sha256": self.source_sha256,
            "source_bytes": len(self.source_bytes),
            "source_format": self.source_format,
            "source_mode": self.source_mode,
            "output_mode": self.image.mode,
            "pixel_sha256": self.pixel_sha256,
            "warnings": list(self.warnings),
            "transform": self.transform.to_dict(),
        }


def load_config(path: Path) -> PreprocessingConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    decode = payload["decode"]
    request_limits = payload["request_limits"]
    resize = payload["resize"]
    if payload.get("pipeline_version") != PREPROCESSING_VERSION:
        raise ValueError("Unsupported preprocessing pipeline version")
    if decode.get("output_mode") != "RGB":
        raise ValueError("T07 v1 output mode must be RGB")
    if resize.get("resample") != "LANCZOS":
        raise ValueError("T07 v1 only supports deterministic LANCZOS resize")
    if payload["orientation_detection"].get("enabled") or payload["deskew"].get("enabled") or payload["contrast"].get("enabled"):
        raise ValueError("Optional transforms require validation evidence before activation")
    background = tuple(decode["alpha_background_rgb"])
    if len(background) != 3 or any(not isinstance(value, int) or not 0 <= value <= 255 for value in background):
        raise ValueError("alpha_background_rgb must contain three bytes")
    return PreprocessingConfig(
        schema_version=payload["schema_version"],
        pipeline_version=payload["pipeline_version"],
        max_decode_bytes=int(decode["max_decode_bytes"]),
        max_decode_pixels=int(decode["max_decode_pixels"]),
        request_max_bytes=int(request_limits["max_bytes"]),
        request_max_pixels=int(request_limits["max_pixels"]),
        apply_exif_orientation=bool(decode["apply_exif_orientation"]),
        output_mode=decode["output_mode"],
        alpha_background_rgb=background,  # type: ignore[arg-type]
        resize_enabled=bool(resize["enabled"]),
        max_long_edge=int(resize["max_long_edge"]),
        allow_upscale=bool(resize["allow_upscale"]),
        resample=resize["resample"],
        orientation_detection_enabled=bool(payload["orientation_detection"]["enabled"]),
        deskew_enabled=bool(payload["deskew"]["enabled"]),
        contrast_enabled=bool(payload["contrast"]["enabled"]),
    )


def _exif_matrix(orientation: int, width: int, height: int) -> tuple[Matrix, tuple[int, int]]:
    mappings: dict[int, tuple[Matrix, tuple[int, int]]] = {
        1: (IDENTITY, (width, height)),
        2: ((-1, 0, width, 0, 1, 0, 0, 0, 1), (width, height)),
        3: ((-1, 0, width, 0, -1, height, 0, 0, 1), (width, height)),
        4: ((1, 0, 0, 0, -1, height, 0, 0, 1), (width, height)),
        5: ((0, 1, 0, 1, 0, 0, 0, 0, 1), (height, width)),
        6: ((0, -1, height, 1, 0, 0, 0, 0, 1), (height, width)),
        7: ((0, -1, height, -1, 0, width, 0, 0, 1), (height, width)),
        8: ((0, 1, 0, -1, 0, width, 0, 0, 1), (height, width)),
    }
    return mappings.get(orientation, mappings[1])


def _normalize_rgb(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (*background, 255))
        return Image.alpha_composite(base, rgba).convert("RGB")
    return image.convert("RGB")


def preprocess_bytes(
    payload: bytes,
    config: PreprocessingConfig,
    *,
    enforce_request_limits: bool = True,
) -> PageImage:
    if not payload:
        raise PreprocessingError("EMPTY_INPUT", "Image input is empty")
    if len(payload) > config.max_decode_bytes:
        raise PreprocessingError("DECODE_BYTE_LIMIT_EXCEEDED", "Image exceeds the decoder safety byte limit", bytes=len(payload), max_bytes=config.max_decode_bytes)
    warnings: list[str] = []
    if len(payload) > config.request_max_bytes:
        if enforce_request_limits:
            raise PreprocessingError("FILE_TOO_LARGE", "Image exceeds the v1 request byte limit", bytes=len(payload), max_bytes=config.request_max_bytes)
        warnings.append("REQUEST_BYTE_LIMIT_EXCEEDED_INTERNAL_DATASET_ONLY")
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            source_format = opened.format or "UNKNOWN"
            source_mode = opened.mode
            source_size = opened.size
            source_pixels = source_size[0] * source_size[1]
            if source_size[0] <= 0 or source_size[1] <= 0 or source_pixels > config.max_decode_pixels:
                raise PreprocessingError("DECODE_PIXEL_LIMIT_EXCEEDED", "Image dimensions exceed the decoder safety pixel limit", size=source_size, max_pixels=config.max_decode_pixels)
            if source_pixels > config.request_max_pixels:
                if enforce_request_limits:
                    raise PreprocessingError("PIXEL_LIMIT_EXCEEDED", "Image dimensions exceed the v1 request pixel limit", size=source_size, max_pixels=config.request_max_pixels)
                warnings.append("REQUEST_PIXEL_LIMIT_EXCEEDED_INTERNAL_DATASET_ONLY")
            orientation = int(opened.getexif().get(274, 1)) if config.apply_exif_orientation else 1
            opened.load()
            image = ImageOps.exif_transpose(opened) if config.apply_exif_orientation else opened.copy()
            image = image.copy()
    except PreprocessingError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise PreprocessingError("IMAGE_DECODE_ERROR", "Image cannot be decoded", error=str(error)) from error

    exif_forward, expected_exif_size = _exif_matrix(orientation, *source_size)
    if image.size != expected_exif_size:
        raise PreprocessingError("EXIF_SIZE_MISMATCH", "Decoded EXIF orientation disagrees with geometry bookkeeping", decoded_size=image.size, expected_size=expected_exif_size)
    steps: list[TransformStep] = [TransformStep(
        name="exif_orientation",
        input_size=source_size,
        output_size=image.size,
        forward_matrix=exif_forward,
        inverse_matrix=_matrix_inverse(exif_forward),
        parameters={"orientation": orientation, "applied": orientation != 1},
    )]
    image = _normalize_rgb(image, config.alpha_background_rgb)

    before_resize = image.size
    long_edge = max(before_resize)
    should_resize = config.resize_enabled and long_edge != config.max_long_edge and (
        long_edge > config.max_long_edge or config.allow_upscale
    )
    if should_resize:
        scale = config.max_long_edge / long_edge
        output_size = (max(1, round(before_resize[0] * scale)), max(1, round(before_resize[1] * scale)))
        image = image.resize(output_size, Image.Resampling.LANCZOS)
    else:
        output_size = before_resize
    scale_x = output_size[0] / before_resize[0]
    scale_y = output_size[1] / before_resize[1]
    resize_forward: Matrix = (scale_x, 0, 0, 0, scale_y, 0, 0, 0, 1)
    steps.append(TransformStep(
        name="resize_keep_aspect",
        input_size=before_resize,
        output_size=output_size,
        forward_matrix=resize_forward,
        inverse_matrix=_matrix_inverse(resize_forward),
        parameters={"applied": should_resize, "scale_x": scale_x, "scale_y": scale_y, "resample": config.resample},
    ))
    chain = TransformChain.from_steps(source_size, steps)
    return PageImage(
        image=image,
        source_bytes=bytes(payload),
        source_sha256=hashlib.sha256(payload).hexdigest(),
        source_format=source_format,
        source_mode=source_mode,
        transform=chain,
        warnings=warnings,
        pipeline_version=config.pipeline_version,
    )


def preprocess_path(
    path: Path,
    config: PreprocessingConfig,
    *,
    enforce_request_limits: bool = True,
) -> PageImage:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise PreprocessingError("IMAGE_READ_ERROR", "Image cannot be read", path=str(path), error=str(error)) from error
    return preprocess_bytes(payload, config, enforce_request_limits=enforce_request_limits)
