from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from invoice_ai.preprocessing import PreprocessingError, load_config, preprocess_bytes, preprocess_path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "preprocessing" / "v1.json"


def encoded_image(mode: str, size: tuple[int, int], fmt: str = "PNG", *, orientation: int | None = None) -> bytes:
    if mode == "RGBA":
        image = Image.new(mode, size, (10, 20, 30, 0))
    elif mode == "L":
        image = Image.new(mode, size, 77)
    else:
        image = Image.new(mode, size, (10, 20, 30))
    output = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    image.save(output, format=fmt, exif=exif)
    return output.getvalue()


class PreprocessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(CONFIG_PATH)
        fixture_path = Path(__file__).parent / "fixtures" / "preprocessing_v1.json"
        cls.golden = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_golden_fixture_rubric_is_versioned(self) -> None:
        self.assertEqual(self.golden["pipeline_version"], self.config.pipeline_version)
        self.assertEqual(len(self.golden["cases"]), 7)

    def test_resize_preserves_geometry_and_round_trip(self) -> None:
        page = preprocess_bytes(encoded_image("RGB", (4000, 1000)), self.config)
        self.assertEqual(page.image.size, (2000, 500))
        polygon = [[0, 0], [4000, 0], [4000, 1000], [0, 1000], [100, 250]]
        mapped = page.transform.map_points(polygon)
        restored = page.transform.map_points(mapped, inverse=True)
        self.assertLessEqual(max(abs(a - b) for left, right in zip(polygon, restored) for a, b in zip(left, right)), 1e-9)
        self.assertEqual(page.transform.map_bbox([100, 100, 900, 500]), [50.0, 50.0, 450.0, 250.0])

    def test_small_image_is_not_upscaled(self) -> None:
        page = preprocess_bytes(encoded_image("RGB", (120, 80)), self.config)
        self.assertEqual(page.image.size, (120, 80))
        self.assertFalse(page.transform.steps[-1].parameters["applied"])

    def test_exif_orientation_6_rotates_frame_and_is_reversible(self) -> None:
        page = preprocess_bytes(encoded_image("RGB", (40, 20), "JPEG", orientation=6), self.config)
        self.assertEqual(page.image.size, (20, 40))
        self.assertEqual(page.transform.map_points([[0, 0], [40, 20]]), [[20.0, 0.0], [0.0, 40.0]])
        restored = page.transform.map_points([[20, 0], [0, 40]], inverse=True)
        self.assertEqual(restored, [[0.0, 0.0], [40.0, 20.0]])
        mapped_bbox = page.transform.map_bbox([5, 2, 30, 15])
        self.assertEqual(page.transform.map_bbox(mapped_bbox, inverse=True), [5.0, 2.0, 30.0, 15.0])

    def test_all_exif_orientations_have_reversible_corner_geometry(self) -> None:
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                page = preprocess_bytes(encoded_image("RGB", (40, 20), "JPEG", orientation=orientation), self.config)
                expected_size = (20, 40) if orientation >= 5 else (40, 20)
                self.assertEqual(page.image.size, expected_size)
                source = [[0, 0], [40, 0], [40, 20], [0, 20]]
                restored = page.transform.map_points(page.transform.map_points(source), inverse=True)
                self.assertLessEqual(
                    max(abs(a - b) for left, right in zip(source, restored) for a, b in zip(left, right)),
                    1e-9,
                )

    def test_rgba_uses_white_background_and_gray_becomes_rgb(self) -> None:
        rgba = preprocess_bytes(encoded_image("RGBA", (8, 5)), self.config)
        gray = preprocess_bytes(encoded_image("L", (8, 5)), self.config)
        self.assertEqual(rgba.image.mode, "RGB")
        self.assertEqual(rgba.image.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(gray.image.mode, "RGB")
        self.assertEqual(gray.image.getpixel((0, 0)), (77, 77, 77))

    def test_out_of_bounds_and_corrupt_input_are_rejected(self) -> None:
        page = preprocess_bytes(encoded_image("RGB", (100, 50)), self.config)
        with self.assertRaisesRegex(PreprocessingError, "outside") as context:
            page.transform.map_points([[101, 10]])
        self.assertEqual(context.exception.code, "POINT_OUT_OF_BOUNDS")
        with self.assertRaises(PreprocessingError) as corrupt:
            preprocess_bytes(b"not an image", self.config)
        self.assertEqual(corrupt.exception.code, "IMAGE_DECODE_ERROR")

    def test_request_limit_is_separate_from_internal_dataset_decode(self) -> None:
        payload = encoded_image("RGB", (20, 10))
        strict = replace(self.config, request_max_pixels=100)
        with self.assertRaises(PreprocessingError) as rejected:
            preprocess_bytes(payload, strict)
        self.assertEqual(rejected.exception.code, "PIXEL_LIMIT_EXCEEDED")
        internal = preprocess_bytes(payload, strict, enforce_request_limits=False)
        self.assertIn("REQUEST_PIXEL_LIMIT_EXCEEDED_INTERNAL_DATASET_ONLY", internal.warnings)

    def test_raw_source_and_output_are_deterministic(self) -> None:
        payload = encoded_image("RGB", (2400, 1200))
        first = preprocess_bytes(payload, self.config)
        second = preprocess_bytes(payload, self.config)
        self.assertEqual(first.source_bytes, payload)
        self.assertEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.pixel_sha256, second.pixel_sha256)
        self.assertEqual(first.to_manifest(), second.to_manifest())
        json.dumps(first.to_manifest(), allow_nan=False)

    def test_path_wrapper_and_optional_transform_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            path.write_bytes(encoded_image("RGB", (20, 10)))
            self.assertEqual(preprocess_path(path, self.config).image.size, (20, 10))
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            payload["deskew"]["enabled"] = True
            bad_config = Path(directory) / "bad.json"
            bad_config.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "validation evidence"):
                load_config(bad_config)


if __name__ == "__main__":
    unittest.main()
