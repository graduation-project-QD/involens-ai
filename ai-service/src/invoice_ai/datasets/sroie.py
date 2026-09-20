"""SROIE adapter for paired image, OCR box, and KIE entity files."""

from __future__ import annotations

from pathlib import Path

from .common import AnnotationError, image_metadata, polygon_bbox, read_json_object, read_utf8_strict
from .schema import (
    CANONICAL_FIELDS,
    SCHEMA_VERSION,
    CanonicalDocument,
    FieldAnnotation,
    LoadResult,
    QuarantineRecord,
    RegionAnnotation,
)

UNCERTAIN_MARKERS = {"***"}


def parse_box_line(line: str) -> tuple[list[float], str]:
    """Parse eight coordinates while preserving commas inside transcripts."""
    parts = line.split(",", 8)
    if len(parts) != 9:
        raise AnnotationError("INVALID_BOX_LINE", "Expected 8 coordinates and transcript")
    try:
        coordinates = [float(value) for value in parts[:8]]
    except ValueError as exc:
        raise AnnotationError("INVALID_BOX_COORDINATE", "Box coordinate is not numeric") from exc
    return coordinates, parts[8]


def _convert_document(root: Path, split: str, document_id: str, dataset_version: str) -> CanonicalDocument:
    image_path = root / split / "img" / f"{document_id}.jpg"
    box_path = root / split / "box" / f"{document_id}.txt"
    entity_path = root / split / "entities" / f"{document_id}.txt"
    width, height, image_hash = image_metadata(image_path)
    box_text = read_utf8_strict(box_path)
    regions: list[RegionAnnotation] = []
    for line_index, line in enumerate(box_text.splitlines(), 1):
        if not line.strip():
            continue
        coordinates, transcript = parse_box_line(line)
        points, bbox = polygon_bbox(coordinates, width, height)
        regions.append(
            RegionAnnotation(
                region_id=f"r{line_index:04d}",
                text=transcript,
                polygons=[points],
                bbox_xyxy=bbox,
                field=None,
                source_label=None,
                label_status="uncertain_marker" if transcript.strip() in UNCERTAIN_MARKERS else "unlabeled",
            )
        )

    entities = read_json_object(entity_path)
    unknown_keys = sorted(set(entities) - set(CANONICAL_FIELDS))
    qa_flags: list[str] = []
    if unknown_keys:
        qa_flags.append("UNKNOWN_ENTITY_KEYS")
    fields: dict[str, FieldAnnotation] = {}
    for name in CANONICAL_FIELDS:
        if name not in entities:
            fields[name] = FieldAnnotation(status="source_missing", raw_value=None, source_key=name)
            qa_flags.append(f"SOURCE_MISSING_{name.upper()}")
            continue
        value = entities[name]
        if not isinstance(value, str):
            raise AnnotationError("NONSTRING_ENTITY_VALUE", f"Entity {name} must be a string", field=name)
        if value == "":
            fields[name] = FieldAnnotation(status="annotated_empty", raw_value=None, source_key=name)
            qa_flags.append(f"ANNOTATED_EMPTY_{name.upper()}")
        else:
            fields[name] = FieldAnnotation(status="annotated", raw_value=value, source_key=name)

    if any(region.label_status == "uncertain_marker" for region in regions):
        qa_flags.append("UNCERTAIN_OCR_MARKER")

    return CanonicalDocument(
        schema_version=SCHEMA_VERSION,
        dataset="sroie_2019",
        dataset_version=dataset_version,
        document_id=document_id,
        source_partition=split,
        split=split,
        locale=None,
        image_path=image_path.relative_to(root).as_posix(),
        image_sha256=image_hash,
        width=width,
        height=height,
        annotation_coverage="ocr_regions_plus_document_fields_without_gold_alignment",
        fields=fields,
        regions=regions,
        qa_flags=sorted(set(qa_flags)),
        source_metadata={
            "source_format": "sroie_box_and_entities_txt",
            "unknown_entity_keys": unknown_keys,
            "ocr_region_count": len(regions),
        },
    )


def load_sroie(root: Path, dataset_version: str = "local_inspected_2026-09-14") -> LoadResult:
    result = LoadResult()
    for split in ("train", "test"):
        image_dir = root / split / "img"
        box_dir = root / split / "box"
        entity_dir = root / split / "entities"
        image_ids = {path.stem for path in image_dir.glob("*.jpg")}
        box_ids = {path.stem for path in box_dir.glob("*.txt")}
        entity_ids = {path.stem for path in entity_dir.glob("*.txt")}
        all_ids = sorted(image_ids | box_ids | entity_ids)
        for document_id in all_ids:
            missing = [
                kind
                for kind, members in (("image", image_ids), ("box", box_ids), ("entities", entity_ids))
                if document_id not in members
            ]
            if missing:
                result.quarantine.append(
                    QuarantineRecord(
                        dataset="sroie_2019",
                        document_id=document_id,
                        source_partition=split,
                        reason_codes=["MISSING_PAIRED_FILE"],
                        details={"missing": missing},
                    )
                )
                continue
            try:
                result.documents.append(_convert_document(root, split, document_id, dataset_version))
            except AnnotationError as exc:
                result.quarantine.append(
                    QuarantineRecord(
                        dataset="sroie_2019",
                        document_id=document_id,
                        source_partition=split,
                        reason_codes=[exc.code],
                        details={"message": str(exc), **exc.details},
                    )
                )
    return result
