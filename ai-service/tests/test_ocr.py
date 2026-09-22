from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from invoice_ai.ocr import (
    OcrCache,
    OcrError,
    OcrRuntimeIdentity,
    canonicalize_engine_output,
    extract_ocr,
    load_ocr_config,
)
from invoice_ai.preprocessing import load_config, preprocess_bytes, preprocess_path


ROOT = Path(__file__).resolve().parents[1]
OCR_CONFIG = ROOT / "configs" / "ocr" / "v1.json"
PREPROCESS_CONFIG = ROOT / "configs" / "preprocessing" / "v1.json"
ENGINE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "paddleocr_3_7_vi_output.json"
IMAGE_FIXTURE = ROOT / "runtime" / "t05" / "fixtures" / "sample_invoice.jpg"


def image_bytes(color: str) -> bytes:
    image = Image.new("RGB", (400, 200), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeEngine:
    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.payload = [] if payload is None else payload
        self.error = error
        self.calls = 0

    def predict(self, page: object) -> object:
        del page
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


class OcrAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_ocr_config(OCR_CONFIG)
        cls.preprocessing_config = load_config(PREPROCESS_CONFIG)
        cls.identity = OcrRuntimeIdentity(
            paddlepaddle_version="3.3.0",
            paddleocr_version="3.7.0",
            paddlex_version="3.7.2",
            detection_model_name="PP-OCRv5_mobile_det",
            recognition_model_name="latin_PP-OCRv5_mobile_rec",
            model_manifest_sha256="a" * 64,
        )

    def test_real_engine_output_fixture_preserves_unicode_and_geometry(self) -> None:
        page = preprocess_path(IMAGE_FIXTURE, self.preprocessing_config)
        raw = json.loads(ENGINE_FIXTURE.read_text(encoding="utf-8"))
        result = canonicalize_engine_output(raw, page, self.config, latency_ms=123.0)
        self.assertEqual(result.status, "OK")
        self.assertEqual(len(result.lines), 42)
        self.assertTrue(any("Ngày bán" in line.text for line in result.lines))
        self.assertTrue(all("\ufffd" not in line.text for line in result.lines))
        self.assertEqual([line.reading_order for line in result.lines], list(range(42)))
        self.assertTrue(all(0 <= value <= 1 for line in result.lines for value in [line.recognition_score or 0]))
        self.assertTrue(all(0 <= x <= page.image.width and 0 <= y <= page.image.height for line in result.lines for x, y in line.polygon_px))

    def test_empty_is_success_and_missing_score_is_null(self) -> None:
        page = preprocess_bytes(image_bytes("white"), self.preprocessing_config)
        empty = canonicalize_engine_output([{"res": {"rec_texts": [], "dt_polys": [], "rec_scores": []}}], page, self.config, latency_ms=1)
        self.assertEqual(empty.status, "EMPTY")
        self.assertEqual(empty.lines, ())
        raw = [{"res": {"rec_texts": ["Địa chỉ"], "dt_polys": [[[1, 1], [100, 1], [100, 20], [1, 20]]]}}]
        one = canonicalize_engine_output(raw, page, self.config, latency_ms=1)
        self.assertIsNone(one.lines[0].recognition_score)
        self.assertIn("NULL_RECOGNITION_SCORE_PRESENT", one.warnings)

    def test_reading_order_groups_rows_then_sorts_left_to_right(self) -> None:
        page = preprocess_bytes(image_bytes("white"), self.preprocessing_config)
        raw = [{"res": {
            "rec_texts": ["right", "bottom", "left"],
            "rec_scores": [0.8, 0.9, 0.7],
            "dt_polys": [
                [[210, 12], [350, 8], [351, 31], [211, 34]],
                [[20, 100], [200, 96], [201, 120], [21, 124]],
                [[10, 10], [180, 10], [180, 30], [10, 30]],
            ],
        }}]
        result = canonicalize_engine_output(raw, page, self.config, latency_ms=1)
        self.assertEqual([line.text for line in result.lines], ["left", "right", "bottom"])
        self.assertEqual([line.engine_index for line in result.lines], [2, 0, 1])

    def test_replacement_character_and_engine_exception_are_failures(self) -> None:
        page = preprocess_bytes(image_bytes("white"), self.preprocessing_config)
        raw = [{"res": {"rec_texts": ["Ng\ufffdy"], "rec_scores": [0.9], "dt_polys": [[[1, 1], [100, 1], [100, 20], [1, 20]]]}}]
        with self.assertRaises(OcrError) as context:
            canonicalize_engine_output(raw, page, self.config, latency_ms=1)
        self.assertEqual(context.exception.code, "OCR_UNICODE_REPLACEMENT_DETECTED")
        with self.assertRaises(OcrError) as context:
            extract_ocr(page, self.config, self.identity, FakeEngine(error=RuntimeError("boom")))
        self.assertEqual(context.exception.code, "OCR_ENGINE_FAILURE")

    def test_cache_is_content_config_and_model_addressed(self) -> None:
        first_page = preprocess_bytes(image_bytes("white"), self.preprocessing_config)
        second_page = preprocess_bytes(image_bytes("gray"), self.preprocessing_config)
        raw = [{"res": {"rec_texts": ["Ngày"], "rec_scores": [0.9], "dt_polys": [[[1, 1], [100, 1], [100, 20], [1, 20]]]}}]
        engine = FakeEngine(raw)
        with tempfile.TemporaryDirectory() as directory:
            cache = OcrCache(Path(directory), self.config, self.identity)
            first = cache.get_or_run(first_page, engine)
            repeated = cache.get_or_run(first_page, engine)
            second = cache.get_or_run(second_page, engine)
            self.assertFalse(first.cache_hit)
            self.assertTrue(repeated.cache_hit)
            self.assertFalse(second.cache_hit)
            self.assertEqual(engine.calls, 2)
            self.assertNotEqual(first.cache_key, second.cache_key)
            changed_config = replace(self.config, config_sha256="b" * 64)
            changed_cache = OcrCache(Path(directory), changed_config, self.identity)
            self.assertNotEqual(cache.key_for(first_page), changed_cache.key_for(first_page))
            changed_identity = replace(self.identity, model_manifest_sha256="c" * 64)
            model_cache = OcrCache(Path(directory), self.config, changed_identity)
            self.assertNotEqual(cache.key_for(first_page), model_cache.key_for(first_page))

    def test_config_freezes_runtime_models_and_low_score_policy(self) -> None:
        self.assertEqual(self.config.language, "vi")
        self.assertEqual(self.config.device, "cpu")
        self.assertEqual(self.config.text_rec_score_thresh, 0.0)
        self.assertEqual(self.config.cpu_threads, 1)
        self.assertEqual(self.config.detection_model_name, "PP-OCRv5_mobile_det")
        self.assertEqual(self.config.recognition_model_name, "latin_PP-OCRv5_mobile_rec")
        self.assertFalse(self.config.use_doc_orientation_classify)
        self.assertFalse(self.config.use_doc_unwarping)
        self.assertFalse(self.config.use_textline_orientation)


if __name__ == "__main__":
    unittest.main()
