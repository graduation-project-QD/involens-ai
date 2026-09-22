"""PaddleOCR adapter, canonical schema and content-addressed cache."""

from .adapter import PaddleOcrEngine, canonicalize_engine_output, extract_ocr
from .cache import CachedOcrResult, OcrCache
from .config import OCR_VERSION, OcrConfig, load_ocr_config
from .models import build_model_manifest, load_runtime_identity
from .schema import OCRLine, OCRPage, OcrError, OcrRuntimeIdentity

__all__ = [
    "OCR_VERSION",
    "OcrConfig",
    "load_ocr_config",
    "OCRLine",
    "OCRPage",
    "OcrError",
    "OcrRuntimeIdentity",
    "PaddleOcrEngine",
    "canonicalize_engine_output",
    "extract_ocr",
    "CachedOcrResult",
    "OcrCache",
    "build_model_manifest",
    "load_runtime_identity",
]
