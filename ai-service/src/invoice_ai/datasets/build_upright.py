"""B3: build an upright copy of train/val (images + annotations rotated by the confirmed GT angle).

The output is a self-contained labeler dataset with ``rotation_to_upright = 0`` for every image, so it
can be opened in apps/mcocr-labeler for a visual check and consumed directly by OCR / BIO / VietOCR crops.

* 0°: image bytes copied unchanged.
* 90/180/270°: lossless pixel transpose (no interpolation), saved as JPEG q95 4:4:4.
* other angles: bicubic warp on an expanded canvas with white fill, saved as JPEG q95 4:4:4.

Image warp and polygon rotation share ``geometry.upright_affine``. Test is excluded from the default
build: its orientation must come from the automatic orientation module (B4), never from GT. For the
final evaluation, test is built alone with the B4 angles (``--rotation-csv``); images and GT polygons
are then rotated by the predicted angle, i.e. the frame the pipeline sees.

Usage::

    python -m invoice_ai.datasets.build_upright --source ../dataset_hoadon/dataset_split_80_10_10 \
        --dest ../dataset_hoadon/dataset_upright_v1
    python -m invoice_ai.datasets.build_upright --source ../dataset_hoadon/dataset_split_80_10_10 \
        --dest ../dataset_hoadon/dataset_upright_test_auto --splits test \
        --rotation-csv ../experiments/reports/orientation_test_2026-10-29/test_predictions.csv
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from invoice_ai.kie.geometry import rotate_points, rotated_size, upright_affine

UPRIGHT_VERSION = "upright_v1"
SPLITS = ("train", "val")
JPEG_OPTIONS = {"quality": 95, "subsampling": 0}
FILL_RGB = (255, 255, 255)
RIGHT_ANGLE_OPS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixel_affine(width: int, height: int, angle_cw: float) -> np.ndarray:
    """``upright_affine`` expressed for OpenCV pixel indices (pixel centres at i + 0.5)."""
    (a, b, c), (d, e, f) = upright_affine(width, height, angle_cw)
    linear = np.array([[a, b], [d, e]], dtype=np.float64)
    shift = linear @ np.array([0.5, 0.5]) + np.array([c, f]) - 0.5
    return np.hstack([linear, shift.reshape(2, 1)])


def rotate_image(rgb: np.ndarray, angle_cw: int) -> tuple[np.ndarray, str]:
    height, width = rgb.shape[:2]
    angle = angle_cw % 360
    if angle in RIGHT_ANGLE_OPS:
        return cv2.rotate(rgb, RIGHT_ANGLE_OPS[angle]), "rot90"
    size = rotated_size(width, height, angle)
    warped = cv2.warpAffine(
        rgb,
        pixel_affine(width, height, angle),
        size,
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=FILL_RGB,
    )
    return warped, "warp_bicubic"


def rotate_polygons(polygons: list[dict[str, Any]], width: int, height: int, angle_cw: int) -> list[dict[str, Any]]:
    new_width, new_height = rotated_size(width, height, angle_cw)
    out = []
    for polygon in polygons:
        flat = polygon["segmentation"][0]
        points = rotate_points([(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)], width, height, angle_cw)
        points = [(min(max(x, 0.0), new_width), min(max(y, 0.0), new_height)) for x, y in points]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        x0, y0 = math.floor(min(xs)), math.floor(min(ys))
        out.append(
            {
                **polygon,
                "segmentation": [[round(v, 2) for p in points for v in p]],
                "bbox": [x0, y0, math.ceil(max(xs)) - x0, math.ceil(max(ys)) - y0],
                "width": new_width,
                "height": new_height,
            }
        )
    return out


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_rotations(source: Path, split: str, rotation_csv: Path | None) -> dict[str, float]:
    """Clockwise angle per image: GT ``rotation_to_upright`` of the split, or ``pred_total_cw`` of a B4
    prediction file (``evaluate_orientation`` output) when ``rotation_csv`` is given."""
    if rotation_csv is None:
        return {r["img_id"]: int(r["rotation_to_upright"]) for r in _read_csv(source / f"mcocr_{split}_rotation.csv")[1]}
    return {r["img_id"]: float(r["pred_total_cw"]) for r in _read_csv(rotation_csv)[1]}


def build(source: Path, dest: Path, splits: tuple[str, ...] = SPLITS, rotation_csv: Path | None = None) -> dict[str, Any]:
    """Writes upright copies of the splits (images, rotated polygons, sidecars, manifest with the affine)."""
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for split in splits:
        fields, rows = _read_csv(source / f"mcocr_{split}_df.csv")
        rotations = read_rotations(source, split, rotation_csv)
        image_dir = dest / f"{split}_images"
        image_dir.mkdir()
        out_rows = []
        for row in rows:
            img_id = row["img_id"]
            angle = rotations[img_id] % 360
            src = source / f"{split}_images" / img_id
            with Image.open(src) as image:
                orientation = image.getexif().get(274)
                if orientation not in (None, 1):
                    raise ValueError(f"{img_id}: EXIF orientation {orientation} is not supported by the labels")
                width, height = image.size
                rgb = np.asarray(image.convert("RGB"))
            out_path = image_dir / img_id
            if angle == 0:
                shutil.copy2(src, out_path)
                method, size = "copy", (width, height)
            else:
                rotated, method = rotate_image(rgb, angle)
                size = (rotated.shape[1], rotated.shape[0])
                if size != rotated_size(width, height, angle):
                    raise RuntimeError(f"{img_id}: canvas {size} != {rotated_size(width, height, angle)}")
                Image.fromarray(rotated).save(out_path, format="JPEG", **JPEG_OPTIONS)
            polygons = ast.literal_eval(row["anno_polygons"]) if row["anno_polygons"].strip() else []
            new_row = dict(row)
            if angle and polygons:
                new_row["anno_polygons"] = str(rotate_polygons(polygons, width, height, angle))
            out_rows.append(new_row)
            (a, b, c), (d, e, f) = upright_affine(width, height, angle)
            manifest.append(
                {
                    "img_id": img_id,
                    "split": split,
                    "rotation_cw": angle,
                    "method": method,
                    "source_width": width,
                    "source_height": height,
                    "upright_width": size[0],
                    "upright_height": size[1],
                    "affine_source_to_upright": json.dumps([[a, b, c], [d, e, f]]),
                    "source_sha256": _sha256(src),
                    "upright_sha256": _sha256(out_path),
                }
            )
        _write_csv(dest / f"mcocr_{split}_df.csv", fields, out_rows)
        _write_csv(dest / f"mcocr_{split}_rotation.csv", ["img_id", "rotation_to_upright"], [{"img_id": r["img_id"], "rotation_to_upright": 0} for r in rows])
        for suffix in ("missing_fields", "completed", "flagged"):
            shutil.copy2(source / f"mcocr_{split}_df.{suffix}.json", dest / f"mcocr_{split}_df.{suffix}.json")
    _write_csv(dest / "upright_manifest.csv", list(manifest[0]), manifest)
    summary = {
        "upright_version": UPRIGHT_VERSION,
        "source": str(source),
        "rotation_source": str(rotation_csv) if rotation_csv else "gt",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "splits": {
            split: {
                "images": sum(m["split"] == split for m in manifest),
                "methods": {k: sum(m["split"] == split and m["method"] == k for m in manifest) for k in ("copy", "rot90", "warp_bicubic")},
            }
            for split in splits
        },
        "jpeg": JPEG_OPTIONS,
        "fill_rgb": FILL_RGB,
    }
    (dest / "upright_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", default=list(SPLITS), choices=("train", "val", "test"))
    parser.add_argument("--rotation-csv", type=Path, help="B4 predictions (pred_total_cw) instead of GT angles")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.dest, tuple(args.splits), args.rotation_csv), indent=1))


if __name__ == "__main__":
    main()
