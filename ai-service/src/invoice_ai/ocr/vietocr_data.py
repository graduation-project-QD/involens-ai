"""B7: build the VietOCR fine-tuning set from GT regions of the upright train/val images.

Each GT box becomes one perspective-rectified line crop (``crops.rectified_crop``: the same cropping
used for detection boxes at inference). Output (``--out``)::

    train/<img_stem>_<region>.png, val/...        line crops (PNG, lossless)
    train_annotation.txt, val_annotation.txt      VietOCR format: "<relative path>\\t<label>"
    crops.csv                                     split, path, img_id, region index, label, text
    build_summary.json                            counts, character inventory, characters outside the vocab

Labels are Unicode NFC with collapsed whitespace. Test is never exported.

    python -m invoice_ai.ocr.vietocr_data --dataset ../dataset_hoadon/dataset_upright_v1 --out ../dataset_hoadon/vietocr_v1
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import cv2

from invoice_ai.kie.data import load_split
from invoice_ai.ocr.crops import CROP_VERSION, normalize_ocr_text, rectified_crop

DATA_VERSION = "vietocr_crops_v1"
SPLITS = ("train", "val")
# Default VietOCR vocabulary (vietocr/config/base.yml); characters outside it cannot be predicted.
VIETOCR_VOCAB = (
    "aAàÀảẢãÃáÁạẠăĂằẰẳẲẵẴắẮặẶâÂầẦẩẨẫẪấẤậẬbBcCdDđĐeEèÈẻẺẽẼéÉẹẸêÊềỀểỂễỄếẾệỆfFgGhHiIìÌỉỈĩĨíÍịỊjJkKlLmMnNoOòÒỏỎõÕóÓọỌôÔồỒổỔỗỖốỐộỘơƠờỜởỞỡỠớỚợỢpPqQrRsStTuUùÙủỦũŨúÚụỤưƯừỪửỬữỮứỨựỰvVwWxXyYỳỲỷỶỹỸýÝỵỴzZ0123456789!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "
)
# Look-alike characters mapped onto the vocabulary (printed receipts use them interchangeably).
CHAR_MAP = {"–": "-", "—": "-", "‐": "-", "×": "x", "“": '"', "”": '"', "‘": "'", "’": "'", " ": " "}


def clean_label(text: str) -> str:
    text = normalize_ocr_text(text)
    return "".join(CHAR_MAP.get(ch, ch) for ch in text)


def build(dataset: Path, out: Path, vocab: str = VIETOCR_VOCAB) -> dict:
    allowed = set(vocab)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    summary: dict = {"data_version": DATA_VERSION, "crop_version": CROP_VERSION, "source": str(dataset), "splits": {}}
    all_chars: Counter[str] = Counter()
    for split in SPLITS:
        from invoice_ai.preprocessing.orientation import read_bgr

        (out / split).mkdir(exist_ok=True)
        kept = skipped_empty = skipped_vocab = skipped_crop = 0
        oov: Counter[str] = Counter()
        lines = []
        for document in load_split(dataset, split):
            if document.rotation_cw % 360:
                raise ValueError("expects the upright dataset (rotation 0)")
            image = read_bgr(document.image_path)
            for region in document.regions:
                label = clean_label(region.text)
                if not label:
                    skipped_empty += 1
                    continue
                bad = {ch for ch in label if ch not in allowed}
                if bad:
                    oov.update(bad)
                    skipped_vocab += 1
                    continue
                crop = rectified_crop(image, region.polygon)
                if crop is None or min(crop.shape[:2]) < 4:
                    skipped_crop += 1
                    continue
                relative = f"{split}/{Path(document.img_id).stem}_{region.index:03d}.png"
                cv2.imencode(".png", crop)[1].tofile(str(out / relative))
                lines.append(f"{relative}\t{label}")
                rows.append({"split": split, "path": relative, "img_id": document.img_id, "region_index": region.index, "label": region.label, "text": label})
                all_chars.update(label)
                kept += 1
        (out / f"{split}_annotation.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary["splits"][split] = {
            "crops": kept,
            "skipped_empty_text": skipped_empty,
            "skipped_out_of_vocab": skipped_vocab,
            "skipped_bad_crop": skipped_crop,
            "out_of_vocab_chars": dict(oov.most_common()),
            "labels": dict(Counter(r["label"] for r in rows if r["split"] == split)),
        }
    with (out / "crops.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary["characters"] = len(all_chars)
    summary["char_map"] = CHAR_MAP
    (out / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = build(args.dataset, args.out)
    print(json.dumps({k: v for k, v in summary.items() if k != "char_map"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
