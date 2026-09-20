"""Verify T12 artifacts against frozen T04/T06 inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .audit import read_jsonl, run
from .core import FIELDS, NORMALIZATION_VERSION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(workspace: Path) -> dict[str, Any]:
    artifact_path = workspace / "experiments" / "manifests" / "t12_validation_normalization.jsonl"
    report_path = workspace / "experiments" / "reports" / "t12_normalization_audit.json"
    config_path = workspace / "ai-service" / "configs" / "normalization" / "v1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    allowed_warning_codes = set(config["warning_codes"])

    first_report = run(workspace)
    first_hash = sha256_file(artifact_path)
    second_report = run(workspace)
    second_hash = sha256_file(artifact_path)
    records = read_jsonl(artifact_path)

    expected: dict[tuple[str, str, str], dict[str, Any]] = {}
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"
    split_root = workspace / "experiments" / "splits" / "t06_v1"
    for dataset in ("mcocr", "sroie"):
        canonical = {
            item["document_id"]: item
            for item in read_jsonl(processed / f"{dataset}.jsonl")
        }
        validation = read_jsonl(split_root / dataset / "validation.jsonl")
        for item in validation:
            document = canonical[item["document_id"]]
            for field_name in FIELDS:
                expected[(dataset, document["document_id"], field_name)] = document["fields"][field_name]

    failures: list[str] = []
    seen: Counter[tuple[str, str, str]] = Counter()
    allowed_statuses = {None, "ok", "missing", "invalid", "ambiguous"}
    for record in records:
        key = (record["dataset"], record["document_id"], record["field"])
        seen[key] += 1
        source = expected.get(key)
        if source is None:
            failures.append(f"unexpected record: {key}")
            continue
        if record["raw_value"] != source["raw_value"]:
            failures.append(f"raw_value changed: {key}")
        if record["annotation_status"] != source["status"]:
            failures.append(f"annotation_status changed: {key}")
        if record["normalizer_version"] != NORMALIZATION_VERSION:
            failures.append(f"wrong normalizer version: {key}")
        if record["normalization_status"] not in allowed_statuses:
            failures.append(f"unknown normalization status: {key}")
        if record["normalized_value"] is not None and not isinstance(record["normalized_value"], str):
            failures.append(f"normalized value is not string/null: {key}")
        unknown_warnings = set(record["warnings"]) - allowed_warning_codes
        if unknown_warnings:
            failures.append(f"unknown warning(s) {sorted(unknown_warnings)}: {key}")
        is_masked = source["status"] not in {"annotated", "annotated_empty"}
        if is_masked != (record["evaluation_status"] == "masked_no_normalization_target"):
            failures.append(f"annotation mask mismatch: {key}")
        if is_masked and (record["normalized_value"] is not None or record["normalization_status"] is not None):
            failures.append(f"masked field was normalized: {key}")

    missing = sorted(set(expected) - set(seen))
    duplicates = sorted(key for key, count in seen.items() if count != 1)
    if missing:
        failures.append(f"missing expected records: {len(missing)}")
    if duplicates:
        failures.append(f"duplicate records: {len(duplicates)}")
    if first_hash != second_hash or first_report != second_report:
        failures.append("audit output is not deterministic across consecutive rebuilds")
    if first_hash != second_report["artifact"]["sha256"]:
        failures.append("artifact hash does not match audit report")
    if len(records) != second_report["artifact"]["records"]:
        failures.append("artifact record count does not match audit report")

    verification = {
        "task": "T12",
        "status": "PASS" if not failures else "FAIL",
        "normalizer_version": NORMALIZATION_VERSION,
        "checks": {
            "expected_records": len(expected),
            "actual_records": len(records),
            "unique_field_slots": len(seen),
            "raw_values_preserved": not any(item.startswith("raw_value changed") for item in failures),
            "annotation_masks_preserved": not any("mask" in item for item in failures),
            "normalized_values_string_or_null": not any("not string/null" in item for item in failures),
            "warning_taxonomy_closed": not any("unknown warning" in item for item in failures),
            "deterministic_rebuild": first_hash == second_hash and first_report == second_report,
            "artifact_sha256": second_hash,
        },
        "normalized_accuracy": second_report["normalized_accuracy"],
        "failures": failures,
        "audit_report_sha256": sha256_file(report_path),
    }
    output = workspace / "experiments" / "manifests" / "t12_verification.json"
    output.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return verification


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.workspace.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
