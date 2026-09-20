"""Build the deterministic T14 reference report and validation coverage audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .core import (
    EVALUATOR_VERSION,
    EVALUABLE_GT_STATUSES,
    EntityDocument,
    EntitySpan,
    EvaluationDocument,
    FieldGroundTruth,
    FieldPrediction,
    evaluate_entities,
    evaluate_fields,
    metrics_table_rows,
    write_metrics_csv,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _field_documents(fixture: dict[str, Any]) -> list[EvaluationDocument]:
    return [
        EvaluationDocument(
            document_id=item["document_id"],
            ground_truth={key: FieldGroundTruth(**value) for key, value in item["ground_truth"].items()},
            prediction={key: FieldPrediction(**value) for key, value in item["prediction"].items()},
        )
        for item in fixture["field_documents"]
    ]


def _entity_documents(fixture: dict[str, Any]) -> list[EntityDocument]:
    return [
        EntityDocument(
            document_id=item["document_id"],
            ground_truth=[EntitySpan(**span) for span in item["ground_truth"]],
            prediction=[EntitySpan(**span) for span in item["prediction"]],
            evaluable_fields=frozenset(item["evaluable_fields"]),
        )
        for item in fixture["entity_documents"]
    ]


def _assert_subset(actual: dict[str, Any], expected: dict[str, Any], path: str) -> None:
    for key, expected_value in expected.items():
        if key not in actual:
            raise AssertionError(f"Missing expected metric {path}.{key}")
        if isinstance(expected_value, dict):
            _assert_subset(actual[key], expected_value, f"{path}.{key}")
        elif actual[key] != expected_value:
            raise AssertionError(
                f"Metric mismatch at {path}.{key}: expected {expected_value!r}, got {actual[key]!r}"
            )


def _verify_fixture_expected(
    fixture: dict[str, Any], raw: dict[str, Any], normalized: dict[str, Any], entity: dict[str, Any]
) -> None:
    expected = fixture["expected"]
    for comparison, report in (("raw", raw), ("normalized", normalized)):
        section = expected[comparison]
        _assert_subset(report["micro"], section["micro"], f"{comparison}.micro")
        _assert_subset(
            report["document_exact_match"], section["document_exact_match"],
            f"{comparison}.document_exact_match",
        )
        for field_name in (set(section) - {"micro", "document_exact_match"}):
            _assert_subset(report["fields"][field_name], section[field_name], f"{comparison}.{field_name}")
    _assert_subset(entity["micro"], expected["entity"]["micro"], "entity.micro")
    for field_name in ("company", "address", "date", "total"):
        _assert_subset(entity["fields"][field_name], expected["entity"][field_name], f"entity.{field_name}")


def validation_coverage(workspace: Path) -> dict[str, Any]:
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"
    split_root = workspace / "experiments" / "splits" / "t06_v1"
    result: dict[str, Any] = {}
    for dataset in ("mcocr", "sroie"):
        canonical = {
            item["document_id"]: item
            for item in read_jsonl(processed / f"{dataset}.jsonl")
        }
        validation = read_jsonl(split_root / dataset / "validation.jsonl")
        status_counts: Counter[str] = Counter()
        referenced_documents = 0
        for split_item in validation:
            document = canonical[split_item["document_id"]]
            referenced_documents += 1
            for field_name, annotation in document["fields"].items():
                status_counts[f"{field_name}:{annotation['status']}"] += 1
        evaluable = sum(
            count
            for key, count in status_counts.items()
            if key.split(":", 1)[1] in EVALUABLE_GT_STATUSES
        )
        total = referenced_documents * 4
        result[dataset] = {
            "documents": referenced_documents,
            "field_slots": total,
            "raw_evaluable_slots": evaluable,
            "raw_masked_slots": total - evaluable,
            "annotation_status": dict(sorted(status_counts.items())),
        }
    return result


def run(workspace: Path) -> dict[str, Any]:
    fixture_path = workspace / "ai-service" / "tests" / "fixtures" / "evaluation_v1.json"
    config_path = workspace / "experiments" / "configs" / "evaluation_v1.json"
    core_path = workspace / "ai-service" / "src" / "invoice_ai" / "evaluation" / "core.py"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    provenance = {
        "dataset": "independent_reference_fixture",
        "fixture_sha256": sha256_file(fixture_path),
        "evaluator_version": EVALUATOR_VERSION,
    }
    documents = _field_documents(fixture)
    raw = evaluate_fields(documents, "raw", provenance)
    normalized = evaluate_fields(documents, "normalized", provenance)
    entity = evaluate_entities(_entity_documents(fixture), provenance)
    _verify_fixture_expected(fixture, raw, normalized, entity)

    report_directory = workspace / "experiments" / "reports"
    report_directory.mkdir(parents=True, exist_ok=True)
    table_path = report_directory / "t14_reference_metrics.csv"
    rows = (
        metrics_table_rows(raw, "field_raw")
        + metrics_table_rows(normalized, "field_normalized")
        + metrics_table_rows(entity, "entity_exact")
    )
    write_metrics_csv(rows, table_path)
    validation_root = workspace / "experiments" / "splits" / "t06_v1"
    report = {
        "task": "T14",
        "status": "PASS",
        "evaluator_version": EVALUATOR_VERSION,
        "reference_fixture": {
            "field_documents": len(fixture["field_documents"]),
            "entity_documents": len(fixture["entity_documents"]),
            "expected_counts": "PASS",
            "raw": raw,
            "normalized": normalized,
            "entity": entity,
        },
        "frozen_validation_coverage": validation_coverage(workspace),
        "actual_runs": {
            "baseline_validation": "NOT_RUN_WAITING_FOR_T13_PREDICTIONS",
            "layoutxlm_validation": "NOT_RUN_WAITING_FOR_T18_CHECKPOINT",
            "normalized_accuracy": "N/A_NO_INDEPENDENT_NORMALIZED_VALIDATION_GT",
            "gold_entity_metrics": "NOT_RUN_WAITING_FOR_QAED_GOLD_SPAN_RUBRIC",
        },
        "artifacts": {
            "metrics_table": "experiments/reports/t14_reference_metrics.csv",
            "metrics_table_sha256": sha256_file(table_path),
        },
        "inputs": {
            "config_sha256": sha256_file(config_path),
            "fixture_sha256": sha256_file(fixture_path),
            "evaluator_code_sha256": sha256_file(core_path),
            "mcocr_validation_sha256": sha256_file(validation_root / "mcocr" / "validation.jsonl"),
            "sroie_validation_sha256": sha256_file(validation_root / "sroie" / "validation.jsonl"),
        },
    }
    output_path = report_directory / "t14_reference_evaluation.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace.resolve()), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
