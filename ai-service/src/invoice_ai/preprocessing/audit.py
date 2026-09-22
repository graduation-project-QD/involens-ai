"""Audit T07 preprocessing on frozen T06 validation documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .core import PREPROCESSING_VERSION, PreprocessingError, load_config, preprocess_path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _sha256_file(path: Path) -> str:
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


def _coordinate_error(left: list[list[float]], right: list[list[float]]) -> float:
    return max((abs(a - b) for p1, p2 in zip(left, right) for a, b in zip(p1, p2)), default=0.0)


def _candidate_stats(sizes: list[tuple[int, int]], max_long_edge: int | None) -> dict[str, Any]:
    ratios: list[float] = []
    scales: list[float] = []
    resized = 0
    for width, height in sizes:
        long_edge = max(width, height)
        scale = 1.0 if max_long_edge is None or long_edge <= max_long_edge else max_long_edge / long_edge
        if scale < 1:
            resized += 1
        scales.append(scale)
        ratios.append(scale * scale)
    return {
        "max_long_edge": max_long_edge,
        "documents": len(sizes),
        "resized_documents": resized,
        "min_linear_scale": min(scales, default=1.0),
        "mean_retained_pixel_ratio": statistics.fmean(ratios) if ratios else 1.0,
        "cer_wer": "NOT_RUN_T10_OCR_CACHE_NOT_AVAILABLE",
    }


def run(workspace: Path) -> dict[str, Any]:
    config_path = workspace / "ai-service" / "configs" / "preprocessing" / "v1.json"
    fixture_path = workspace / "ai-service" / "tests" / "fixtures" / "preprocessing_v1.json"
    core_path = workspace / "ai-service" / "src" / "invoice_ai" / "preprocessing" / "core.py"
    config = load_config(config_path)
    processed_root = workspace / "experiments" / "data" / "processed" / "t04_v1"
    split_root = workspace / "experiments" / "splits" / "t06_v1"
    dataset_specs = {
        "mcocr": {
            "canonical": processed_root / "mcocr.jsonl",
            "validation": split_root / "mcocr" / "validation.jsonl",
            "image_root": workspace / "dataset_hoadon",
        },
        "sroie": {
            "canonical": processed_root / "sroie.jsonl",
            "validation": split_root / "sroie" / "validation.jsonl",
            "image_root": workspace / "dataset_hoadon" / "SROIE2019",
        },
    }
    records: list[dict[str, Any]] = []
    dataset_summary: dict[str, Any] = {}
    all_sizes: list[tuple[int, int]] = []
    global_max_error = 0.0
    failures = 0

    for dataset_name, spec in dataset_specs.items():
        canonical = {item["document_id"]: item for item in _read_jsonl(spec["canonical"])}
        validation = _read_jsonl(spec["validation"])
        modes: Counter[str] = Counter()
        formats: Counter[str] = Counter()
        exif_orientations: Counter[str] = Counter()
        resized = 0
        request_limit_exceeded = 0
        dataset_failures = 0
        dataset_max_error = 0.0
        for split_item in validation:
            document_id = split_item["document_id"]
            document = canonical[document_id]
            image_path = spec["image_root"] / split_item["image_path"]
            try:
                page = preprocess_path(image_path, config, enforce_request_limits=False)
                if page.source_sha256 != split_item["image_sha256"]:
                    raise PreprocessingError("SOURCE_HASH_MISMATCH", "Source image differs from frozen T06 manifest")
                max_error = 0.0
                polygon_count = 0
                bbox_count = 0
                for region in document["regions"]:
                    for polygon in region["polygons"]:
                        mapped = page.transform.map_points(polygon)
                        restored = page.transform.map_points(mapped, inverse=True)
                        max_error = max(max_error, _coordinate_error(polygon, restored))
                        polygon_count += 1
                    mapped_bbox = page.transform.map_bbox(region["bbox_xyxy"])
                    restored_bbox = page.transform.map_bbox(mapped_bbox, inverse=True)
                    max_error = max(max_error, max(abs(a - b) for a, b in zip(region["bbox_xyxy"], restored_bbox)))
                    bbox_count += 1
                resize_step = page.transform.steps[-1]
                resized += int(bool(resize_step.parameters["applied"]))
                request_limit_exceeded += int("REQUEST_PIXEL_LIMIT_EXCEEDED_INTERNAL_DATASET_ONLY" in page.warnings)
                orientation = str(page.transform.steps[0].parameters["orientation"])
                modes[page.source_mode] += 1
                formats[page.source_format] += 1
                exif_orientations[orientation] += 1
                all_sizes.append(page.transform.steps[0].output_size)
                dataset_max_error = max(dataset_max_error, max_error)
                global_max_error = max(global_max_error, max_error)
                records.append({
                    "dataset": dataset_name,
                    "document_id": document_id,
                    "split": "validation",
                    "status": "PASS",
                    "source_sha256": page.source_sha256,
                    "source_size": list(page.transform.source_size),
                    "output_size": list(page.transform.output_size),
                    "source_mode": page.source_mode,
                    "output_mode": page.image.mode,
                    "source_format": page.source_format,
                    "exif_orientation": int(orientation),
                    "resize_applied": bool(resize_step.parameters["applied"]),
                    "scale_x": resize_step.parameters["scale_x"],
                    "scale_y": resize_step.parameters["scale_y"],
                    "polygons_checked": polygon_count,
                    "bboxes_checked": bbox_count,
                    "max_round_trip_error_pixels": max_error,
                    "transform_chain": page.transform.to_dict(),
                    "pixel_sha256": page.pixel_sha256,
                    "request_contract_eligible": not page.warnings,
                    "warnings": page.warnings,
                })
            except (PreprocessingError, OSError, ValueError) as error:
                dataset_failures += 1
                failures += 1
                records.append({
                    "dataset": dataset_name,
                    "document_id": document_id,
                    "split": "validation",
                    "status": "FAIL",
                    "error_code": getattr(error, "code", type(error).__name__),
                    "error": str(error),
                })
        dataset_summary[dataset_name] = {
            "documents": len(validation),
            "pass": len(validation) - dataset_failures,
            "fail": dataset_failures,
            "resized_documents": resized,
            "request_pixel_limit_exceeded_internal_only": request_limit_exceeded,
            "source_modes": dict(sorted(modes.items())),
            "source_formats": dict(sorted(formats.items())),
            "exif_orientations": dict(sorted(exif_orientations.items())),
            "max_round_trip_error_pixels": dataset_max_error,
        }

    records.sort(key=lambda item: (item["dataset"], item["document_id"]))
    manifest_path = workspace / "experiments" / "manifests" / "t07_preprocessing_validation.jsonl"
    artifact = _write_jsonl(manifest_path, records)
    report = {
        "task": "T07",
        "status": "PASS" if failures == 0 and global_max_error <= 1e-6 else "FAIL",
        "pipeline_version": PREPROCESSING_VERSION,
        "config": {
            "path": config_path.relative_to(workspace).as_posix(),
            "sha256": _sha256_file(config_path),
            "default_max_long_edge": config.max_long_edge,
            "output_mode": config.output_mode,
            "decoder_safety_max_pixels": config.max_decode_pixels,
            "request_max_pixels": config.request_max_pixels,
            "orientation_detection_enabled": config.orientation_detection_enabled,
            "deskew_enabled": config.deskew_enabled,
            "contrast_enabled": config.contrast_enabled,
        },
        "datasets": dataset_summary,
        "geometry": {
            "max_round_trip_error_pixels": global_max_error,
            "acceptance_tolerance_pixels": 1e-6,
            "crop_applied": False,
            "raw_sources_modified": False,
        },
        "validation_variants": {
            "max_edge_1600": _candidate_stats(all_sizes, 1600),
            "max_edge_2000_selected_initial": _candidate_stats(all_sizes, 2000),
            "no_resize": _candidate_stats(all_sizes, None),
            "selection_note": "2000 px remains the documented initial setting; OCR CER/WER ablation is deferred to T10, so no optional transform was enabled.",
        },
        "ocr_validation": {
            "status": "NOT_RUN",
            "reason": "T10 OCR cache and full-page OCR ground truth are not available yet",
            "optional_transforms_activated": False,
        },
        "artifacts": {
            "validation_manifest": manifest_path.relative_to(workspace).as_posix(),
            **artifact,
            "golden_fixture": fixture_path.relative_to(workspace).as_posix(),
            "golden_fixture_sha256": _sha256_file(fixture_path),
        },
        "inputs": {
            "core_sha256": _sha256_file(core_path),
            "mcocr_validation_sha256": _sha256_file(dataset_specs["mcocr"]["validation"]),
            "sroie_validation_sha256": _sha256_file(dataset_specs["sroie"]["validation"]),
        },
    }
    report_path = workspace / "experiments" / "reports" / "t07_preprocessing_audit.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace.resolve()), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
