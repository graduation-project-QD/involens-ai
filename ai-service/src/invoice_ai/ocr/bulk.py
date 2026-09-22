"""Build resumable T10 OCR caches for frozen T06 train/validation splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from invoice_ai.preprocessing import load_config, preprocess_path

from .adapter import PaddleOcrEngine
from .cache import OcrCache
from .config import load_ocr_config
from .models import build_model_manifest, load_runtime_identity


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            stream.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
    return {"records": count, "sha256": digest.hexdigest()}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def run(
    workspace: Path,
    *,
    limit: int | None = None,
    shard_count: int = 1,
    shard_index: int = 0,
    cache_only: bool = False,
) -> dict[str, Any]:
    preprocess_config_path = workspace / "ai-service" / "configs" / "preprocessing" / "v1.json"
    ocr_config_path = workspace / "ai-service" / "configs" / "ocr" / "v1.json"
    preprocess_config = load_config(preprocess_config_path)
    ocr_config = load_ocr_config(ocr_config_path)
    model_cache = workspace / ".cache" / "paddlex"
    model_manifest_path = workspace / "experiments" / "manifests" / "t10_paddleocr_models.json"
    if not cache_only:
        build_model_manifest(ocr_config, model_cache, model_manifest_path)
    identity = load_runtime_identity(ocr_config, model_cache, model_manifest_path)
    engine = PaddleOcrEngine(ocr_config, model_cache)
    cache_root = workspace / "experiments" / "runs" / "ocr_v1" / "cache"
    cache = OcrCache(cache_root, ocr_config, identity)
    specs = {
        "mcocr": {
            "image_root": workspace / "dataset_hoadon",
            "split_root": workspace / "experiments" / "splits" / "t06_v1" / "mcocr",
        },
        "sroie": {
            "image_root": workspace / "dataset_hoadon" / "SROIE2019",
            "split_root": workspace / "experiments" / "splits" / "t06_v1" / "sroie",
        },
    }
    work: list[tuple[str, str, dict[str, Any], Path]] = []
    split_hashes: dict[str, str] = {}
    for dataset, spec in specs.items():
        for split in ("train", "validation"):
            split_path = spec["split_root"] / f"{split}.jsonl"
            split_hashes[f"{dataset}_{split}"] = _sha256(split_path)
            for item in _read_jsonl(split_path):
                work.append((dataset, split, item, spec["image_root"] / item["image_path"]))
    selected = work[shard_index::shard_count]
    selected = selected[:limit] if limit is not None else selected
    records: list[dict[str, Any]] = []
    started_all = time.perf_counter()
    for index, (dataset, split, item, image_path) in enumerate(selected, start=1):
        started = time.perf_counter()
        base = {
            "dataset": dataset,
            "split": split,
            "document_id": item["document_id"],
            "image_sha256": item["image_sha256"],
        }
        try:
            page = preprocess_path(image_path, preprocess_config, enforce_request_limits=False)
            if page.source_sha256 != item["image_sha256"]:
                raise ValueError("Source hash differs from frozen T06 split")
            result = cache.get_or_run(page, engine)
            records.append({
                **base,
                "status": "PASS",
                "ocr_status": result.page.status,
                "line_count": len(result.page.lines),
                "ocr_latency_ms": result.page.latency_ms,
                "document_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "cache_hit": result.cache_hit,
                "cache_key": result.cache_key,
                "cache_path": result.cache_path.relative_to(workspace).as_posix(),
                "pixel_sha256": result.page.pixel_sha256,
                "warnings": list(result.page.warnings),
            })
        except Exception as error:
            records.append({
                **base,
                "status": "FAIL",
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", None),
                "error": str(error),
                "details": getattr(error, "details", {}),
                "document_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            })
        if index == 1 or index % 10 == 0 or index == len(selected):
            print(json.dumps({
                "progress": index,
                "total": len(selected),
                "pass": sum(record["status"] == "PASS" for record in records),
                "fail": sum(record["status"] == "FAIL" for record in records),
                "cache_hits": sum(bool(record.get("cache_hit")) for record in records),
            }), flush=True)

    if cache_only:
        failures = sum(record["status"] == "FAIL" for record in records)
        return {
            "task": "T10",
            "status": "PASS" if failures == 0 else "FAIL",
            "cache_only": True,
            "shard_count": shard_count,
            "shard_index": shard_index,
            "documents_processed": len(records),
            "pass": len(records) - failures,
            "fail": failures,
            "cache_hits": sum(bool(record.get("cache_hit")) for record in records),
        }

    records.sort(key=lambda item: (item["dataset"], item["split"], item["document_id"]))
    manifest_path = workspace / "experiments" / "manifests" / "t10_ocr_cache.jsonl"
    manifest = _write_jsonl(manifest_path, records)
    summaries: dict[str, Any] = {}
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        buckets[(record["dataset"], record["split"])].append(record)
    for (dataset, split), items in sorted(buckets.items()):
        passed = [item for item in items if item["status"] == "PASS"]
        # OCRPage retains original inference latency across cache replay, so the
        # final audit can report inference cost after parallel cache generation.
        latencies = [float(item["ocr_latency_ms"]) for item in passed]
        summaries[f"{dataset}_{split}"] = {
            "documents": len(items),
            "pass": len(passed),
            "fail": len(items) - len(passed),
            "empty": sum(item.get("ocr_status") == "EMPTY" for item in passed),
            "total_lines": sum(int(item.get("line_count", 0)) for item in passed),
            "cache_hits": sum(bool(item.get("cache_hit")) for item in passed),
            "cache_misses": sum(not bool(item.get("cache_hit")) for item in passed),
            "inference_latency_ms": {
                "count": len(latencies),
                "median": statistics.median(latencies) if latencies else None,
                "p95": _percentile(latencies, 0.95),
                "max": max(latencies) if latencies else None,
            },
        }
    failures = sum(record["status"] == "FAIL" for record in records)
    report = {
        "task": "T10",
        "status": "PASS" if failures == 0 and len(selected) == len(work) else ("PASS_LIMITED" if failures == 0 else "FAIL"),
        "complete_bulk_scope": len(selected) == len(work),
        "documents_expected": len(work),
        "documents_processed": len(selected),
        "elapsed_seconds": round(time.perf_counter() - started_all, 3),
        "ocr_version": ocr_config.ocr_version,
        "runtime_identity": identity.to_dict(),
        "summaries": summaries,
        "totals": {
            "pass": len(records) - failures,
            "fail": failures,
            "empty": sum(record.get("ocr_status") == "EMPTY" for record in records),
            "lines": sum(int(record.get("line_count", 0)) for record in records),
            "cache_hits": sum(bool(record.get("cache_hit")) for record in records),
            "cache_misses": sum(record["status"] == "PASS" and not bool(record.get("cache_hit")) for record in records),
        },
        "artifacts": {
            "cache_root": cache_root.relative_to(workspace).as_posix(),
            "cache_manifest": manifest_path.relative_to(workspace).as_posix(),
            **manifest,
            "model_manifest": model_manifest_path.relative_to(workspace).as_posix(),
            "model_manifest_file_sha256": _sha256(model_manifest_path),
        },
        "inputs": {
            "ocr_config_sha256": ocr_config.config_sha256,
            "preprocessing_config_sha256": _sha256(preprocess_config_path),
            "split_sha256": split_hashes,
        },
        "accuracy": "NOT_RUN_T11",
    }
    report_path = workspace / "experiments" / "reports" / "t10_ocr_cache_audit.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.shard_count <= 0 or not 0 <= args.shard_index < args.shard_count:
        parser.error("shard index must be within [0, shard count)")
    report = run(
        args.workspace.resolve(),
        limit=args.limit,
        shard_count=args.shard_count,
        shard_index=args.shard_index,
        cache_only=args.cache_only,
    )
    raise SystemExit(0 if report["status"] in {"PASS", "PASS_LIMITED"} else 1)


if __name__ == "__main__":
    main()
