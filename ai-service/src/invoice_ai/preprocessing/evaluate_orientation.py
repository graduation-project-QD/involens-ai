"""Run and evaluate the B4 orientation module against the confirmed GT rotation files.

Step 1 (models, resumable, needs the T10 OCR venv)::

    PYTHONUTF8=1 ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.preprocessing.evaluate_orientation observe \
        --dataset ../dataset_hoadon/dataset_split_80_10_10 --splits train val \
        --paddlex-home ../.cache/paddlex --observations ../experiments/data/processed/orientation_v1

Observations recorded before the 180° flip check existed are completed with ``flipcheck`` (same
arguments as ``observe``; the detector is not re-run).

Step 2 (decision + metrics, plain Python)::

    python -m invoice_ai.preprocessing.evaluate_orientation evaluate \
        --dataset ../dataset_hoadon/dataset_split_80_10_10 --splits train val \
        --observations ../experiments/data/processed/orientation_v1 --out ../experiments/reports/orientation_v1_2026-10-10

``--sweep`` additionally grid-searches the deskew rule on the first split given (use train).
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from statistics import mean, median
from typing import Any

from invoice_ai.preprocessing.orientation import (
    ORIENTATION_VERSION,
    DeskewParams,
    Observation,
    angular_error,
    decide,
    read_bgr,
)


def _gt(dataset: Path, split: str) -> dict[str, int]:
    with (dataset / f"mcocr_{split}_rotation.csv").open(encoding="utf-8-sig", newline="") as handle:
        return {r["img_id"]: int(r["rotation_to_upright"]) % 360 for r in csv.DictReader(handle)}


def _load_observations(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return {record["img_id"]: record for record in map(json.loads, handle) if record}


def observe(args: argparse.Namespace) -> None:
    from invoice_ai.preprocessing.orientation import OrientationModels

    models = OrientationModels(args.paddlex_home, cpu_threads=args.cpu_threads)
    args.observations.mkdir(parents=True, exist_ok=True)
    for split in args.splits:
        path = args.observations / f"{split}.jsonl"
        done = _load_observations(path)
        todo = [i for i in sorted(_gt(args.dataset, split)) if i not in done]
        print(f"{split}: {len(done)} cached, {len(todo)} to run", flush=True)
        with path.open("a", encoding="utf-8") as handle:
            for index, img_id in enumerate(todo, 1):
                start = time.perf_counter()
                observation = observe_one(models, args.dataset / f"{split}_images" / img_id)
                record = {"img_id": img_id, "seconds": round(time.perf_counter() - start, 3), **observation.to_dict()}
                handle.write(json.dumps(record) + "\n")
                handle.flush()
                if index % 50 == 0:
                    print(f"  {split} {index}/{len(todo)}", flush=True)


def observe_one(models: Any, path: Path) -> Observation:
    return models.observe(read_bgr(path))


def flipcheck(args: argparse.Namespace) -> None:
    """Add ``flip_pairs`` to observations recorded before the flip check existed (no detector re-run)."""
    from invoice_ai.preprocessing.orientation import OrientationModels

    models = OrientationModels(args.paddlex_home, cpu_threads=args.cpu_threads)
    for split in args.splits:
        path = args.observations / f"{split}.jsonl"
        records = _load_observations(path)
        updated = 0
        for index, (img_id, record) in enumerate(sorted(records.items()), 1):
            if "flip_pairs" in record and not args.force:
                continue
            start = time.perf_counter()
            observation = models.add_flip_check(read_bgr(args.dataset / f"{split}_images" / img_id), Observation.from_dict(record))
            record.update(observation.to_dict())
            record["flip_seconds"] = round(time.perf_counter() - start, 3)
            updated += 1
            if index % 100 == 0:
                print(f"  {split} {index}/{len(records)}", flush=True)
                _write_records(path, records)  # checkpoint: progress survives an interruption
        _write_records(path, records)
        print(f"{split}: flip check added to {updated} records", flush=True)


def _write_records(path: Path, records: dict[str, dict[str, Any]]) -> None:
    temporary = path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for img_id in sorted(records):
            handle.write(json.dumps(records[img_id]) + "\n")
    temporary.replace(path)


def score(gt: dict[str, int], observations: dict[str, dict[str, Any]], params: DeskewParams) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    for img_id, truth in sorted(gt.items()):
        if img_id not in observations:
            continue
        observation = Observation.from_dict(observations[img_id])
        result = decide(observation, params)
        truth_coarse = (round(truth / 90) % 4) * 90
        rows.append(
            {
                "img_id": img_id,
                "gt_cw": truth,
                "gt_coarse_cw": truth_coarse,
                "pred_coarse_cw": result.coarse_cw,
                "coarse_score": round(result.coarse_score, 4),
                "skew_deg": result.skew_deg,
                "pred_total_cw": result.total_cw,
                "boxes_used": result.boxes_used,
                "flipped": result.flipped,
                "coarse_correct": result.coarse_cw == truth_coarse,
                "error_total": round(angular_error(result.total_cw, truth), 2),
                "error_coarse_only": round(angular_error(result.coarse_cw, truth), 2),
                "seconds": observations[img_id].get("seconds"),
                "flip_seconds": observations[img_id].get("flip_seconds"),
            }
        )
    return summarize(rows), rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"images": 0}
    correct = [r for r in rows if r["coarse_correct"]]

    def stats(key: str, subset: list[dict[str, Any]]) -> dict[str, Any]:
        values = [r[key] for r in subset]
        return {
            "mae": round(mean(values), 3),
            "median": round(median(values), 3),
            "within_1deg": round(sum(v <= 1 for v in values) / len(values), 4),
            "within_2deg": round(sum(v <= 2 for v in values) / len(values), 4),
        }

    by_class: dict[str, dict[str, Any]] = {}
    for angle in (0, 90, 180, 270):
        subset = [r for r in rows if r["gt_coarse_cw"] == angle]
        if subset:
            by_class[str(angle)] = {"images": len(subset), "coarse_accuracy": round(sum(r["coarse_correct"] for r in subset) / len(subset), 4)}
    seconds = [r["seconds"] for r in rows if r["seconds"] is not None]
    flip_seconds = [r["flip_seconds"] for r in rows if r["flip_seconds"] is not None]
    return {
        "images": len(rows),
        "coarse_accuracy": round(len(correct) / len(rows), 4),
        "coarse_by_gt_class": by_class,
        "error_with_deskew_on_coarse_correct": stats("error_total", correct) if correct else None,
        "error_coarse_only_on_coarse_correct": stats("error_coarse_only", correct) if correct else None,
        "mean_seconds_classify_detect": round(mean(seconds), 3) if seconds else None,
        "mean_seconds_flip_check": round(mean(flip_seconds), 3) if flip_seconds else None,
        "coarse_errors": [
            {k: r[k] for k in ("img_id", "gt_cw", "pred_coarse_cw", "coarse_score")} for r in rows if not r["coarse_correct"]
        ],
    }


def sweep(gt: dict[str, int], observations: dict[str, dict[str, Any]]) -> tuple[DeskewParams, list[dict[str, Any]]]:
    grid = []
    grid_values = itertools.product((2.0, 2.5, 4.0, 6.0), (0.0, 0.5, 1.0), (3, 5), (None, 0.05, 0.1, 0.2))
    for min_aspect, min_abs, min_boxes, flip_margin in grid_values:
        params = DeskewParams(min_aspect=min_aspect, min_abs_skew=min_abs, min_boxes=min_boxes, flip_margin=flip_margin)
        summary, _ = score(gt, observations, params)
        error = summary["error_with_deskew_on_coarse_correct"]
        grid.append({**asdict(params), "coarse_accuracy": summary["coarse_accuracy"], **error})
    # Orientation first (a wrong 180° ruins OCR), then the fine angle.
    best = min(grid, key=lambda g: (-g["coarse_accuracy"], g["mae"], -g["within_1deg"]))
    chosen = replace(
        DeskewParams(),
        min_aspect=best["min_aspect"],
        min_abs_skew=best["min_abs_skew"],
        min_boxes=best["min_boxes"],
        flip_margin=best["flip_margin"],
    )
    return chosen, grid


def evaluate(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    params = DeskewParams()
    report: dict[str, Any] = {"orientation_version": ORIENTATION_VERSION, "splits": {}}
    if args.sweep:
        tune = args.splits[0]
        params, grid = sweep(_gt(args.dataset, tune), _load_observations(args.observations / f"{tune}.jsonl"))
        report["sweep_split"] = tune
        report["sweep"] = grid
    report["params"] = asdict(params)
    for split in args.splits:
        summary, rows = score(_gt(args.dataset, split), _load_observations(args.observations / f"{split}.jsonl"), params)
        report["splits"][split] = summary
        if rows:
            with (args.out / f"{split}_predictions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    (args.out / "orientation_metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"params": report["params"], "splits": report["splits"]}, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("observe", "flipcheck", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--dataset", type=Path, required=True)
        p.add_argument("--splits", nargs="+", default=["train", "val"])
        p.add_argument("--observations", type=Path, required=True)
        if name in ("observe", "flipcheck"):
            p.add_argument("--paddlex-home", type=Path, required=True)
            p.add_argument("--cpu-threads", type=int, default=6)
            if name == "flipcheck":
                p.add_argument("--force", action="store_true", help="recompute existing flip_pairs")
        else:
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--sweep", action="store_true")
    args = parser.parse_args()
    {"observe": observe, "flipcheck": flipcheck, "evaluate": evaluate}[args.command](args)


if __name__ == "__main__":
    main()
