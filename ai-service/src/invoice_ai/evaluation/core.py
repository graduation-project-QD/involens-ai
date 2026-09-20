"""Deterministic T14 metrics for exact entity and final-field evaluation."""

from __future__ import annotations

import csv
import math
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from invoice_ai.normalization.core import FIELDS

EVALUATOR_VERSION = "evaluation_v1"

Comparison = Literal["raw", "normalized"]
EVALUABLE_GT_STATUSES = frozenset({"annotated", "annotated_empty", "absent"})
MASKED_GT_STATUSES = frozenset({"source_missing", "unlabeled"})


@dataclass(frozen=True)
class FieldGroundTruth:
    status: str
    raw_value: str | None
    normalized_value: str | None = None
    normalization_status: str | None = None


@dataclass(frozen=True)
class FieldPrediction:
    raw_value: str | None = None
    normalized_value: str | None = None


@dataclass(frozen=True)
class EvaluationDocument:
    document_id: str
    ground_truth: dict[str, FieldGroundTruth]
    prediction: dict[str, FieldPrediction]


@dataclass(frozen=True)
class EntitySpan:
    field: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.field not in FIELDS:
            raise ValueError(f"Unsupported entity field: {self.field}")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Entity spans must satisfy 0 <= start < end")


@dataclass(frozen=True)
class EntityDocument:
    document_id: str
    ground_truth: list[EntitySpan]
    prediction: list[EntitySpan]
    evaluable_fields: frozenset[str] = field(default_factory=lambda: frozenset(FIELDS))

    def __post_init__(self) -> None:
        unknown = set(self.evaluable_fields) - set(FIELDS)
        if unknown:
            raise ValueError(f"Unsupported evaluable entity fields: {sorted(unknown)}")


def _require_contract_fields(values: dict[str, Any], label: str) -> None:
    if set(values) != set(FIELDS):
        raise ValueError(f"{label} must contain exactly {', '.join(FIELDS)}")


def canonical_raw(value: str | None) -> str | None:
    """NFC plus trim/collapse whitespace, while preserving case and accents."""
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value)
    collapsed = " ".join(normalized.split())
    return collapsed or None


def strict_raw(value: str | None) -> str | None:
    """Diagnostic comparison that preserves whitespace but canonicalizes Unicode."""
    return None if value is None else unicodedata.normalize("NFC", value)


def _safe_divide(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _classification_metrics(tp: int, fp: int, fn: int, support: int, evaluable: int) -> dict[str, Any]:
    if evaluable == 0:
        precision = recall = f1 = None
    else:
        precision_denominator = tp + fp
        precision = tp / precision_denominator if precision_denominator else (0.0 if support else None)
        recall = tp / support if support else None
        if precision is None or recall is None:
            f1 = None
        elif precision + recall == 0:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": support,
        "evaluable": evaluable,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _mean_defined(values: Iterable[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _validate_gt(field_name: str, gt: FieldGroundTruth) -> None:
    if gt.status not in EVALUABLE_GT_STATUSES | MASKED_GT_STATUSES:
        raise ValueError(f"Unknown GT status for {field_name}: {gt.status}")
    if gt.status == "annotated" and canonical_raw(gt.raw_value) is None:
        raise ValueError(f"Annotated GT for {field_name} must have a non-empty raw value")
    if gt.status in {"annotated_empty", "absent", "source_missing", "unlabeled"} and gt.raw_value is not None:
        raise ValueError(f"GT status {gt.status} for {field_name} requires raw_value=null")
    if gt.normalized_value is not None and not isinstance(gt.normalized_value, str):
        raise ValueError(f"Normalized GT for {field_name} must be string/null")


def _validate_prediction(field_name: str, prediction: FieldPrediction) -> None:
    if prediction.raw_value is not None and not isinstance(prediction.raw_value, str):
        raise ValueError(f"Raw prediction for {field_name} must be string/null")
    if prediction.normalized_value is not None and not isinstance(prediction.normalized_value, str):
        raise ValueError(f"Normalized prediction for {field_name} must be string/null")


def _field_values(
    gt: FieldGroundTruth,
    prediction: FieldPrediction,
    comparison: Comparison,
) -> tuple[bool, str | None, str | None, str | None]:
    """Return evaluable, GT, prediction and optional mask reason."""
    if gt.status in MASKED_GT_STATUSES:
        return False, None, None, "missing_annotation"
    if comparison == "raw":
        gt_value = canonical_raw(gt.raw_value)
        prediction_value = canonical_raw(prediction.raw_value)
        return True, gt_value, prediction_value, None
    if gt.status == "annotated" and (
        gt.normalization_status != "ok" or gt.normalized_value is None
    ):
        return False, None, None, "unresolved_normalized_gt"
    gt_value = gt.normalized_value if gt.status == "annotated" else None
    prediction_value = prediction.normalized_value
    if prediction_value == "":
        prediction_value = None
    return True, gt_value, prediction_value, None


def evaluate_fields(
    documents: Iterable[EvaluationDocument],
    comparison: Comparison = "raw",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if comparison not in {"raw", "normalized"}:
        raise ValueError("comparison must be 'raw' or 'normalized'")
    document_list = list(documents)
    if len({document.document_id for document in document_list}) != len(document_list):
        raise ValueError("document_id values must be unique")

    per_field = {
        field_name: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "support": 0,
            "evaluable_slots": 0,
            "correct_slots": 0,
            "masked_slots": 0,
            "unresolved_normalized_gt_slots": 0,
            "strict_correct_slots": 0,
        }
        for field_name in FIELDS
    }
    document_eligible = 0
    document_correct = 0

    for document in document_list:
        _require_contract_fields(document.ground_truth, "ground_truth")
        _require_contract_fields(document.prediction, "prediction")
        all_evaluable = True
        all_correct = True
        for field_name in FIELDS:
            gt = document.ground_truth[field_name]
            prediction = document.prediction[field_name]
            _validate_gt(field_name, gt)
            _validate_prediction(field_name, prediction)
            evaluable, gt_value, prediction_value, mask_reason = _field_values(gt, prediction, comparison)
            counters = per_field[field_name]
            if not evaluable:
                all_evaluable = False
                if mask_reason == "unresolved_normalized_gt":
                    counters["unresolved_normalized_gt_slots"] += 1
                else:
                    counters["masked_slots"] += 1
                continue

            counters["evaluable_slots"] += 1
            gt_present = gt_value is not None
            prediction_present = prediction_value is not None
            if gt_present:
                counters["support"] += 1
            slot_correct = gt_value == prediction_value
            if slot_correct:
                counters["correct_slots"] += 1
            else:
                all_correct = False

            if gt_present and slot_correct:
                counters["tp"] += 1
            elif gt_present and prediction_present:
                counters["fp"] += 1
                counters["fn"] += 1
            elif gt_present:
                counters["fn"] += 1
            elif prediction_present:
                counters["fp"] += 1

            if comparison == "raw" and strict_raw(gt.raw_value) == strict_raw(prediction.raw_value):
                counters["strict_correct_slots"] += 1

        if all_evaluable:
            document_eligible += 1
            if all_correct:
                document_correct += 1

    field_reports: dict[str, dict[str, Any]] = {}
    for field_name, counters in per_field.items():
        report = _classification_metrics(
            counters["tp"], counters["fp"], counters["fn"], counters["support"], counters["evaluable_slots"]
        )
        report.update({
            "evaluable_slots": counters["evaluable_slots"],
            "correct_slots": counters["correct_slots"],
            "masked_slots": counters["masked_slots"],
            "unresolved_normalized_gt_slots": counters["unresolved_normalized_gt_slots"],
            "slot_exact_match": _safe_divide(counters["correct_slots"], counters["evaluable_slots"]),
        })
        report.pop("evaluable")
        if comparison == "raw":
            report["strict_preserve_whitespace_exact_match"] = _safe_divide(
                counters["strict_correct_slots"], counters["evaluable_slots"]
            )
        field_reports[field_name] = report

    aggregate = {
        key: sum(report[key] for report in field_reports.values())
        for key in ("tp", "fp", "fn", "support", "evaluable_slots", "correct_slots", "masked_slots", "unresolved_normalized_gt_slots")
    }
    micro = _classification_metrics(
        aggregate["tp"], aggregate["fp"], aggregate["fn"], aggregate["support"], aggregate["evaluable_slots"]
    )
    micro.pop("evaluable")
    micro.update(aggregate)
    micro["slot_exact_match"] = _safe_divide(aggregate["correct_slots"], aggregate["evaluable_slots"])
    if comparison == "raw":
        strict_correct = sum(item["strict_correct_slots"] for item in per_field.values())
        micro["strict_preserve_whitespace_exact_match"] = _safe_divide(strict_correct, aggregate["evaluable_slots"])

    macro = {
        "precision": _mean_defined(report["precision"] for report in field_reports.values()),
        "recall": _mean_defined(report["recall"] for report in field_reports.values()),
        "f1": _mean_defined(report["f1"] for report in field_reports.values()),
        "defined_f1_fields": sum(report["f1"] is not None for report in field_reports.values()),
    }
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "comparison": comparison,
        "fields": field_reports,
        "micro": micro,
        "macro": macro,
        "document_exact_match": {
            "input_documents": len(document_list),
            "eligible_documents": document_eligible,
            "correct_documents": document_correct,
            "value": _safe_divide(document_correct, document_eligible),
            "eligibility": "all four GT field slots are evaluable for the selected comparison",
        },
        "provenance": dict(sorted((provenance or {}).items())),
    }


def evaluate_entities(
    documents: Iterable[EntityDocument],
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document_list = list(documents)
    if len({document.document_id for document in document_list}) != len(document_list):
        raise ValueError("document_id values must be unique")
    counts = {field_name: {"tp": 0, "fp": 0, "fn": 0, "support": 0, "evaluable_documents": 0} for field_name in FIELDS}
    for document in document_list:
        for field_name in FIELDS:
            if field_name not in document.evaluable_fields:
                continue
            counts[field_name]["evaluable_documents"] += 1
            gold = Counter(
                (entity.start, entity.end)
                for entity in document.ground_truth
                if entity.field == field_name
            )
            predicted = Counter(
                (entity.start, entity.end)
                for entity in document.prediction
                if entity.field == field_name
            )
            matched = gold & predicted
            tp = sum(matched.values())
            counts[field_name]["tp"] += tp
            counts[field_name]["fp"] += sum((predicted - matched).values())
            counts[field_name]["fn"] += sum((gold - matched).values())
            counts[field_name]["support"] += sum(gold.values())

    field_reports: dict[str, dict[str, Any]] = {}
    for field_name, item in counts.items():
        report = _classification_metrics(
            item["tp"], item["fp"], item["fn"], item["support"], item["evaluable_documents"]
        )
        report["evaluable_documents"] = report.pop("evaluable")
        field_reports[field_name] = report
    aggregate = {
        key: sum(report[key] for report in field_reports.values())
        for key in ("tp", "fp", "fn", "support")
    }
    evaluable = sum(report["evaluable_documents"] for report in field_reports.values())
    micro = _classification_metrics(
        aggregate["tp"], aggregate["fp"], aggregate["fn"], aggregate["support"], evaluable
    )
    micro.pop("evaluable")
    micro.update(aggregate)
    macro = {
        "precision": _mean_defined(report["precision"] for report in field_reports.values()),
        "recall": _mean_defined(report["recall"] for report in field_reports.values()),
        "f1": _mean_defined(report["f1"] for report in field_reports.values()),
        "defined_f1_fields": sum(report["f1"] is not None for report in field_reports.values()),
    }
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "matching": "exact field class and exact [start,end) boundary",
        "fields": field_reports,
        "micro": micro,
        "macro": macro,
        "input_documents": len(document_list),
        "provenance": dict(sorted((provenance or {}).items())),
    }


def metrics_table_rows(report: dict[str, Any], metric_family: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name in FIELDS:
        item = report["fields"][field_name]
        rows.append({
            "metric_family": metric_family,
            "scope": "field",
            "field": field_name,
            "tp": item["tp"],
            "fp": item["fp"],
            "fn": item["fn"],
            "support": item["support"],
            "precision": item["precision"],
            "recall": item["recall"],
            "f1": item["f1"],
            "slot_exact_match": item.get("slot_exact_match"),
        })
    for scope in ("micro", "macro"):
        item = report[scope]
        rows.append({
            "metric_family": metric_family,
            "scope": scope,
            "field": "ALL",
            "tp": item.get("tp"),
            "fp": item.get("fp"),
            "fn": item.get("fn"),
            "support": item.get("support"),
            "precision": item["precision"],
            "recall": item["recall"],
            "f1": item["f1"],
            "slot_exact_match": item.get("slot_exact_match"),
        })
    if "document_exact_match" in report:
        item = report["document_exact_match"]
        rows.append({
            "metric_family": metric_family,
            "scope": "document",
            "field": "ALL",
            "tp": item["correct_documents"],
            "fp": None,
            "fn": item["eligible_documents"] - item["correct_documents"],
            "support": item["eligible_documents"],
            "precision": None,
            "recall": None,
            "f1": None,
            "slot_exact_match": item["value"],
        })
    return rows


def write_metrics_csv(rows: Iterable[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "metric_family", "scope", "field", "tp", "fp", "fn", "support",
        "precision", "recall", "f1", "slot_exact_match",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            serialized = {
                key: ("" if row.get(key) is None else row.get(key))
                for key in fieldnames
            }
            for key, value in serialized.items():
                if isinstance(value, float):
                    if not math.isfinite(value):
                        raise ValueError("Metrics table cannot contain NaN or infinity")
                    serialized[key] = format(value, ".12g")
            writer.writerow(serialized)
