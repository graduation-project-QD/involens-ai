"""B7: fine-tune and evaluate VietOCR on the GT line crops built by ``vietocr_data``.

Runs on the rented GPU VM (VietOCR environment, see ``runtime/b7/README.md``)::

    # throughput check (a few minutes): how many seconds per iteration on this GPU
    python -m invoice_ai.ocr.vietocr_finetune train --data ../data/vietocr_v1 --model vgg_transformer \
        --iters 200 --valid-every 100000 --out runs/bench_transformer
    # E1 recognizer: pretrained VietOCR without fine-tuning, CER per label on val crops
    python -m invoice_ai.ocr.vietocr_finetune evaluate --data ../data/vietocr_v1 --model vgg_transformer \
        --weights pretrained --out runs/pretrained_transformer
    # E2 recognizer: fine-tune, then evaluate the exported weights
    python -m invoice_ai.ocr.vietocr_finetune train --data ../data/vietocr_v1 --model vgg_transformer \
        --iters 20000 --out runs/ft_transformer
    python -m invoice_ai.ocr.vietocr_finetune evaluate --data ../data/vietocr_v1 --model vgg_transformer \
        --weights runs/ft_transformer/weights.pth --out runs/ft_transformer

Selection is done on val only; test crops are never exported. CER uses the same definition as the
PaddleOCR reference in B5 (NFC, collapsed whitespace, case and diacritics kept).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path
from typing import Any

from invoice_ai.ocr.recognition_eval import score

FINETUNE_VERSION = "vietocr_finetune_v1"
MODELS = ("vgg_transformer", "vgg_seq2seq")


def build_config(args: argparse.Namespace) -> Any:
    from vietocr.tool.config import Cfg

    config = Cfg.load_config_from_name(args.model)
    data = Path(args.data).resolve()
    out = Path(args.out).resolve()
    config["device"] = args.device
    config["dataset"].update(
        {
            "name": "lmdb",  # VietOCR caches annotations as ./train_lmdb, ./valid_lmdb (relative to the cwd)
            "data_root": str(data) + "/",
            "train_annotation": "train_annotation.txt",
            "valid_annotation": "val_annotation.txt",
            "image_height": 32,
            "image_min_width": 32,
            "image_max_width": args.max_width,
        }
    )
    config["trainer"].update(
        {
            "batch_size": args.batch_size,
            "iters": args.iters,
            "print_every": args.print_every,
            "valid_every": args.valid_every,
            "export": str(out / "weights.pth"),
            "checkpoint": str(out / "checkpoint.pth"),
            "log": str(out / "train.log"),
            "metrics": None,  # validate on the whole val set
        }
    )
    config["optimizer"]["max_lr"] = args.lr
    config["aug"]["image_aug"] = not args.no_aug
    config["dataloader"]["num_workers"] = args.workers
    if args.weights and args.weights != "pretrained":
        config["weights"] = str(Path(args.weights).resolve())
    return config


def train(args: argparse.Namespace) -> None:
    from vietocr.model.trainer import Trainer

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    config = build_config(args)
    config.save(str(out / "config.yml"))
    if args.dry_run:
        print(json.dumps({k: config[k] for k in ("dataset", "trainer", "optimizer", "aug", "dataloader", "device")}, indent=1))
        return
    os.chdir(out)  # keep VietOCR's relative LMDB caches inside the run folder
    trainer = Trainer(config, pretrained=True)  # starts from the published VietOCR weights (config["pretrain"])
    start = time.perf_counter()
    trainer.train()
    seconds = time.perf_counter() - start
    summary = {
        "finetune_version": FINETUNE_VERSION,
        "model": args.model,
        "iters": args.iters,
        "batch_size": args.batch_size,
        "max_lr": args.lr,
        "image_aug": not args.no_aug,
        "seconds_total": round(seconds, 1),
        "seconds_per_iter": round(seconds / max(1, args.iters), 4),
    }
    Path("train_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def evaluate(args: argparse.Namespace) -> None:
    from PIL import Image
    from vietocr.tool.predictor import Predictor

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    config = build_config(args)
    config["predictor"]["beamsearch"] = args.beamsearch
    predictor = Predictor(config)
    data = Path(args.data)
    with (data / "crops.csv").open(encoding="utf-8-sig", newline="") as handle:
        items = [row for row in csv.DictReader(handle) if row["split"] == args.split]
    if args.limit:
        items = items[: args.limit]
    predictions: list[str] = []
    start = time.perf_counter()
    for i in range(0, len(items), args.batch_size):
        images = [Image.open(data / row["path"]).convert("RGB") for row in items[i : i + args.batch_size]]
        predictions.extend(predictor.predict_batch(images))
    seconds = (time.perf_counter() - start) / max(1, len(items))
    metrics = score(items, predictions)
    report = {
        "finetune_version": FINETUNE_VERSION,
        "model": args.model,
        "weights": args.weights,
        "split": args.split,
        "crops": len(items),
        "beamsearch": args.beamsearch,
        "seconds_per_crop": round(seconds, 4),
        "by_label": metrics,
    }
    tag = f"{args.split}{'_beam' if args.beamsearch else ''}"
    (out / f"eval_{tag}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / f"predictions_{tag}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "label", "gt", "prediction"])
        writer.writerows([row["path"], row["label"], row["text"], p] for row, p in zip(items, predictions))
    print(json.dumps({"crops": len(items), "seconds_per_crop": report["seconds_per_crop"], "ALL": metrics.get("ALL")}, ensure_ascii=False))


def recognize(args: argparse.Namespace) -> None:
    """Read detector-box crops (``ocr.det_crops build``): text + probability per crop, no GT needed."""
    from PIL import Image
    from vietocr.tool.predictor import Predictor

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    config = build_config(args)
    config["predictor"]["beamsearch"] = args.beamsearch
    predictor = Predictor(config)
    crops = Path(args.crops)
    with (crops / "det_crops.csv").open(encoding="utf-8-sig", newline="") as handle:
        items = [row for row in csv.DictReader(handle) if args.split == "all" or row["split"] == args.split]
    if args.limit:
        items = items[: args.limit]
    texts: list[str] = []
    probs: list[float] = []
    start = time.perf_counter()
    for i in range(0, len(items), args.batch_size):
        images = [Image.open(crops / row["path"]).convert("RGB") for row in items[i : i + args.batch_size]]
        batch_texts, batch_probs = predictor.predict_batch(images, return_prob=True)
        texts.extend(batch_texts)
        probs.extend(float(p) for p in batch_probs)
        if (i // args.batch_size) % 200 == 0:
            print(f"  {i + len(images)}/{len(items)}", flush=True)
    seconds = (time.perf_counter() - start) / max(1, len(items))
    tag = f"det_{args.split}{'_beam' if args.beamsearch else ''}"
    with (out / f"predictions_{tag}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "prediction", "prob"])
        writer.writerows([row["path"], t, round(p, 5)] for row, t, p in zip(items, texts, probs))
    summary = {"finetune_version": FINETUNE_VERSION, "model": args.model, "weights": args.weights, "split": args.split, "crops": len(items), "seconds_per_crop": round(seconds, 4)}
    (out / f"recognize_{tag}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("train", "evaluate", "recognize"):
        p = sub.add_parser(name)
        p.add_argument("--data", type=Path, required=True, help="folder produced by invoice_ai.ocr.vietocr_data")
        p.add_argument("--model", choices=MODELS, default="vgg_transformer")
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--device", default="cuda:0")
        p.add_argument("--weights", default="pretrained", help="'pretrained' or a .pth file (fine-tuned weights)")
        p.add_argument("--batch-size", type=int, default=32)
        p.add_argument("--max-width", type=int, default=512)
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--lr", type=float, default=3e-4)
        p.add_argument("--no-aug", action="store_true")
        p.add_argument("--iters", type=int, default=20000)
        p.add_argument("--print-every", type=int, default=200)
        p.add_argument("--valid-every", type=int, default=2000)
        if name == "train":
            p.add_argument("--dry-run", action="store_true", help="write config.yml and stop")
        elif name == "recognize":
            p.add_argument("--crops", type=Path, required=True, help="folder produced by invoice_ai.ocr.det_crops build")
            p.add_argument("--split", default="val", choices=("train", "val", "all"))
            p.add_argument("--beamsearch", action="store_true")
            p.add_argument("--limit", type=int, default=0)
        else:
            p.add_argument("--split", default="val", choices=("train", "val"))
            p.add_argument("--beamsearch", action="store_true")
            p.add_argument("--limit", type=int, default=0, help="evaluate only the first N crops (smoke test)")
    args = parser.parse_args()
    {"train": train, "evaluate": evaluate, "recognize": recognize}[args.command](args)


if __name__ == "__main__":
    main()
