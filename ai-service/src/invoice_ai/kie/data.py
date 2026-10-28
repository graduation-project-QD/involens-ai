"""Loader for the merged labeler output in ``dataset_hoadon/dataset_merge``."""

from __future__ import annotations

import ast
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from invoice_ai.kie.geometry import Polygon, bbox, flat_to_points, rotate_points, rotated_size
from invoice_ai.kie.labels import LABEL_TO_CATEGORY, LINE_ITEM_LABELS

SEPARATOR = "|||"


@dataclass(frozen=True)
class Region:
    index: int
    label: str
    text: str
    polygon: Polygon  # source-image pixels
    line_item_id: int | None


@dataclass(frozen=True)
class LabeledDocument:
    img_id: str
    split: str
    image_path: Path
    width: int
    height: int
    rotation_cw: int
    regions: tuple[Region, ...]
    missing_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def upright_size(self) -> tuple[int, int]:
        return rotated_size(self.width, self.height, self.rotation_cw)

    def upright(self, polygon: Polygon) -> Polygon:
        return rotate_points(polygon, self.width, self.height, self.rotation_cw)

    def upright_bbox(self, region: Region) -> tuple[float, float, float, float]:
        return bbox(self.upright(region.polygon))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_row(row: dict[str, str], split: str, image_dir: Path, rotation: int, missing: list[str]) -> LabeledDocument:
    img_id = row["img_id"]
    polygons = ast.literal_eval(row["anno_polygons"]) if row["anno_polygons"].strip() else []
    texts = row["anno_texts"].split(SEPARATOR) if polygons else []
    labels = row["anno_labels"].split(SEPARATOR) if polygons else []
    item_ids = json.loads(row.get("anno_line_item_ids") or "[]") or [None] * len(polygons)
    if not (len(polygons) == len(texts) == len(labels) == len(item_ids)):
        raise ValueError(f"{img_id}: polygon/text/label/line_item_id counts differ")
    regions = []
    width = height = 0
    for index, (polygon, text, label, item_id) in enumerate(zip(polygons, texts, labels, item_ids)):
        if LABEL_TO_CATEGORY.get(label) != int(polygon["category_id"]):
            raise ValueError(f"{img_id}#{index}: category_id does not match label {label}")
        if (label in LINE_ITEM_LABELS) != (item_id is not None):
            raise ValueError(f"{img_id}#{index}: line_item_id inconsistent with label {label}")
        width, height = int(polygon["width"]), int(polygon["height"])
        regions.append(Region(index, label, text, flat_to_points(polygon["segmentation"][0]), item_id))
    if not regions:
        from PIL import Image

        with Image.open(image_dir / img_id) as image:
            width, height = image.size
    return LabeledDocument(
        img_id=img_id,
        split=split,
        image_path=image_dir / img_id,
        width=width,
        height=height,
        rotation_cw=rotation,
        regions=tuple(regions),
        missing_fields=tuple(missing),
    )


def available_splits(dataset_dir: Path) -> list[str]:
    """Splits present in a dataset directory, in train/val/test order."""
    return [s for s in ("train", "val", "test") if (Path(dataset_dir) / f"mcocr_{s}_df.csv").exists()]


def load_split(dataset_dir: Path, split: str) -> list[LabeledDocument]:
    """Load ``mcocr_{split}_df.csv`` with rotation and missing-field sidecars (split: ``train``/``val``/``test``)."""
    dataset_dir = Path(dataset_dir)
    rows = _read_csv(dataset_dir / f"mcocr_{split}_df.csv")
    rotations = {
        r["img_id"]: int(r["rotation_to_upright"])
        for r in _read_csv(dataset_dir / f"mcocr_{split}_rotation.csv")
        if r["rotation_to_upright"].strip()
    }
    missing_path = dataset_dir / f"mcocr_{split}_df.missing_fields.json"
    missing = json.loads(missing_path.read_text(encoding="utf-8"))["images"] if missing_path.exists() else {}
    image_dir = dataset_dir / f"{split}_images"
    documents = []
    for row in rows:
        if row["img_id"] not in rotations:
            raise ValueError(f"{row['img_id']}: rotation_to_upright is not confirmed")
        documents.append(_parse_row(row, split, image_dir, rotations[row["img_id"]], missing.get(row["img_id"], [])))
    return documents
