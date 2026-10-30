from __future__ import annotations

import io
import unittest

import numpy as np
from PIL import Image

from invoice_ai.inference.pipeline import PipelineError, decode_image, reading_order_lines, upright_page
from invoice_ai.kie.tokenize_layoutxlm import model_image


def jpeg_bytes(width: int = 40, height: int = 20, exif_orientation: int | None = None) -> bytes:
    image = Image.new("RGB", (width, height), (200, 10, 10))
    image.paste((10, 10, 200), (0, 0, width // 2, height))  # left half blue, to see rotations
    buffer = io.BytesIO()
    exif = Image.Exif()
    if exif_orientation:
        exif[274] = exif_orientation
    image.save(buffer, format="JPEG", quality=95, exif=exif)
    return buffer.getvalue()


class DecodeTests(unittest.TestCase):
    def test_plain_image_keeps_original_bytes(self):
        data = jpeg_bytes()
        rgb, page = decode_image(data)
        self.assertEqual(rgb.shape, (20, 40, 3))
        self.assertIs(page, data)

    def test_exif_orientation_is_applied(self):
        rgb, page = decode_image(jpeg_bytes(exif_orientation=6))  # 6 = rotate 90° clockwise to display
        self.assertEqual(rgb.shape, (40, 20, 3))
        self.assertEqual(Image.open(io.BytesIO(page)).size, (20, 40))

    def test_garbage_raises_decode_error(self):
        with self.assertRaises(PipelineError) as raised:
            decode_image(b"not an image")
        self.assertEqual(raised.exception.code, "IMAGE_DECODE_FAILED")


class UprightPageTests(unittest.TestCase):
    def test_zero_angle_returns_original_bytes(self):
        data = jpeg_bytes()
        rgb, page = decode_image(data)
        self.assertIs(upright_page(rgb, page, 0.0), data)
        self.assertIs(upright_page(rgb, page, 360.0), data)

    def test_right_angle_swaps_size_and_is_jpeg(self):
        rgb, page = decode_image(jpeg_bytes())
        rotated = Image.open(io.BytesIO(upright_page(rgb, page, 90.0)))
        self.assertEqual((rotated.format, rotated.size), ("JPEG", (20, 40)))

    def test_small_angle_expands_canvas(self):
        rgb, page = decode_image(jpeg_bytes(400, 200))
        width, height = Image.open(io.BytesIO(upright_page(rgb, page, 3.0))).size
        self.assertGreater(width, 400)
        self.assertGreater(height, 200)


class ReadingOrderTests(unittest.TestCase):
    def test_drops_empty_and_implausible_and_orders_rows(self):
        boxes = [
            [[100, 50], [200, 50], [200, 70], [100, 70]],  # second row, right
            [[0, 0], [300, 0], [300, 20], [0, 20]],  # first row
            [[0, 52], [80, 52], [80, 70], [0, 70]],  # second row, left
            [[0, 100], [10, 100], [10, 108], [0, 108]],  # tiny box with a long hallucinated reading
            [[0, 200], [100, 200], [100, 220], [0, 220]],  # empty reading
        ]
        texts = ["12.000", "NHÀ SÁCH", "Bút bi", "Phúc Anh Minimart", " "]
        lines = reading_order_lines(boxes, texts, [0.9] * 5)
        self.assertEqual([line.text for line in lines], ["NHÀ SÁCH", "Bút bi", "12.000"])
        self.assertEqual(lines[0].polygon[0], (0.0, 0.0))

    def test_no_text(self):
        self.assertEqual(reading_order_lines([], [], []), [])


class ModelImageTests(unittest.TestCase):
    def test_model_image_is_224_rgb(self):
        image = model_image(Image.new("L", (300, 500)))
        self.assertEqual((image.mode, image.size), ("RGB", (224, 224)))
        self.assertEqual(np.asarray(image).shape, (224, 224, 3))


if __name__ == "__main__":
    unittest.main()
