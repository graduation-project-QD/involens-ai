from __future__ import annotations

import unittest

import numpy as np

from invoice_ai.ocr.preprocess_benchmark import region_match, substring_distance
from invoice_ai.preprocessing.enhance import clahe


class EndToEndMatchTests(unittest.TestCase):
    def test_substring_distance_ignores_surrounding_text(self) -> None:
        self.assertEqual(substring_distance("10/08/2020", "Ngày: 10/08/2020 (07:58 CH)"), 0)
        self.assertEqual(substring_distance("35.000", "35.00"), 1)

    def test_region_match_uses_best_line(self) -> None:
        lines = ["HÓA ĐƠN THANH TOÁN", "Tổng thanh toán 135.000đ"]
        self.assertEqual(region_match("135.000đ", lines), 0.0)
        self.assertAlmostEqual(region_match("135.001đ", lines), 1 / 8)
        self.assertEqual(region_match("xyz", []), 1.0)


class ClaheTests(unittest.TestCase):
    def test_clahe_keeps_shape_and_raises_contrast(self) -> None:
        image = np.full((64, 64, 3), 120, np.uint8)
        image[20:40, 20:40] = 135
        out = clahe(image)
        self.assertEqual(out.shape, image.shape)
        self.assertGreater(int(out[30, 30, 0]) - int(out[5, 5, 0]), 15 - 1)


if __name__ == "__main__":
    unittest.main()
