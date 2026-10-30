"""B5: tune PaddleOCR text detection (input size, thresholds, background crop) by recall per label.

Selection uses train only (two rounds: a seller-stratified subset, then the full train split for the
best configurations); the chosen configuration is reported once on val. No recognition is involved.

Metric per GT region (upright frame): *detected* when one detection box overlaps it by at least half of
the smaller of the two areas (a tight box inside a generously drawn GT box counts, as does a line box
that contains the region; this matches the word-in-region rule of BIO alignment); *merged* when that
box overlaps a region with another label in the same way.
Background crop is checked with the share of GT regions that stay inside the crop rectangle.

Commands (``run`` needs the T10 OCR venv; ``evaluate`` is plain Python)::

    PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.ocr.detection_tuning run \
        --dataset ../dataset_hoadon/dataset_upright_v1 --split train --subset 300 \
        --configs L960 L1280 --paddlex-home ../.cache/paddlex --out ../experiments/data/processed/detection_tuning_v1
    python -m invoice_ai.ocr.detection_tuning evaluate --dataset ../dataset_hoadon/dataset_upright_v1 --split train \
        --subset 300 --out ../experiments/data/processed/detection_tuning_v1 --report <dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Sequence

import numpy as np

from invoice_ai.kie.data import LabeledDocument, load_split
from invoice_ai.kie.geometry import area, bbox, intersection_area
from invoice_ai.kie.labels import SEMANTIC_LABELS

TUNING_VERSION = "detection_tuning_v1"
SEED = 42
DETECTION_MODEL = "PP-OCRv5_mobile_det"
CROP_SOURCE = "L960"  # boxes of the default-size pass decide the crop (B4 already runs this pass online)


@dataclass(frozen=True)
class DetConfig:
    name: str
    resize_long: int = 960  # long side fed to the detector (PaddleOCR default for this model: max 960)
    box_thresh: float = 0.6
    unclip_ratio: float = 1.5
    crop: bool = False
    thresh: float = 0.3  # DB binarisation threshold of the probability map
    model: str = DETECTION_MODEL
    crop_from_self: bool = False  # crop from the same settings without crop (instead of L960) + 3% margin

    @property
    def crop_source(self) -> str:
        return self.name.replace("_s1", "").replace("C", "L", 1) if self.crop_from_self else CROP_SOURCE


CONFIGS: dict[str, DetConfig] = {
    c.name: c
    for c in [
        DetConfig("L960"),
        DetConfig("L1280", 1280),
        DetConfig("L1600", 1600),
        DetConfig("L1920", 1920),
        DetConfig("C960", 960, crop=True),
        DetConfig("C1280", 1280, crop=True),
        DetConfig("C1600", 1600, crop=True),
        DetConfig("C1920", 1920, crop=True),
    ]
}


MODEL_PREFIXES = {"V6": "PP-OCRv6_medium_det"}


def config_by_name(name: str) -> DetConfig:
    """Parse ``[V6]{L|C}<size>[_b<box_thresh>][_u<unclip>][_t<thresh>][_s1]``, e.g. ``V6C1600_b0.3_t0.2``.

    ``_s1`` crops from the boxes of the matching non-crop configuration and adds a 3% page margin.
    """
    if name in CONFIGS:
        return CONFIGS[name]
    head, *options = name.split("_")
    model = DETECTION_MODEL
    for prefix, model_name in MODEL_PREFIXES.items():
        if head.startswith(prefix):
            model, head = model_name, head[len(prefix):]
    if head[0] not in "LC" or not head[1:].isdigit():
        raise ValueError(f"unknown detection config {name}")
    values = {"b": 0.6, "u": 1.5, "t": 0.3, "s": 0.0}
    for option in options:
        values[option[0]] = float(option[1:])
    config = DetConfig(name, int(head[1:]), values["b"], values["u"], head[0] == "C", values["t"], model, values["s"] == 1.0)
    CONFIGS[name] = config
    return config


# ----------------------------------------------------------------------------- background crop


@dataclass(frozen=True)
class CropParams:
    min_score: float = 0.5
    min_height_px: float = 6.0
    min_boxes: int = 5
    link_gap: float = 6.0  # boxes closer than link_gap x median text height belong to one cluster
    margin: float = 2.5  # margin around the cluster, in median text heights
    margin_page: float = 0.0  # minimum margin as a fraction of the page's long side
    max_area_ratio: float = 0.85  # do not crop when the cluster already fills the page


def text_crop_rect(
    boxes: Sequence[Sequence[tuple[float, float]]],
    scores: Sequence[float],
    width: int,
    height: int,
    params: CropParams = CropParams(),
) -> tuple[int, int, int, int] | None:
    """Rectangle around the largest cluster of text boxes (drops camera watermarks, background text)."""
    rects = []
    for quad, score in zip(boxes, scores):
        x0, y0, x1, y1 = bbox(quad)
        if score >= params.min_score and (y1 - y0) >= params.min_height_px and x1 > x0:
            rects.append((x0, y0, x1, y1))
    if len(rects) < params.min_boxes:
        return None
    text_height = median(r[3] - r[1] for r in rects)
    gap_limit = params.link_gap * text_height
    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(rects):
        for j in range(i + 1, len(rects)):
            b = rects[j]
            dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
            dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
            if max(dx, dy) <= gap_limit:
                parent[find(i)] = find(j)
    clusters: defaultdict[int, list[tuple[float, float, float, float]]] = defaultdict(list)
    for i, r in enumerate(rects):
        clusters[find(i)].append(r)
    main = max(clusters.values(), key=lambda c: sum((r[2] - r[0]) * (r[3] - r[1]) for r in c))
    pad = max(params.margin * text_height, params.margin_page * max(width, height))
    x0 = max(0, int(min(r[0] for r in main) - pad))
    y0 = max(0, int(min(r[1] for r in main) - pad))
    x1 = min(width, int(max(r[2] for r in main) + pad + 1))
    y1 = min(height, int(max(r[3] for r in main) + pad + 1))
    if (x1 - x0) * (y1 - y0) >= params.max_area_ratio * width * height:
        return None
    return x0, y0, x1, y1


# ----------------------------------------------------------------------------- data helpers


def stratified_subset(dataset_split_dir: Path, split: str, size: int, seed: int = SEED) -> list[str]:
    """Seller-bucket-stratified sample from ``split_manifest.csv`` of the 80/10/10 split."""
    with (dataset_split_dir / "split_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["split"] == split]
    by_bucket: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_bucket[row["seller_bucket"]].append(row["img_id"])
    rng = random.Random(seed)
    chosen: list[str] = []
    total = len(rows)
    remainders = []
    for bucket in sorted(by_bucket):
        ids = sorted(by_bucket[bucket])
        rng.shuffle(ids)
        exact = size * len(ids) / total
        take = int(exact)
        chosen.extend(ids[:take])
        remainders.append((exact - take, bucket, ids[take:]))
    for _, _, rest in sorted(remainders, reverse=True)[: size - len(chosen)]:
        chosen.append(rest[0])
    return sorted(chosen)


def image_ids(args: argparse.Namespace) -> list[str]:
    documents = load_split(args.dataset, args.split)
    if args.subset:
        return stratified_subset(args.split_dataset, args.split, args.subset)
    return sorted(d.img_id for d in documents)


def _load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return {r["img_id"]: r for r in map(json.loads, handle) if r}


# ----------------------------------------------------------------------------- running the detector


def create_detector(config: DetConfig, paddlex_home: Path, cpu_threads: int = 6) -> Any:
    """Loads the PaddleOCR text detector of one configuration (CPU, local model files)."""
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddlex_home))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import TextDetection

    return TextDetection(
        model_name=config.model,
        model_dir=str(Path(paddlex_home) / "official_models" / config.model),
        device="cpu",
        cpu_threads=cpu_threads,
        enable_mkldnn=False,  # oneDNN fails on this Paddle build (T05/B4)
        limit_side_len=config.resize_long,
        limit_type="resize_long",
        box_thresh=config.box_thresh,
        unclip_ratio=config.unclip_ratio,
        thresh=config.thresh,
    )


def crop_rectangle(config: DetConfig, source: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int] | None:
    """Background-crop rectangle of a cropping configuration, from the boxes of its crop-source pass."""
    if not config.crop:
        return None
    params = CropParams(margin_page=0.03) if config.crop_from_self else CropParams()
    return text_crop_rect(source["boxes"], source["scores"], width, height, params)


def detect(detector: Any, image: np.ndarray, rect: Sequence[int] | None = None) -> dict[str, Any]:
    """Text boxes of an upright image, optionally only inside the background-crop rectangle ``rect``.

    Boxes are in full-image pixels rounded to 0.1 px (the precision stored for evaluation), with their
    detector scores, the crop rectangle and the detection time.
    """
    x0, y0 = (rect[0], rect[1]) if rect else (0, 0)
    view = image[rect[1] : rect[3], rect[0] : rect[2]] if rect else image
    start = time.perf_counter()
    result = list(detector.predict(view))[0]
    seconds = time.perf_counter() - start
    return {
        "boxes": [[[round(x + x0, 1), round(y + y0, 1)] for x, y in quad] for quad in np.asarray(result["dt_polys"]).tolist()],
        "scores": [round(float(s), 4) for s in result["dt_scores"]],
        "crop_rect": list(rect) if rect else None,
        "seconds": round(seconds, 3),
    }


def run(args: argparse.Namespace) -> None:
    from invoice_ai.preprocessing.orientation import read_bgr

    ids = image_ids(args)
    out_dir = args.out / args.split
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in args.configs:
        config = config_by_name(name)
        path = out_dir / f"{name}.jsonl"
        done = _load_jsonl(path)
        todo = [i for i in ids if i not in done]
        print(f"{args.split} {name}: {len(done)} cached, {len(todo)} to run", flush=True)
        if not todo:
            continue
        crop_source = _load_jsonl(out_dir / f"{config.crop_source}.jsonl") if config.crop else {}
        if config.crop and any(i not in crop_source for i in todo):
            raise SystemExit(f"run {config.crop_source} on the same images before {name}")
        detector = create_detector(config, args.paddlex_home, args.cpu_threads)
        with path.open("a", encoding="utf-8") as handle:
            for index, img_id in enumerate(todo, 1):
                image = read_bgr(args.dataset / f"{args.split}_images" / img_id)
                height, width = image.shape[:2]
                rect = crop_rectangle(config, crop_source[img_id], width, height) if config.crop else None
                record = {"img_id": img_id, **detect(detector, image, rect)}
                handle.write(json.dumps(record) + "\n")
                handle.flush()
                if index % 50 == 0:
                    print(f"  {name} {index}/{len(todo)}", flush=True)


# ----------------------------------------------------------------------------- evaluation


def score_document(document: LabeledDocument, record: dict[str, Any]) -> list[dict[str, Any]]:
    boxes = [tuple((float(x), float(y)) for x, y in quad) for quad in record["boxes"]]
    rect = record.get("crop_rect")
    rows = []
    regions = [(r, document.upright(r.polygon)) for r in document.regions]
    box_areas = [area(quad) for quad in boxes]

    def overlap(k: int, polygon: Sequence[tuple[float, float]], polygon_area: float) -> float:
        smaller = min(box_areas[k], polygon_area)
        return intersection_area(boxes[k], polygon) / smaller if smaller > 0 else 0.0

    region_areas = [area(polygon) for _, polygon in regions]
    for index, (region, polygon) in enumerate(regions):
        best, best_cover = None, 0.0
        for k in range(len(boxes)):
            cover = overlap(k, polygon, region_areas[index])
            if cover > best_cover:
                best, best_cover = k, cover
        detected = best_cover >= 0.5
        merged = False
        if detected:
            merged = any(
                other.label != region.label and overlap(best, other_polygon, region_areas[j]) >= 0.5
                for j, (other, other_polygon) in enumerate(regions)
                if j != index
            )
        inside = True
        if rect:
            x0, y0, x1, y1 = bbox(polygon)
            inside = x0 >= rect[0] - 1 and y0 >= rect[1] - 1 and x1 <= rect[2] + 1 and y1 <= rect[3] + 1
        rows.append({"label": region.label, "detected": detected, "merged": merged, "inside_crop": inside, "cover": best_cover})
    return rows


def _amount(text: str) -> int | None:
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def _quantity(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


def quantity_with_inference(documents: dict[str, LabeledDocument], records: dict[str, dict[str, Any]], ids: Sequence[str]) -> dict[str, Any]:
    """Share of line items whose quantity is detected, or recoverable as line_total / unit_price.

    Upper bound for the post-processing fallback: it assumes the KIE model labels the detected
    UNIT_PRICE/LINE_TOTAL correctly. An inference counts only if it reproduces the GT quantity.
    """
    counts = {"items_with_quantity": 0, "detected": 0, "inferred_correct": 0, "inferred_wrong": 0, "not_recoverable": 0}
    for img_id in ids:
        document = documents[img_id]
        items: defaultdict[int, dict[str, tuple[str, bool]]] = defaultdict(dict)
        for region, row in zip(document.regions, score_document(document, records[img_id])):
            if region.line_item_id is not None:
                items[region.line_item_id][region.label] = (region.text, row["detected"])
        for item in items.values():
            if "QUANTITY" not in item:
                continue
            counts["items_with_quantity"] += 1
            text, detected = item["QUANTITY"]
            if detected:
                counts["detected"] += 1
                continue
            price, total = item.get("UNIT_PRICE"), item.get("LINE_TOTAL")
            if price and total and price[1] and total[1] and _amount(price[0]) and _amount(total[0]) is not None:
                truth = _quantity(text)
                inferred = _amount(total[0]) / _amount(price[0])
                ok = truth is not None and abs(inferred - truth) < 1e-6
                counts["inferred_correct" if ok else "inferred_wrong"] += 1
            else:
                counts["not_recoverable"] += 1
    n = counts["items_with_quantity"]
    counts["detection_rate"] = round(counts["detected"] / n, 4) if n else None
    counts["with_inference_rate"] = round((counts["detected"] + counts["inferred_correct"]) / n, 4) if n else None
    return counts


def evaluate_config(documents: dict[str, LabeledDocument], records: dict[str, dict[str, Any]], ids: Sequence[str]) -> dict[str, Any] | None:
    if any(i not in records for i in ids):
        return None
    per_label: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for img_id in ids:
        for row in score_document(documents[img_id], records[img_id]):
            per_label[row["label"]].append(row)
    labels = {}
    for label in SEMANTIC_LABELS:
        rows = per_label[label]
        labels[label] = {
            "regions": len(rows),
            "recall": round(sum(r["detected"] for r in rows) / len(rows), 4) if rows else None,
            "merged_rate": round(sum(r["merged"] for r in rows) / len(rows), 4) if rows else None,
        }
    all_rows = [r for rows in per_label.values() for r in rows]
    recalls = [v["recall"] for v in labels.values() if v["recall"] is not None]
    cropped = [records[i] for i in ids if records[i].get("crop_rect")]
    return {
        "images": len(ids),
        "min_label_recall": min(recalls),
        "mean_label_recall": round(mean(recalls), 4),
        "overall_recall": round(sum(r["detected"] for r in all_rows) / len(all_rows), 4),
        "merged_rate": round(sum(r["merged"] for r in all_rows) / len(all_rows), 4),
        "images_cropped": len(cropped),
        "gt_inside_crop": round(sum(r["inside_crop"] for r in all_rows) / len(all_rows), 4),
        "mean_boxes": round(mean(len(records[i]["boxes"]) for i in ids), 1),
        "mean_seconds": round(mean(records[i]["seconds"] for i in ids), 3),
        "by_label": labels,
        "quantity_with_inference": quantity_with_inference(documents, records, ids),
    }


def evaluate(args: argparse.Namespace) -> None:
    documents = {d.img_id: d for d in load_split(args.dataset, args.split)}
    ids = image_ids(args)
    out_dir = args.out / args.split
    results = {}
    for path in sorted(out_dir.glob("*.jsonl")):
        config = config_by_name(path.stem)
        summary = evaluate_config(documents, _load_jsonl(path), ids)
        if summary is not None:
            results[path.stem] = {"config": asdict(config), **summary}
    ranking = sorted(results, key=lambda n: (-results[n]["min_label_recall"], -results[n]["mean_label_recall"], results[n]["mean_seconds"]))
    report = {
        "tuning_version": TUNING_VERSION,
        "split": args.split,
        "images": len(ids),
        "subset": args.subset,
        "selection": "max min-label recall, then mean label recall, then speed",
        "ranking": ranking,
        "configs": results,
    }
    args.report.mkdir(parents=True, exist_ok=True)
    tag = f"{args.split}_subset{args.subset}" if args.subset else args.split
    (args.report / f"detection_{tag}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    header = ["config", "images", "min_label_recall", "mean_label_recall", "merged_rate", "gt_inside_crop", "mean_seconds"] + [
        f"recall_{label}" for label in SEMANTIC_LABELS
    ]
    with (args.report / f"detection_{tag}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for name in ranking:
            r = results[name]
            writer.writerow(
                [name, r["images"], r["min_label_recall"], r["mean_label_recall"], r["merged_rate"], r["gt_inside_crop"], r["mean_seconds"]]
                + [r["by_label"][label]["recall"] for label in SEMANTIC_LABELS]
            )
    for name in ranking:
        r = results[name]
        print(
            f"{name:22s} min={r['min_label_recall']:.4f} mean={r['mean_label_recall']:.4f} merged={r['merged_rate']:.4f} "
            f"inside={r['gt_inside_crop']:.4f} sec={r['mean_seconds']:.2f} QTY={r['by_label']['QUANTITY']['recall']} "
            f"QTY+infer={r['quantity_with_inference']['with_inference_rate']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--dataset", type=Path, required=True, help="upright dataset (rotation 0)")
        p.add_argument("--split-dataset", type=Path, default=Path("../dataset_hoadon/dataset_split_80_10_10"))
        p.add_argument("--split", default="train")
        p.add_argument("--subset", type=int, default=0, help="seller-stratified subset size (0 = whole split)")
        p.add_argument("--out", type=Path, required=True)
        if name == "run":
            p.add_argument("--configs", nargs="+", required=True)
            p.add_argument("--paddlex-home", type=Path, required=True)
            p.add_argument("--cpu-threads", type=int, default=6)
        else:
            p.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args) if args.command == "run" else evaluate(args)


if __name__ == "__main__":
    main()
