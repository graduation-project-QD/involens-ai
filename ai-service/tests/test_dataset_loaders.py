from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invoice_ai.datasets.common import AnnotationError, polygon_bbox  # noqa: E402
from invoice_ai.datasets.mcocr import load_mcocr  # noqa: E402
from invoice_ai.datasets.schema import validate_document  # noqa: E402
from invoice_ai.datasets.sroie import load_sroie, parse_box_line  # noqa: E402


def create_image(path: Path, size: tuple[int, int] = (100, 80)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)


class SroieParserTests(unittest.TestCase):
    def test_box_parser_preserves_commas_in_transcript(self) -> None:
        coordinates, text = parse_box_line("0,0,50,0,50,20,0,20,NO. 5, ROAD A, CITY")
        self.assertEqual(8, len(coordinates))
        self.assertEqual("NO. 5, ROAD A, CITY", text)

    def test_degenerate_polygon_is_rejected(self) -> None:
        with self.assertRaisesRegex(AnnotationError, "zero area"):
            polygon_bbox([1, 2, 1, 2, 1, 2, 1, 2], 100, 80)

    def test_loader_preserves_missing_empty_and_unlabeled_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for split in ("train", "test"):
                for folder in ("img", "box", "entities"):
                    (root / split / folder).mkdir(parents=True)
            create_image(root / "train/img/A.jpg")
            (root / "train/box/A.txt").write_text(
                "0,0,50,0,50,20,0,20,ADDRESS, WITH, COMMA\n"
                "0,30,50,30,50,50,0,50,***\n",
                encoding="utf-8",
            )
            (root / "train/entities/A.txt").write_text(
                json.dumps({"company": "Shop", "date": "01/02/2020", "total": ""}),
                encoding="utf-8",
            )
            result = load_sroie(root, dataset_version="fixture")
            self.assertEqual(1, len(result.documents))
            self.assertFalse(result.quarantine)
            document = result.documents[0]
            self.assertEqual("source_missing", document.fields["address"].status)
            self.assertIsNone(document.fields["address"].raw_value)
            self.assertEqual("annotated_empty", document.fields["total"].status)
            self.assertIsNone(document.fields["total"].raw_value)
            self.assertEqual("unlabeled", document.regions[0].label_status)
            self.assertEqual("uncertain_marker", document.regions[1].label_status)
            validate_document(document)

    def test_non_utf8_annotation_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for split in ("train", "test"):
                for folder in ("img", "box", "entities"):
                    (root / split / folder).mkdir(parents=True)
            create_image(root / "test/img/B.jpg")
            (root / "test/box/B.txt").write_bytes(b"0,0,50,0,50,20,0,20,A\xa3\xac")
            (root / "test/entities/B.txt").write_text(
                json.dumps({"company": "A", "address": "B", "date": "1/1/2020", "total": "1.00"}),
                encoding="utf-8",
            )
            result = load_sroie(root, dataset_version="fixture")
            self.assertFalse(result.documents)
            self.assertEqual(["NON_UTF8_ANNOTATION"], result.quarantine[0].reason_codes)


class McocrLoaderTests(unittest.TestCase):
    headers = [
        "img_id",
        "anno_polygons",
        "anno_texts",
        "anno_labels",
        "anno_num",
        "anno_image_quality",
    ]

    def _root_with_rows(self, rows: list[dict[str, str]]) -> Path:
        root = Path(self.temp_directory.name)
        image_dir = root / "train_images/train_images"
        image_dir.mkdir(parents=True)
        for row in rows:
            create_image(image_dir / row["img_id"])
        with (root / "mcocr_train_df.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.headers)
            writer.writeheader()
            writer.writerows(rows)
        return root

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_valid_multipart_polygon_and_multiline_field(self) -> None:
        polygons = [
            {
                "category_id": 16,
                "segmentation": [[0, 0, 40, 0, 40, 10, 0, 10], [0, 15, 40, 15, 40, 25, 0, 25]],
                "bbox": [0, 0, 40, 25],
                "width": 100,
                "height": 80,
            },
            {
                "category_id": 16,
                "segmentation": [[0, 30, 40, 30, 40, 40, 0, 40]],
                "bbox": [0, 30, 40, 10],
                "width": 100,
                "height": 80,
            },
        ]
        rows = [{
            "img_id": "receipt.jpg",
            "anno_polygons": repr(polygons),
            "anno_texts": "Line one|||Line two",
            "anno_labels": "ADDRESS|||ADDRESS",
            "anno_num": "2",
            "anno_image_quality": "0.75",
        }]
        result = load_mcocr(self._root_with_rows(rows), dataset_version="fixture")
        self.assertFalse(result.quarantine)
        document = result.documents[0]
        self.assertEqual("Line one\nLine two", document.fields["address"].raw_value)
        self.assertEqual(2, len(document.regions[0].polygons))
        self.assertEqual("unlabeled", document.fields["company"].status)
        validate_document(document)

    def test_empty_annotation_and_unknown_label_are_quarantined(self) -> None:
        unknown_polygon = [{
            "category_id": 18,
            "segmentation": [[0, 0, 30, 0, 30, 10, 0, 10]],
            "bbox": [0, 0, 30, 10],
            "width": 100,
            "height": 80,
        }]
        rows = [
            {
                "img_id": "empty.jpg",
                "anno_polygons": "[]",
                "anno_texts": "",
                "anno_labels": "",
                "anno_num": "0",
                "anno_image_quality": "0.5",
            },
            {
                "img_id": "unknown.jpg",
                "anno_polygons": repr(unknown_polygon),
                "anno_texts": "100",
                "anno_labels": "TOTAL_TOTAL_COST",
                "anno_num": "1",
                "anno_image_quality": "0.5",
            },
        ]
        result = load_mcocr(self._root_with_rows(rows), dataset_version="fixture")
        self.assertFalse(result.documents)
        reasons = {record.document_id: record.reason_codes for record in result.quarantine}
        self.assertEqual(["EMPTY_DOCUMENT_ANNOTATION"], reasons["empty.jpg"])
        self.assertEqual(["UNKNOWN_SOURCE_LABEL"], reasons["unknown.jpg"])


if __name__ == "__main__":
    unittest.main()
