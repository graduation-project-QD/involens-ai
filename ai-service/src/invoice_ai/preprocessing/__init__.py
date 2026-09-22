"""Deterministic image preprocessing with reversible geometry bookkeeping."""

from .core import (
    PREPROCESSING_VERSION,
    PageImage,
    PreprocessingConfig,
    PreprocessingError,
    TransformChain,
    TransformStep,
    load_config,
    preprocess_bytes,
    preprocess_path,
)
from .augmentation import (
    AUGMENTATION_VERSION,
    AugmentationConfig,
    AugmentationError,
    AugmentedPageImage,
    augment_page,
    load_augmentation_config,
)
from .pdf_intake import (
    PDF_INTAKE_VERSION,
    PdfIntakeConfig,
    PdfIntakeResult,
    intake_pdf_bytes,
    intake_pdf_path,
    load_pdf_intake_config,
)

__all__ = [
    "PREPROCESSING_VERSION",
    "PageImage",
    "PreprocessingConfig",
    "PreprocessingError",
    "TransformChain",
    "TransformStep",
    "load_config",
    "preprocess_bytes",
    "preprocess_path",
    "AUGMENTATION_VERSION",
    "AugmentationConfig",
    "AugmentationError",
    "AugmentedPageImage",
    "augment_page",
    "load_augmentation_config",
    "PDF_INTAKE_VERSION",
    "PdfIntakeConfig",
    "PdfIntakeResult",
    "intake_pdf_bytes",
    "intake_pdf_path",
    "load_pdf_intake_config",
]
