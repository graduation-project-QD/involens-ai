"""B10: fine-tune LayoutXLM (``microsoft/layoutxlm-base``) for 17-label BIO token classification.

Runs on the rented GPU VM (``runtime/b10``). Inputs come from ``kie.tokenize_layoutxlm``. The model is
trained on train and the epoch with the best entity-level micro F1 on val is kept (early stopping);
test is never touched here.

    # E2 (main): OCR = PaddleOCR detection + fine-tuned VietOCR
    python -m invoice_ai.kie.train_layoutxlm train --data ../data/layoutxlm_v1 --train train.ocr.jsonl \
        --val val.ocr.jsonl --out runs/e2
    # E3 (oracle): GT text inside the labelled regions
    python -m invoice_ai.kie.train_layoutxlm train --data ../data/layoutxlm_v1 --train train.oracle.jsonl \
        --val val.oracle.jsonl --out runs/e3
    # E1: the E2 model on OCR from the pretrained VietOCR
    python -m invoice_ai.kie.train_layoutxlm predict --model runs/e2/best --data ../data/layoutxlm_v1 \
        --split val.ocr_pretrained.jsonl --out runs/e2/predict_val_e1
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from invoice_ai.kie.kie_metrics import entity_scores, merge_windows
from invoice_ai.kie.labels import BIO_LABELS, IGNORE_INDEX, IGNORE_TAG, ID_TO_LABEL, LABEL_TO_ID

TRAIN_VERSION = "layoutxlm_train_v1"
MODEL_NAME = "microsoft/layoutxlm-base"
PAD_TOKEN_ID = 1  # XLM-RoBERTa <pad>


def load_samples(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def load_image(path: Path) -> Any:
    """224 x 224 image as a float BGR CHW tensor in 0-255 (the detectron2 backbone normalises it)."""
    import numpy as np
    import torch
    from PIL import Image

    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"), dtype=np.float32)[:, :, ::-1].copy()
    return torch.from_numpy(array).permute(2, 0, 1)


class SampleDataset:
    def __init__(self, data_dir: Path, samples: list[dict[str, Any]]) -> None:
        self.data_dir, self.samples = data_dir, samples
        self.images: dict[str, Any] = {}

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        sample = self.samples[index]
        if sample["image"] not in self.images:
            self.images[sample["image"]] = load_image(self.data_dir / sample["image"])
        return {"index": index, "image": self.images[sample["image"]], **{k: sample[k] for k in ("input_ids", "bbox", "labels")}}


def collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
    import torch

    length = max(len(item["input_ids"]) for item in batch)

    def pad(key: str, value: Any) -> Any:
        return torch.tensor([item[key] + [value] * (length - len(item[key])) for item in batch])

    return {
        "index": torch.tensor([item["index"] for item in batch]),
        "input_ids": pad("input_ids", PAD_TOKEN_ID),
        "bbox": pad("bbox", [0, 0, 0, 0]),
        "labels": pad("labels", IGNORE_INDEX),
        "attention_mask": torch.tensor([[1] * len(item["input_ids"]) + [0] * (length - len(item["input_ids"])) for item in batch]),
        "image": torch.stack([item["image"] for item in batch]),
    }


def word_tags(sample: dict[str, Any], token_values: list[Any]) -> dict[int, Any]:
    """Value at the first sub-token of every word of a window."""
    values: dict[int, Any] = {}
    for position, word in enumerate(sample["word_ids"]):
        if word is not None and word not in values:
            values[word] = token_values[position]
    return values


def documents(samples: list[dict[str, Any]], predictions: dict[int, list[tuple[str, float]]] | None) -> dict[str, dict[str, Any]]:
    """Per document: gold tags (from the first sub-token labels) and merged predicted tags + scores."""
    windows: dict[str, list[int]] = defaultdict(list)
    for index, sample in enumerate(samples):
        windows[sample["img_id"]].append(index)
    out = {}
    for img_id, indices in windows.items():
        gold = merge_windows(
            [{"word_range": samples[i]["word_range"], "values": word_tags(samples[i], [IGNORE_TAG if l == IGNORE_INDEX else ID_TO_LABEL[l] for l in samples[i]["labels"]])} for i in indices]
        )
        doc = {"gold": [gold[w] for w in sorted(gold)]}
        if predictions is not None:
            merged = merge_windows([{"word_range": samples[i]["word_range"], "values": word_tags(samples[i], predictions[i])} for i in indices])
            doc["pred"] = [merged[w][0] for w in sorted(merged)]
            doc["score"] = [round(merged[w][1], 4) for w in sorted(merged)]
        out[img_id] = doc
    return out


def run_predict(model: Any, dataset: SampleDataset, batch_size: int, device: str, amp: Any) -> dict[int, list[tuple[str, float]]]:
    import torch
    from torch.utils.data import DataLoader

    model.eval()
    out: dict[int, list[tuple[str, float]]] = {}
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=collate):
            index = batch.pop("index")
            batch.pop("labels")
            batch = {k: v.to(device) for k, v in batch.items()}
            with amp():
                logits = model(**batch).logits.float()
            probs = logits.softmax(-1)
            best, ids = probs.max(-1)
            for row, sample_index in enumerate(index.tolist()):
                n = len(dataset.samples[sample_index]["input_ids"])
                out[sample_index] = [(ID_TO_LABEL[i], p) for i, p in zip(ids[row, :n].tolist(), best[row, :n].tolist())]
    return out


def evaluate(model: Any, dataset: SampleDataset, batch_size: int, device: str, amp: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    docs = documents(dataset.samples, run_predict(model, dataset, batch_size, device, amp))
    return entity_scores((d["gold"], d["pred"]) for d in docs.values()), docs


def setup(args: argparse.Namespace) -> tuple[str, Any]:
    import contextlib

    import numpy as np
    import torch

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    use_bf16 = device == "cuda" and torch.cuda.is_bf16_supported() and not args.no_amp
    amp = (lambda: torch.autocast("cuda", dtype=torch.bfloat16)) if use_bf16 else contextlib.nullcontext
    return device, amp


def train(args: argparse.Namespace) -> None:
    import torch
    from torch.utils.data import DataLoader
    from transformers import LayoutLMv2ForTokenClassification, get_linear_schedule_with_warmup

    device, amp = setup(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    train_set = SampleDataset(args.data, load_samples(args.data / args.train))
    val_set = SampleDataset(args.data, load_samples(args.data / args.val))
    model = LayoutLMv2ForTokenClassification.from_pretrained(
        args.model, num_labels=len(BIO_LABELS), id2label=dict(ID_TO_LABEL), label2id=dict(LABEL_TO_ID)
    ).to(device)
    generator = torch.Generator().manual_seed(args.seed)
    loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True, collate_fn=collate, generator=generator)
    steps_per_epoch = len(loader)
    total_steps = args.max_steps or steps_per_epoch * args.epochs
    no_decay = ("bias", "LayerNorm.weight", "layer_norm.weight")
    groups = [
        {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)], "weight_decay": args.weight_decay},
        {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
    ]
    optimizer = torch.optim.AdamW(groups, lr=args.lr)
    scheduler = get_linear_schedule_with_warmup(optimizer, int(args.warmup_ratio * total_steps), total_steps)
    config = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items() if k != "func"}
    config.update({"train_version": TRAIN_VERSION, "device": device, "steps_per_epoch": steps_per_epoch, "total_steps": total_steps, "train_samples": len(train_set), "val_samples": len(val_set)})
    (out / "train_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    history, best_f1, best_epoch, step, start = [], -1.0, 0, 0, time.perf_counter()
    for epoch in range(1, math.ceil(total_steps / steps_per_epoch) + 1):
        model.train()
        losses = []
        for batch in loader:
            batch.pop("index")
            batch = {k: v.to(device) for k, v in batch.items()}
            with amp():
                loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            losses.append(loss.item())
            step += 1
            if step >= total_steps:
                break
        scores, _ = evaluate(model, val_set, args.eval_batch_size, device, amp)
        f1 = scores["micro"]["f1"]
        record = {"epoch": epoch, "step": step, "train_loss": round(sum(losses) / len(losses), 4), "val_f1": f1, "val_precision": scores["micro"]["precision"], "val_recall": scores["micro"]["recall"], "minutes": round((time.perf_counter() - start) / 60, 2)}
        history.append(record)
        print(json.dumps(record), flush=True)
        if f1 > best_f1:
            best_f1, best_epoch = f1, epoch
            model.save_pretrained(str(out / "best"))
            (out / "best_val_scores.json").write_text(json.dumps({"epoch": epoch, "scores": scores}, indent=2), encoding="utf-8")
        (out / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        if args.patience and epoch - best_epoch >= args.patience:
            print(f"early stop: no val F1 gain for {args.patience} epochs", flush=True)
            break
        if step >= total_steps:
            break
    summary = {"best_epoch": best_epoch, "best_val_f1": best_f1, "epochs_run": len(history), "minutes": round((time.perf_counter() - start) / 60, 2)}
    (out / "train_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


def predict(args: argparse.Namespace) -> None:
    from transformers import LayoutLMv2ForTokenClassification

    device, amp = setup(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dataset = SampleDataset(args.data, load_samples(args.data / args.split))
    model = LayoutLMv2ForTokenClassification.from_pretrained(str(args.model)).to(device)
    start = time.perf_counter()
    scores, docs = evaluate(model, dataset, args.eval_batch_size, device, amp)
    seconds = (time.perf_counter() - start) / max(1, len(docs))
    (out / "scores.json").write_text(json.dumps({"split": args.split, "model": str(args.model), "seconds_per_document": round(seconds, 4), "scores": scores}, indent=2), encoding="utf-8")
    with (out / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for img_id, doc in docs.items():
            handle.write(json.dumps({"img_id": img_id, **doc}, ensure_ascii=False) + "\n")
    print(json.dumps({"split": args.split, "micro": scores["micro"], "seconds_per_document": round(seconds, 4)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("train", "predict"):
        p = sub.add_parser(name)
        p.add_argument("--data", type=Path, required=True, help="output folder of kie.tokenize_layoutxlm")
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--eval-batch-size", type=int, default=16)
        p.add_argument("--no-amp", action="store_true", help="disable bf16 autocast")
        if name == "train":
            p.add_argument("--train", required=True)
            p.add_argument("--val", required=True)
            p.add_argument("--model", default=MODEL_NAME)
            p.add_argument("--epochs", type=int, default=30)
            p.add_argument("--max-steps", type=int, default=0, help="stop after N steps (smoke test)")
            p.add_argument("--batch-size", type=int, default=8)
            p.add_argument("--lr", type=float, default=5e-5)
            p.add_argument("--weight-decay", type=float, default=0.01)
            p.add_argument("--warmup-ratio", type=float, default=0.1)
            p.add_argument("--max-grad-norm", type=float, default=1.0)
            p.add_argument("--patience", type=int, default=8, help="early stopping on val F1 (0 = off)")
        else:
            p.add_argument("--model", type=Path, required=True)
            p.add_argument("--split", required=True, help="jsonl file inside --data")
    args = parser.parse_args()
    {"train": train, "predict": predict}[args.command](args)


if __name__ == "__main__":
    main()
