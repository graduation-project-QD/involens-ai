"""Verify T06 split coverage, leakage guards, and deterministic rebuild hashes."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from .split import SPLIT_VERSION, build, file_sha256, read_jsonl


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def key_sets(records: dict[str, list[dict[str, Any]]], key: str) -> dict[str, set[str]]:
    return {name: {record[key] for record in values} for name, values in records.items()}


def assert_pairwise_disjoint(values: dict[str, set[str]], label: str) -> None:
    names = list(values)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            overlap = values[left] & values[right]
            assert_true(not overlap, f"{label} overlap between {left} and {right}: {sorted(overlap)[:10]}")


def verify(workspace: Path) -> dict[str, Any]:
    output = workspace / "experiments" / "splits" / SPLIT_VERSION
    summary = json.loads((output / "split_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"

    split_records: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for dataset in ("mcocr", "sroie"):
        split_records[dataset] = {
            split: read_jsonl(output / dataset / f"{split}.jsonl")
            for split in ("train", "validation", "test")
        }
        assert_pairwise_disjoint(key_sets(split_records[dataset], "document_id"), f"{dataset} document")
        assert_pairwise_disjoint(key_sets(split_records[dataset], "group_id"), f"{dataset} group")
        assert_pairwise_disjoint(key_sets(split_records[dataset], "image_sha256"), f"{dataset} image hash")

    mcocr_canonical = read_jsonl(processed / "mcocr.jsonl")
    mcocr_expected = {record["document_id"] for record in mcocr_canonical}
    mcocr_actual = {
        record["document_id"]
        for records in split_records["mcocr"].values()
        for record in records
    }
    assert_true(mcocr_actual == mcocr_expected, "MC-OCR accepted coverage differs from canonical data")

    sroie_canonical = read_jsonl(processed / "sroie.jsonl")
    sroie_test_expected = {
        record["document_id"] for record in sroie_canonical if record["source_partition"] == "test"
    }
    sroie_test_actual = {record["document_id"] for record in split_records["sroie"]["test"]}
    assert_true(sroie_test_actual == sroie_test_expected, "SROIE official test was not preserved")
    exclusions = read_jsonl(output / "sroie" / "adapted_exclusions.jsonl")
    excluded_ids = {record["document_id"] for record in exclusions}
    sroie_dev_expected = {
        record["document_id"] for record in sroie_canonical
        if record["source_partition"] == "train" and record["document_id"] not in excluded_ids
    }
    sroie_dev_actual = {
        record["document_id"]
        for split in ("train", "validation")
        for record in split_records["sroie"][split]
    }
    assert_true(sroie_dev_actual == sroie_dev_expected, "SROIE adapted development coverage mismatch")

    quarantine_ids = {
        record["document_id"]
        for name in ("mcocr_quarantine.jsonl", "sroie_quarantine.jsonl")
        for record in read_jsonl(processed / name)
    }
    all_split_ids = mcocr_actual | sroie_test_actual | sroie_dev_actual
    assert_true(not (quarantine_ids & all_split_ids), "Quarantine document found in a split")

    for name, artifact in manifest["artifacts"].items():
        artifact_path = workspace / artifact["path"]
        assert_true(file_sha256(artifact_path) == artifact["sha256"], f"Artifact hash mismatch: {name}")
        assert_true(len(read_jsonl(artifact_path)) == artifact["records"], f"Artifact count mismatch: {name}")

    deterministic_keys = {
        "mcocr_train", "mcocr_validation", "mcocr_test", "mcocr_groups", "mcocr_near_candidates",
        "mcocr_unlabeled_official_validation", "sroie_train", "sroie_validation", "sroie_test",
        "sroie_groups", "sroie_official_train_reference", "sroie_exclusions", "sroie_near_candidates",
    }
    temp_parent = workspace / "experiments" / "splits"
    with tempfile.TemporaryDirectory(prefix="t06_verify_", dir=temp_parent) as temporary:
        rebuilt = build(workspace, Path(temporary) / SPLIT_VERSION)
        for key in sorted(deterministic_keys):
            assert_true(
                rebuilt["artifacts"][key]["sha256"] == summary["artifacts"][key]["sha256"],
                f"Deterministic rebuild mismatch: {key}",
            )

    result = {
        "task": "T06",
        "verification_status": "PASS",
        "split_version": SPLIT_VERSION,
        "checks": {
            "deterministic_rebuild_hashes": True,
            "document_ids_pairwise_disjoint": True,
            "group_ids_pairwise_disjoint": True,
            "image_sha256_pairwise_disjoint": True,
            "mcocr_accepted_coverage_complete": True,
            "sroie_official_test_preserved": True,
            "sroie_adapted_development_coverage_complete_after_disclosed_exclusions": True,
            "quarantine_excluded": True,
            "augmentation_generated": False,
        },
        "counts": {
            "mcocr": {split: len(records) for split, records in split_records["mcocr"].items()},
            "sroie": {split: len(records) for split, records in split_records["sroie"].items()},
            "sroie_adapted_exclusions": len(exclusions),
        },
    }
    verification_path = workspace / "experiments" / "manifests" / "t06_verification.json"
    verification_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["verification"] = {
        "path": verification_path.relative_to(workspace).as_posix(),
        "sha256": file_sha256(verification_path),
        "status": "PASS",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.workspace.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
