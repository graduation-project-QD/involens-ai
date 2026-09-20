"""Build versioned canonical JSONL artifacts without changing source datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .mcocr import load_mcocr
from .schema import CanonicalDocument, QuarantineRecord, validate_document
from .sroie import load_sroie

PROCESSED_DATASET_VERSION = "t04_v1"


def _json_line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            line = _json_line(record)
            stream.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
    return count, digest.hexdigest()


def _document_summary(documents: list[CanonicalDocument]) -> dict[str, Any]:
    field_status = Counter()
    qa_flags = Counter()
    source_partitions = Counter()
    region_status = Counter()
    for document in documents:
        source_partitions[document.source_partition] += 1
        qa_flags.update(document.qa_flags)
        for name, annotation in document.fields.items():
            field_status[f"{name}:{annotation.status}"] += 1
        region_status.update(region.label_status for region in document.regions)
    return {
        "documents": len(documents),
        "regions": sum(len(document.regions) for document in documents),
        "source_partitions": dict(sorted(source_partitions.items())),
        "field_status": dict(sorted(field_status.items())),
        "qa_flags": dict(sorted(qa_flags.items())),
        "region_label_status": dict(sorted(region_status.items())),
    }


def _quarantine_summary(records: list[QuarantineRecord]) -> dict[str, Any]:
    reasons = Counter(reason for record in records for reason in record.reason_codes)
    return {"documents": len(records), "reason_codes": dict(sorted(reasons.items()))}


def build(workspace: Path, output_dir: Path) -> dict[str, Any]:
    mcocr_root = workspace / "dataset_hoadon"
    sroie_root = mcocr_root / "SROIE2019"
    mcocr = load_mcocr(mcocr_root)
    sroie = load_sroie(sroie_root)
    datasets = {"mcocr": mcocr, "sroie": sroie}
    artifact_info: dict[str, Any] = {}
    for name, result in datasets.items():
        for document in result.documents:
            validate_document(document)
        data_path = output_dir / f"{name}.jsonl"
        quarantine_path = output_dir / f"{name}_quarantine.jsonl"
        data_count, data_hash = _write_jsonl(data_path, (document.to_dict() for document in result.documents))
        quarantine_count, quarantine_hash = _write_jsonl(
            quarantine_path, (record.to_dict() for record in result.quarantine)
        )
        artifact_info[name] = {
            "data": {"path": data_path.relative_to(workspace).as_posix(), "records": data_count, "sha256": data_hash},
            "quarantine": {
                "path": quarantine_path.relative_to(workspace).as_posix(),
                "records": quarantine_count,
                "sha256": quarantine_hash,
            },
            "summary": _document_summary(result.documents),
            "quarantine_summary": _quarantine_summary(result.quarantine),
        }
    report = {
        "task": "T04",
        "processed_dataset_version": PROCESSED_DATASET_VERSION,
        "canonical_schema_version": "1.0",
        "split_created": False,
        "normalization_applied": False,
        "source_datasets_modified": False,
        "artifacts": artifact_info,
    }
    report_path = output_dir / "conversion_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    arguments = parser.parse_args()
    workspace = arguments.workspace.resolve()
    output_dir = arguments.output_dir or workspace / "experiments" / "data" / "processed" / PROCESSED_DATASET_VERSION
    report = build(workspace, output_dir.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
