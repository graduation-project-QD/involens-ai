from __future__ import annotations

import unittest
from pathlib import Path

from invoice_ai.kie.data import LabeledDocument, Region
import numpy as np

from invoice_ai.ocr.crops import edit_distance, normalize_ocr_text, rectified_crop
from invoice_ai.ocr.det_crops import plausible_text
from invoice_ai.ocr.detection_tuning import config_by_name, quantity_with_inference, score_document, text_crop_rect
from invoice_ai.ocr.recognition_eval import strip_marks


def rect(x0: float, y0: float, x1: float, y1: float) -> tuple[tuple[float, float], ...]:
    return (x0, y0), (x1, y0), (x1, y1), (x0, y1)


class CropTests(unittest.TestCase):
    def receipt_lines(self) -> list[tuple[tuple[float, float], ...]]:
        return [rect(300, 200 + 30 * i, 600, 220 + 30 * i) for i in range(12)]

    def test_crop_keeps_main_cluster_and_drops_watermark(self) -> None:
        boxes = self.receipt_lines() + [rect(20, 1250, 200, 1275)]  # camera watermark far below
        crop = text_crop_rect(boxes, [0.9] * len(boxes), 1000, 1300)
        self.assertIsNotNone(crop)
        x0, y0, x1, y1 = crop
        self.assertLessEqual(x0, 300 - 40)  # margin 2.5 x 20 px text height
        self.assertLessEqual(y0, 200 - 40)
        self.assertGreaterEqual(x1, 600 + 40)
        self.assertLess(y1, 1250)  # watermark excluded

    def test_no_crop_when_text_fills_page_or_too_few_boxes(self) -> None:
        full = [rect(10, 10 + 25 * i, 990, 30 + 25 * i) for i in range(50)]
        self.assertIsNone(text_crop_rect(full, [0.9] * 50, 1000, 1300))
        self.assertIsNone(text_crop_rect(self.receipt_lines()[:3], [0.9] * 3, 1000, 1300))

    def test_low_score_boxes_are_ignored(self) -> None:
        boxes = self.receipt_lines() + [rect(900, 1200, 990, 1290)]
        scores = [0.9] * 12 + [0.2]
        crop = text_crop_rect(boxes, scores, 1000, 1300)
        self.assertLess(crop[2], 900)


class ScoreTests(unittest.TestCase):
    def test_detected_merged_and_inside_crop(self) -> None:
        document = LabeledDocument(
            img_id="x.jpg",
            split="train",
            image_path=Path("x.jpg"),
            width=400,
            height=300,
            rotation_cw=0,
            regions=(
                Region(0, "QUANTITY", "1", rect(100, 100, 120, 120), 1),
                Region(1, "UNIT_PRICE", "5.000", rect(150, 100, 220, 120), 1),
                Region(2, "TOTAL_COST", "5.000", rect(300, 200, 370, 220), None),
            ),
        )
        record = {"boxes": [rect(95, 98, 225, 122)], "crop_rect": [50, 50, 350, 250]}  # one box spans qty + price
        rows = score_document(document, record)
        self.assertEqual([r["detected"] for r in rows], [True, True, False])
        self.assertEqual([r["merged"] for r in rows], [True, True, False])
        self.assertEqual([r["inside_crop"] for r in rows], [True, True, False])

    def test_threshold_variant_names(self) -> None:
        config = config_by_name("C1600_b0.45_u2.0")
        self.assertEqual((config.resize_long, config.box_thresh, config.unclip_ratio, config.crop), (1600, 0.45, 2.0, True))
        v6 = config_by_name("V6L1280_b0.3_t0.2")
        self.assertEqual((v6.model, v6.resize_long, v6.box_thresh, v6.thresh, v6.crop), ("PP-OCRv6_medium_det", 1280, 0.3, 0.2, False))


class QuantityInferenceTests(unittest.TestCase):
    def test_missing_quantity_recovered_from_price_and_total(self) -> None:
        document = LabeledDocument(
            img_id="q.jpg",
            split="train",
            image_path=Path("q.jpg"),
            width=400,
            height=300,
            rotation_cw=0,
            regions=(
                Region(0, "QUANTITY", "2", rect(100, 100, 110, 120), 1),
                Region(1, "UNIT_PRICE", "5.000", rect(150, 100, 220, 120), 1),
                Region(2, "LINE_TOTAL", "10.000", rect(250, 100, 320, 120), 1),
            ),
        )
        record = {"boxes": [rect(150, 100, 220, 120), rect(250, 100, 320, 120)], "crop_rect": None}
        result = quantity_with_inference({"q.jpg": document}, {"q.jpg": record}, ["q.jpg"])
        self.assertEqual((result["detected"], result["inferred_correct"], result["with_inference_rate"]), (0, 1, 1.0))


class PlausibleTextTests(unittest.TestCase):
    def test_tiny_box_cannot_hold_long_text(self) -> None:
        self.assertFalse(plausible_text("Phúc Anh Minimart", [(0, 0), (10, 0), (10, 8), (0, 8)]))
        self.assertTrue(plausible_text("1", [(0, 0), (6, 0), (6, 12), (0, 12)]))
        self.assertTrue(plausible_text("Số GD: 000AC2212008001565 Ngày: 11/08/2020-21:19", [(0, 0), (413, 0), (413, 36), (0, 36)]))


class CropTextTests(unittest.TestCase):
    def test_rectified_crop_is_horizontal_with_padding(self) -> None:
        image = np.zeros((200, 300, 3), np.uint8)
        crop = rectified_crop(image, [(50, 50), (250, 50), (250, 70), (50, 70)])
        self.assertGreater(crop.shape[1], crop.shape[0])
        self.assertAlmostEqual(crop.shape[0], 26, delta=1)  # 20 px line + 15% padding each side
        vertical = rectified_crop(image, [(100, 20), (120, 20), (120, 180), (100, 180)])
        self.assertGreater(vertical.shape[1], vertical.shape[0])

    def test_text_normalization_and_marks(self) -> None:
        self.assertEqual(normalize_ocr_text("  Cảm   ơn "), "Cảm ơn")
        self.assertEqual(strip_marks("Đường Trần Phú"), "Duong Tran Phu")
        self.assertEqual(edit_distance("abc", "abd"), 1)


if __name__ == "__main__":
    unittest.main()
