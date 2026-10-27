"""Build LayoutXLM BIO records from OCR output and the merged GT labels.

Usage (old T10 cache, OCR ran on the source orientation)::

    python -m invoice_ai.kie.build_bio --dataset ../dataset_hoadon/dataset_merge \
        --ocr-cache ../experiments/runs/ocr_v1/cache --ocr-frame source \
        --out ../experiments/reports/kie_bio_pilot

For the final data, run OCR on the upright images and pass ``--ocr-frame upright``.
Writes ``{split}.ocr.jsonl`` (tags on real OCR words), ``{split}.oracle.jsonl`` (GT text for labeled
regions, OCR words as background) and ``alignment_stats.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from invoice_ai.kie.bio import BIO_VERSION, AlignedDocument, OcrLineInput, align_document, match_key, oracle_document
from invoice_ai.kie.data import LabeledDocument, available_splits, load_split
from invoice_ai.kie.labels import IGNORE_TAG, SEMANTIC_LABELS


def load_ocr_cache(cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Index T10 cache records (``canonical`` OCR pages) by the SHA-256 of the source file."""
    index: dict[str, dict[str, Any]] = {}
    for path in cache_dir.rglob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        canonical = payload.get("canonical") or {}
        if canonical.get("status") == "OK" and canonical.get("source_sha256"):
            index[canonical["source_sha256"]] = canonical
    return index


def ocr_lines(canonical: dict[str, Any], document: LabeledDocument, frame: str) -> list[OcrLineInput]:
    expected = document.upright_size if frame == "upright" else (document.width, document.height)
    sx, sy = expected[0] / canonical["width"], expected[1] / canonical["height"]
    lines = []
    for line in sorted(canonical["lines"], key=lambda item: item["reading_order"]):
        polygon = tuple((x * sx, y * sy) for x, y in line["polygon_px"])
        lines.append(OcrLineInput(line["text"], polygon, line.get("recognition_score")))
    return lines


def bio_is_valid(tags: Iterable[str]) -> bool:
    previous = "O"
    for tag in tags:
        if tag.startswith("I-") and previous[2:] != tag[2:]:
            return False
        previous = tag if tag != IGNORE_TAG else previous
    return True


def summarize(aligned: list[AlignedDocument]) -> dict[str, Any]:
    per_label: dict[str, dict[str, list[float] | int]] = defaultdict(lambda: {"regions": 0, "matched": 0, "cer": [], "raw": 0, "key": 0})
    tags: Counter[str] = Counter()
    invalid = 0
    for document in aligned:
        tags.update(w.tag for w in document.words)
        invalid += not bio_is_valid(w.tag for w in document.words)
        for region in document.regions:
            stats = per_label[region.label]
            stats["regions"] += 1  # type: ignore[operator]
            if region.matched:
                stats["matched"] += 1  # type: ignore[operator]
                stats["cer"].append(region.cer)  # type: ignore[union-attr]
                stats["raw"] += " ".join(region.gt_text.split()) == " ".join(region.ocr_text.split())  # type: ignore[operator]
                stats["key"] += match_key(region.gt_text) == match_key(region.ocr_text)  # type: ignore[operator]
    labels = {}
    for label in SEMANTIC_LABELS:
        stats = per_label[label]
        cers = stats["cer"]
        labels[label] = {
            "regions": stats["regions"],
            "match_rate": round(stats["matched"] / stats["regions"], 4) if stats["regions"] else None,
            "mean_cer_matched": round(mean(cers), 4) if cers else None,
            "median_cer_matched": round(median(cers), 4) if cers else None,
            "exact_text_rate_matched": round(sum(c == 0 for c in cers) / len(cers), 4) if cers else None,  # case-insensitive
            "exact_raw_rate_matched": round(stats["raw"] / len(cers), 4) if cers else None,  # type: ignore[operator]
            "exact_normalized_rate_matched": round(stats["key"] / len(cers), 4) if cers else None,  # type: ignore[operator]
        }
    total_regions = sum(v["regions"] for v in labels.values())
    matched = sum(per_label[label]["matched"] for label in SEMANTIC_LABELS)
    words = sum(tags.values())
    return {
        "documents": len(aligned),
        "words": words,
        "regions": total_regions,
        "region_match_rate": round(matched / total_regions, 4) if total_regions else None,
        "ignore_word_rate": round(tags[IGNORE_TAG] / words, 4) if words else None,
        "o_word_rate": round(tags["O"] / words, 4) if words else None,
        "documents_with_invalid_bio": invalid,
        "tag_counts": dict(sorted(tags.items())),
        "by_label": labels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--ocr-cache", type=Path, required=True)
    parser.add_argument("--ocr-frame", choices=("source", "upright"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--assign-threshold", type=float, default=0.5)
    parser.add_argument("--ignore-threshold", type=float, default=0.2)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cache = load_ocr_cache(args.ocr_cache)
    report: dict[str, Any] = {
        "bio_version": BIO_VERSION,
        "ocr_frame": args.ocr_frame,
        "assign_threshold": args.assign_threshold,
        "ignore_threshold": args.ignore_threshold,
        "splits": {},
    }
    low_match = []
    for split in available_splits(args.dataset):
        documents = load_split(args.dataset, split)
        aligned, oracle = [], []
        near_upright: set[str] = set()
        for document in documents:
            canonical = cache.get(hashlib.sha256(document.image_path.read_bytes()).hexdigest())
            if canonical is None:
                continue
            lines = ocr_lines(canonical, document, args.ocr_frame)
            result = align_document(
                document,
                lines,
                ocr_frame=args.ocr_frame,
                assign_threshold=args.assign_threshold,
                ignore_threshold=args.ignore_threshold,
            )
            aligned.append(result)
            if min(document.rotation_cw % 360, 360 - document.rotation_cw % 360) <= 10:
                near_upright.add(document.img_id)
            oracle.append(oracle_document(document, result))
            rate = sum(r.matched for r in result.regions) / max(1, len(result.regions))
            if rate < 0.9:
                low_match.append({"split": split, "img_id": document.img_id, "rotation": document.rotation_cw, "region_match_rate": round(rate, 3)})
        for name, records in (("ocr", aligned), ("oracle", oracle)):
            with (args.out / f"{split}.{name}.jsonl").open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        report["splits"][split] = {
            "documents_total": len(documents),
            "documents_with_ocr": len(aligned),
            "ocr": summarize(aligned),
            # OCR that ran on a sideways source image is not representative of the upright pipeline.
            "ocr_near_upright": summarize([a for a in aligned if a.img_id in near_upright]),
            "oracle": summarize(oracle),
        }
    report["documents_region_match_below_0_9"] = low_match
    (args.out / "alignment_stats.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({s: {k: v for k, v in r["ocr"].items() if k != "by_label"} for s, r in report["splits"].items()}, indent=1))


if __name__ == "__main__":
    main()
