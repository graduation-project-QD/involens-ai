"""B7b/B8: detector-box line crops, their VietOCR evaluation against GT, and the OCR cache for BIO.

Three steps:

1. ``build`` (local CPU): cut every box of the chosen detector configuration (B5,
   ``C1920_b0.2_t0.15``) from the upright train/val images with the same ``rectified_crop`` used for
   GT crops. Writes ``<out>/<split>/<stem>_<k>.png`` and ``det_crops.csv``.
2. ``vietocr_finetune recognize`` (GPU VM): read the crops, write text + probability per crop.
3. ``evaluate`` (local): for every GT region, join the recognized text of the detector boxes that
   overlap it (>= half of the smaller area, as in B5) in reading order and compute the distance of the
   GT text to the best-matching substring, so neighbouring text merged into the same box is not
   penalised; regions without any box count as missed. ``export-cache`` writes the per-image OCR
   cache (T10 canonical layout) that ``kie.build_bio --ocr-frame upright`` consumes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2

from invoice_ai.kie.data import load_split
from invoice_ai.kie.geometry import area, bbox, intersection_area, order_rows
from invoice_ai.kie.labels import SEMANTIC_LABELS
from invoice_ai.ocr.crops import CROP_VERSION, normalize_ocr_text, rectified_crop
from invoice_ai.ocr.detection_tuning import _load_jsonl
from invoice_ai.ocr.preprocess_benchmark import substring_distance

DET_CROPS_VERSION = "det_crops_v1"
# A printed character is about half as wide as the line is tall; dense receipt fonts reach ~4 per line
# height, so allow 5 (3.5 dropped real "Số GD: ... Ngày: ..." lines).
MAX_CHARS_PER_HEIGHT = 5.0
DETECTION_CONFIG = "C1920_b0.2_t0.15"
SPLITS = ("train", "val")


def build(dataset: Path, detections: Path, out: Path) -> dict[str, Any]:
    from invoice_ai.preprocessing.orientation import read_bgr

    out.mkdir(parents=True, exist_ok=True)
    rows = []
    summary: dict[str, Any] = {"det_crops_version": DET_CROPS_VERSION, "crop_version": CROP_VERSION, "detection_config": DETECTION_CONFIG, "splits": {}}
    for split in SPLITS:
        (out / split).mkdir(exist_ok=True)
        records = _load_jsonl(detections / split / f"{DETECTION_CONFIG}.jsonl")
        kept = skipped = 0
        for document in load_split(dataset, split):
            image = read_bgr(document.image_path)
            for k, quad in enumerate(records[document.img_id]["boxes"]):
                crop = rectified_crop(image, [tuple(p) for p in quad])
                if crop is None or min(crop.shape[:2]) < 4:
                    skipped += 1
                    continue
                relative = f"{split}/{Path(document.img_id).stem}_{k:03d}.png"
                cv2.imencode(".png", crop)[1].tofile(str(out / relative))
                rows.append({"split": split, "img_id": document.img_id, "box_index": k, "path": relative, "polygon": json.dumps(quad)})
                kept += 1
        summary["splits"][split] = {"images": len(records), "crops": kept, "skipped_tiny": skipped}
    with (out / "det_crops.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "det_crops_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def plausible_text(text: str, polygon: list[tuple[float, float]]) -> bool:
    """False when the box cannot hold that many characters.

    VietOCR (seq2seq) returns a memorised training string for tiny boxes around specks or single
    digits, e.g. "Phúc Anh Minimart" for a 10 x 8 px box.
    """
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = polygon[:4]
    width = (((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 + ((x2 - x3) ** 2 + (y2 - y3) ** 2) ** 0.5) / 2
    height = (((x3 - x0) ** 2 + (y3 - y0) ** 2) ** 0.5 + ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5) / 2
    long_side, short_side = max(width, height), max(1.0, min(width, height))
    return len(text.replace(" ", "")) <= MAX_CHARS_PER_HEIGHT * long_side / short_side + 1


def load_predictions(crops_dir: Path, predictions: Path, split: str, *, filter_implausible: bool = True) -> dict[str, list[dict[str, Any]]]:
    """img_id -> boxes with polygon, recognized text and probability (only the given split).

    With ``filter_implausible`` the text of boxes that are too small for it is replaced by "".
    """
    meta = {r["path"]: r for r in _read_csv(crops_dir / "det_crops.csv") if r["split"] == split}
    per_image: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_csv(predictions):
        if row["path"] not in meta:
            continue
        m = meta[row["path"]]
        polygon = [tuple(p) for p in json.loads(m["polygon"])]
        text = row["prediction"]
        if filter_implausible and not plausible_text(text, polygon):
            text = ""
        per_image[m["img_id"]].append({"box_index": int(m["box_index"]), "polygon": polygon, "text": text, "prob": float(row["prob"]) if row.get("prob") else None})
    return per_image


def evaluate(dataset: Path, crops_dir: Path, predictions: Path, split: str) -> dict[str, Any]:
    per_image = load_predictions(crops_dir, predictions, split)
    totals: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"regions": 0, "missed": 0, "chars": 0, "edits": 0, "exact": 0})
    for document in load_split(dataset, split):
        boxes = per_image.get(document.img_id, [])
        areas = [area(b["polygon"]) for b in boxes]
        for region in document.regions:
            reference = normalize_ocr_text(region.text)
            if not reference:
                continue
            region_area = area(region.polygon)
            matched = []
            for b, box_area in zip(boxes, areas):
                smaller = min(region_area, box_area)
                if smaller > 0 and intersection_area(b["polygon"], region.polygon) / smaller >= 0.5:
                    matched.append(b)
            for key in (region.label, "ALL"):
                t = totals[key]
                t["regions"] += 1
                t["chars"] += len(reference)
                if not matched:
                    t["missed"] += 1
                    t["edits"] += len(reference)
                    continue
                order = [i for row in order_rows([bbox(b["polygon"]) for b in matched]) for i in row]
                hypothesis = normalize_ocr_text(" ".join(matched[i]["text"] for i in order))
                distance = substring_distance(reference, hypothesis)
                t["edits"] += distance
                t["exact"] += distance == 0
    result = {}
    for key in list(SEMANTIC_LABELS) + ["ALL"]:
        t = totals[key]
        if t["regions"]:
            result[key] = {
                "regions": t["regions"],
                "missed_rate": round(t["missed"] / t["regions"], 4),
                "cer": round(t["edits"] / t["chars"], 4),
                "exact_rate": round(t["exact"] / t["regions"], 4),
            }
    return result


def export_cache(dataset: Path, crops_dir: Path, predictions: Path, split: str, out: Path, ocr_version: str) -> int:
    """Per-image OCR cache in the T10 canonical layout (frame: upright images), keyed by image SHA-256."""
    per_image = load_predictions(crops_dir, predictions, split)
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for document in load_split(dataset, split):
        boxes = [b for b in per_image.get(document.img_id, []) if b["text"].strip()]
        order = [i for row in order_rows([bbox(b["polygon"]) for b in boxes]) for i in row] if boxes else []
        sha = hashlib.sha256(document.image_path.read_bytes()).hexdigest()
        lines = []
        for rank, i in enumerate(order):
            b = boxes[i]
            lines.append(
                {
                    "line_id": f"ocr_line_{rank:04d}",
                    "engine_index": b["box_index"],
                    "reading_order": rank,
                    "text": b["text"],
                    "polygon_px": [list(p) for p in b["polygon"]],
                    "bbox_xyxy_px": list(bbox(b["polygon"])),
                    "recognition_score": b["prob"],
                }
            )
        canonical = {"status": "OK", "ocr_version": ocr_version, "source_sha256": sha, "width": document.width, "height": document.height, "lines": lines}
        (out / f"{sha}.json").write_text(json.dumps({"canonical": canonical}, ensure_ascii=False), encoding="utf-8")
        written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--dataset", type=Path, required=True, help="upright dataset (dataset_upright_v1)")
    b.add_argument("--detections", type=Path, default=Path("../experiments/data/processed/detection_tuning_v1"))
    b.add_argument("--out", type=Path, required=True)
    for name in ("evaluate", "export-cache"):
        p = sub.add_parser(name)
        p.add_argument("--dataset", type=Path, required=True)
        p.add_argument("--crops", type=Path, required=True)
        p.add_argument("--predictions", type=Path, required=True, help="predictions CSV from vietocr_finetune recognize")
        p.add_argument("--split", default="val", choices=SPLITS)
        if name == "evaluate":
            p.add_argument("--report", type=Path)
        else:
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--ocr-version", default="paddle_det_c1920__vietocr_ft_v1")
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build(args.dataset, args.detections, args.out), indent=1))
    elif args.command == "evaluate":
        result = evaluate(args.dataset, args.crops, args.predictions, args.split)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({"split": args.split, "predictions": str(args.predictions), "by_label": result}, indent=2), encoding="utf-8")
        for key, value in result.items():
            print(key, value)
    else:
        print("images written:", export_cache(args.dataset, args.crops, args.predictions, args.split, args.out, args.ocr_version))


if __name__ == "__main__":
    main()
