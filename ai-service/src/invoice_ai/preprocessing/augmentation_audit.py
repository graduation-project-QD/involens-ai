"""Audit T08 train-only augmentation without activating it for T10."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw

from .augmentation import augment_page, load_augmentation_config
from .core import load_config, preprocess_path


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


def _max_error(left: list[list[float]], right: list[list[float]]) -> float:
    return max((abs(a - b) for p1, p2 in zip(left, right) for a, b in zip(p1, p2)), default=0.0)


def _bbox_corners(bbox_xyxy: list[float]) -> list[list[float]]:
    x0, y0, x1, y1 = bbox_xyxy
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _bbox_contains(bbox_xyxy: list[float], points: list[list[float]], tolerance: float = 1e-6) -> bool:
    x0, y0, x1, y1 = bbox_xyxy
    return all(
        x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance
        for x, y in points
    )


def _bbox_within_image(bbox_xyxy: list[float], size: tuple[int, int], tolerance: float = 1e-6) -> bool:
    x0, y0, x1, y1 = bbox_xyxy
    width, height = size
    return (
        x0 >= -tolerance
        and y0 >= -tolerance
        and x1 <= width + tolerance
        and y1 <= height + tolerance
        and x0 < x1
        and y0 < y1
    )


def _field_color(field: str | None) -> tuple[int, int, int]:
    return {
        "company": (30, 144, 255),
        "address": (50, 205, 50),
        "date": (255, 165, 0),
        "total": (255, 50, 50),
    }.get(field, (160, 160, 160))


def _overlay(image: Image.Image, document: dict[str, Any], transform: Any) -> Image.Image:
    output = image.copy()
    draw = ImageDraw.Draw(output)
    width = max(2, round(max(output.size) / 700))
    for region in document["regions"]:
        color = _field_color(region.get("field"))
        for polygon in region["polygons"]:
            mapped = transform.map_points(polygon)
            draw.line([tuple(point) for point in mapped] + [tuple(mapped[0])], fill=color, width=width)
    return output


def _fit(image: Image.Image, max_width: int = 750, max_height: int = 850) -> Image.Image:
    scale = min(max_width / image.width, max_height / image.height, 1.0)
    if scale == 1:
        return image
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)


def _save_qa(
    output_path: Path,
    document: dict[str, Any],
    page: Any,
    augmented: Any,
) -> dict[str, Any]:
    before = _fit(_overlay(page.image, document, page.transform))
    after = _fit(_overlay(augmented.image, document, augmented.transform))
    header = 32
    canvas = Image.new("RGB", (before.width + after.width, max(before.height, after.height) + header), (35, 35, 35))
    canvas.paste(before, (0, header))
    canvas.paste(after, (before.width, header))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 9), "T07 canonical", fill="white")
    draw.text((before.width + 8, 9), "T08 preview", fill="white")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=88, optimize=True)
    return {
        "path": output_path.as_posix(),
        "sha256": _sha256_file(output_path),
        "document_id": document["document_id"],
        "operations": augmented.operations,
    }


def run(workspace: Path) -> dict[str, Any]:
    preprocessing_config_path = workspace / "ai-service" / "configs" / "preprocessing" / "v1.json"
    augmentation_config_path = workspace / "experiments" / "configs" / "layoutxlm" / "augmentation_v1.json"
    preprocessing_config = load_config(preprocessing_config_path)
    augmentation_config = load_augmentation_config(augmentation_config_path)
    processed_root = workspace / "experiments" / "data" / "processed" / "t04_v1"
    split_root = workspace / "experiments" / "splits" / "t06_v1"
    specs = {
        "mcocr": {
            "canonical": processed_root / "mcocr.jsonl",
            "train": split_root / "mcocr" / "train.jsonl",
            "image_root": workspace / "dataset_hoadon",
        },
        "sroie": {
            "canonical": processed_root / "sroie.jsonl",
            "train": split_root / "sroie" / "train.jsonl",
            "image_root": workspace / "dataset_hoadon" / "SROIE2019",
        },
    }
    records: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    qa: list[dict[str, Any]] = []
    global_max_error = 0.0
    total_failures = 0
    total_invalid_boxes = 0
    deterministic_rechecks = 0

    for dataset_name, spec in specs.items():
        canonical = {item["document_id"]: item for item in _read_jsonl(spec["canonical"])}
        train = _read_jsonl(spec["train"])
        operation_counts: Counter[str] = Counter()
        combination_counts: Counter[str] = Counter()
        failures = 0
        invalid_boxes = 0
        max_error = 0.0
        dataset_qa = 0
        for index, split_item in enumerate(train):
            document_id = split_item["document_id"]
            document = canonical[document_id]
            try:
                if split_item["split"] != "train":
                    raise ValueError("Non-train document entered T08 audit")
                page = preprocess_path(spec["image_root"] / split_item["image_path"], preprocessing_config, enforce_request_limits=False)
                if page.source_sha256 != split_item["image_sha256"]:
                    raise ValueError("Source hash differs from frozen T06 train manifest")
                augmented = augment_page(
                    page,
                    augmentation_config,
                    document_id=document_id,
                    split="train",
                    allow_disabled_preview=True,
                )
                applied = [item["name"] for item in augmented.operations if item["applied"]]
                for name in applied:
                    operation_counts[name] += 1
                combination_counts["+".join(applied) if applied else "none"] += 1
                document_error = 0.0
                polygons = 0
                bboxes = 0
                for region in document["regions"]:
                    for polygon in region["polygons"]:
                        mapped = augmented.transform.map_points(polygon)
                        restored = augmented.transform.map_points(mapped, inverse=True)
                        document_error = max(document_error, _max_error(polygon, restored))
                        polygons += 1
                    # A rotated axis-aligned bbox becomes a larger axis-aligned
                    # envelope. That envelope is lossy, so round-trip its four
                    # source corners and validate the output envelope instead.
                    bbox = [float(value) for value in region["bbox_xyxy"]]
                    bbox_corners = _bbox_corners(bbox)
                    mapped_corners = augmented.transform.map_points(bbox_corners)
                    restored_corners = augmented.transform.map_points(mapped_corners, inverse=True)
                    document_error = max(document_error, _max_error(bbox_corners, restored_corners))
                    mapped_bbox = augmented.transform.map_bbox(bbox)
                    if not _bbox_within_image(mapped_bbox, augmented.image.size) or not _bbox_contains(
                        mapped_bbox, mapped_corners
                    ):
                        invalid_boxes += 1
                        total_invalid_boxes += 1
                        raise ValueError("Transformed bbox is invalid or does not contain its transformed corners")
                    bboxes += 1
                if index < 16:
                    repeated = augment_page(
                        page,
                        augmentation_config,
                        document_id=document_id,
                        split="train",
                        allow_disabled_preview=True,
                    )
                    if augmented.to_manifest() != repeated.to_manifest():
                        raise ValueError("Augmentation is not deterministic")
                    deterministic_rechecks += 1
                if "rotation" in applied and dataset_qa < 2:
                    safe_document_id = Path(document_id).stem
                    relative = Path("experiments") / "artifacts" / "t08" / "qa" / f"{dataset_name}_{safe_document_id}.jpg"
                    qa.append(_save_qa(workspace / relative, document, page, augmented) | {"path": relative.as_posix()})
                    dataset_qa += 1
                max_error = max(max_error, document_error)
                global_max_error = max(global_max_error, document_error)
                records.append({
                    "dataset": dataset_name,
                    "document_id": document_id,
                    "split": "train",
                    "status": "PASS",
                    "augmentation_status": augmented.status,
                    "derived_seed": augmented.derived_seed,
                    "source_sha256": page.source_sha256,
                    "t07_output_size": list(page.image.size),
                    "t08_output_size": list(augmented.image.size),
                    "operations": augmented.operations,
                    "cache_namespace": augmented.cache_namespace,
                    "pixel_sha256": augmented.pixel_sha256,
                    "polygons_checked": polygons,
                    "bboxes_checked": bboxes,
                    "max_round_trip_error_pixels": document_error,
                    "warnings": augmented.warnings,
                })
            except Exception as error:  # The audit records a bounded failure instead of hiding it.
                failures += 1
                total_failures += 1
                records.append({
                    "dataset": dataset_name,
                    "document_id": document_id,
                    "split": "train",
                    "status": "FAIL",
                    "error_type": type(error).__name__,
                    "error": str(error),
                })
        summaries[dataset_name] = {
            "documents": len(train),
            "pass": len(train) - failures,
            "fail": failures,
            "invalid_boxes": invalid_boxes,
            "operation_applied_counts": dict(sorted(operation_counts.items())),
            "operation_combination_counts": dict(sorted(combination_counts.items())),
            "max_round_trip_error_pixels": max_error,
        }

    records.sort(key=lambda item: (item["dataset"], item["document_id"]))
    manifest_path = workspace / "experiments" / "manifests" / "t08_augmentation_train_audit.jsonl"
    manifest = _write_jsonl(manifest_path, records)
    report = {
        "task": "T08",
        "status": "PASS_DISABLED_BY_DEFAULT" if total_failures == 0 and global_max_error <= 1e-6 else "FAIL",
        "augmentation_version": augmentation_config.augmentation_version,
        "activation": {
            "enabled_by_default": augmentation_config.enabled,
            "audit_mode": "PREVIEW_ONLY_DISABLED_CONFIG",
            "allowed_splits": list(augmentation_config.allowed_splits),
            "mode": augmentation_config.mode,
            "rerun_ocr": augmentation_config.rerun_ocr,
            "claim_ocr_robustness": augmentation_config.claim_ocr_robustness,
            "activation_gate": augmentation_config.activation_gate,
        },
        "datasets": summaries,
        "geometry": {
            "max_round_trip_error_pixels": global_max_error,
            "acceptance_tolerance_pixels": 1e-6,
            "round_trip_scope": "polygon vertices and source bbox corners",
            "axis_aligned_bbox_policy": "validate transformed-corner envelope; inverse AABB is intentionally not used",
            "rotation_expand_canvas": augmentation_config.rotation_expand_canvas,
            "invalid_boxes": total_invalid_boxes,
            "raw_sources_modified": False,
        },
        "determinism": {
            "rechecked_documents": deterministic_rechecks,
            "status": "PASS" if deterministic_rechecks == 32 else "FAIL",
            "seed_scope": "global seed + document id + source hash + version + config hash",
        },
        "t10_isolation": {
            "baseline_uses_t07_canonical_images": True,
            "augmentation_cache_namespace_separate": augmentation_config.baseline_cache_must_remain_separate,
            "validation_and_test_augmented": False,
            "ocr_ablation": "NOT_RUN_WAITING_FOR_T10",
        },
        "artifacts": {
            "train_audit_manifest": manifest_path.relative_to(workspace).as_posix(),
            **manifest,
            "qa_previews": qa,
        },
        "inputs": {
            "augmentation_config": augmentation_config_path.relative_to(workspace).as_posix(),
            "augmentation_config_sha256": _sha256_file(augmentation_config_path),
            "preprocessing_config_sha256": _sha256_file(preprocessing_config_path),
            "mcocr_train_sha256": _sha256_file(specs["mcocr"]["train"]),
            "sroie_train_sha256": _sha256_file(specs["sroie"]["train"]),
        },
    }
    output_path = workspace / "experiments" / "reports" / "t08_augmentation_audit.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace.resolve()), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
