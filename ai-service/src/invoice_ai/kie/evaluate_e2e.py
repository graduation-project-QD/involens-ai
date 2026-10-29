"""End-to-end evaluation of B11 post-processing, plus the train-GT audit used to choose its rules.

Usage::

    python -m invoice_ai.kie.evaluate_e2e evaluate --dataset ../dataset_hoadon/dataset_upright_v1 --split val \
        --predictions ../experiments/artifacts/b10/b10_results_20261026/e2/predict_val/predictions.jsonl \
        --ocr ../experiments/data/processed/kie_bio_v3/val.ocr.jsonl --out ../experiments/reports/b11_postprocess_2026-10-29
    python -m invoice_ai.kie.evaluate_e2e audit-gt --dataset ../dataset_hoadon/dataset_upright_v1 --split train \
        --ocr ../experiments/data/processed/kie_bio_v3/train.ocr.jsonl --out ../experiments/reports/b11_postprocess_2026-10-29

``evaluate`` compares three modes against GT on the same documents: ``raw`` (grouped OCR text, no B11),
``normalized`` (B11 normalization without quantity inference) and ``b11`` (full post-processing).
GT field values join the labelled regions in reading order and use the same normalizers. Text values compare
with ``bio.match_key`` (case and spacing around punctuation ignored); numbers and timestamps compare normalized.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

from invoice_ai.evaluation.core import EvaluationDocument, FieldGroundTruth, FieldPrediction, evaluate_fields
from invoice_ai.kie.bio import match_key
from invoice_ai.kie.data import LabeledDocument, load_split
from invoice_ai.kie.grouping import Entity, group_document_fields
from invoice_ai.kie.labels import DOCUMENT_LABELS, LINE_ITEM_LABELS
from invoice_ai.kie.postprocess import (
    CONTRACT_KEYS,
    POSTPROCESS_VERSION,
    DocumentPrediction,
    FieldResult,
    PostprocessResult,
    infer_quantity,
    normalize_value,
    postprocess_document,
)

logger = logging.getLogger(__name__)

MODES: dict[str, dict[str, bool]] = {
    "raw": {"normalize": False, "infer": False},
    "normalized": {"normalize": True, "infer": False},
    "b11": {"normalize": True, "infer": True},
}
TEXT_KEYS = frozenset({"seller", "address", "item_name"})
HEADER_KEYS = tuple(CONTRACT_KEYS[label] for label in DOCUMENT_LABELS)
ITEM_KEYS = tuple(CONTRACT_KEYS[label] for label in LINE_ITEM_LABELS)
# evaluation.core keeps the T14 field names; timestamps are compared as full ISO date-times in the "date" slot.
EVALUATOR_SLOTS = {"seller": "company", "address": "address", "timestamp": "date", "total_cost": "total"}
DATE_WORD_RE = re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}[.,:;]?")


@dataclass(frozen=True)
class GroundTruth:
    """Reference values of one document: raw and normalized header fields (None when absent) and line items."""

    header_raw: dict[str, str | None]
    header_value: dict[str, str | None]
    header_status: dict[str, str]
    items_raw: list[dict[str, str | None]]
    items_value: list[dict[str, str | None]]


def comparison_key(key: str, value: str | None, mode: str) -> str | None:
    """Value used for equality: match_key for text (and for every field in raw mode), normalized string otherwise."""
    if value is None:
        return None
    return match_key(value) or None if mode == "raw" or key in TEXT_KEYS else value


def load_predictions(predictions_path: Path, ocr_path: Path) -> dict[str, DocumentPrediction]:
    """Joins LayoutXLM word predictions with the OCR records (words, 0–1000 boxes, line index, image size)."""
    logger.info("Loading predictions. predictions=%s, ocr=%s", predictions_path, ocr_path)
    ocr = {}
    with ocr_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            ocr[record["img_id"]] = record
    documents = {}
    with predictions_path.open(encoding="utf-8") as handle:
        for line in handle:
            prediction = json.loads(line)
            record = ocr[prediction["img_id"]]
            if len(prediction["pred"]) != len(record["words"]):
                logger.error("Prediction length differs from OCR words. img_id=%s", prediction["img_id"])
                raise ValueError(f"{prediction['img_id']}: prediction and OCR word counts differ")
            documents[prediction["img_id"]] = DocumentPrediction(
                prediction["img_id"], record["words"], record["boxes"], record["line_index"], prediction["pred"],
                prediction.get("score"), int(record["width"]), int(record["height"]),
            )
    logger.info("Predictions loaded. documents=%d", len(documents))
    return documents


def _join_reading_order(regions: Iterable[tuple[tuple[float, float, float, float], str]]) -> str | None:
    """Joins region texts top-to-bottom, left-to-right; None when there is no text."""
    ordered = sorted(regions, key=lambda item: (item[0][1], item[0][0]))
    text = " ".join(t.strip() for _, t in ordered if t.strip())
    return text or None


def build_ground_truth(document: LabeledDocument) -> GroundTruth:
    """Builds reference values from labelled regions: header fields via the same field grouping as predictions,
    line items from ``line_item_id``. A header label marked missing by annotators is ``absent``; a label with no
    region and no mark is ``unlabeled`` and excluded from scoring."""
    regions = [Entity(r.index, r.label, r.text, document.upright_bbox(r)) for r in document.regions]
    joined, _ = group_document_fields(regions)
    header_raw, header_value, header_status = {}, {}, {}
    for label in DOCUMENT_LABELS:
        key = CONTRACT_KEYS[label]
        header_raw[key] = joined[label]
        header_value[key] = normalize_value(label, joined[label]).normalized_value if joined[label] else None
        header_status[key] = "annotated" if joined[label] else ("absent" if label in document.missing_fields else "unlabeled")
    by_item: dict[int, list[Any]] = defaultdict(list)
    for region in document.regions:
        if region.line_item_id is not None:
            by_item[region.line_item_id].append(region)
    items_raw, items_value = [], []
    for item_id in sorted(by_item):
        raw = {
            CONTRACT_KEYS[label]: _join_reading_order((document.upright_bbox(r), r.text) for r in by_item[item_id] if r.label == label)
            for label in LINE_ITEM_LABELS
        }
        items_raw.append(raw)
        items_value.append({
            CONTRACT_KEYS[label]: normalize_value(label, raw[CONTRACT_KEYS[label]]).normalized_value if raw[CONTRACT_KEYS[label]] else None
            for label in LINE_ITEM_LABELS
        })
    return GroundTruth(header_raw, header_value, header_status, items_raw, items_value)


def _gt_items(gt: GroundTruth, mode: str) -> list[dict[str, str | None]]:
    return [{k: comparison_key(k, v, mode) for k, v in item.items()} for item in (gt.items_raw if mode == "raw" else gt.items_value)]


def _pred_items(result: PostprocessResult, mode: str) -> list[dict[str, str | None]]:
    return [{k: comparison_key(k, v.value, mode) for k, v in item.items()} for item in result.line_items]


def pair_line_items(gt_items: list[dict[str, str | None]], pred_items: list[dict[str, str | None]]) -> list[tuple[int | None, int | None]]:
    """Pairs each GT item with the unused predicted item sharing the most equal non-empty cells (greedy, in order).

    Unpaired GT items (missed) and predicted items (extra) are returned with None on the other side.
    """
    left = list(range(len(pred_items)))
    pairs: list[tuple[int | None, int | None]] = []
    for gi, gt_item in enumerate(gt_items):
        def agreement(pi: int) -> int:
            return sum(1 for k in ITEM_KEYS if gt_item[k] is not None and gt_item[k] == pred_items[pi][k])

        best = max(left, key=agreement, default=None)
        if best is not None and agreement(best) > 0:
            left.remove(best)
            pairs.append((gi, best))
        else:
            pairs.append((gi, None))
    pairs.extend((None, pi) for pi in left)
    return pairs


def score_document(gt: GroundTruth, result: PostprocessResult, mode: str) -> dict[str, Any]:
    """Counts the cells a user would have to correct (wrong, missing or extra values) and exact line items."""
    errors = []
    for key in HEADER_KEYS:
        if gt.header_status[key] == "unlabeled":
            continue
        gt_value = gt.header_raw[key] if mode == "raw" else gt.header_value[key]
        if gt.header_status[key] == "annotated" and gt_value is None:
            continue  # GT itself cannot be normalized: not scorable
        expected, predicted = comparison_key(key, gt_value, mode), comparison_key(key, result.fields[key].value, mode)
        if expected != predicted:
            errors.append({"field": key, "item": None, "gt": gt_value, "pred": result.fields[key].value, "raw": result.fields[key].raw_text})
    gt_items, pred_items = _gt_items(gt, mode), _pred_items(result, mode)
    source_gt = gt.items_raw if mode == "raw" else gt.items_value
    inferred_total = inferred_correct = 0
    cells = sum(1 for key in HEADER_KEYS if gt.header_status[key] != "unlabeled")
    for gi, pi in pair_line_items(gt_items, pred_items):
        for key in ITEM_KEYS:
            expected = gt_items[gi][key] if gi is not None else None
            predicted = pred_items[pi][key] if pi is not None else None
            cell = result.line_items[pi][key] if pi is not None else FieldResult(None, None, None)
            if expected is None and predicted is None:
                continue
            cells += 1
            if cell.inferred:
                inferred_total += 1
                inferred_correct += expected == predicted
            if expected != predicted:
                errors.append({
                    "field": key, "item": gi if gi is not None else f"extra{pi}",
                    "gt": source_gt[gi][key] if gi is not None else None, "pred": cell.value, "raw": cell.raw_text,
                })
    exact_items = sum((Counter(tuple(i[k] for k in ITEM_KEYS) for i in gt_items)
                       & Counter(tuple(i[k] for k in ITEM_KEYS) for i in pred_items)).values())
    return {
        "cells": cells, "errors": errors, "gt_items": len(gt_items), "pred_items": len(pred_items), "exact_items": exact_items,
        "inferred": inferred_total, "inferred_correct": inferred_correct,
    }


def header_evaluation_document(img_id: str, gt: GroundTruth, result: PostprocessResult, mode: str) -> EvaluationDocument:
    """Maps one document to the shared T14 field evaluator (exact match on comparison keys)."""
    ground_truth, prediction = {}, {}
    for key, slot in EVALUATOR_SLOTS.items():
        status = gt.header_status[key]
        raw = gt.header_raw[key] if status == "annotated" else None
        value = comparison_key(key, gt.header_raw[key] if mode == "raw" else gt.header_value[key], mode)
        ground_truth[slot] = FieldGroundTruth("unlabeled" if status == "unlabeled" else status, raw, value,
                                              "ok" if value is not None else "invalid")
        prediction[slot] = FieldPrediction(result.fields[key].raw_text, comparison_key(key, result.fields[key].value, mode))
    return EvaluationDocument(img_id, ground_truth, prediction)


def summarize(scored: dict[str, dict[str, Any]], results: dict[str, PostprocessResult], header: dict[str, Any]) -> dict[str, Any]:
    """Aggregates per-document scores: cells to fix, line-item F1, per-field error rates and review routing."""
    documents = len(scored)
    cells = sum(s["cells"] for s in scored.values())
    wrong = sum(len(s["errors"]) for s in scored.values())
    per_doc = Counter(min(len(s["errors"]), 4) for s in scored.values())
    by_field_wrong = Counter(e["field"] for s in scored.values() for e in s["errors"])
    gt_items = sum(s["gt_items"] for s in scored.values())
    pred_items = sum(s["pred_items"] for s in scored.values())
    exact = sum(s["exact_items"] for s in scored.values())
    precision, recall = exact / pred_items if pred_items else 0.0, exact / gt_items if gt_items else 0.0
    flagged = {d for d, r in results.items() if r.needs_review}
    with_errors = {d for d, s in scored.items() if s["errors"]}
    return {
        "documents": documents,
        "cells": cells,
        "wrong_cells": wrong,
        "wrong_cell_rate": round(wrong / cells, 4) if cells else None,
        "wrong_cells_per_document": round(wrong / documents, 3) if documents else None,
        "documents_by_wrong_cells": {("4+" if k == 4 else str(k)): per_doc[k] for k in range(5)},
        "error_free_documents": round(per_doc[0] / documents, 4) if documents else None,
        "wrong_cells_by_field": dict(sorted(by_field_wrong.items())),
        "line_items": {
            "gt": gt_items, "predicted": pred_items, "exact": exact,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        },
        "header_fields": {
            slot_key: {"f1": header["fields"][slot]["f1"], "slot_exact_match": header["fields"][slot]["slot_exact_match"]}
            for slot_key, slot in EVALUATOR_SLOTS.items()
        },
        "header_document_exact_match": header["document_exact_match"]["value"],
        "quantity_inferred": {
            "count": sum(s["inferred"] for s in scored.values()),
            "correct": sum(s["inferred_correct"] for s in scored.values()),
        },
        "review_routing": {
            "needs_review": len(flagged),
            "with_errors": len(with_errors),
            "flagged_with_errors": len(flagged & with_errors),
            "flagged_without_errors": len(flagged - with_errors),
            "missed_with_errors": len(with_errors - flagged),
            "warnings_by_code": dict(Counter(w["code"] for r in results.values() for w in r.warnings)),
        },
    }


def evaluate(args: argparse.Namespace) -> None:
    """Scores the three modes on one split and writes metrics, per-document counts and the B11 error list."""
    logger.info("Starting end-to-end evaluation. split=%s", args.split)
    predictions = load_predictions(args.predictions, args.ocr)
    documents = {d.img_id: d for d in load_split(args.dataset, args.split) if d.img_id in predictions}
    ground_truth = {img_id: build_ground_truth(document) for img_id, document in documents.items()}
    report: dict[str, Any] = {"postprocess_version": POSTPROCESS_VERSION, "split": args.split, "predictions": str(args.predictions), "modes": {}}
    args.out.mkdir(parents=True, exist_ok=True)
    for mode, options in MODES.items():
        results = {img_id: postprocess_document(predictions[img_id], **options) for img_id in documents}
        scored = {img_id: score_document(ground_truth[img_id], results[img_id], mode) for img_id in documents}
        header = evaluate_fields([header_evaluation_document(i, ground_truth[i], results[i], mode) for i in documents], "normalized")
        report["modes"][mode] = summarize(scored, results, header)
        logger.info("Mode evaluated. mode=%s, wrong_cells_per_document=%s", mode, report["modes"][mode]["wrong_cells_per_document"])
        if mode == "b11":
            write_b11_details(args.out, scored, results)
    (args.out / f"metrics_{args.split}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("End-to-end evaluation completed. out=%s", args.out)


def write_b11_details(out: Path, scored: dict[str, dict[str, Any]], results: dict[str, PostprocessResult]) -> None:
    """Writes every wrong cell (for the error analysis) and per-document counts of the full B11 mode."""
    with (out / "errors_b11.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["img_id", "field", "item", "gt", "pred", "raw_text"])
        for img_id, score in scored.items():
            for error in score["errors"]:
                writer.writerow([img_id, error["field"], error["item"], error["gt"], error["pred"], error["raw"]])
    with (out / "per_document_b11.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["img_id", "cells", "wrong_cells", "gt_items", "pred_items", "exact_items", "needs_review", "warnings"])
        for img_id, score in scored.items():
            result = results[img_id]
            writer.writerow([img_id, score["cells"], len(score["errors"]), score["gt_items"], score["pred_items"], score["exact_items"],
                             result.needs_review, ";".join(f"{w['code']}:{w['target']}" for w in result.warnings)])


def audit_ground_truth(args: argparse.Namespace) -> None:
    """Measures on train GT the facts the B11 rules rely on: normalizer coverage, quantity inference accuracy
    and which timestamp annotators label when a receipt prints several dates."""
    logger.info("Starting GT audit. split=%s", args.split)
    documents = load_split(args.dataset, args.split)
    coverage: dict[str, Counter[str]] = defaultdict(Counter)
    failures: dict[str, list[str]] = defaultdict(list)
    inference = Counter()
    for document in documents:
        gt = build_ground_truth(document)
        for label in DOCUMENT_LABELS:
            key = CONTRACT_KEYS[label]
            if gt.header_raw[key]:
                ok = gt.header_value[key] is not None
                coverage[key]["ok" if ok else "failed"] += 1
                if not ok:
                    failures[key].append(gt.header_raw[key])
        for raw, value in zip(gt.items_raw, gt.items_value):
            for key in ITEM_KEYS:
                if raw[key]:
                    ok = value[key] is not None
                    coverage[key]["ok" if ok else "failed"] += 1
                    if not ok:
                        failures[key].append(raw[key])
            item = {k: FieldResult(value[k], raw[k], None) for k in ITEM_KEYS}
            item["quantity"] = FieldResult(None, None, None)
            inferred = infer_quantity(item)
            if value["quantity"] is not None and value["unit_price"] and value["line_total"]:
                if inferred is None:
                    inference["not_inferred"] += 1
                elif Decimal(inferred.value) == Decimal(value["quantity"]):
                    inference["correct"] += 1
                else:
                    inference["wrong"] += 1
            elif value["quantity"] is None and inferred is not None:
                inference["would_fill_absent_gt_quantity"] += 1
    report = {
        "split": args.split,
        "documents": len(documents),
        "normalizer_coverage": {k: dict(v) for k, v in coverage.items()},
        "normalizer_failures": {k: v[:30] for k, v in failures.items()},
        "quantity_inference_on_gt": dict(inference),
        "multiple_dates": timestamp_choice_audit(args.ocr) if args.ocr else None,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"audit_gt_{args.split}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("GT audit completed. out=%s", args.out)


def timestamp_choice_audit(ocr_path: Path) -> dict[str, int]:
    """On receipts whose OCR words contain two or more full dates, counts which of them GT labels as TIMESTAMP
    (first only, last only, all, other mixes or none), using the GT-aligned tags of the BIO records."""
    counts: Counter[str] = Counter()
    with ocr_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            indices = [i for i, word in enumerate(record["words"]) if DATE_WORD_RE.fullmatch(word)]
            if len(indices) < 2:
                continue
            labelled = [record["tags"][i].endswith("TIMESTAMP") for i in indices]
            if all(labelled):
                counts["all"] += 1
            elif not any(labelled):
                counts["none"] += 1
            elif labelled[0] and not any(labelled[1:]):
                counts["first_only"] += 1
            elif labelled[-1] and not any(labelled[:-1]):
                counts["last_only"] += 1
            else:
                counts["mixed"] += 1
    return dict(counts)


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("invoice_ai.kie.postprocess").setLevel(logging.WARNING)  # per-document logs are too verbose for batch scoring
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--dataset", type=Path, required=True)
    e.add_argument("--split", default="val")
    e.add_argument("--predictions", type=Path, required=True)
    e.add_argument("--ocr", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("audit-gt")
    a.add_argument("--dataset", type=Path, required=True)
    a.add_argument("--split", default="train")
    a.add_argument("--ocr", type=Path, help="BIO records of the split, for the multiple-date audit")
    a.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    {"evaluate": evaluate, "audit-gt": audit_ground_truth}[args.command](args)


if __name__ == "__main__":
    main()
