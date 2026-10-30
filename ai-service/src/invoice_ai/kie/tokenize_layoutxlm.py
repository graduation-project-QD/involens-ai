"""B9: turn BIO records (``kie.build_bio``) into LayoutXLM model inputs.

For every document: words -> SentencePiece sub-tokens of ``microsoft/layoutxlm-base``; the first
sub-token of a word carries the word's label id, the other sub-tokens and every sub-token of an
``IGNORE`` word carry -100; all sub-tokens of a word share the word box (0-1000). The upright image is
stored once per document, already resized to 224 x 224 (what the LayoutXLM image processor feeds the
visual backbone), so the training VM does not need the full-size images.

Documents longer than ``max_length`` tokens (about 1%) are cut at word boundaries into overlapping
windows; ``word_ids`` keep the document word index of each token so window predictions can be merged.

    python -m invoice_ai.kie.tokenize_layoutxlm --bio ../experiments/data/processed/kie_bio_v3 \
        --dataset ../dataset_hoadon/dataset_upright_v1 --out ../experiments/data/processed/layoutxlm_v1
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from invoice_ai.kie.data import load_split
from invoice_ai.kie.labels import BIO_LABELS, IGNORE_INDEX, IGNORE_TAG, LABEL_TO_ID

TOKENIZE_VERSION = "layoutxlm_inputs_v1"
TOKENIZER_NAME = "microsoft/layoutxlm-base"
IMAGE_SIZE = 224


def plan_windows(token_counts: Sequence[int], max_tokens: int, overlap: int) -> list[tuple[int, int]]:
    """Word ranges [start, end) whose sub-token total fits ``max_tokens``; consecutive windows share
    about ``overlap`` tokens of context. A single word longer than ``max_tokens`` gets its own window."""
    n = len(token_counts)
    windows: list[tuple[int, int]] = []
    start = 0
    while start < n:
        end, total = start, 0
        while end < n and (end == start or total + token_counts[end] <= max_tokens):
            total += token_counts[end]
            end += 1
        windows.append((start, end))
        if end >= n:
            break
        back, shared = end, 0
        while back - 1 > start and shared + token_counts[back - 1] <= overlap:
            back -= 1
            shared += token_counts[back]
        start = back
    return windows


def word_label_ids(tags: Sequence[str]) -> list[int]:
    return [IGNORE_INDEX if tag == IGNORE_TAG else LABEL_TO_ID[tag] for tag in tags]


def encode_document(tokenizer: Any, record: dict[str, Any], max_length: int, overlap: int) -> list[dict[str, Any]]:
    words, boxes = record["words"], [list(b) for b in record["boxes"]]
    labels = word_label_ids(record["tags"])
    budget = max_length - 2  # <s> and </s>
    counts = [len(tokenizer.tokenize(w)) for w in words]
    out = []
    for index, (start, end) in enumerate(plan_windows(counts, budget, overlap)):
        enc = tokenizer(words[start:end], boxes=boxes[start:end], truncation=True, max_length=max_length)
        word_ids = [None if w is None else w + start for w in enc.word_ids()]
        # Label the first sub-token of each word ourselves: the fast tokenizer's word_labels also labels
        # the second sub-token when a word splits into a bare "▁" plus the rest ("PONTE" -> ▁ PON TE).
        token_labels, seen = [], set()
        for word in word_ids:
            token_labels.append(IGNORE_INDEX if word is None or word in seen else labels[word])
            if word is not None:
                seen.add(word)
        out.append(
            {
                "img_id": record["img_id"],
                "window": index,
                "word_range": [start, end],
                "input_ids": enc["input_ids"],
                "bbox": enc["bbox"],
                "labels": token_labels,
                "word_ids": word_ids,
            }
        )
    return out


def check_sample(sample: dict[str, Any], record: dict[str, Any]) -> list[str]:
    """Every word of the window appears, and its first sub-token carries exactly the word label."""
    problems = []
    lengths = {len(sample[k]) for k in ("input_ids", "bbox", "labels", "word_ids")}
    if len(lengths) != 1:
        problems.append("length mismatch")
    first: dict[int, int] = {}
    for position, word in enumerate(sample["word_ids"]):
        if word is None:
            if sample["labels"][position] != IGNORE_INDEX:
                problems.append("special token labelled")
            continue
        if sample["bbox"][position] != list(record["boxes"][word]):
            problems.append(f"box of word {word}")
        if word not in first:
            first[word] = sample["labels"][position]
        elif sample["labels"][position] != IGNORE_INDEX:
            problems.append(f"second sub-token of word {word} labelled")
    start, end = sample["word_range"]
    expected = word_label_ids(record["tags"][start:end])
    for offset, label in enumerate(expected):
        if first.get(start + offset, "missing") != label:
            problems.append(f"word {start + offset}: {first.get(start + offset, 'missing')} != {label}")
    return problems


def model_image(image: Any) -> Any:
    """The page as the LayoutXLM visual backbone sees it: RGB, resized to 224 x 224 (bilinear)."""
    from PIL import Image

    return image.convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE), Image.BILINEAR)


def save_image(source: Path, target: Path) -> None:
    from PIL import Image

    with Image.open(source) as image:
        model_image(image).save(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bio", type=Path, required=True, help="output of kie.build_bio")
    parser.add_argument("--dataset", type=Path, required=True, help="upright dataset (images)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--overlap", type=int, default=128, help="tokens shared by consecutive windows")
    parser.add_argument("--splits", nargs="+", default=["train", "val"])
    parser.add_argument("--sources", nargs="+", default=["ocr", "oracle"], help="BIO files {split}.{source}.jsonl")
    parser.add_argument("--suffix", default="", help="appended to output names, e.g. _pretrained -> val.ocr_pretrained.jsonl")
    args = parser.parse_args()

    from transformers import LayoutXLMTokenizerFast

    tokenizer = LayoutXLMTokenizerFast.from_pretrained(TOKENIZER_NAME)
    args.out.mkdir(parents=True, exist_ok=True)
    tokenizer.save_pretrained(str(args.out / "tokenizer"))  # offline copy for the training VM
    summary: dict[str, Any] = {
        "tokenize_version": TOKENIZE_VERSION,
        "tokenizer": TOKENIZER_NAME,
        "max_length": args.max_length,
        "overlap": args.overlap,
        "image_size": IMAGE_SIZE,
        "labels": list(BIO_LABELS),
        "splits": {},
    }
    summary_path = args.out / "summary.json"
    if summary_path.exists():
        summary["splits"] = json.loads(summary_path.read_text(encoding="utf-8")).get("splits", {})
    for split in args.splits:
        images = {d.img_id: d.image_path for d in load_split(args.dataset, split)}
        (args.out / "images" / split).mkdir(parents=True, exist_ok=True)
        for img_id, path in images.items():
            target = args.out / "images" / split / (Path(img_id).stem + ".png")
            if not target.exists():
                save_image(path, target)
        for source in args.sources:
            records = [json.loads(line) for line in (args.bio / f"{split}.{source}.jsonl").open(encoding="utf-8")]
            samples, problems, label_counts = [], 0, Counter()
            for record in records:
                for sample in encode_document(tokenizer, record, args.max_length, args.overlap):
                    issues = check_sample(sample, record)
                    if issues:
                        problems += 1
                        print(record["img_id"], sample["window"], issues[:3])
                    sample["image"] = f"images/{split}/{Path(record['img_id']).stem}.png"
                    label_counts.update(BIO_LABELS[l] for l in sample["labels"] if l != IGNORE_INDEX)
                    samples.append(sample)
            name = f"{split}.{source}{args.suffix}"
            with (args.out / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
                for sample in samples:
                    handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
            lengths = [len(s["input_ids"]) for s in samples]
            summary["splits"][name] = {
                "documents": len(records),
                "samples": len(samples),
                "documents_split_into_windows": sum(1 for r in {s["img_id"] for s in samples if s["window"] > 0}),
                "tokens_mean": round(mean(lengths), 1),
                "tokens_max": max(lengths),
                "samples_over_max_length": sum(l > args.max_length for l in lengths),
                "samples_with_problems": problems,
                "labelled_tokens": dict(sorted(label_counts.items())),
            }
            print(name, json.dumps({k: v for k, v in summary["splits"][name].items() if k != "labelled_tokens"}))
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
