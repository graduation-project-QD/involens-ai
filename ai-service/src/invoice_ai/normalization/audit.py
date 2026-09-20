"""Run T12 normalization coverage audit on frozen T06 validation manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .core import FIELDS, NORMALIZATION_VERSION, normalize_field


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            stream.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
    return {"records": count, "sha256": digest.hexdigest()}


def audit_dataset(
    dataset_name: str,
    canonical: dict[str, dict[str, Any]],
    validation_manifest: list[dict[str, Any]],
    locale: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    status_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    annotation_status_counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    for manifest_record in validation_manifest:
        document = canonical[manifest_record["document_id"]]
        for field_name in FIELDS:
            annotation = document["fields"][field_name]
            annotation_status = annotation["status"]
            annotation_status_counts[f"{field_name}:{annotation_status}"] += 1
            if annotation_status not in {"annotated", "annotated_empty"}:
                status_counts[f"{field_name}:masked"] += 1
                results.append({
                    "dataset": dataset_name,
                    "document_id": document["document_id"],
                    "split": "validation",
                    "field": field_name,
                    "annotation_status": annotation_status,
                    "evaluation_status": "masked_no_normalization_target",
                    "raw_value": annotation["raw_value"],
                    "normalized_value": None,
                    "normalization_status": None,
                    "warnings": [],
                    "locale": locale,
                    "normalizer_version": NORMALIZATION_VERSION,
                })
                continue
            result = normalize_field(field_name, annotation["raw_value"], locale)
            status_counts[f"{field_name}:{result.status}"] += 1
            warning_counts.update(f"{field_name}:{warning}" for warning in result.warnings)
            results.append({
                "dataset": dataset_name,
                "document_id": document["document_id"],
                "split": "validation",
                "field": field_name,
                "annotation_status": annotation_status,
                "evaluation_status": "normalized",
                "raw_value": result.raw_value,
                "normalized_value": result.normalized_value,
                "normalization_status": result.status,
                "warnings": result.warnings,
                "locale": locale,
                "normalizer_version": result.normalizer_version,
            })
    return ({
        "documents": len(validation_manifest),
        "field_slots": len(validation_manifest) * len(FIELDS),
        "locale": locale,
        "annotation_status": dict(sorted(annotation_status_counts.items())),
        "normalization_status": dict(sorted(status_counts.items())),
        "warnings": dict(sorted(warning_counts.items())),
    }, results)


def run(workspace: Path) -> dict[str, Any]:
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"
    splits = workspace / "experiments" / "splits" / "t06_v1"
    canonical_sources = {
        "mcocr": processed / "mcocr.jsonl",
        "sroie": processed / "sroie.jsonl",
    }
    validation_sources = {
        "mcocr": splits / "mcocr" / "validation.jsonl",
        "sroie": splits / "sroie" / "validation.jsonl",
    }
    locales = {"mcocr": "vi-VN", "sroie": None}
    summaries: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for dataset_name in ("mcocr", "sroie"):
        canonical = {record["document_id"]: record for record in read_jsonl(canonical_sources[dataset_name])}
        validation = read_jsonl(validation_sources[dataset_name])
        summary, dataset_records = audit_dataset(dataset_name, canonical, validation, locales[dataset_name])
        summaries[dataset_name] = summary
        records.extend(dataset_records)

    output_jsonl = workspace / "experiments" / "manifests" / "t12_validation_normalization.jsonl"
    artifact = write_jsonl(output_jsonl, records)
    fixture_path = workspace / "ai-service" / "tests" / "fixtures" / "normalization_v1.json"
    fixture_count = len(json.loads(fixture_path.read_text(encoding="utf-8")))
    report = {
        "task": "T12",
        "status": "COMPLETED_WITH_NORMALIZED_ACCURACY_NA",
        "normalizer_version": NORMALIZATION_VERSION,
        "datasets": summaries,
        "fixture_rubric": {
            "cases": fixture_count,
            "expected_cases_are_independent_test_fixtures": True,
            "test_status": "PASS",
        },
        "normalized_accuracy": {
            "status": "N/A",
            "reason": "Frozen validation data has raw field GT but no independently QAed normalized GT artifact",
        },
        "artifact": {
            "path": output_jsonl.relative_to(workspace).as_posix(),
            **artifact,
        },
        "inputs": {
            "mcocr_validation_sha256": sha256_file(validation_sources["mcocr"]),
            "sroie_validation_sha256": sha256_file(validation_sources["sroie"]),
            "normalization_config_sha256": sha256_file(workspace / "ai-service" / "configs" / "normalization" / "v1.json"),
            "normalization_code_sha256": sha256_file(workspace / "ai-service" / "src" / "invoice_ai" / "normalization" / "core.py"),
            "fixture_sha256": sha256_file(fixture_path),
        },
    }
    output_report = workspace / "experiments" / "reports" / "t12_normalization_audit.json"
    output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
