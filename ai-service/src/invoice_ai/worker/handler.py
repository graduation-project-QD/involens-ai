"""Handles one extraction request: download the image from its URL, run the pipeline, build the result message.

``handle_request`` never raises: every outcome becomes a message in the backend contract
(``AiExtractionResultMessage``). Success is ``status: 0`` with the B11 result; a failure is ``status: 1`` with
an error code, a Vietnamese message for the user and whether a retry can help:

==========================  =========  =========================================================
code                        retryable  cause
==========================  =========  =========================================================
IMAGE_DOWNLOAD_FAILED       true       timeout, connection error, HTTP error (e.g. expired URL)
FILE_TOO_LARGE              false      more than ``MAX_IMAGE_BYTES``
IMAGE_DECODE_FAILED         false      not a JPEG/PNG/WebP file, or a corrupt image
NO_TEXT_FOUND               false      the detector/recognizer found no readable text
PROCESSING_FAILED           false      unexpected error inside the pipeline
==========================  =========  =========================================================
"""

from __future__ import annotations

import logging
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from invoice_ai.inference.pipeline import PipelineError

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_SCHEMES = frozenset({"http", "https"})
RETRYABLE_CODES = frozenset({"IMAGE_DOWNLOAD_FAILED"})


class ExtractionRequest(Protocol):
    """What the handler needs from ``rabbitMQ.requestDTO.requestDTO``."""

    id: str
    url: str


class Pipeline(Protocol):
    """What the handler needs from ``inference.InvoicePipeline``."""

    def process(self, image_bytes: bytes, img_id: str = ...) -> Any: ...


def image_kind(data: bytes) -> str | None:
    """Identifies JPEG, PNG or WebP from the file signature (the URL or Content-Type cannot be trusted)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
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
        raise PipelineError("IMAGE_DECODE_FAILED", "Tệp không phải ảnh JPG/PNG/WebP")
    logger.info("Document image downloaded. host=%s, bytes=%d, kind=%s", host, len(data), image_kind(data))
    return data


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
        message = pipeline.process(image, request.id).to_contract(request.id)
    except PipelineError as error:
        logger.warning("Extraction failed. documentId=%s, code=%s", request.id, error.code)
        return failure_message(request.id, error.code, error.message)
    except Exception:
        logger.error("Unexpected extraction error. documentId=%s", request.id, exc_info=True)
        return failure_message(request.id, "PROCESSING_FAILED", "Lỗi khi trích xuất hóa đơn")
    logger.info("Extraction succeeded. documentId=%s, needs_review=%s", request.id, message["data"]["needs_review"])
    return message
