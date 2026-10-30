"""Handles one extraction request: download the image from its URL, run the pipeline, build the result message.

``handle_request`` never raises: every outcome becomes a message in the backend contract
(``AiExtractionResultMessage``). Success is ``status: 0`` with the B11 result; a failure is ``status: 1`` with
an error code, a Vietnamese message for the user and whether a retry can help:

==========================  =========  =========================================================
code                        retryable  cause
==========================  =========  =========================================================
IMAGE_DOWNLOAD_FAILED       true       timeout, connection error, HTTP error (e.g. expired URL)
FILE_TOO_LARGE              false      more than ``MAX_IMAGE_BYTES``
IMAGE_DECODE_FAILED         false      not a JPEG/PNG/WebP/PDF file, or a corrupt image
PDF_* (T09 intake codes)    false      PDF with several pages, encrypted, corrupt, too large, ...
NO_TEXT_FOUND               false      the detector/recognizer found no readable text
PROCESSING_FAILED           false      unexpected error inside the pipeline
==========================  =========  =========================================================

A PDF goes through the T09 intake unchanged (``preprocessing.pdf_intake``: exactly one page, no encryption,
10 MB, rendered at 200 DPI by pypdfium2 in an isolated process); the rendered page enters the pipeline as PNG.
"""

from __future__ import annotations

import io
import logging
import socket
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from invoice_ai.inference.pipeline import PipelineError
from invoice_ai.preprocessing.core import PreprocessingConfig, PreprocessingError, load_config
from invoice_ai.preprocessing.pdf_intake import PdfIntakeConfig, intake_pdf_bytes, load_pdf_intake_config

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_SCHEMES = frozenset({"http", "https"})
RETRYABLE_CODES = frozenset({"IMAGE_DOWNLOAD_FAILED"})
PDF_HEADER_SCAN_BYTES = 1024  # same window as configs/preprocessing/pdf_v1.json
PREPROCESSING_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "preprocessing"
PDF_ERROR_MESSAGES = {
    "PDF_PAGE_COUNT_UNSUPPORTED": "Chỉ hỗ trợ PDF 1 trang",
    "PDF_ENCRYPTED": "PDF có mật khẩu, không đọc được",
    "FILE_TOO_LARGE": "PDF vượt quá dung lượng cho phép (10 MB)",
    "PIXEL_LIMIT_EXCEEDED": "Trang PDF quá lớn",
    "DECODE_PIXEL_LIMIT_EXCEEDED": "Trang PDF quá lớn",
    "PDF_RENDERER_UNAVAILABLE": "Hệ thống chưa sẵn sàng đọc PDF",
    "PDF_RENDERER_VERSION_MISMATCH": "Hệ thống chưa sẵn sàng đọc PDF",
}
PDF_DEFAULT_MESSAGE = "Không đọc được file PDF"


class ExtractionRequest(Protocol):
    """What the handler needs from ``rabbitMQ.requestDTO.requestDTO``."""

    id: str
    url: str


class Pipeline(Protocol):
    """What the handler needs from ``inference.InvoicePipeline``."""

    def process(self, image_bytes: bytes, img_id: str = ...) -> Any: ...


def image_kind(data: bytes) -> str | None:
    """Identifies JPEG, PNG, WebP or PDF from the file signature (the URL or Content-Type cannot be trusted)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if b"%PDF-" in data[:PDF_HEADER_SCAN_BYTES]:
        return "pdf"
    return None


def download_image(url: str, timeout: float = DOWNLOAD_TIMEOUT_SECONDS, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """Downloads the document image from its (presigned) URL with a time and size limit and checks it is an image.

    Raises ``PipelineError`` with ``IMAGE_DOWNLOAD_FAILED``, ``FILE_TOO_LARGE`` or ``IMAGE_DECODE_FAILED``.
    """
    host = urlparse(url).hostname
    logger.info("Downloading document image. host=%s", host)  # the query string holds the presigned signature
    if urlparse(url).scheme not in ALLOWED_SCHEMES:
        logger.warning("Rejected image URL scheme. scheme=%s", urlparse(url).scheme)
        raise PipelineError("IMAGE_DOWNLOAD_FAILED", "Đường dẫn ảnh không hợp lệ")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError) as error:
        logger.warning("Image download failed. host=%s, error=%s", host, type(error).__name__)
        raise PipelineError("IMAGE_DOWNLOAD_FAILED", "Không tải được ảnh từ MinIO") from error
    if len(data) > max_bytes:
        logger.warning("Image too large. host=%s, limit_bytes=%d", host, max_bytes)
        raise PipelineError("FILE_TOO_LARGE", "Ảnh vượt quá dung lượng cho phép (20 MB)")
    if image_kind(data) is None:
        logger.warning("Downloaded file is not a supported image. host=%s, bytes=%d", host, len(data))
        raise PipelineError("IMAGE_DECODE_FAILED", "Tệp không phải ảnh JPG/PNG/WebP hoặc PDF")
    logger.info("Document image downloaded. host=%s, bytes=%d, kind=%s", host, len(data), image_kind(data))
    return data


@lru_cache(maxsize=1)
def pdf_configs() -> tuple[PdfIntakeConfig, PreprocessingConfig]:
    """Frozen T09/T07 configurations (``configs/preprocessing``), loaded once per worker."""
    preprocessing = load_config(PREPROCESSING_CONFIG_DIR / "v1.json")
    return load_pdf_intake_config(PREPROCESSING_CONFIG_DIR / "pdf_v1.json", preprocessing), preprocessing


def render_pdf(data: bytes) -> bytes:
    """Renders a one-page PDF with the T09 intake and returns the page as PNG bytes for the pipeline.

    T09 errors keep their code (``PDF_PAGE_COUNT_UNSUPPORTED``, ``PDF_ENCRYPTED``, ...) as a ``PipelineError``.
    """
    logger.info("Rendering PDF document. bytes=%d", len(data))
    try:
        intake = intake_pdf_bytes(data, *pdf_configs())
    except PreprocessingError as error:
        logger.warning("PDF intake rejected the document. code=%s", error.code)
        raise PipelineError(error.code, PDF_ERROR_MESSAGES.get(error.code, PDF_DEFAULT_MESSAGE)) from error
    buffer = io.BytesIO()
    intake.page.image.save(buffer, format="PNG")
    logger.info("PDF page rendered. size=%s, render_ms=%.0f", intake.page.image.size, intake.render_ms)
    return buffer.getvalue()


def failure_message(document_id: str, code: str, message: str) -> dict[str, Any]:
    """Backend failure message: ``status: 1``, the error, and ``data.id`` so the backend can find the document."""
    return {
        "status": 1,
        "error": {"code": code, "message": message, "retryable": code in RETRYABLE_CODES},
        "data": {"id": document_id},
    }


def handle_request(request: ExtractionRequest, pipeline: Pipeline, downloader: Callable[[str], bytes] = download_image) -> dict[str, Any]:
    """Turns one extraction request into the result message for the backend (success or failure)."""
    logger.info("Handling extraction request. documentId=%s", request.id)
    try:
        image = downloader(request.url)
        if image_kind(image) == "pdf":
            image = render_pdf(image)
        message = pipeline.process(image, request.id).to_contract(request.id)
    except PipelineError as error:
        logger.warning("Extraction failed. documentId=%s, code=%s", request.id, error.code)
        return failure_message(request.id, error.code, error.message)
    except Exception:
        logger.error("Unexpected extraction error. documentId=%s", request.id, exc_info=True)
        return failure_message(request.id, "PROCESSING_FAILED", "Lỗi khi trích xuất hóa đơn")
    logger.info("Extraction succeeded. documentId=%s, needs_review=%s", request.id, message["data"]["needs_review"])
    return message
