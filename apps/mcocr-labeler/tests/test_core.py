from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mcocr_label_server", APP_ROOT / "server.py")
server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(server)


class AnnotationCoreTests(unittest.TestCase):
    def test_regions_to_row_calculates_derived_fields(self) -> None:
        row = server.regions_to_row(
            "receipt.jpg",
            [
                {
                    "label": "SELLER",
                    "text": "Cửa hàng A",
                    "segmentation": [10, 20, 110, 20, 110, 60, 10, 60],
                }
            ],
            width=640,
            height=480,
        )
        self.assertEqual(row["anno_num"], "1")
        self.assertEqual(row["anno_image_quality"], "")
        self.assertEqual(row["anno_line_item_ids"], "[null]")
        polygon = server.ast.literal_eval(row["anno_polygons"])[0]
        self.assertEqual(polygon["category_id"], 15)
        self.assertEqual(polygon["bbox"], [10, 20, 100, 40])
        self.assertEqual(polygon["area"], 4000)
        self.assertEqual((polygon["width"], polygon["height"]), (640, 480))

    def test_csv_roundtrip_preserves_vietnamese_text(self) -> None:
        row = server.regions_to_row(
            "receipt.jpg",
            [
                {
                    "label": "ADDRESS",
                    "text": "Chợ Sủi Phú Thị Gia Lâm",
                    "segmentation": [5, 5, 205, 5, 205, 35, 5, 35],
                }
            ],
            width=300,
            height=500,
        )
        encoded = server.encode_rows([row])
        parsed = server.parse_csv_text(encoded.decode("utf-8"))
        self.assertEqual(parsed[0]["anno_texts"], "Chợ Sủi Phú Thị Gia Lâm")
        self.assertEqual(server.row_to_regions(parsed[0])[0]["label"], "ADDRESS")

    def test_line_item_roundtrip_preserves_group_id(self) -> None:
        row = server.regions_to_row(
            "receipt.jpg",
            [
                {
                    "label": "ITEM_NAME",
                    "text": "Cà phê sữa",
                    "line_item_id": 2,
                    "segmentation": [10, 20, 210, 20, 210, 50, 10, 50],
                },
                {
                    "label": "LINE_TOTAL",
                    "text": "25000",
                    "line_item_id": 2,
                    "segmentation": [220, 20, 300, 20, 300, 50, 220, 50],
                },
            ],
            width=400,
            height=600,
        )
        self.assertEqual(row["anno_labels"], "ITEM_NAME|||LINE_TOTAL")
        self.assertEqual(row["anno_line_item_ids"], "[2,2]")
        regions = server.row_to_regions(row)
        self.assertEqual([region["line_item_id"] for region in regions], [2, 2])
        self.assertEqual([region["category_id"] for region in regions], [19, 22])

    def test_line_item_requires_positive_group_id(self) -> None:
        with self.assertRaises(server.ApiError):
            server.regions_to_row(
                "receipt.jpg",
                [
                    {
                        "label": "QUANTITY",
                        "text": "2",
                        "line_item_id": None,
                        "segmentation": [0, 0, 10, 0, 10, 10, 0, 10],
                    }
                ],
                100,
                100,
            )

    def test_multi_component_source_polygon_is_preserved(self) -> None:
        source_polygon = {
            "category_id": 18,
            "segmentation": [
                [1, 1, 2, 2, 1, 2],
                [10, 10, 90, 10, 90, 40, 10, 40],
            ],
            "area": 2400,
            "bbox": [10, 10, 80, 30],
            "width": 100,
            "height": 100,
        }
        source_row = {
            "img_id": "receipt.jpg",
            "anno_polygons": repr([source_polygon]),
            "anno_texts": "100000",
            "anno_labels": "TOTAL_COST",
            "anno_num": "1",
            "anno_image_quality": "",
            "anno_line_item_ids": "[null]",
        }
        regions = server.row_to_regions(source_row)
        self.assertEqual(regions[0]["segmentation"], [10, 10, 90, 10, 90, 40, 10, 40])
        saved = server.regions_to_row("receipt.jpg", regions, 100, 100)
        self.assertEqual(server.ast.literal_eval(saved["anno_polygons"])[0], source_polygon)

    def test_legacy_six_column_csv_is_accepted(self) -> None:
        text = (
            "img_id,anno_polygons,anno_texts,anno_labels,anno_num,anno_image_quality\n"
            "receipt.jpg,[],\"\",\"\",0,\n"
        )
        rows = server.parse_csv_text(text)
        self.assertEqual(rows[0]["anno_line_item_ids"], "")
        upgraded = server.encode_rows(rows).decode("utf-8-sig")
        self.assertIn("anno_line_item_ids", upgraded.splitlines()[0])

    def test_known_total_cost_alias_is_normalized(self) -> None:
        text = (
            "img_id,anno_polygons,anno_texts,anno_labels,anno_num,anno_image_quality\n"
            "receipt.jpg,\"[{'category_id': 18, 'segmentation': [[0, 0, 10, 0, 10, 10, 0, 10]], "
            "'bbox': [0, 0, 10, 10]}]\",100000,TOTAL_TOTAL_COST,1,\n"
        )
        rows = server.parse_csv_text(text)
        self.assertEqual(rows[0]["anno_labels"], "TOTAL_COST")

    def test_upsert_replaces_existing_img_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            first = server.regions_to_row(
                "receipt.jpg",
                [{"label": "SELLER", "text": "A", "segmentation": [0, 0, 10, 0, 10, 10, 0, 10]}],
                100,
                100,
            )
            second = server.regions_to_row(
                "receipt.jpg",
                [{"label": "SELLER", "text": "B", "segmentation": [0, 0, 20, 0, 20, 20, 0, 20]}],
                100,
                100,
            )
            server.upsert_row(path, first)
            server.upsert_row(path, second)
            rows = server.read_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["anno_texts"], "B")

    def test_train_save_allows_editing_document_fields(self) -> None:
        original = server.regions_to_row(
            "receipt.jpg",
            [{"label": "SELLER", "text": "Cửa hàng gốc", "segmentation": [0, 0, 50, 0, 50, 20, 0, 20]}],
            100,
            100,
            "0.82",
        )
        submitted = [
            {"label": "SELLER", "text": "Bị sửa", "segmentation": [0, 0, 10, 0, 10, 10, 0, 10]},
            {
                "label": "ITEM_NAME",
                "text": "Cà phê",
                "line_item_id": 1,
                "segmentation": [10, 30, 70, 30, 70, 50, 10, 50],
            },
        ]
        merged = server.regions_for_save("train", original, submitted)
        saved = server.regions_to_row("receipt.jpg", merged, 100, 100, original["anno_image_quality"])
        self.assertEqual(saved["anno_texts"], "Bị sửa|||Cà phê")
        self.assertEqual(saved["anno_labels"], "SELLER|||ITEM_NAME")
        self.assertEqual(saved["anno_line_item_ids"], "[null,1]")
        self.assertEqual(saved["anno_image_quality"], "0.82")

    def test_train_save_allows_deleting_original_document_fields(self) -> None:
        original = server.regions_to_row(
            "receipt.jpg",
            [{"label": "SELLER", "text": "Cửa hàng gốc", "segmentation": [0, 0, 50, 0, 50, 20, 0, 20]}],
            100,
            100,
        )
        submitted = [
            {
                "label": "ITEM_NAME",
                "text": "Cà phê",
                "line_item_id": 1,
                "segmentation": [10, 30, 70, 30, 70, 50, 10, 50],
            },
        ]
        saved = server.regions_to_row(
            "receipt.jpg",
            server.regions_for_save("train", original, submitted),
            100,
            100,
        )
        self.assertEqual(saved["anno_labels"], "ITEM_NAME")
        self.assertEqual(saved["anno_texts"], "Cà phê")

    def test_train_save_accepts_document_fields_on_blank_row(self) -> None:
        blank = {
            "img_id": "receipt.jpg",
            "anno_polygons": "[]",
            "anno_texts": "",
            "anno_labels": "",
            "anno_num": "0",
            "anno_image_quality": "",
            "anno_line_item_ids": "[]",
        }
        seller = {"label": "SELLER", "text": "Shop", "segmentation": [0, 0, 50, 0, 50, 20, 0, 20]}
        saved = server.regions_to_row("receipt.jpg", server.regions_for_save("train", blank, [seller]), 100, 100)
        self.assertEqual(saved["anno_labels"], "SELLER")
        self.assertEqual(server.regions_for_save("train", saved, []), [])

    def test_open_workspace_requires_exact_csv_image_match(self) -> None:
        original_config = server.WORKSPACE_CONFIG
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                server.WORKSPACE_CONFIG = root / "workspaces.json"
                image_dir = root / "images"
                image_dir.mkdir()
                server.Image.new("RGB", (20, 20), "white").save(image_dir / "receipt.jpg")
                csv_path = root / "labels.csv"
                server.write_rows(
                    csv_path,
                    [
                        {
                            "img_id": "receipt.jpg",
                            "anno_polygons": "[]",
                            "anno_texts": "",
                            "anno_labels": "",
                            "anno_num": "0",
                            "anno_image_quality": "",
                            "anno_line_item_ids": "[]",
                        }
                    ],
                )
                info, count = server.open_workspace("val", str(csv_path), str(image_dir))
                self.assertEqual(count, 1)
                self.assertEqual(Path(info["csv_path"]), csv_path)
                server.Image.new("RGB", (20, 20), "white").save(image_dir / "extra.jpg")
                with self.assertRaises(server.ApiError):
                    server.open_workspace("val", str(csv_path), str(image_dir))
        finally:
            server.WORKSPACE_CONFIG = original_config

    def test_open_workspace_initializes_empty_csv_from_images(self) -> None:
        original_config = server.WORKSPACE_CONFIG
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                server.WORKSPACE_CONFIG = root / "workspaces.json"
                image_dir = root / "images"
                image_dir.mkdir()
                for name in ("second.jpg", "first.jpg"):
                    server.Image.new("RGB", (20, 20), "white").save(image_dir / name)
                csv_path = root / "labels.csv"
                csv_path.touch()

                _, count = server.open_workspace("train", str(csv_path), str(image_dir))
                self.assertEqual(count, 2)
                rows = server.read_rows(csv_path)
                self.assertEqual([row["img_id"] for row in rows], ["first.jpg", "second.jpg"])
                self.assertTrue(all(row["anno_num"] == "0" for row in rows))
                self.assertTrue(all(row["anno_polygons"] == "[]" for row in rows))
                self.assertEqual(server.open_workspace("train", str(csv_path), str(image_dir))[1], 2)
        finally:
            server.WORKSPACE_CONFIG = original_config

    def test_workspace_flag_is_persisted_beside_csv(self) -> None:
        original_config = server.WORKSPACE_CONFIG
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                server.WORKSPACE_CONFIG = root / "workspaces.json"
                image_dir = root / "images"
                image_dir.mkdir()
                server.Image.new("RGB", (20, 20), "white").save(image_dir / "receipt.jpg")
                csv_path = root / "labels.csv"
                server.write_rows(
                    csv_path,
                    [
                        {
                            "img_id": "receipt.jpg",
                            "anno_polygons": "[]",
                            "anno_texts": "",
                            "anno_labels": "",
                            "anno_num": "0",
                            "anno_image_quality": "",
                            "anno_line_item_ids": "[]",
                        }
                    ],
                )
                server.open_workspace("val", str(csv_path), str(image_dir))
                flagged, flag_path = server.set_workspace_flagged("val", "receipt.jpg", True)
                self.assertTrue(flagged)
                self.assertEqual(flag_path, root / "labels.flagged.json")
                self.assertTrue(flag_path.is_file())
                self.assertTrue(server.list_workspace_images("val")[0]["flagged"])
                unflagged, _ = server.set_workspace_flagged("val", "receipt.jpg", False)
                self.assertFalse(unflagged)
                self.assertFalse(server.list_workspace_images("val")[0]["flagged"])
        finally:
            server.WORKSPACE_CONFIG = original_config

    def test_workspace_rotation_is_persisted_in_separate_csv(self) -> None:
        original_config = server.WORKSPACE_CONFIG
        original_backup_dir = server.BACKUP_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                server.WORKSPACE_CONFIG = root / "workspaces.json"
                server.BACKUP_DIR = root / "backups"
                image_dir = root / "images"
                image_dir.mkdir()
                server.Image.new("RGB", (20, 30), "white").save(image_dir / "receipt.jpg")
                csv_path = root / "mcocr_train_df.csv"
                server.write_rows(
                    csv_path,
                    [{
                        "img_id": "receipt.jpg",
                        "anno_polygons": "[]",
                        "anno_texts": "",
                        "anno_labels": "",
                        "anno_num": "0",
                        "anno_image_quality": "",
                        "anno_line_item_ids": "[]",
                    }],
                )
                info, _ = server.open_workspace("train", str(csv_path), str(image_dir))
                rotation, path = server.set_workspace_rotation("train", "receipt.jpg", 0)
                self.assertEqual(rotation, 0)
                self.assertEqual(path, root / "mcocr_train_rotation.csv")
                self.assertEqual(server.workspace_rotations(info), {"receipt.jpg": 0})
                server.set_workspace_rotation("train", "receipt.jpg", 270)
                self.assertEqual(server.workspace_rotations(info), {"receipt.jpg": 270})
                image = server.list_workspace_images("train")[0]
                self.assertTrue(image["rotation_confirmed"])
                self.assertEqual(image["rotation_to_upright"], 270)
        finally:
            server.WORKSPACE_CONFIG = original_config
            server.BACKUP_DIR = original_backup_dir

    def test_workspace_rotation_rejects_non_quarter_turn(self) -> None:
        with self.assertRaises(server.ApiError):
            server.set_workspace_rotation("train", "receipt.jpg", 45)

    def test_completeness_accepts_explicitly_missing_fields(self) -> None:
        regions = [{"label": "ITEM_NAME", "line_item_id": 1}]
        missing = ["QUANTITY:1", "UNIT_PRICE:1", "LINE_TOTAL:1"]
        self.assertEqual(server.annotation_completeness_issues("train", regions, missing), [])
        val_issues = server.annotation_completeness_issues("val", regions, missing)
        self.assertIn("thiếu SELLER", val_issues)
        self.assertIn("thiếu ADDRESS", val_issues)

    def test_completion_requires_complete_labels_and_rotation(self) -> None:
        original_config = server.WORKSPACE_CONFIG
        original_backup_dir = server.BACKUP_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                server.WORKSPACE_CONFIG = root / "workspaces.json"
                server.BACKUP_DIR = root / "backups"
                image_dir = root / "images"
                image_dir.mkdir()
                server.Image.new("RGB", (20, 30), "white").save(image_dir / "receipt.jpg")
                csv_path = root / "mcocr_train_df.csv"
                row = server.regions_to_row(
                    "receipt.jpg",
                    [{
                        "label": "ITEM_NAME",
                        "text": "Cà phê",
                        "line_item_id": 1,
                        "segmentation": [1, 1, 10, 1, 10, 5, 1, 5],
                    }],
                    20,
                    30,
                )
                server.write_rows(csv_path, [row])
                server.open_workspace("train", str(csv_path), str(image_dir))
                with self.assertRaises(server.ApiError):
                    server.set_workspace_completed("train", "receipt.jpg", True)
                server.set_workspace_missing_fields(
                    "train",
                    "receipt.jpg",
                    ["QUANTITY:1", "UNIT_PRICE:1", "LINE_TOTAL:1"],
                )
                with self.assertRaises(server.ApiError):
                    server.set_workspace_completed("train", "receipt.jpg", True)
                server.set_workspace_rotation("train", "receipt.jpg", 0)
                self.assertTrue(server.set_workspace_completed("train", "receipt.jpg", True))
        finally:
            server.WORKSPACE_CONFIG = original_config
            server.BACKUP_DIR = original_backup_dir


if __name__ == "__main__":
    unittest.main()
