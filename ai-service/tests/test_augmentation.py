from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

from invoice_ai.preprocessing import load_config, preprocess_bytes
from invoice_ai.preprocessing.augmentation import AugmentationError, augment_page, load_augmentation_config


ROOT = Path(__file__).resolve().parents[1]
PREPROCESS_CONFIG = ROOT / "configs" / "preprocessing" / "v1.json"
AUGMENT_CONFIG = ROOT.parent / "experiments" / "configs" / "layoutxlm" / "augmentation_v1.json"


def source_image() -> bytes:
    image = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 180, 80), fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class AugmentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.page = preprocess_bytes(source_image(), load_config(PREPROCESS_CONFIG))
        cls.config = load_augmentation_config(AUGMENT_CONFIG)

    def test_disabled_by_default_preserves_image_and_transform(self) -> None:
        result = augment_page(self.page, self.config, document_id="doc-1", split="train")
        self.assertEqual(result.status, "SKIPPED_DISABLED")
        self.assertEqual(result.image.tobytes(), self.page.image.tobytes())
        self.assertEqual(result.transform.to_dict(), self.page.transform.to_dict())

    def test_validation_and_test_are_always_rejected(self) -> None:
        for split in ("validation", "test"):
            with self.subTest(split=split), self.assertRaises(AugmentationError) as context:
                augment_page(self.page, self.config, document_id="doc-1", split=split, allow_disabled_preview=True)
            self.assertEqual(context.exception.code, "SPLIT_NOT_ALLOWED")

    def test_preview_is_deterministic_and_cache_is_namespaced(self) -> None:
        first = augment_page(self.page, self.config, document_id="doc-1", split="train", allow_disabled_preview=True)
        second = augment_page(self.page, self.config, document_id="doc-1", split="train", allow_disabled_preview=True)
        self.assertEqual(first.to_manifest(), second.to_manifest())
        self.assertEqual(first.pixel_sha256, second.pixel_sha256)
        self.assertEqual(first.cache_namespace, second.cache_namespace)
        self.assertNotEqual(first.cache_namespace, self.page.source_sha256)

    def test_forced_operations_keep_geometry_reversible_and_do_not_crop(self) -> None:
        forced = replace(
            self.config,
            enabled=True,
            rotation_probability=1.0,
            brightness_probability=1.0,
            blur_probability=1.0,
        )
        result = augment_page(self.page, forced, document_id="geometry", split="train")
        self.assertEqual([item["applied"] for item in result.operations], [True, True, True])
        source = [[0, 0], [400, 0], [400, 200], [0, 200], [20, 20], [180, 80]]
        mapped = result.transform.map_points(source)
        restored = result.transform.map_points(mapped, inverse=True)
        self.assertLessEqual(max(abs(a - b) for left, right in zip(source, restored) for a, b in zip(left, right)), 1e-9)
        self.assertTrue(all(0 <= x <= result.image.width and 0 <= y <= result.image.height for x, y in mapped))
        source_bbox = [20, 20, 180, 80]
        source_bbox_corners = [[20, 20], [180, 20], [180, 80], [20, 80]]
        mapped_bbox_corners = result.transform.map_points(source_bbox_corners)
        x0, y0, x1, y1 = result.transform.map_bbox(source_bbox)
        self.assertTrue(all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in mapped_bbox_corners))
        self.assertTrue(0 <= x0 < x1 <= result.image.width)
        self.assertTrue(0 <= y0 < y1 <= result.image.height)
        self.assertGreaterEqual(result.image.width, self.page.image.width)
        self.assertGreaterEqual(result.image.height, self.page.image.height)

    def test_document_identity_changes_deterministic_seed(self) -> None:
        first = augment_page(self.page, self.config, document_id="doc-a", split="train", allow_disabled_preview=True)
        second = augment_page(self.page, self.config, document_id="doc-b", split="train", allow_disabled_preview=True)
        self.assertNotEqual(first.derived_seed, second.derived_seed)
        self.assertNotEqual(first.cache_namespace, second.cache_namespace)

    def test_config_rejects_non_train_scope_and_ocr_claims(self) -> None:
        payload = json.loads(AUGMENT_CONFIG.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            payload["allowed_splits"] = ["train", "validation"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "train-only"):
                load_augmentation_config(path)
            payload["allowed_splits"] = ["train"]
            payload["ocr_policy"]["claim_ocr_robustness"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "OCR claims"):
                load_augmentation_config(path)


if __name__ == "__main__":
    unittest.main()
