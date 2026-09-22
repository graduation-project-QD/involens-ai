from __future__ import annotations

import hashlib
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from invoice_ai.preprocessing import (
    PDF_INTAKE_VERSION,
    PreprocessingError,
    intake_pdf_bytes,
    intake_pdf_path,
    load_config,
    load_pdf_intake_config,
)


ROOT = Path(__file__).resolve().parents[1]
PREPROCESS_CONFIG = ROOT / "configs" / "preprocessing" / "v1.json"
PDF_CONFIG = ROOT / "configs" / "preprocessing" / "pdf_v1.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdf"


class PdfIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preprocessing_config = load_config(PREPROCESS_CONFIG)
        cls.config = load_pdf_intake_config(PDF_CONFIG, cls.preprocessing_config)

    def assert_error(self, filename: str, expected_code: str) -> PreprocessingError:
        with self.assertRaises(PreprocessingError) as context:
            intake_pdf_path(FIXTURES / filename, self.config, self.preprocessing_config)
        self.assertEqual(context.exception.code, expected_code)
        return context.exception

    def test_valid_single_page_renders_then_uses_t07(self) -> None:
        path = FIXTURES / "valid_one_page.pdf"
        result = intake_pdf_path(
            path,
            self.config,
            self.preprocessing_config,
            declared_mime="application/pdf; charset=binary",
        )
        self.assertEqual(result.intake_version, PDF_INTAKE_VERSION)
        self.assertEqual(result.pdf_source_sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.renderer, "pypdfium2")
        self.assertEqual(result.renderer_version, "5.13.0")
        self.assertFalse(result.text_layer_used)
        self.assertIsNotNone(result.peak_rss_bytes)
        self.assertGreater(result.peak_rss_bytes or 0, 0)
        self.assertEqual(result.page.source_format, "PNG")
        self.assertEqual(result.page.image.mode, "RGB")
        self.assertEqual(max(result.page.image.size), 2000)
        self.assertLessEqual(result.rendered_pixels, self.config.max_pixels)
        corners = [[0, 0], [result.rendered_size[0], 0], list(result.rendered_size), [0, result.rendered_size[1]]]
        mapped = result.page.transform.map_points(corners)
        restored = result.page.transform.map_points(mapped, inverse=True)
        error = max(abs(a - b) for left, right in zip(corners, restored) for a, b in zip(left, right))
        self.assertLessEqual(error, 1e-9)

    def test_render_is_pixel_deterministic(self) -> None:
        path = FIXTURES / "valid_one_page.pdf"
        first = intake_pdf_path(path, self.config, self.preprocessing_config)
        second = intake_pdf_path(path, self.config, self.preprocessing_config)
        self.assertEqual(first.page.pixel_sha256, second.page.pixel_sha256)
        self.assertEqual(first.rendered_size, second.rendered_size)

    def test_multipage_encrypted_corrupt_and_pixel_bomb_have_specific_codes(self) -> None:
        cases = {
            "two_pages.pdf": "PDF_PAGE_COUNT_UNSUPPORTED",
            "encrypted.pdf": "PDF_ENCRYPTED",
            "corrupt.pdf": "PDF_DECODE_ERROR",
            "pixel_bomb.pdf": "PIXEL_LIMIT_EXCEEDED",
        }
        for filename, expected_code in cases.items():
            with self.subTest(filename=filename):
                self.assert_error(filename, expected_code)

    def test_byte_limit_and_mime_are_checked_before_render(self) -> None:
        payload = (FIXTURES / "valid_one_page.pdf").read_bytes()
        with self.assertRaises(PreprocessingError) as context:
            intake_pdf_bytes(payload, replace(self.config, max_bytes=100), self.preprocessing_config)
        self.assertEqual(context.exception.code, "FILE_TOO_LARGE")
        with self.assertRaises(PreprocessingError) as context:
            intake_pdf_bytes(payload, self.config, self.preprocessing_config, declared_mime="image/png")
        self.assertEqual(context.exception.code, "UNSUPPORTED_MEDIA_TYPE")
        with self.assertRaises(PreprocessingError) as context:
            intake_pdf_bytes(b"not a pdf", self.config, self.preprocessing_config)
        self.assertEqual(context.exception.code, "UNSUPPORTED_MEDIA_TYPE")

    def test_renderer_timeout_has_bounded_error(self) -> None:
        payload = (FIXTURES / "valid_one_page.pdf").read_bytes()
        with patch(
            "invoice_ai.preprocessing.pdf_intake.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pdf-worker", timeout=self.config.renderer_timeout_seconds),
        ):
            with self.assertRaises(PreprocessingError) as context:
                intake_pdf_bytes(payload, self.config, self.preprocessing_config)
        self.assertEqual(context.exception.code, "PDF_RENDER_TIMEOUT")
        self.assertEqual(context.exception.details["timeout_seconds"], self.config.renderer_timeout_seconds)

    def test_config_is_locked_to_t03_t07_limits(self) -> None:
        self.assertEqual(self.config.max_bytes, 10 * 1024 * 1024)
        self.assertEqual(self.config.max_pixels, 20_000_000)
        self.assertEqual(self.config.required_page_count, 1)
        self.assertTrue(self.config.reject_encrypted)
        self.assertFalse(self.config.use_text_layer)
        incompatible = replace(self.preprocessing_config, request_max_pixels=19_000_000)
        with self.assertRaisesRegex(ValueError, "must match"):
            load_pdf_intake_config(PDF_CONFIG, incompatible)


if __name__ == "__main__":
    unittest.main()
