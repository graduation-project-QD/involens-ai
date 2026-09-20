"""Canonical dataset schema used by MC-OCR and SROIE adapters.

The schema intentionally represents missing, empty, and unlabeled annotations
as different states. Dataset adapters must not turn unknown regions into the
background label ``O``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CANONICAL_FIELDS = ("company", "address", "date", "total")
SCHEMA_VERSION = "1.0"

FieldName = Literal["company", "address", "date", "total"]
FieldStatus = Literal[
    "annotated",
    "annotated_empty",
    "source_missing",
    "unlabeled",
    "absent",
]
RegionLabelStatus = Literal["mapped", "unlabeled", "uncertain_marker"]


@dataclass(frozen=True)
class FieldAnnotation:
    status: FieldStatus
    raw_value: str | None
    region_ids: list[str] = field(default_factory=list)
    source_key: str | None = None


@dataclass(frozen=True)
class RegionAnnotation:
    region_id: str
    text: str
    polygons: list[list[list[float]]]
    bbox_xyxy: list[float]
    field: FieldName | None
    source_label: str | None
    label_status: RegionLabelStatus
    source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalDocument:
    schema_version: str
    dataset: str
    dataset_version: str
    document_id: str
    source_partition: str
    split: str | None
    locale: str | None
    image_path: str
    image_sha256: str
    width: int
    height: int
    annotation_coverage: str
    fields: dict[str, FieldAnnotation]
    regions: list[RegionAnnotation]
    qa_flags: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuarantineRecord:
    dataset: str
    document_id: str
    source_partition: str
    reason_codes: list[str]
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoadResult:
    documents: list[CanonicalDocument] = field(default_factory=list)
    quarantine: list[QuarantineRecord] = field(default_factory=list)


def empty_fields(status: FieldStatus = "unlabeled") -> dict[str, FieldAnnotation]:
    return {
        name: FieldAnnotation(status=status, raw_value=None, source_key=None)
        for name in CANONICAL_FIELDS
    }


def validate_document(document: CanonicalDocument) -> None:
    """Validate invariants that downstream dataset consumers may rely on."""
    if document.schema_version != SCHEMA_VERSION:
        raise ValueError("Unsupported canonical schema version")
    if set(document.fields) != set(CANONICAL_FIELDS):
        raise ValueError("Canonical document must contain exactly four field slots")
    if document.width <= 0 or document.height <= 0:
        raise ValueError("Image dimensions must be positive")
    if PathLike.is_absolute(document.image_path):
        raise ValueError("image_path must be relative to the dataset root")
    region_ids = [region.region_id for region in document.regions]
    if len(region_ids) != len(set(region_ids)):
        raise ValueError("Region IDs must be unique within a document")
    known_region_ids = set(region_ids)
    for name, annotation in document.fields.items():
        if annotation.raw_value == "":
            raise ValueError(f"Field {name} must use null instead of an empty string")
        if not set(annotation.region_ids).issubset(known_region_ids):
            raise ValueError(f"Field {name} references an unknown region")
    for region in document.regions:
        x0, y0, x1, y1 = region.bbox_xyxy
        if not (0 <= x0 < x1 <= document.width and 0 <= y0 < y1 <= document.height):
            raise ValueError(f"Region {region.region_id} has an invalid bbox")


class PathLike:
    """Small path check that handles Windows paths on every host."""

    @staticmethod
    def is_absolute(value: str) -> bool:
        return value.startswith(("/", "\\")) or (len(value) >= 2 and value[1] == ":")
