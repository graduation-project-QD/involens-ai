"""T09 single-page PDF intake with bounded, isolated rasterization."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import PageImage, PreprocessingConfig, PreprocessingError, preprocess_bytes

PDF_INTAKE_VERSION = "t09_pdf_intake_v1"


@dataclass(frozen=True)
class PdfIntakeConfig:
    schema_version: str
    intake_version: str
    max_bytes: int
    max_pixels: int
    allowed_mime_types: tuple[str, ...]
    header_scan_bytes: int
    required_page_count: int
    reject_encrypted: bool
    use_text_layer: bool
    renderer_backend: str
    renderer_dependency: str
    renderer_dpi: int
    renderer_timeout_seconds: float
    renderer_output_format: str
    renderer_background_rgb: tuple[int, int, int]
    config_sha256: str


@dataclass
class PdfIntakeResult:
    page: PageImage
    pdf_source_sha256: str
    pdf_source_bytes: int
    declared_mime: str
    page_count: int
    page_size_points: tuple[float, float]
    rendered_size: tuple[int, int]
    rendered_pixels: int
    render_ms: float
    peak_rss_bytes: int | None
    renderer: str
    renderer_version: str
    renderer_dependency: str
    intake_version: str
    config_sha256: str
    text_layer_used: bool = False

    def to_manifest(self) -> dict[str, Any]:
        return {
            "intake_version": self.intake_version,
            "config_sha256": self.config_sha256,
            "pdf_source_sha256": self.pdf_source_sha256,
            "pdf_source_bytes": self.pdf_source_bytes,
            "declared_mime": self.declared_mime,
            "page_count": self.page_count,
            "page_size_points": list(self.page_size_points),
            "rendered_size": list(self.rendered_size),
            "rendered_pixels": self.rendered_pixels,
            "render_ms": self.render_ms,
            "peak_rss_bytes": self.peak_rss_bytes,
            "renderer": self.renderer,
            "renderer_version": self.renderer_version,
            "renderer_dependency": self.renderer_dependency,
            "text_layer_used": self.text_layer_used,
            "page": self.page.to_manifest(),
        }


def load_pdf_intake_config(path: Path, preprocessing_config: PreprocessingConfig | None = None) -> PdfIntakeConfig:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("intake_version") != PDF_INTAKE_VERSION:
        raise ValueError("Unsupported PDF intake version")
    limits = payload["request_limits"]
    pdf = payload["pdf"]
    renderer = payload["renderer"]
    allowed_mime_types = tuple(str(value).lower() for value in pdf["allowed_mime_types"])
    if allowed_mime_types != ("application/pdf",):
        raise ValueError("T09 v1 must accept only application/pdf")
    if int(pdf["required_page_count"]) != 1:
        raise ValueError("T09 v1 requires exactly one PDF page")
    if not pdf["reject_encrypted"] or pdf["use_text_layer"]:
        raise ValueError("T09 v1 rejects encrypted PDFs and never uses the PDF text layer")
    if renderer["backend"] != "pypdfium2" or renderer["output_format"] != "PNG":
        raise ValueError("T09 v1 requires the locked pypdfium2 PNG renderer")
    dependency = str(renderer["dependency"])
    if not dependency.startswith("pypdfium2=="):
        raise ValueError("The PDF renderer dependency must be exactly pinned")
    background = tuple(renderer["background_rgb"])
    if len(background) != 3 or any(not isinstance(value, int) or not 0 <= value <= 255 for value in background):
        raise ValueError("renderer.background_rgb must contain three bytes")
    result = PdfIntakeConfig(
        schema_version=payload["schema_version"],
        intake_version=payload["intake_version"],
        max_bytes=int(limits["max_bytes"]),
        max_pixels=int(limits["max_pixels"]),
        allowed_mime_types=allowed_mime_types,
        header_scan_bytes=int(pdf["header_scan_bytes"]),
        required_page_count=int(pdf["required_page_count"]),
        reject_encrypted=bool(pdf["reject_encrypted"]),
        use_text_layer=bool(pdf["use_text_layer"]),
        renderer_backend=renderer["backend"],
        renderer_dependency=dependency,
        renderer_dpi=int(renderer["dpi"]),
        renderer_timeout_seconds=float(renderer["timeout_seconds"]),
        renderer_output_format=renderer["output_format"],
        renderer_background_rgb=background,  # type: ignore[arg-type]
        config_sha256=hashlib.sha256(raw).hexdigest(),
    )
    if result.max_bytes <= 0 or result.max_pixels <= 0 or result.header_scan_bytes < 5:
        raise ValueError("PDF intake limits must be positive")
    if result.renderer_dpi <= 0 or result.renderer_timeout_seconds <= 0:
        raise ValueError("PDF renderer DPI and timeout must be positive")
    if preprocessing_config and (
        result.max_bytes != preprocessing_config.request_max_bytes
        or result.max_pixels != preprocessing_config.request_max_pixels
    ):
        raise ValueError("T09 request limits must match the frozen T03/T07 limits")
    return result


def _raise_worker_error(metadata: dict[str, Any]) -> None:
    error = metadata.get("error") or {}
    raise PreprocessingError(
        str(error.get("code") or "PDF_RENDER_ERROR"),
        str(error.get("message") or "PDF rendering failed"),
        **dict(error.get("details") or {}),
    )


def intake_pdf_bytes(
    payload: bytes,
    config: PdfIntakeConfig,
    preprocessing_config: PreprocessingConfig,
    *,
    declared_mime: str = "application/pdf",
) -> PdfIntakeResult:
    if not payload:
        raise PreprocessingError("EMPTY_INPUT", "PDF input is empty")
    if len(payload) > config.max_bytes:
        raise PreprocessingError(
            "FILE_TOO_LARGE",
            "PDF exceeds the v1 request byte limit",
            bytes=len(payload),
            max_bytes=config.max_bytes,
        )
    normalized_mime = declared_mime.split(";", 1)[0].strip().lower()
    if normalized_mime not in config.allowed_mime_types:
        raise PreprocessingError(
            "UNSUPPORTED_MEDIA_TYPE",
            "Declared MIME type is not accepted for PDF intake",
            declared_mime=declared_mime,
        )
    if b"%PDF-" not in payload[: config.header_scan_bytes]:
        raise PreprocessingError("UNSUPPORTED_MEDIA_TYPE", "Input does not have a PDF signature")

    with tempfile.TemporaryDirectory(prefix="invoice_ai_pdf_") as directory:
        root = Path(directory)
        input_path = root / "source.pdf"
        output_path = root / "page.png"
        metadata_path = root / "render.json"
        input_path.write_bytes(payload)
        command = [
            sys.executable,
            "-m",
            "invoice_ai.preprocessing.pdf_render_worker",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--metadata",
            str(metadata_path),
            "--dpi",
            str(config.renderer_dpi),
            "--max-pixels",
            str(config.max_pixels),
            "--required-page-count",
            str(config.required_page_count),
            "--background",
            *(str(value) for value in config.renderer_background_rgb),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=config.renderer_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise PreprocessingError(
                "PDF_RENDER_TIMEOUT",
                "PDF rendering exceeded the configured timeout",
                timeout_seconds=config.renderer_timeout_seconds,
            ) from error
        if not metadata_path.is_file():
            raise PreprocessingError(
                "PDF_RENDER_ERROR",
                "PDF renderer did not produce metadata",
                return_code=completed.returncode,
                stderr=completed.stderr[-1000:],
            )
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PreprocessingError("PDF_RENDER_ERROR", "PDF renderer metadata is invalid") from error
        if completed.returncode != 0 or metadata.get("status") != "PASS":
            _raise_worker_error(metadata)
        if not output_path.is_file():
            raise PreprocessingError("PDF_RENDER_ERROR", "PDF renderer did not produce a page image")
        expected_version = config.renderer_dependency.split("==", 1)[1]
        if metadata.get("renderer_version") != expected_version:
            raise PreprocessingError(
                "PDF_RENDERER_VERSION_MISMATCH",
                "Installed PDF renderer differs from the locked version",
                expected=expected_version,
                actual=metadata.get("renderer_version"),
            )
        rendered_payload = output_path.read_bytes()

    # The 10 MiB request cap applies to the uploaded PDF. The intermediate PNG
    # is internal; the 20 MP request cap was enforced before and after render.
    page = preprocess_bytes(rendered_payload, preprocessing_config, enforce_request_limits=False)
    if page.transform.source_size[0] * page.transform.source_size[1] > config.max_pixels:
        raise PreprocessingError("PIXEL_LIMIT_EXCEEDED", "Rendered PDF page exceeds the v1 pixel limit")
    return PdfIntakeResult(
        page=page,
        pdf_source_sha256=hashlib.sha256(payload).hexdigest(),
        pdf_source_bytes=len(payload),
        declared_mime=normalized_mime,
        page_count=int(metadata["page_count"]),
        page_size_points=tuple(float(value) for value in metadata["page_size_points"]),  # type: ignore[arg-type]
        rendered_size=tuple(int(value) for value in metadata["rendered_size"]),  # type: ignore[arg-type]
        rendered_pixels=int(metadata["rendered_pixels"]),
        render_ms=float(metadata["render_ms"]),
        peak_rss_bytes=int(metadata["peak_rss_bytes"]) if metadata.get("peak_rss_bytes") is not None else None,
        renderer=str(metadata["renderer"]),
        renderer_version=str(metadata["renderer_version"]),
        renderer_dependency=config.renderer_dependency,
        intake_version=config.intake_version,
        config_sha256=config.config_sha256,
        text_layer_used=bool(metadata["text_layer_used"]),
    )


def intake_pdf_path(
    path: Path,
    config: PdfIntakeConfig,
    preprocessing_config: PreprocessingConfig,
    *,
    declared_mime: str = "application/pdf",
) -> PdfIntakeResult:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise PreprocessingError("PDF_READ_ERROR", "PDF cannot be read", path=str(path), error=str(error)) from error
    return intake_pdf_bytes(payload, config, preprocessing_config, declared_mime=declared_mime)
