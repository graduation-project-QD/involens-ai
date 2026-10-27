"""Evaluate line-item grouping and field ordering on GT boxes, using ``line_item_id`` as the reference.

Usage::

    python -m invoice_ai.kie.evaluate_grouping --dataset ../dataset_hoadon/dataset_merge \
        --out ../experiments/reports/kie_grouping_v1
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Sequence

from invoice_ai.kie.data import LabeledDocument, available_splits, load_split
from invoice_ai.kie.geometry import order_rows
from invoice_ai.kie.grouping import (
    GROUPING_VERSION,
    Entity,
    LineItem,
    group_document_fields,
    group_line_items,
    group_line_items_anchored,
)
from invoice_ai.kie.labels import DOCUMENT_LABELS, LINE_ITEM_LABELS

Grouper = Callable[[Sequence[Entity]], tuple[list[LineItem], str]]


def gt_entities(document: LabeledDocument) -> list[Entity]:
    return [Entity(r.index, r.label, r.text, document.upright_bbox(r)) for r in document.regions]


def one_row_one_item(entities: Sequence[Entity]) -> tuple[list[LineItem], str]:
    """Naive baseline: every visual row of item boxes is one line item."""
    items = [e for e in entities if e.label in LINE_ITEM_LABELS]
    groups = []
    for row in order_rows([e.box for e in items]):
        group = LineItem()
        group.add([items[i] for i in row])
        groups.append(group)
    return groups, "rows"


def _pairs(partition: Sequence[Sequence[int]]) -> set[tuple[int, int]]:
    return {tuple(sorted(p)) for group in partition for p in itertools.combinations(group, 2)}


def evaluate(documents: Sequence[LabeledDocument], grouper: Grouper) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    counts: Counter[str] = Counter()
    layouts: Counter[str] = Counter()
    per_layout: defaultdict[str, Counter[str]] = defaultdict(Counter)
    failures = []
    for document in documents:
        entities = gt_entities(document)
        gt_groups: defaultdict[int, list[int]] = defaultdict(list)
        for region in document.regions:
            if region.line_item_id is not None:
                gt_groups[region.line_item_id].append(region.index)
        if not gt_groups:
            continue
        predicted, layout = grouper(entities)
        pred_sets = {frozenset(g.members) for g in predicted}
        gt_sets = {frozenset(g) for g in gt_groups.values()}
        gt_pairs, pred_pairs = _pairs(list(gt_groups.values())), _pairs([g.members for g in predicted])
        exact = len(gt_sets & pred_sets)
        ok = gt_sets == pred_sets
        for target in (counts, per_layout[layout]):
            target["images"] += 1
            target["images_exact"] += ok
            target["gt_items"] += len(gt_sets)
            target["pred_items"] += len(pred_sets)
            target["exact_items"] += exact
            target["pair_tp"] += len(gt_pairs & pred_pairs)
            target["pair_gt"] += len(gt_pairs)
            target["pair_pred"] += len(pred_pairs)
        layouts[layout] += 1
        if not ok:
            by_index = {r.index: r for r in document.regions}

            def describe(groups: Sequence[Sequence[int]]) -> str:
                return " || ".join(
                    " + ".join(f"{by_index[i].label[:4]}:{by_index[i].text}" for i in sorted(g)) for g in groups
                )

            failures.append(
                {
                    "split": document.split,
                    "img_id": document.img_id,
                    "layout": layout,
                    "gt_items": len(gt_sets),
                    "pred_items": len(pred_sets),
                    "missing_gt_items": describe([sorted(g) for g in gt_sets - pred_sets]),
                    "wrong_pred_items": describe([sorted(g) for g in pred_sets - gt_sets]),
                }
            )
    return {"overall": _summarize(counts), "by_layout": {k: _summarize(v) for k, v in per_layout.items()}}, failures


def _summarize(c: Counter[str]) -> dict[str, Any]:
    def ratio(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    precision, recall = ratio(c["pair_tp"], c["pair_pred"]), ratio(c["pair_tp"], c["pair_gt"])
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall else None
    return {
        "images": c["images"],
        "image_exact_rate": ratio(c["images_exact"], c["images"]),
        "gt_items": c["gt_items"],
        "pred_items": c["pred_items"],
        "item_exact_recall": ratio(c["exact_items"], c["gt_items"]),
        "item_exact_precision": ratio(c["exact_items"], c["pred_items"]),
        "pair_precision": precision,
        "pair_recall": recall,
        "pair_f1": f1,
    }


def evaluate_field_order(documents: Sequence[LabeledDocument]) -> dict[str, Any]:
    """Share of multi-box document fields whose reading-order join equals the annotation order."""
    result: dict[str, Any] = {}
    for label in DOCUMENT_LABELS:
        total = same = 0
        for document in documents:
            entities = gt_entities(document)
            boxes = [e for e in entities if e.label == label]
            if len(boxes) < 2 or label == "TOTAL_COST":
                continue
            _, members = group_document_fields(entities)
            total += 1
            same += members[label] == [e.ref for e in boxes]
        result[label] = {"multi_box_fields": total, "same_as_annotation_order": round(same / total, 4) if total else None}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"grouping_version": GROUPING_VERSION, "dataset": str(args.dataset), "splits": {}}
    all_failures = []
    for split in available_splits(args.dataset):
        documents = load_split(args.dataset, split)
        anchored, failures = evaluate(documents, group_line_items_anchored)
        row_walk, _ = evaluate(documents, group_line_items)
        baseline, _ = evaluate(documents, one_row_one_item)
        report["splits"][split] = {
            "line_items_anchored": anchored,
            "line_items_row_walk": row_walk,
            "line_items_baseline_one_row_one_item": baseline,
            "document_field_order": evaluate_field_order(documents),
        }
        all_failures.extend(failures)
    (args.out / "grouping_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.out / "grouping_failures.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["split", "img_id", "layout", "gt_items", "pred_items", "missing_gt_items", "wrong_pred_items"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_failures)
    print(json.dumps(report["splits"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
