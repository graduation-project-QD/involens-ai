"""Rebuild and verify deterministic T14 reference artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .audit import run
from .core import EVALUATOR_VERSION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(workspace: Path) -> dict[str, Any]:
    json_path = workspace / "experiments" / "reports" / "t14_reference_evaluation.json"
    csv_path = workspace / "experiments" / "reports" / "t14_reference_metrics.csv"
    first = run(workspace)
    first_hashes = {"json": sha256_file(json_path), "csv": sha256_file(csv_path)}
    second = run(workspace)
    second_hashes = {"json": sha256_file(json_path), "csv": sha256_file(csv_path)}
    failures: list[str] = []
    if first != second or first_hashes != second_hashes:
        failures.append("reference evaluation artifacts are not deterministic")
    if second["reference_fixture"]["expected_counts"] != "PASS":
        failures.append("reference fixture expected counts did not pass")
    coverage = second["frozen_validation_coverage"]
    if coverage["mcocr"]["documents"] != 173 or coverage["sroie"]["documents"] != 93:
        failures.append("frozen T06 validation document counts changed")
    if coverage["mcocr"]["field_slots"] + coverage["sroie"]["field_slots"] != 1064:
        failures.append("frozen validation field-slot count changed")
    verification = {
        "task": "T14",
        "status": "PASS" if not failures else "FAIL",
        "evaluator_version": EVALUATOR_VERSION,
        "checks": {
            "reference_expected_counts": second["reference_fixture"]["expected_counts"],
            "deterministic_rebuild": first == second and first_hashes == second_hashes,
            "frozen_validation_documents": coverage["mcocr"]["documents"] + coverage["sroie"]["documents"],
            "frozen_validation_field_slots": coverage["mcocr"]["field_slots"] + coverage["sroie"]["field_slots"],
            "raw_evaluable_field_slots": coverage["mcocr"]["raw_evaluable_slots"] + coverage["sroie"]["raw_evaluable_slots"],
            "artifact_sha256": second_hashes,
        },
        "actual_metric_runs": second["actual_runs"],
        "failures": failures,
    }
    output_path = workspace / "experiments" / "manifests" / "t14_verification.json"
    output_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
