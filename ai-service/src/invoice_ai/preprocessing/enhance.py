"""B6 image enhancements evaluated before OCR: CLAHE (contrast) and UVDoc (document unwarping)."""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np


def clahe(image_bgr: np.ndarray, clip_limit: float = 2.0, tiles: int = 8) -> np.ndarray:
    """Contrast-limited adaptive histogram equalisation on the L channel (LAB); geometry is unchanged."""
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tiles, tiles)).apply(lightness)
    return cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)


class UVDocUnwarper:
    """PaddleOCR ``UVDoc`` text-image unwarping. The output geometry differs from the input (no GT mapping)."""

    def __init__(self, paddlex_home: Path, cpu_threads: int = 10) -> None:
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddlex_home))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import TextImageUnwarping

        self.model = TextImageUnwarping(model_name="UVDoc", device="cpu", cpu_threads=cpu_threads, enable_mkldnn=True)

    def __call__(self, image_bgr: np.ndarray) -> np.ndarray:
        output = np.asarray(list(self.model.predict(image_bgr))[0]["doctr_img"])
        if output.dtype != np.uint8:
            output = np.clip(output, 0, 255).astype(np.uint8)
        return cv2.cvtColor(output, cv2.COLOR_RGB2BGR)  # the model returns RGB for a BGR input
