"""MC-OCR adapter for the verified local CSV format."""

from __future__ import annotations

import ast
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from .common import AnnotationError, image_metadata, polygon_bbox
from .schema import (
    CANONICAL_FIELDS,
    SCHEMA_VERSION,
    CanonicalDocument,
    FieldAnnotation,
    LoadResult,
    QuarantineRecord,
    RegionAnnotation,
    empty_fields,
)

MCOCR_LABEL_MAP = {
    "SELLER": "company",
    "ADDRESS": "address",
    "TIMESTAMP": "date",
    "TOTAL_COST": "total",
}
MCOCR_CATEGORY_MAP = {15: "SELLER", 16: "ADDRESS", 17: "TIMESTAMP", 18: "TOTAL_COST"}


def _parse_literal_list(value: str, field_name: str) -> list[Any]:
    if value == "":
        return []
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise AnnotationError("INVALID_LITERAL", f"Cannot parse {field_name}") from exc
    if not isinstance(parsed, list):
        raise AnnotationError("INVALID_LITERAL_TYPE", f"{field_name} must be a list")
    return parsed


def _split_delimited(value: str) -> list[str]:
    return [] if value == "" else value.split("|||")


def _convert_row(row: dict[str, str], root: Path, dataset_version: str) -> CanonicalDocument:
    document_id = row["img_id"]
    image_path = root / "train_images" / "train_images" / document_id
    width, height, image_hash = image_metadata(image_path)
    polygons = _parse_literal_list(row["anno_polygons"], "anno_polygons")
    texts = _split_delimited(row["anno_texts"])
    labels = _split_delimited(row["anno_labels"])
    try:
        expected_count = int(row["anno_num"])
    except ValueError as exc:
        raise AnnotationError("INVALID_ANNO_NUM", "anno_num must be an integer") from exc
    if not (len(polygons) == len(texts) == len(labels) == expected_count):
        raise AnnotationError(
            "ANNOTATION_LENGTH_MISMATCH",
            "polygon/text/label/anno_num counts differ",
            counts=[len(polygons), len(texts), len(labels), expected_count],
        )
    if expected_count == 0:
        raise AnnotationError("EMPTY_DOCUMENT_ANNOTATION", "No annotated target regions")

    regions: list[RegionAnnotation] = []
    values: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for index, (source_polygon, text, source_label) in enumerate(zip(polygons, texts, labels)):
        if source_label not in MCOCR_LABEL_MAP:
            raise AnnotationError("UNKNOWN_SOURCE_LABEL", f"Unknown MC-OCR label: {source_label}")
        if not isinstance(source_polygon, dict):
            raise AnnotationError("INVALID_POLYGON_RECORD", "Polygon record must be an object")
        category_id = source_polygon.get("category_id")
        expected_source_label = MCOCR_CATEGORY_MAP.get(category_id)
        if expected_source_label != source_label:
            raise AnnotationError(
                "CATEGORY_LABEL_MISMATCH",
                "category_id and semantic label do not agree",
                category_id=category_id,
                source_label=source_label,
                expected_source_label=expected_source_label,
            )
        segmentation = source_polygon.get("segmentation")
        if not isinstance(segmentation, list) or not segmentation:
            raise AnnotationError("MISSING_SEGMENTATION", "segmentation must be a non-empty list")
        all_points: list[list[list[float]]] = []
        part_boxes: list[list[float]] = []
        for part in segmentation:
            if not isinstance(part, list):
                raise AnnotationError("INVALID_SEGMENTATION_PART", "segmentation part must be a list")
            points, part_bbox = polygon_bbox(part, width, height)
            all_points.append(points)
            part_boxes.append(part_bbox)
        bbox = [
            min(box[0] for box in part_boxes),
            min(box[1] for box in part_boxes),
            max(box[2] for box in part_boxes),
            max(box[3] for box in part_boxes),
        ]
        field_name = MCOCR_LABEL_MAP[source_label]
        region_id = f"r{index:04d}"
        regions.append(
            RegionAnnotation(
                region_id=region_id,
                text=text,
                polygons=all_points,
                bbox_xyxy=bbox,
                field=field_name,  # type: ignore[arg-type]
                source_label=source_label,
                label_status="mapped",
                source_metadata={"category_id": category_id},
            )
        )
        values[field_name].append((region_id, text))

    fields = empty_fields("unlabeled")
    for name in CANONICAL_FIELDS:
        candidates = values.get(name, [])
        if candidates:
            fields[name] = FieldAnnotation(
                status="annotated",
                raw_value="\n".join(value for _, value in candidates),
                region_ids=[region_id for region_id, _ in candidates],
                source_key=next(
                    key for key, mapped in MCOCR_LABEL_MAP.items() if mapped == name
                ),
            )

    annotation_widths = {record.get("width") for record in polygons if isinstance(record, dict)}
    annotation_heights = {record.get("height") for record in polygons if isinstance(record, dict)}
    if annotation_widths != {width} or annotation_heights != {height}:
        raise AnnotationError(
            "ANNOTATION_IMAGE_SIZE_MISMATCH",
            "Annotation dimensions differ from decoded image dimensions",
            annotation_widths=sorted(str(value) for value in annotation_widths),
            annotation_heights=sorted(str(value) for value in annotation_heights),
            image_size=[width, height],
        )

    return CanonicalDocument(
        schema_version=SCHEMA_VERSION,
        dataset="mcocr_2021",
        dataset_version=dataset_version,
        document_id=document_id,
        source_partition="train",
        split=None,
        locale="vi-VN",
        image_path=image_path.relative_to(root).as_posix(),
        image_sha256=image_hash,
        width=width,
        height=height,
        annotation_coverage="target_field_regions_only",
        fields=fields,
        regions=regions,
        source_metadata={
            "annotation_quality": float(row["anno_image_quality"]),
            "source_annotation_count": expected_count,
            "source_format": "mcocr_train_csv",
        },
    )


def load_mcocr(root: Path, dataset_version: str = "local_inspected_2026-09-14") -> LoadResult:
    result = LoadResult()
    csv_path = root / "mcocr_train_df.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "img_id",
            "anno_polygons",
            "anno_texts",
            "anno_labels",
            "anno_num",
            "anno_image_quality",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise AnnotationError("MISSING_CSV_COLUMNS", "MC-OCR CSV columns do not match expected format")
        for row in reader:
            document_id = row.get("img_id", "")
            try:
                result.documents.append(_convert_row(row, root, dataset_version))
            except AnnotationError as exc:
                result.quarantine.append(
                    QuarantineRecord(
                        dataset="mcocr_2021",
                        document_id=document_id,
                        source_partition="train",
                        reason_codes=[exc.code],
                        details={"message": str(exc), **exc.details},
                    )
                )
    return result
