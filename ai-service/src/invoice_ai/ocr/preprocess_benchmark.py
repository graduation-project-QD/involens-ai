"""B6: does CLAHE or UVDoc help the chosen OCR configuration?

Three measurements, all chosen on a seller-stratified train subset and confirmed once on val:

* ``det``     – detection recall per label with the enhancement applied before detection
                (CLAHE only: it keeps the geometry, so GT boxes stay valid);
* ``crop``    – recognition CER on GT crops cut from the enhanced image (CLAHE only);
* ``e2e``     – geometry-free end-to-end check for any variant (needed for UVDoc, which warps the
                page): detection + recognition on the whole page, then for every GT region the best
                approximate substring match of its text inside the OCR lines.

Recognition uses ``PP-OCRv6_medium_rec`` as the reference recognizer (VietOCR replaces it in B7).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Sequence

import numpy as np

from invoice_ai.kie.data import load_split
from invoice_ai.kie.labels import SEMANTIC_LABELS
from invoice_ai.ocr.crops import edit_distance, normalize_ocr_text, rectified_crop
from invoice_ai.ocr.detection_tuning import (
    CropParams,
    _load_jsonl,
    evaluate_config,
    stratified_subset,
    text_crop_rect,
)

BENCHMARK_VERSION = "preprocess_benchmark_v1"
DET_MODEL = "PP-OCRv5_mobile_det"
REC_MODEL = "PP-OCRv6_medium_rec"
CHOSEN = {"limit_side_len": 1920, "box_thresh": 0.2, "thresh": 0.15, "unclip_ratio": 1.5}
DEFAULT = {"limit_side_len": 960, "box_thresh": 0.6, "thresh": 0.3, "unclip_ratio": 1.5}
VARIANTS = ("none", "clahe2", "clahe4", "uvdoc")


def substring_distance(reference: str, hypothesis: str) -> int:
    """Edit distance of ``reference`` against the best-matching substring of ``hypothesis``."""
    previous = [0] * (len(hypothesis) + 1)  # free start anywhere in the hypothesis
    for i, ref_char in enumerate(reference, 1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_char != hyp_char)))
        previous = current
    return min(previous)  # free end anywhere


def region_match(reference: str, lines: Sequence[str]) -> float:
    """Normalised distance of a GT region text to its best match inside any OCR line (0 = found exactly)."""
    reference = normalize_ocr_text(reference)
    if not reference:
        return 0.0
    best = min((substring_distance(reference, normalize_ocr_text(line)) for line in lines), default=len(reference))
    return min(1.0, best / len(reference))


class Pipeline:
    def __init__(self, paddlex_home: Path, cpu_threads: int, need_rec: bool, need_uvdoc: bool) -> None:
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddlex_home))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import TextDetection, TextRecognition

        models = Path(paddlex_home) / "official_models"

        def detector(settings: dict[str, Any]) -> Any:
            return TextDetection(
                model_name=DET_MODEL, model_dir=str(models / DET_MODEL), device="cpu", cpu_threads=cpu_threads,
                enable_mkldnn=False, limit_type="resize_long", **settings,
            )

        self.default_det = detector(DEFAULT)
        self.chosen_det = detector(CHOSEN)
        self.rec = (
            TextRecognition(model_name=REC_MODEL, model_dir=str(models / REC_MODEL), device="cpu", cpu_threads=cpu_threads, enable_mkldnn=False)
            if need_rec
            else None
        )
        if need_uvdoc:
            from invoice_ai.preprocessing.enhance import UVDocUnwarper

            self.uvdoc = UVDocUnwarper(paddlex_home, cpu_threads)

    def enhance(self, image: np.ndarray, variant: str) -> np.ndarray:
        from invoice_ai.preprocessing.enhance import clahe

        if variant == "none":
            return image
        if variant == "clahe2":
            return clahe(image, 2.0)
        if variant == "clahe4":
            return clahe(image, 4.0)
        if variant == "uvdoc":
            return self.uvdoc(image)
        raise ValueError(variant)

    def detect(self, image: np.ndarray, crop_source: dict[str, Any] | None = None) -> tuple[list, list, list | None]:
        """Chosen detection (B5): background crop from the default pass, then the tuned detector."""
        if crop_source is None:
            first = list(self.default_det.predict(image))[0]
            crop_source = {"boxes": np.asarray(first["dt_polys"]).tolist(), "scores": [float(s) for s in first["dt_scores"]]}
        h, w = image.shape[:2]
        rect = text_crop_rect(crop_source["boxes"], crop_source["scores"], w, h, CropParams())
        x0, y0 = (rect[0], rect[1]) if rect else (0, 0)
        view = image[rect[1] : rect[3], rect[0] : rect[2]] if rect else image
        result = list(self.chosen_det.predict(view))[0]
        boxes = [[[x + x0, y + y0] for x, y in quad] for quad in np.asarray(result["dt_polys"]).tolist()]
        return boxes, [float(s) for s in result["dt_scores"]], list(rect) if rect else None

    def recognize(self, crops: list[np.ndarray]) -> list[str]:
        return [str(r["rec_text"]) for r in self.rec.predict(crops, batch_size=1)] if crops else []


def _ids(args: argparse.Namespace) -> list[str]:
    if args.subset:
        return stratified_subset(args.split_dataset, args.split, args.subset)
    return sorted(d.img_id for d in load_split(args.dataset, args.split))


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(args: argparse.Namespace) -> None:
    from invoice_ai.preprocessing.orientation import read_bgr

    documents = {d.img_id: d for d in load_split(args.dataset, args.split)}
    ids = _ids(args)
    out = args.out / args.split
    out.mkdir(parents=True, exist_ok=True)
    pipe = Pipeline(args.paddlex_home, args.cpu_threads, need_rec=args.mode in ("crop", "e2e"), need_uvdoc="uvdoc" in args.variants)
    crop_sources = _load_jsonl(args.detection_cache / args.split / "L960.jsonl") if args.mode == "det" else {}
    for variant in args.variants:
        if args.mode in ("det", "crop") and variant == "uvdoc":
            raise SystemExit("UVDoc changes the geometry: use --mode e2e")
        path = out / f"{args.mode}_{variant}.jsonl"
        done = _load_jsonl(path)
        todo = [i for i in ids if i not in done]
        print(f"{args.split} {args.mode} {variant}: {len(done)} cached, {len(todo)} to run", flush=True)
        for index, img_id in enumerate(todo, 1):
            start = time.perf_counter()
            image = pipe.enhance(read_bgr(documents[img_id].image_path), variant)
            if args.mode == "det":
                boxes, scores, rect = pipe.detect(image, crop_sources.get(img_id))
                record = {"img_id": img_id, "boxes": boxes, "scores": scores, "crop_rect": rect}
            elif args.mode == "crop":
                regions = [r for r in documents[img_id].regions if r.text.strip()]
                crops = [rectified_crop(image, r.polygon) for r in regions]
                texts = pipe.recognize([c for c in crops if c is not None])
                it = iter(texts)
                record = {"img_id": img_id, "predictions": [next(it) if c is not None else "" for c in crops], "region_index": [r.index for r in regions]}
            else:
                boxes, _, _ = pipe.detect(image)
                crops = [c for c in (rectified_crop(image, q, pad_y=0.15) for q in boxes) if c is not None]
                record = {"img_id": img_id, "lines": pipe.recognize(crops)}
            record["seconds"] = round(time.perf_counter() - start, 3)
            _append(path, record)
            if index % 25 == 0:
                print(f"  {variant} {index}/{len(todo)}", flush=True)


def summarize(args: argparse.Namespace) -> None:
    documents = {d.img_id: d for d in load_split(args.dataset, args.split)}
    ids = _ids(args)
    out = args.out / args.split
    report: dict[str, Any] = {"benchmark_version": BENCHMARK_VERSION, "split": args.split, "images": len(ids), "subset": args.subset, "results": {}}
    for path in sorted(out.glob("*.jsonl")):
        mode, variant = path.stem.split("_", 1)
        records = _load_jsonl(path)
        if any(i not in records for i in ids):
            continue
        seconds = round(mean(records[i]["seconds"] for i in ids), 3)
        if mode == "det":
            metrics = evaluate_config(documents, records, ids)
            entry = {"mean_label_recall": metrics["mean_label_recall"], "by_label": {k: v["recall"] for k, v in metrics["by_label"].items()}}
        else:
            per_label: defaultdict[str, list[tuple[int, int, bool]]] = defaultdict(list)
            for img_id in ids:
                regions = {r.index: r for r in documents[img_id].regions}
                if mode == "crop":
                    pairs = [(regions[k], p) for k, p in zip(records[img_id]["region_index"], records[img_id]["predictions"])]
                    for region, prediction in pairs:
                        ref, hyp = normalize_ocr_text(region.text), normalize_ocr_text(prediction)
                        per_label[region.label].append((edit_distance(ref, hyp), len(ref), ref == hyp))
                else:
                    lines = records[img_id]["lines"]
                    for region in regions.values():
                        ref = normalize_ocr_text(region.text)
                        if ref:
                            d = region_match(ref, lines)
                            per_label[region.label].append((round(d * len(ref)), len(ref), d == 0.0))
            def agg(rows: list[tuple[int, int, bool]]) -> dict[str, Any]:
                return {"regions": len(rows), "cer": round(sum(r[0] for r in rows) / max(1, sum(r[1] for r in rows)), 4), "exact_rate": round(sum(r[2] for r in rows) / max(1, len(rows)), 4)}
            entry = {"all": agg([r for rows in per_label.values() for r in rows]), "by_label": {k: agg(per_label[k]) for k in SEMANTIC_LABELS if per_label[k]}}
        report["results"][f"{mode}/{variant}"] = {"mean_seconds": seconds, **entry}
    args.report.mkdir(parents=True, exist_ok=True)
    tag = f"{args.split}_subset{args.subset}" if args.subset else args.split
    (args.report / f"b6_{tag}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for key, value in report["results"].items():
        print(key, json.dumps({k: v for k, v in value.items() if k != "by_label"}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "summarize"):
        p = sub.add_parser(name)
        p.add_argument("--dataset", type=Path, required=True)
        p.add_argument("--split-dataset", type=Path, default=Path("../dataset_hoadon/dataset_split_80_10_10"))
        p.add_argument("--split", default="train")
        p.add_argument("--subset", type=int, default=0)
        p.add_argument("--out", type=Path, required=True)
        if name == "run":
            p.add_argument("--mode", choices=("det", "crop", "e2e"), required=True)
            p.add_argument("--variants", nargs="+", choices=VARIANTS, required=True)
            p.add_argument("--paddlex-home", type=Path, required=True)
            p.add_argument("--detection-cache", type=Path, default=Path("../experiments/data/processed/detection_tuning_v1"))
            p.add_argument("--cpu-threads", type=int, default=10)
        else:
            p.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args) if args.command == "run" else summarize(args)


if __name__ == "__main__":
    main()
