"""Re-split the merged labeler dataset into train/val/test (80/10/10), group- and seller-aware.

* Groups: photos of the same receipt (same TIMESTAMP digits and TOTAL_COST digits; when the timestamp
  has no time part the item names must match too) never cross splits. Image hashes are not used for
  grouping: same-template receipts on the same background produce near-identical hashes.
* Stratification: groups are assigned per seller bucket (frequent sellers individually, the rest pooled)
  to the split with the largest deficit, so every split sees the same seller mix.

Usage::

    python -m invoice_ai.datasets.resplit_merge --source ../dataset_hoadon/dataset_merge \
        --dest ../dataset_hoadon/dataset_split_80_10_10
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from invoice_ai.datasets.split import DisjointSet
from invoice_ai.kie.data import LabeledDocument, load_split

SPLIT_VERSION = "merge_resplit_80_10_10_v1"
SEED = 42
RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}
FREQUENT_SELLER_MIN_IMAGES = 20
SOURCE_SPLITS = ("train", "val")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.upper())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").replace("Đ", "D")
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text).split())


def _field(document: LabeledDocument, label: str) -> str:
    return " ".join(r.text for r in document.regions if r.label == label)


def receipt_key(document: LabeledDocument) -> tuple[str, ...] | None:
    timestamp, total = _digits(_field(document, "TIMESTAMP")), _digits(_field(document, "TOTAL_COST"))
    if not timestamp or not total:
        return None
    if len(timestamp) >= 10:  # date and time
        return timestamp, total
    items = tuple(sorted(_fold(r.text) for r in document.regions if r.label == "ITEM_NAME"))
    return (timestamp, total, *items) if items else None


def seller_key(document: LabeledDocument) -> str:
    seller = _fold(_field(document, "SELLER"))
    return seller or "<NO_SELLER>"


def assign_splits(documents: list[LabeledDocument], seed: int = SEED) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return img_id -> split, img_id -> group id, img_id -> seller bucket."""
    ids = [d.img_id for d in documents]
    sets = DisjointSet(ids)
    by_key: defaultdict[tuple[str, ...], list[str]] = defaultdict(list)
    for document in documents:
        key = receipt_key(document)
        if key is not None:
            by_key[key].append(document.img_id)
    for members in by_key.values():
        for other in members[1:]:
            sets.union(members[0], other)

    sellers = {d.img_id: seller_key(d) for d in documents}
    frequency = Counter(sellers.values())
    bucket = {i: (s if frequency[s] >= FREQUENT_SELLER_MIN_IMAGES else "<OTHER>") for i, s in sellers.items()}

    groups = sets.groups()
    group_of = {member: f"g{index:04d}" for index, group in enumerate(groups) for member in group}
    strata: defaultdict[str, list[list[str]]] = defaultdict(list)
    for group in groups:
        strata[Counter(bucket[m] for m in group).most_common(1)[0][0]].append(group)

    rng = random.Random(seed)
    split_of: dict[str, str] = {}
    for name in sorted(strata):
        stratum = strata[name]
        rng.shuffle(stratum)
        stratum.sort(key=len, reverse=True)  # stable: shuffled order among equal sizes
        counts = Counter({split: 0 for split in RATIOS})
        total = sum(len(g) for g in stratum)
        for group in stratum:
            target = max(RATIOS, key=lambda s: (RATIOS[s] * total - counts[s], RATIOS[s]))
            counts[target] += len(group)
            for member in group:
                split_of[member] = target
    return split_of, group_of, bucket


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source: Path, dest: Path, seed: int = SEED) -> dict[str, Any]:
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")
    documents = [d for split in SOURCE_SPLITS for d in load_split(source, split)]
    split_of, group_of, bucket = assign_splits(documents, seed)
    source_split = {d.img_id: d.split for d in documents}

    rows: dict[str, dict[str, str]] = {}
    rotations: dict[str, dict[str, str]] = {}
    missing: dict[str, Any] = {}
    completed: set[str] = set()
    fields: list[str] = []
    for split in SOURCE_SPLITS:
        fields, csv_rows = _read_csv(source / f"mcocr_{split}_df.csv")
        rows.update({r["img_id"]: r for r in csv_rows})
        rotations.update({r["img_id"]: r for r in _read_csv(source / f"mcocr_{split}_rotation.csv")[1]})
        missing.update(json.loads((source / f"mcocr_{split}_df.missing_fields.json").read_text(encoding="utf-8"))["images"])
        completed.update(json.loads((source / f"mcocr_{split}_df.completed.json").read_text(encoding="utf-8"))["completed_images"])

    dest.mkdir(parents=True, exist_ok=True)
    order = [d.img_id for d in documents]
    manifest = []
    now = datetime.now(timezone.utc).isoformat()
    for split in RATIOS:
        members = sorted(i for i in order if split_of[i] == split)
        image_dir = dest / f"{split}_images"
        image_dir.mkdir()
        for img_id in members:
            src = source / f"{source_split[img_id]}_images" / img_id
            shutil.copy2(src, image_dir / img_id)
            sha = _sha256(image_dir / img_id)
            if sha != _sha256(src):
                raise RuntimeError(f"copy mismatch: {img_id}")
            manifest.append(
                {
                    "img_id": img_id,
                    "split": split,
                    "source_split": source_split[img_id],
                    "group_id": group_of[img_id],
                    "seller_bucket": bucket[img_id],
                    "image_sha256": sha,
                }
            )
        _write_csv(dest / f"mcocr_{split}_df.csv", fields, [rows[i] for i in members])
        _write_csv(dest / f"mcocr_{split}_rotation.csv", ["img_id", "rotation_to_upright"], [rotations[i] for i in members])
        (dest / f"mcocr_{split}_df.missing_fields.json").write_text(
            json.dumps({"version": 1, "images": {i: missing[i] for i in members if i in missing}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (dest / f"mcocr_{split}_df.completed.json").write_text(
            json.dumps({"version": 1, "completed_images": [i for i in members if i in completed]}, indent=2), encoding="utf-8"
        )
        (dest / f"mcocr_{split}_df.flagged.json").write_text(
            json.dumps({"version": 1, "flagged_images": [], "updated_at": now}, indent=2), encoding="utf-8"
        )
    _write_csv(dest / "split_manifest.csv", list(manifest[0]), manifest)
    summary = summarize(dest, manifest, documents, seed)
    (dest / "split_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def summarize(dest: Path, manifest: list[dict[str, str]], documents: list[LabeledDocument], seed: int) -> dict[str, Any]:
    by_id = {d.img_id: d for d in documents}
    split_of = {m["img_id"]: m["split"] for m in manifest}
    groups: defaultdict[str, set[str]] = defaultdict(set)
    for m in manifest:
        groups[m["group_id"]].add(m["split"])
    train_sellers = {seller_key(by_id[i]) for i, s in split_of.items() if s == "train"}
    result: dict[str, Any] = {
        "split_version": SPLIT_VERSION,
        "seed": seed,
        "ratios": RATIOS,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "images": len(manifest),
        "groups": len(groups),
        "multi_image_groups": sum(size > 1 for size in Counter(m["group_id"] for m in manifest).values()),
        "groups_crossing_splits": sum(len(v) > 1 for v in groups.values()),
        "splits": {},
    }
    for split in RATIOS:
        members = [by_id[i] for i, s in split_of.items() if s == split]
        labels = Counter(r.label for d in members for r in d.regions)
        rotation = Counter(
            "0" if d.rotation_cw % 360 == 0 else "small_<=10" if min(d.rotation_cw % 360, 360 - d.rotation_cw % 360) <= 10 else "large"
            for d in members
        )
        items = sum(len({r.line_item_id for r in d.regions if r.line_item_id is not None}) for d in members)
        unseen = [d for d in members if seller_key(d) not in train_sellers]
        result["splits"][split] = {
            "images": len(members),
            "share": round(len(members) / len(manifest), 4),
            "from_source_train": sum(d.split == "train" for d in members),
            "from_source_val": sum(d.split == "val" for d in members),
            "labels": sum(labels.values()),
            "label_counts": dict(sorted(labels.items())),
            "line_items": items,
            "rotation": dict(sorted(rotation.items())),
            "images_with_seller_unseen_in_train": len(unseen) if split != "train" else None,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    summary = build(args.source, args.dest, args.seed)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
