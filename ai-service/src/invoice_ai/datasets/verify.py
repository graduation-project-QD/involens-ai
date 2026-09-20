"""Verify T04 artifacts against the inspected source inventories."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .schema import CANONICAL_FIELDS, SCHEMA_VERSION

FIELD_STATUSES = {"annotated", "annotated_empty", "source_missing", "unlabeled", "absent"}
REGION_STATUSES = {"mapped", "unlabeled", "uncertain_marker"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            records.append(value)
    return records


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_record(record: dict[str, Any]) -> tuple[int, Counter[str]]:
    document_id = record.get("document_id", "<unknown>")
    assert_true(record.get("schema_version") == SCHEMA_VERSION, f"{document_id}: schema version")
    assert_true(set(record.get("fields", {})) == set(CANONICAL_FIELDS), f"{document_id}: field slots")
    width, height = record.get("width"), record.get("height")
    assert_true(isinstance(width, int) and width > 0, f"{document_id}: width")
    assert_true(isinstance(height, int) and height > 0, f"{document_id}: height")
    image_path = record.get("image_path")
    assert_true(isinstance(image_path, str) and image_path, f"{document_id}: image path")
    assert_true(not image_path.startswith(("/", "\\")) and not (len(image_path) > 1 and image_path[1] == ":"),
                f"{document_id}: absolute image path")

    regions = record.get("regions", [])
    region_ids = [region.get("region_id") for region in regions]
    assert_true(len(region_ids) == len(set(region_ids)), f"{document_id}: duplicate region ID")
    known_region_ids = set(region_ids)
    status_counts: Counter[str] = Counter()
    for name, annotation in record["fields"].items():
        status = annotation.get("status")
        assert_true(status in FIELD_STATUSES, f"{document_id}/{name}: invalid field status")
        raw_value = annotation.get("raw_value")
        assert_true(raw_value != "", f"{document_id}/{name}: empty string instead of null")
        if status == "annotated":
            assert_true(isinstance(raw_value, str) and bool(raw_value), f"{document_id}/{name}: annotated value")
        else:
            assert_true(raw_value is None, f"{document_id}/{name}: non-annotated value must be null")
        assert_true(set(annotation.get("region_ids", [])).issubset(known_region_ids),
                    f"{document_id}/{name}: unknown region reference")

    for region in regions:
        region_id = region["region_id"]
        status = region.get("label_status")
        assert_true(status in REGION_STATUSES, f"{document_id}/{region_id}: invalid region status")
        assert_true(status != "O", f"{document_id}/{region_id}: unknown region mapped to O")
        status_counts[status] += 1
        bbox = region.get("bbox_xyxy")
        assert_true(isinstance(bbox, list) and len(bbox) == 4, f"{document_id}/{region_id}: bbox")
        x0, y0, x1, y1 = bbox
        assert_true(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height,
                    f"{document_id}/{region_id}: bbox bounds")
        polygons = region.get("polygons")
        assert_true(isinstance(polygons, list) and bool(polygons), f"{document_id}/{region_id}: polygons")
        for polygon in polygons:
            assert_true(isinstance(polygon, list) and len(polygon) >= 3,
                        f"{document_id}/{region_id}: polygon points")
            for point in polygon:
                assert_true(isinstance(point, list) and len(point) == 2,
                            f"{document_id}/{region_id}: polygon point")
                x, y = point
                assert_true(0 <= x <= width and 0 <= y <= height,
                            f"{document_id}/{region_id}: polygon bounds")
    return len(regions), status_counts


def source_keys(workspace: Path) -> dict[str, set[tuple[str, str]]]:
    mcocr: set[tuple[str, str]] = set()
    with (workspace / "dataset_hoadon" / "mcocr_train_df.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            mcocr.add(("train", row["img_id"]))
    sroie: set[tuple[str, str]] = set()
    root = workspace / "dataset_hoadon" / "SROIE2019"
    for split in ("train", "test"):
        for image_path in (root / split / "img").glob("*.jpg"):
            sroie.add((split, image_path.stem))
    return {"mcocr": mcocr, "sroie": sroie}


def verify_source_inventory(workspace: Path) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    inventory_specs = {
        "mcocr_images": (
            workspace / "experiments" / "manifests" / "mcocr_image_inventory.jsonl",
            workspace / "dataset_hoadon",
            lambda value: value["path"].startswith("train_images/train_images/"),
        ),
        "mcocr_metadata": (
            workspace / "experiments" / "manifests" / "mcocr_metadata_hashes.jsonl",
            workspace / "dataset_hoadon",
            lambda value: value["path"] == "mcocr_train_df.csv",
        ),
        "sroie_consumed_files": (
            workspace / "experiments" / "manifests" / "sroie_file_inventory.jsonl",
            workspace / "dataset_hoadon" / "SROIE2019",
            lambda value: value["path"].startswith(("train/", "test/")),
        ),
    }
    for name, (manifest_path, source_root, predicate) in inventory_specs.items():
        records = [record for record in read_jsonl(manifest_path) if predicate(record)]
        mismatches: list[str] = []
        for record in records:
            path = source_root / record["path"]
            if not path.is_file():
                mismatches.append(record["path"])
                continue
            if "bytes" in record and path.stat().st_size != record["bytes"]:
                mismatches.append(record["path"])
                continue
            if sha256_file(path) != record["sha256"]:
                mismatches.append(record["path"])
        checks[name] = {"files_checked": len(records), "mismatches": mismatches, "passed": not mismatches}
        assert_true(not mismatches, f"Source inventory mismatch: {name}")
    return checks


def digest_inputs(workspace: Path, paths: Iterable[str]) -> dict[str, str]:
    return {path: sha256_file(workspace / path) for path in paths}


def verify(workspace: Path, output_path: Path) -> dict[str, Any]:
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"
    report = json.loads((processed / "conversion_report.json").read_text(encoding="utf-8"))
    expected_sources = source_keys(workspace)
    dataset_results: dict[str, Any] = {}
    for name in ("mcocr", "sroie"):
        artifact = report["artifacts"][name]
        data_path = workspace / artifact["data"]["path"]
        quarantine_path = workspace / artifact["quarantine"]["path"]
        documents = read_jsonl(data_path)
        quarantine = read_jsonl(quarantine_path)
        assert_true(len(documents) == artifact["data"]["records"], f"{name}: data count")
        assert_true(len(quarantine) == artifact["quarantine"]["records"], f"{name}: quarantine count")
        assert_true(sha256_file(data_path) == artifact["data"]["sha256"], f"{name}: data hash")
        assert_true(sha256_file(quarantine_path) == artifact["quarantine"]["sha256"], f"{name}: quarantine hash")

        accepted_keys = {(doc["source_partition"], doc["document_id"]) for doc in documents}
        quarantine_keys = {(item["source_partition"], item["document_id"]) for item in quarantine}
        assert_true(len(accepted_keys) == len(documents), f"{name}: duplicate accepted document")
        assert_true(len(quarantine_keys) == len(quarantine), f"{name}: duplicate quarantine document")
        assert_true(accepted_keys.isdisjoint(quarantine_keys), f"{name}: accepted/quarantine overlap")
        assert_true(accepted_keys | quarantine_keys == expected_sources[name], f"{name}: source coverage")

        region_count = 0
        region_statuses: Counter[str] = Counter()
        image_records = read_jsonl(
            workspace / "experiments" / "manifests" /
            ("mcocr_image_inventory.jsonl" if name == "mcocr" else "sroie_image_inventory.jsonl")
        )
        if name == "mcocr":
            image_records = [
                item for item in image_records
                if item["path"].startswith("train_images/train_images/")
            ]
        image_inventory = {
            (item.get("split", "train"), item["id"]): item
            for item in image_records
        }
        for document in documents:
            count, statuses = validate_record(document)
            region_count += count
            region_statuses.update(statuses)
            inventory_record = image_inventory[(document["source_partition"], document["document_id"])]
            assert_true(document["image_sha256"] == inventory_record["sha256"],
                        f"{name}/{document['document_id']}: image hash differs from inventory")
            assert_true(document["width"] == inventory_record["width"] and
                        document["height"] == inventory_record["height"],
                        f"{name}/{document['document_id']}: dimensions differ from inventory")
        assert_true(region_count == artifact["summary"]["regions"], f"{name}: region count")
        assert_true(dict(sorted(region_statuses.items())) == artifact["summary"]["region_label_status"],
                    f"{name}: region status summary")
        dataset_results[name] = {
            "accepted": len(documents),
            "quarantined": len(quarantine),
            "source_documents_accounted_for": len(accepted_keys | quarantine_keys),
            "regions_validated": region_count,
            "artifact_hashes_match_report": True,
            "image_metadata_matches_inspection_inventory": True,
            "accepted_and_quarantine_disjoint": True,
            "source_coverage_complete": True,
        }

    source_checks = verify_source_inventory(workspace)
    result = {
        "task": "T04",
        "verification_status": "PASS",
        "processed_dataset_version": report["processed_dataset_version"],
        "canonical_schema_version": report["canonical_schema_version"],
        "datasets": dataset_results,
        "source_inventory_checks": source_checks,
        "invariants": {
            "exactly_four_field_slots": True,
            "empty_values_use_null": True,
            "unknown_regions_never_mapped_to_O": True,
            "polygons_and_bboxes_within_image_bounds": True,
            "field_region_references_resolve": True,
            "no_new_split_created": report["split_created"] is False,
            "no_value_normalization_applied": report["normalization_applied"] is False,
        },
        "reproducibility_inputs": digest_inputs(workspace, [
            "ai-service/src/invoice_ai/datasets/schema.py",
            "ai-service/src/invoice_ai/datasets/common.py",
            "ai-service/src/invoice_ai/datasets/mcocr.py",
            "ai-service/src/invoice_ai/datasets/sroie.py",
            "ai-service/src/invoice_ai/datasets/build.py",
            "ai-service/src/invoice_ai/datasets/verify.py",
            "ai-service/src/invoice_ai/datasets/export_quarantine.py",
            "ai-service/configs/datasets/t04_qa_policy.json",
            "experiments/manifests/field_mapping.json",
            "experiments/manifests/t04_qa_decisions.json",
        ]),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def write_dataset_manifest(workspace: Path, verification_path: Path) -> Path:
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"
    conversion_path = processed / "conversion_report.json"
    conversion = json.loads(conversion_path.read_text(encoding="utf-8"))
    try:
        import PIL
        pillow_version: str | None = PIL.__version__
    except ImportError:
        pillow_version = None
    manifest = {
        "task": "T04",
        "status": "COMPLETED_WITH_QUARANTINE",
        "processed_dataset_version": conversion["processed_dataset_version"],
        "canonical_schema_version": conversion["canonical_schema_version"],
        "source_roots": {
            "mcocr_2021": "dataset_hoadon",
            "sroie_2019": "dataset_hoadon/SROIE2019",
        },
        "source_inspection_inventories": {
            path: sha256_file(workspace / path)
            for path in (
                "experiments/manifests/mcocr_image_inventory.jsonl",
                "experiments/manifests/mcocr_metadata_hashes.jsonl",
                "experiments/manifests/sroie_file_inventory.jsonl",
                "experiments/manifests/sroie_image_inventory.jsonl",
            )
        },
        "conversion_artifacts": conversion["artifacts"],
        "control_artifacts": {
            "conversion_report": {
                "path": conversion_path.relative_to(workspace).as_posix(),
                "sha256": sha256_file(conversion_path),
            },
            "verification": {
                "path": verification_path.relative_to(workspace).as_posix(),
                "sha256": sha256_file(verification_path),
            },
            "field_mapping": {
                "path": "experiments/manifests/field_mapping.json",
                "sha256": sha256_file(workspace / "experiments/manifests/field_mapping.json"),
            },
            "qa_decisions": {
                "path": "experiments/manifests/t04_qa_decisions.json",
                "sha256": sha256_file(workspace / "experiments/manifests/t04_qa_decisions.json"),
            },
            "quarantine_package": {
                "path": "experiments/data/quarantine/t04_v1/manifest.json",
                "sha256": sha256_file(workspace / "experiments/data/quarantine/t04_v1/manifest.json"),
                "document_count": 5,
                "excluded_from_canonical_data": True,
            },
        },
        "runtime": {"python": platform.python_version(), "pillow": pillow_version},
        "scope_guards": {
            "split_created": conversion["split_created"],
            "normalization_applied": conversion["normalization_applied"],
            "source_datasets_modified": conversion["source_datasets_modified"],
        },
    }
    manifest_path = workspace / "experiments" / "manifests" / "t04_canonical_dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.workspace / "experiments" / "manifests" / "t04_verification.json"
    result = verify(args.workspace.resolve(), output.resolve())
    manifest_path = write_dataset_manifest(args.workspace.resolve(), output.resolve())
    result["dataset_manifest"] = manifest_path.relative_to(args.workspace.resolve()).as_posix()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
