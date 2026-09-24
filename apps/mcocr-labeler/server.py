from __future__ import annotations

import ast
import base64
import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from PIL import Image


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parents[1]
STATIC_DIR = APP_ROOT / "static"
DATA_DIR = APP_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "images"
BACKUP_DIR = DATA_DIR / "backups"
REVIEW_DIR = DATA_DIR / "review_sessions"
CURRENT_REVIEW = REVIEW_DIR / "current.json"
WORKSPACE_CONFIG = DATA_DIR / "annotation_workspaces.json"
DEFAULT_IMAGE_DIR = PROJECT_ROOT / "dataset_hoadon" / "val_images" / "val_images"

LEGACY_CSV_FIELDS = [
    "img_id",
    "anno_polygons",
    "anno_texts",
    "anno_labels",
    "anno_num",
    "anno_image_quality",
]
CSV_FIELDS = [*LEGACY_CSV_FIELDS, "anno_line_item_ids"]
LABEL_TO_CATEGORY = {
    "SELLER": 15,
    "ADDRESS": 16,
    "TIMESTAMP": 17,
    "TOTAL_COST": 18,
    "ITEM_NAME": 19,
    "QUANTITY": 20,
    "UNIT_PRICE": 21,
    "LINE_TOTAL": 22,
}
CATEGORY_TO_LABEL = {value: key for key, value in LABEL_TO_CATEGORY.items()}
LINE_ITEM_LABELS = {"ITEM_NAME", "QUANTITY", "UNIT_PRICE", "LINE_TOTAL"}
DOCUMENT_LABELS = {"SELLER", "ADDRESS", "TIMESTAMP", "TOTAL_COST"}
LABEL_ALIASES = {"TOTAL_TOTAL_COST": "TOTAL_COST"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
MAX_REQUEST_BYTES = 16 * 1024 * 1024
WRITE_LOCK = threading.RLock()


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def ensure_storage() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, BACKUP_DIR, REVIEW_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def safe_filename(value: str) -> str:
    name = Path(value).name
    if not name or name in {".", ".."}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Tên file không hợp lệ")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if Path(cleaned).suffix.lower() not in IMAGE_SUFFIXES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Chỉ hỗ trợ JPG, JPEG và PNG")
    return cleaned


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dimensions(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except Exception as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"Không đọc được ảnh: {exc}") from exc


def atomic_write(path: Path, data: bytes, make_backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with WRITE_LOCK:
        if make_backup and path.exists() and path.stat().st_size:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = BACKUP_DIR / f"{path.stem}.{stamp}{path.suffix}.bak"
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)


def parse_csv_text(text: str) -> list[dict[str, str]]:
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames not in (LEGACY_CSV_FIELDS, CSV_FIELDS):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "CSV phải có 6 cột MC-OCR gốc hoặc 7 cột mở rộng: " + ", ".join(CSV_FIELDS),
        )
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(reader, start=2):
        row = {field: (raw.get(field) or "") for field in CSV_FIELDS}
        img_id = row["img_id"].strip()
        if not img_id:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Dòng {line_number}: img_id trống")
        if img_id in seen:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Dòng {line_number}: img_id bị trùng: {img_id}")
        try:
            regions = row_to_regions(row)
        except (ValueError, SyntaxError, TypeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Dòng {line_number}: {exc}") from exc
        row["anno_labels"] = "|||".join(region["label"] for region in regions)
        seen.add(img_id)
        rows.append(row)
    return rows


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return parse_csv_text(path.read_text(encoding="utf-8-sig"))


def encode_rows(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)
    return output.getvalue().encode("utf-8-sig")


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    atomic_write(path, encode_rows(rows), make_backup=True)


def split_compound(value: str) -> list[str]:
    if value == "":
        return []
    return value.split("|||")


def segmentation_components(value: object, index: int) -> list[list[float]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"polygon #{index + 1}: segmentation không hợp lệ")
    raw_components = value if isinstance(value[0], list) else [value]
    components: list[list[float]] = []
    for component in raw_components:
        if not isinstance(component, list) or len(component) < 6 or len(component) % 2:
            continue
        try:
            components.append([float(number) for number in component])
        except (TypeError, ValueError):
            continue
    if not components:
        raise ValueError(f"polygon #{index + 1}: segmentation không hợp lệ")
    return components


def representative_component(value: object, index: int) -> list[float]:
    components = segmentation_components(value, index)
    return max(components, key=polygon_area)


def parse_line_item_ids(value: str, count: int) -> list[int | None]:
    if not value.strip():
        return [None] * count
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("anno_line_item_ids không phải JSON hợp lệ") from exc
    if not isinstance(parsed, list) or len(parsed) != count:
        raise ValueError("số line_item_id không khớp số vùng nhãn")
    result: list[int | None] = []
    for index, item_id in enumerate(parsed):
        if item_id is None:
            result.append(None)
            continue
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
            raise ValueError(f"line_item_id #{index + 1} phải là số nguyên dương hoặc null")
        result.append(item_id)
    return result


def row_to_regions(row: dict[str, str]) -> list[dict]:
    polygon_text = row.get("anno_polygons", "").strip()
    polygons = ast.literal_eval(polygon_text) if polygon_text else []
    if not isinstance(polygons, list):
        raise ValueError("anno_polygons không phải list")
    texts = split_compound(row.get("anno_texts", ""))
    labels = [LABEL_ALIASES.get(label, label) for label in split_compound(row.get("anno_labels", ""))]
    if not (len(polygons) == len(texts) == len(labels)):
        raise ValueError("số polygon, text và label không khớp")
    line_item_ids = parse_line_item_ids(row.get("anno_line_item_ids", ""), len(polygons))

    regions = []
    for index, (polygon, text, label, line_item_id) in enumerate(zip(polygons, texts, labels, line_item_ids)):
        if not isinstance(polygon, dict):
            raise ValueError(f"polygon #{index + 1} không hợp lệ")
        category_id = int(polygon.get("category_id", LABEL_TO_CATEGORY.get(label, -1)))
        expected = LABEL_TO_CATEGORY.get(label)
        if expected is None or expected != category_id:
            raise ValueError(f"polygon #{index + 1}: category_id và label không khớp")
        if label in LINE_ITEM_LABELS and line_item_id is None:
            raise ValueError(f"polygon #{index + 1}: nhãn {label} thiếu line_item_id")
        if label not in LINE_ITEM_LABELS and line_item_id is not None:
            raise ValueError(f"polygon #{index + 1}: nhãn {label} phải có line_item_id là null")
        points = representative_component(polygon.get("segmentation", []), index)
        bbox = [float(value) for value in polygon.get("bbox", [])]
        if len(bbox) != 4:
            raise ValueError(f"polygon #{index + 1}: bbox không hợp lệ")
        regions.append(
            {
                "id": f"region-{index + 1}",
                "category_id": category_id,
                "label": label,
                "text": text,
                "line_item_id": line_item_id,
                "segmentation": points,
                "bbox": bbox,
                "source_polygon": polygon,
            }
        )
    return regions


def normalized_number(value: float) -> int | float:
    rounded = round(float(value), 2)
    return int(rounded) if rounded.is_integer() else rounded


def polygon_area(points: list[float]) -> float:
    pairs = list(zip(points[0::2], points[1::2]))
    total = 0.0
    for index, (x1, y1) in enumerate(pairs):
        x2, y2 = pairs[(index + 1) % len(pairs)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def same_points(left: list[float], right: list[float], tolerance: float = 0.01) -> bool:
    return len(left) == len(right) and all(abs(a - b) <= tolerance for a, b in zip(left, right))


def regions_to_row(
    img_id: str,
    regions: list[dict],
    width: int,
    height: int,
    image_quality: str = "",
) -> dict[str, str]:
    polygons = []
    texts = []
    labels = []
    line_item_ids: list[int | None] = []
    for index, region in enumerate(regions):
        label = str(region.get("label", "")).strip().upper()
        if label not in LABEL_TO_CATEGORY:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Vùng #{index + 1}: category không hợp lệ")
        text = str(region.get("text", "")).strip()
        if not text:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Vùng #{index + 1}: nội dung chữ đang trống")
        raw_line_item_id = region.get("line_item_id")
        if label in LINE_ITEM_LABELS:
            if isinstance(raw_line_item_id, bool):
                raise ApiError(HTTPStatus.BAD_REQUEST, f"Vùng #{index + 1}: line_item_id phải là số nguyên dương")
            try:
                line_item_id = int(raw_line_item_id)
            except (TypeError, ValueError) as exc:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    f"Vùng #{index + 1}: nhãn {label} cần line_item_id",
                ) from exc
            if line_item_id < 1 or str(raw_line_item_id).strip() != str(line_item_id):
                raise ApiError(HTTPStatus.BAD_REQUEST, f"Vùng #{index + 1}: line_item_id phải là số nguyên dương")
        else:
            line_item_id = None
        raw_points = region.get("segmentation")
        if not isinstance(raw_points, list) or len(raw_points) < 8 or len(raw_points) % 2:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Vùng #{index + 1}: segmentation không hợp lệ")
        points = [float(value) for value in raw_points]
        xs = points[0::2]
        ys = points[1::2]
        if min(xs) < 0 or min(ys) < 0 or max(xs) > width or max(ys) > height:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Vùng #{index + 1}: tọa độ vượt ngoài ảnh")
        x_min, y_min = min(xs), min(ys)
        x_max, y_max = max(xs), max(ys)
        if x_max <= x_min or y_max <= y_min:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Vùng #{index + 1}: vùng chọn rỗng")
        bbox = [
            normalized_number(x_min),
            normalized_number(y_min),
            normalized_number(x_max - x_min),
            normalized_number(y_max - y_min),
        ]
        source_polygon = region.get("source_polygon")
        preserve_source = False
        if isinstance(source_polygon, dict):
            try:
                source_points = representative_component(source_polygon.get("segmentation", []), index)
                preserve_source = (
                    int(source_polygon.get("category_id", -1)) == LABEL_TO_CATEGORY[label]
                    and int(source_polygon.get("width", width)) == width
                    and int(source_polygon.get("height", height)) == height
                    and same_points(source_points, points)
                )
            except (TypeError, ValueError):
                preserve_source = False
        if preserve_source:
            polygons.append(source_polygon)
        else:
            polygons.append(
                {
                    "category_id": LABEL_TO_CATEGORY[label],
                    "segmentation": [[normalized_number(value) for value in points]],
                    "area": normalized_number(polygon_area(points)),
                    "bbox": bbox,
                    "width": width,
                    "height": height,
                }
            )
        texts.append(text)
        labels.append(label)
        line_item_ids.append(line_item_id)
    return {
        "img_id": img_id,
        "anno_polygons": repr(polygons),
        "anno_texts": "|||".join(texts),
        "anno_labels": "|||".join(labels),
        "anno_num": str(len(regions)),
        "anno_image_quality": image_quality,
        "anno_line_item_ids": json.dumps(line_item_ids, ensure_ascii=False, separators=(",", ":")),
    }


def upsert_row(path: Path, row: dict[str, str]) -> None:
    rows = read_rows(path)
    for index, current in enumerate(rows):
        if current["img_id"] == row["img_id"]:
            rows[index] = row
            write_rows(path, rows)
            return
    rows.append(row)
    write_rows(path, rows)


def regions_for_save(mode: str, existing: dict[str, str] | None, submitted: list[dict]) -> list[dict]:
    if mode != "train" or not existing:
        return submitted
    original_regions = row_to_regions(existing)
    document_regions = [region for region in original_regions if region["label"] not in LINE_ITEM_LABELS]
    original_document_labels = {region["label"] for region in document_regions}
    new_document_regions = [
        region for region in submitted
        if str(region.get("label", "")).strip().upper() in LABEL_TO_CATEGORY
        and str(region.get("label", "")).strip().upper() not in LINE_ITEM_LABELS
        and str(region.get("label", "")).strip().upper() not in original_document_labels
    ]
    submitted_items = [
        region
        for region in submitted
        if str(region.get("label", "")).strip().upper() in LINE_ITEM_LABELS
    ]
    return document_regions + new_document_regions + submitted_items


def current_review_info() -> dict | None:
    if not CURRENT_REVIEW.exists():
        return None
    try:
        info = json.loads(CURRENT_REVIEW.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    working = Path(info.get("working_csv", ""))
    return info if working.is_file() else None


def workspace_configs() -> dict[str, dict]:
    if not WORKSPACE_CONFIG.exists():
        return {}
    try:
        value = json.loads(WORKSPACE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def workspace_info(mode: str) -> dict | None:
    if mode not in {"train", "val"}:
        return None
    info = workspace_configs().get(mode)
    if not isinstance(info, dict):
        return None
    csv_path = Path(str(info.get("csv_path", "")))
    image_directory = Path(str(info.get("image_directory", "")))
    return info if csv_path.is_file() and image_directory.is_dir() else None


def save_workspace(mode: str, csv_path: Path, image_directory: Path) -> dict:
    configs = workspace_configs()
    previous = configs.get(mode, {}) if isinstance(configs.get(mode), dict) else {}
    info = {
        "mode": mode,
        "csv_path": str(csv_path),
        "image_directory": str(image_directory),
        "completed": previous.get("completed", [])
        if previous.get("csv_path") == str(csv_path) and previous.get("image_directory") == str(image_directory)
        else [],
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    configs[mode] = info
    atomic_write(WORKSPACE_CONFIG, json_bytes(configs), make_backup=False)
    return info


def annotation_csv(mode: str) -> Path:
    if mode in {"train", "val"}:
        info = workspace_info(mode)
        if not info:
            raise ApiError(HTTPStatus.NOT_FOUND, f"Chưa mở phiên đánh nhãn {mode}")
        return Path(info["csv_path"])
    if mode == "review":
        info = current_review_info()
        if not info:
            raise ApiError(HTTPStatus.NOT_FOUND, "Chưa có phiên kiểm tra CSV")
        return Path(info["working_csv"])
    raise ApiError(HTTPStatus.BAD_REQUEST, "Chế độ không hợp lệ")


def image_roots(mode: str | None = None) -> list[Path]:
    roots: list[Path] = []
    if mode in {"train", "val"}:
        info = workspace_info(mode)
        if info:
            roots.append(Path(info["image_directory"]))
    elif mode == "review":
        info = current_review_info()
        if info and info.get("source_directory"):
            roots.append(Path(info["source_directory"]))
    else:
        for workspace_mode in ("train", "val"):
            info = workspace_info(workspace_mode)
            if info:
                roots.append(Path(info["image_directory"]))
        info = current_review_info()
        if info and info.get("source_directory"):
            roots.append(Path(info["source_directory"]))
        roots.extend([UPLOAD_DIR, DEFAULT_IMAGE_DIR])
    return list(dict.fromkeys(roots))


def find_image(img_id: str, mode: str | None = None) -> Path | None:
    if Path(img_id).name != img_id:
        return None
    for root in image_roots(mode):
        candidate = root / img_id
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES:
            return candidate
    return None


def list_workspace_images(mode: str) -> list[dict]:
    info = workspace_info(mode)
    if not info:
        return []
    completed = set(info.get("completed", []))
    flagged = workspace_flagged_ids(info)
    rotations = workspace_rotations(info)
    result = []
    for row in read_rows(Path(info["csv_path"])):
        path = find_image(row["img_id"], mode)
        dimensions = image_dimensions(path) if path else (None, None)
        result.append(
            {
                "img_id": row["img_id"],
                "width": dimensions[0],
                "height": dimensions[1],
                "annotated": int(row["anno_num"] or 0) > 0,
                "anno_num": int(row["anno_num"] or 0),
                "checked": row["img_id"] in completed,
                "flagged": row["img_id"] in flagged,
                "rotation_confirmed": row["img_id"] in rotations,
                "rotation_to_upright": rotations.get(row["img_id"]),
                "missing_image": path is None,
            }
        )
    return result


def list_review_images() -> list[dict]:
    info = current_review_info()
    if not info:
        return []
    checked = set(info.get("checked", []))
    result = []
    for row in read_rows(Path(info["working_csv"])):
        path = find_image(row["img_id"], "review")
        dimensions = image_dimensions(path) if path else (None, None)
        result.append(
            {
                "img_id": row["img_id"],
                "width": dimensions[0],
                "height": dimensions[1],
                "annotated": True,
                "anno_num": int(row["anno_num"] or 0),
                "checked": row["img_id"] in checked,
                "flagged": False,
                "missing_image": path is None,
            }
        )
    return result


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def open_workspace(mode: str, csv_value: str, directory_value: str) -> tuple[dict, int]:
    if mode not in {"train", "val"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Phiên trực tiếp chỉ hỗ trợ train hoặc val")
    csv_path = Path(csv_value).expanduser().resolve()
    image_directory = Path(directory_value).expanduser().resolve()
    if not csv_path.is_file() or csv_path.suffix.lower() != ".csv":
        raise ApiError(HTTPStatus.BAD_REQUEST, "Đường dẫn CSV không tồn tại hoặc không phải file .csv")
    if not image_directory.is_dir():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Thư mục ảnh không tồn tại")
    if not os.access(csv_path, os.W_OK):
        raise ApiError(HTTPStatus.BAD_REQUEST, "CSV không có quyền ghi")

    rows = read_rows(csv_path)
    csv_names = {row["img_id"] for row in rows}
    image_names = {
        path.name
        for path in image_directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    }
    if csv_path.stat().st_size == 0:
        if not image_names:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Thư mục ảnh không có ảnh được hỗ trợ")
        rows = [
            {
                "img_id": name,
                "anno_polygons": "[]",
                "anno_texts": "",
                "anno_labels": "",
                "anno_num": "0",
                "anno_image_quality": "",
                "anno_line_item_ids": "[]",
            }
            for name in sorted(image_names)
        ]
        write_rows(csv_path, rows)
        csv_names = image_names
    missing = sorted(csv_names - image_names)
    extra = sorted(image_names - csv_names)
    if missing or extra:
        details = []
        if missing:
            details.append(f"thiếu {len(missing)} ảnh cho CSV (ví dụ: {', '.join(missing[:3])})")
        if extra:
            details.append(f"có {len(extra)} ảnh không nằm trong CSV (ví dụ: {', '.join(extra[:3])})")
        raise ApiError(HTTPStatus.BAD_REQUEST, "CSV và thư mục ảnh không khớp: " + "; ".join(details))
    return save_workspace(mode, csv_path, image_directory), len(rows)


def workspace_flags_path(info: dict) -> Path:
    csv_path = Path(info["csv_path"])
    return csv_path.with_name(f"{csv_path.stem}.flagged.json")


def workspace_rotation_path(info: dict) -> Path:
    csv_path = Path(info["csv_path"])
    stem = csv_path.stem.removesuffix("_df")
    return csv_path.with_name(f"{stem}_rotation.csv")


def workspace_missing_fields_path(info: dict) -> Path:
    csv_path = Path(info["csv_path"])
    return csv_path.with_name(f"{csv_path.stem}.missing_fields.json")


def workspace_missing_fields(info: dict) -> dict[str, list[str]]:
    path = workspace_missing_fields_path(info)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    images = payload.get("images", {}) if isinstance(payload, dict) else {}
    if not isinstance(images, dict):
        return {}
    result = {}
    for img_id, values in images.items():
        if isinstance(img_id, str) and isinstance(values, list):
            result[img_id] = sorted({str(value) for value in values if isinstance(value, str)})
    return result


def valid_missing_field_key(value: str) -> bool:
    if value in DOCUMENT_LABELS:
        return True
    match = re.fullmatch(r"(ITEM_NAME|QUANTITY|UNIT_PRICE|LINE_TOTAL):(\d+)", value)
    return bool(match and int(match.group(2)) > 0)


def set_workspace_missing_fields(mode: str, img_id: str, values: list[str]) -> tuple[list[str], Path]:
    if mode not in {"train", "val"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Trường vắng mặt chỉ áp dụng cho train hoặc validation")
    info = workspace_info(mode)
    if not info:
        raise ApiError(HTTPStatus.NOT_FOUND, f"Chưa mở phiên đánh nhãn {mode}")
    valid_ids = {row["img_id"] for row in read_rows(Path(info["csv_path"]))}
    if img_id not in valid_ids:
        raise ApiError(HTTPStatus.NOT_FOUND, "Ảnh không thuộc CSV đang mở")
    normalized = sorted({str(value) for value in values if valid_missing_field_key(str(value))})
    if len(normalized) != len(set(map(str, values))):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Danh sách trường vắng mặt không hợp lệ")
    images = workspace_missing_fields(info)
    if normalized:
        images[img_id] = normalized
    else:
        images.pop(img_id, None)
    path = workspace_missing_fields_path(info)
    payload = {"version": 1, "images": images, "updated_at": datetime.now(timezone.utc).isoformat()}
    atomic_write(path, json_bytes(payload))
    return normalized, path


def annotation_completeness_issues(mode: str, regions: list[dict], missing_fields: list[str]) -> list[str]:
    if mode not in {"train", "val"}:
        return []
    missing = set(missing_fields)
    present_document = {str(region.get("label")) for region in regions if region.get("label") in DOCUMENT_LABELS}
    present_items = {
        (str(region.get("label")), int(region.get("line_item_id")))
        for region in regions
        if region.get("label") in LINE_ITEM_LABELS
        and isinstance(region.get("line_item_id"), int)
        and int(region["line_item_id"]) > 0
    }
    issues = []
    if mode == "val":
        for label in sorted(DOCUMENT_LABELS):
            if label not in present_document and label not in missing:
                issues.append(f"thiếu {label}")
            if label in present_document and label in missing:
                issues.append(f"{label} vừa có nhãn vừa đánh dấu không xuất hiện")
    item_ids = {item_id for _, item_id in present_items}
    for value in missing:
        match = re.fullmatch(r"(ITEM_NAME|QUANTITY|UNIT_PRICE|LINE_TOTAL):(\d+)", value)
        if match:
            item_ids.add(int(match.group(2)))
    if not item_ids:
        issues.append("chưa có dòng mặt hàng")
    for item_id in sorted(item_ids):
        for label in sorted(LINE_ITEM_LABELS):
            key = f"{label}:{item_id}"
            present = (label, item_id) in present_items
            if not present and key not in missing:
                issues.append(f"dòng {item_id} thiếu {label}")
            if present and key in missing:
                issues.append(f"dòng {item_id} {label} vừa có nhãn vừa đánh dấu không xuất hiện")
    return issues


def workspace_rotations(info: dict) -> dict[str, int]:
    path = workspace_rotation_path(info)
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle)
            result = {}
            for row in rows:
                img_id = str(row.get("img_id", "")).strip()
                try:
                    rotation = int(str(row.get("rotation_to_upright", "")).strip())
                except ValueError:
                    continue
                if img_id and rotation in {0, 90, 180, 270}:
                    result[img_id] = rotation
            return result
    except (OSError, csv.Error):
        return {}


def encode_rotations(rotations: dict[str, int]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["img_id", "rotation_to_upright"], lineterminator="\n")
    writer.writeheader()
    for img_id in sorted(rotations):
        writer.writerow({"img_id": img_id, "rotation_to_upright": rotations[img_id]})
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def set_workspace_rotation(mode: str, img_id: str, rotation: int) -> tuple[int, Path]:
    if mode not in {"train", "val"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Góc xoay chỉ áp dụng cho train hoặc validation")
    if rotation not in {0, 90, 180, 270}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Góc xoay phải là 0, 90, 180 hoặc 270")
    info = workspace_info(mode)
    if not info:
        raise ApiError(HTTPStatus.NOT_FOUND, f"Chưa mở phiên đánh nhãn {mode}")
    valid_ids = {row["img_id"] for row in read_rows(Path(info["csv_path"]))}
    if img_id not in valid_ids:
        raise ApiError(HTTPStatus.NOT_FOUND, "Ảnh không thuộc CSV đang mở")
    rotations = workspace_rotations(info)
    rotations[img_id] = rotation
    path = workspace_rotation_path(info)
    atomic_write(path, encode_rotations(rotations))
    return rotation, path


def workspace_flagged_ids(info: dict) -> set[str]:
    path = workspace_flags_path(info)
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = payload.get("flagged_images", []) if isinstance(payload, dict) else []
    return {str(value) for value in values if isinstance(value, str)}


def set_workspace_flagged(mode: str, img_id: str, flagged: bool) -> tuple[bool, Path]:
    info = workspace_info(mode)
    if not info:
        raise ApiError(HTTPStatus.NOT_FOUND, f"Chưa mở phiên đánh nhãn {mode}")
    valid_ids = {row["img_id"] for row in read_rows(Path(info["csv_path"]))}
    if img_id not in valid_ids:
        raise ApiError(HTTPStatus.NOT_FOUND, "Ảnh không thuộc CSV đang mở")
    flagged_ids = workspace_flagged_ids(info)
    if flagged:
        flagged_ids.add(img_id)
    else:
        flagged_ids.discard(img_id)
    path = workspace_flags_path(info)
    payload = {
        "version": 1,
        "flagged_images": sorted(flagged_ids),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write(path, json_bytes(payload), make_backup=False)
    return img_id in flagged_ids, path


def set_workspace_completed(mode: str, img_id: str, checked: bool) -> bool:
    info = workspace_info(mode)
    if not info:
        raise ApiError(HTTPStatus.NOT_FOUND, f"Chưa mở phiên đánh nhãn {mode}")
    valid_ids = {row["img_id"] for row in read_rows(Path(info["csv_path"]))}
    if img_id not in valid_ids:
        raise ApiError(HTTPStatus.NOT_FOUND, "Ảnh không thuộc CSV đang mở")
    if checked:
        rows = {row["img_id"]: row for row in read_rows(Path(info["csv_path"]))}
        regions = row_to_regions(rows[img_id])
        missing = workspace_missing_fields(info).get(img_id, [])
        issues = annotation_completeness_issues(mode, regions, missing)
        if issues:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Nhãn chưa hoàn chỉnh: " + "; ".join(issues[:6]))
        if img_id not in workspace_rotations(info):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Ảnh chưa xác nhận chiều đọc")
    completed = set(info.get("completed", []))
    if checked:
        completed.add(img_id)
    else:
        completed.discard(img_id)
    configs = workspace_configs()
    info["completed"] = sorted(completed)
    configs[mode] = info
    atomic_write(WORKSPACE_CONFIG, json_bytes(configs), make_backup=False)
    return img_id in completed


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "MCOCRLabelStudio/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, status: int, payload: object) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, status: int, data: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Content-Length không hợp lệ") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request rỗng hoặc vượt 16 MiB")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON không hợp lệ") from exc
        if not isinstance(value, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON phải là object")
        return value

    def do_GET(self) -> None:
        try:
            self.handle_get()
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception as exc:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            self.handle_post()
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception as exc:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_PUT(self) -> None:
        try:
            self.handle_put()
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception as exc:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def handle_get(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/state":
            mode = query.get("mode", ["train"])[0]
            if mode in {"train", "val"}:
                info = workspace_info(mode)
                images = list_workspace_images(mode)
            elif mode == "review":
                info = current_review_info()
                images = list_review_images()
            else:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Chế độ không hợp lệ")
            self.send_json(
                HTTPStatus.OK,
                {
                    "mode": mode,
                    "images": images,
                    "csv_path": str(annotation_csv(mode)) if info else None,
                    "workspace": info if mode in {"train", "val"} else None,
                    "rotation_csv_path": str(workspace_rotation_path(info)) if mode in {"train", "val"} and info else None,
                    "missing_fields_path": str(workspace_missing_fields_path(info)) if mode in {"train", "val"} and info else None,
                    "review": info if mode == "review" else None,
                },
            )
            return
        if parsed.path == "/api/annotation":
            mode = query.get("mode", ["train"])[0]
            img_id = query.get("img_id", [""])[0]
            image_path = find_image(img_id, mode)
            if not image_path:
                raise ApiError(HTTPStatus.NOT_FOUND, "Không tìm thấy ảnh")
            rows = {row["img_id"]: row for row in read_rows(annotation_csv(mode))}
            row = rows.get(img_id)
            width, height = image_dimensions(image_path)
            regions = row_to_regions(row) if row else []
            if mode == "train":
                for region in regions:
                    region["locked"] = region["label"] not in LINE_ITEM_LABELS
            self.send_json(
                HTTPStatus.OK,
                {
                    "img_id": img_id,
                    "width": width,
                    "height": height,
                    "regions": regions,
                    "anno_image_quality": row["anno_image_quality"] if row else "",
                    "missing_fields": workspace_missing_fields(workspace_info(mode)).get(img_id, [])
                    if mode in {"train", "val"} and workspace_info(mode)
                    else [],
                },
            )
            return
        if parsed.path.startswith("/api/image/"):
            img_id = unquote(parsed.path.removeprefix("/api/image/"))
            mode = query.get("mode", ["train"])[0]
            image_path = find_image(img_id, mode)
            if not image_path:
                raise ApiError(HTTPStatus.NOT_FOUND, "Không tìm thấy ảnh")
            content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
            self.send_bytes(HTTPStatus.OK, image_path.read_bytes(), content_type)
            return
        if parsed.path == "/api/export":
            mode = query.get("mode", ["train"])[0]
            path = annotation_csv(mode)
            self.send_bytes(HTTPStatus.OK, path.read_bytes(), "text/csv; charset=utf-8", path.name)
            return
        self.serve_static(parsed.path)

    def handle_post(self) -> None:
        parsed = urlparse(self.path)
        body = self.read_json()
        if parsed.path == "/api/workspace/open":
            mode = str(body.get("mode", ""))
            info, row_count = open_workspace(
                mode,
                str(body.get("csv_path", "")).strip(),
                str(body.get("image_directory", "")).strip(),
            )
            self.send_json(HTTPStatus.OK, {"workspace": info, "rows": row_count})
            return
        if parsed.path == "/api/workspace/check":
            mode = str(body.get("mode", ""))
            img_id = str(body.get("img_id", ""))
            checked = set_workspace_completed(mode, img_id, bool(body.get("checked", True)))
            self.send_json(HTTPStatus.OK, {"checked": checked})
            return
        if parsed.path == "/api/workspace/flag":
            mode = str(body.get("mode", ""))
            img_id = str(body.get("img_id", ""))
            flagged, path = set_workspace_flagged(mode, img_id, bool(body.get("flagged", True)))
            self.send_json(HTTPStatus.OK, {"flagged": flagged, "flag_file": str(path)})
            return
        if parsed.path == "/api/workspace/rotation":
            mode = str(body.get("mode", ""))
            img_id = str(body.get("img_id", ""))
            try:
                requested_rotation = int(body.get("rotation_to_upright"))
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Góc xoay không hợp lệ") from exc
            rotation, path = set_workspace_rotation(mode, img_id, requested_rotation)
            self.send_json(
                HTTPStatus.OK,
                {"rotation_to_upright": rotation, "rotation_csv_path": str(path)},
            )
            return
        if parsed.path == "/api/images":
            name = safe_filename(str(body.get("name", "")))
            encoded = body.get("data_base64", "")
            try:
                data = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Dữ liệu ảnh không hợp lệ") from exc
            if len(data) > 10 * 1024 * 1024:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Ảnh vượt giới hạn 10 MiB")
            incoming_hash = sha256_bytes(data)
            target = UPLOAD_DIR / name
            same_name = next(
                (
                    root / name
                    for root in (UPLOAD_DIR, DEFAULT_IMAGE_DIR)
                    if (root / name).is_file()
                ),
                None,
            )
            if same_name:
                if sha256_file(same_name) == incoming_hash:
                    width, height = image_dimensions(same_name)
                    self.send_json(HTTPStatus.OK, {"status": "existing", "img_id": name, "width": width, "height": height})
                    return
                raise ApiError(HTTPStatus.CONFLICT, "Cùng tên file nhưng nội dung khác. Hãy đổi tên ảnh.")
            for root in (UPLOAD_DIR, DEFAULT_IMAGE_DIR):
                if not root.is_dir():
                    continue
                for existing in root.iterdir():
                    if existing.is_file() and existing.suffix.lower() in IMAGE_SUFFIXES and sha256_file(existing) == incoming_hash:
                        width, height = image_dimensions(existing)
                        self.send_json(
                            HTTPStatus.OK,
                            {"status": "duplicate", "img_id": existing.name, "width": width, "height": height},
                        )
                        return
            atomic_write(target, data, make_backup=False)
            width, height = image_dimensions(target)
            self.send_json(HTTPStatus.CREATED, {"status": "created", "img_id": name, "width": width, "height": height})
            return
        if parsed.path == "/api/review/import":
            name = Path(str(body.get("name", "import.csv"))).name
            csv_text = str(body.get("csv_text", ""))
            source_directory = str(body.get("source_directory", "")).strip()
            if source_directory:
                source_path = Path(source_directory).expanduser().resolve()
                if not source_path.is_dir():
                    raise ApiError(HTTPStatus.BAD_REQUEST, "Thư mục ảnh không tồn tại")
                source_directory = str(source_path)
            rows = parse_csv_text(csv_text)
            session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            session_dir = REVIEW_DIR / session_id
            counter = 1
            while session_dir.exists():
                session_dir = REVIEW_DIR / f"{session_id}-{counter}"
                counter += 1
            session_dir.mkdir(parents=True)
            original = session_dir / "original.csv"
            working = session_dir / "reviewed.csv"
            atomic_write(original, csv_text.lstrip("\ufeff").encode("utf-8"), make_backup=False)
            atomic_write(working, encode_rows(rows), make_backup=False)
            info = {
                "session_id": session_dir.name,
                "source_name": name,
                "source_directory": source_directory,
                "original_csv": str(original),
                "working_csv": str(working),
                "checked": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_write(CURRENT_REVIEW, json_bytes(info), make_backup=False)
            missing = sum(1 for row in rows if find_image(row["img_id"], "review") is None)
            self.send_json(HTTPStatus.CREATED, {"session": info, "rows": len(rows), "missing_images": missing})
            return
        if parsed.path == "/api/review/check":
            info = current_review_info()
            if not info:
                raise ApiError(HTTPStatus.NOT_FOUND, "Chưa có phiên kiểm tra")
            img_id = str(body.get("img_id", ""))
            checked = set(info.get("checked", []))
            if body.get("checked", True):
                checked.add(img_id)
            else:
                checked.discard(img_id)
            info["checked"] = sorted(checked)
            atomic_write(CURRENT_REVIEW, json_bytes(info), make_backup=False)
            self.send_json(HTTPStatus.OK, {"checked": img_id in checked})
            return
        raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint không tồn tại")

    def handle_put(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/annotation":
            raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint không tồn tại")
        body = self.read_json()
        mode = str(body.get("mode", "train"))
        img_id = str(body.get("img_id", ""))
        image_path = find_image(img_id, mode)
        if not image_path:
            raise ApiError(HTTPStatus.NOT_FOUND, "Không tìm thấy ảnh")
        width, height = image_dimensions(image_path)
        if int(body.get("width", width)) != width or int(body.get("height", height)) != height:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Kích thước ảnh phía trình duyệt không khớp ảnh gốc")
        regions = body.get("regions", [])
        if not isinstance(regions, list):
            raise ApiError(HTTPStatus.BAD_REQUEST, "regions phải là list")
        missing_fields = body.get("missing_fields", []) if mode in {"train", "val"} else []
        if not isinstance(missing_fields, list) or any(not valid_missing_field_key(str(value)) for value in missing_fields):
            raise ApiError(HTTPStatus.BAD_REQUEST, "missing_fields không hợp lệ")
        existing = {row["img_id"]: row for row in read_rows(annotation_csv(mode))}.get(img_id)
        quality = existing["anno_image_quality"] if existing else ""
        regions = regions_for_save(mode, existing, regions)
        row = regions_to_row(img_id, regions, width, height, quality)
        upsert_row(annotation_csv(mode), row)
        if mode in {"train", "val"}:
            set_workspace_missing_fields(mode, img_id, missing_fields)
        self.send_json(
            HTTPStatus.OK,
            {"saved": True, "img_id": img_id, "anno_num": len(regions), "csv_path": str(annotation_csv(mode))},
        )

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        path = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in path.parents and path != STATIC_DIR.resolve():
            raise ApiError(HTTPStatus.FORBIDDEN, "Đường dẫn không hợp lệ")
        if not path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "Không tìm thấy tài nguyên")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_bytes(HTTPStatus.OK, path.read_bytes(), content_type)


def main() -> None:
    ensure_storage()
    host = "127.0.0.1"
    port = 8765
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"MC-OCR Label Studio: http://{host}:{port}")
    print("Direct train/validation workspaces write to the selected CSV paths.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng server. Dữ liệu đã lưu vẫn còn trên ổ đĩa.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
