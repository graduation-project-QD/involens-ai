from __future__ import annotations

import math
import unittest

import numpy as np

from invoice_ai.preprocessing.orientation import (
    DeskewParams,
    Observation,
    angular_error,
    decide,
    rotate_right_angle,
    text_skew,
)


def line_box(cx: float, cy: float, length: float, thickness: float, degrees: float) -> tuple[tuple[float, float], ...]:
    """Quad of a text line tilted ``degrees`` clockwise (image coordinates, y down)."""
    a = math.radians(degrees)
    ux, uy, vx, vy = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    hl, ht = length / 2, thickness / 2
    return (
        (cx - ux * hl - vx * ht, cy - uy * hl - vy * ht),
        (cx + ux * hl - vx * ht, cy + uy * hl - vy * ht),
        (cx + ux * hl + vx * ht, cy + uy * hl + vy * ht),
        (cx - ux * hl + vx * ht, cy - uy * hl + vy * ht),
    )


def page(degrees: float, count: int = 6) -> tuple[tuple[tuple[float, float], ...], ...]:
    return tuple(line_box(200, 100 + 40 * i, 240, 20, degrees) for i in range(count))


class OrientationTests(unittest.TestCase):
    def test_skew_sign_and_filters(self) -> None:
        for degrees in (0, 3, -4, 12):
            skew, used = text_skew(page(degrees))
            self.assertAlmostEqual(skew, degrees, places=3)
            self.assertEqual(used, 6)
        # Square-ish boxes (logos, digits) and too few lines are ignored.
        self.assertEqual(text_skew([line_box(50, 50, 30, 28, 20)] * 5)[1], 0)
        self.assertEqual(text_skew(page(5, count=2)), (0.0, 2))

    def test_weighted_median_resists_outliers(self) -> None:
        boxes = page(2) + (line_box(100, 400, 60, 10, 30),)
        self.assertAlmostEqual(text_skew(boxes)[0], 2, places=3)

    def test_decide_combines_classifier_and_skew(self) -> None:
        # Classifier label 270 (counter-clockwise) means the page needs 90° clockwise.
        result = decide(Observation(270, 0.9, page(-3), (0.9,) * 6))
        self.assertEqual(result.coarse_cw, 90)
        self.assertAlmostEqual(result.total_cw, 93.0)
        level = decide(Observation(0, 0.9, page(4), (0.9,) * 6))
        self.assertAlmostEqual(level.total_cw, 356.0)
        untouched = decide(Observation(0, 0.9, page(0.3), (0.9,) * 6), DeskewParams(min_abs_skew=0.5))
        self.assertEqual(untouched.total_cw, 0.0)

    def test_angular_error_wraps(self) -> None:
        self.assertEqual(angular_error(359.0, 1.0), 2.0)
        self.assertEqual(angular_error(90.0, 270.0), 180.0)

    def test_rotate_right_angle_shapes(self) -> None:
        image = np.zeros((10, 20, 3), np.uint8)
        self.assertEqual(rotate_right_angle(image, 90).shape, (20, 10, 3))
        self.assertEqual(rotate_right_angle(image, 0).shape, (10, 20, 3))


if __name__ == "__main__":
    unittest.main()
