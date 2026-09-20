"""Export T04 quarantine documents into a separate, reviewable package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "path": destination.as_posix(),
        "bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
        "source_path": source.as_posix(),
        "source_sha256": _sha256(source),
    }


def _write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": path.as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _assert_excluded(accepted_path: Path, quarantined_ids: set[str]) -> None:
    accepted_ids = {
        record["document_id"]
        for record in _read_jsonl(accepted_path)
    }
    overlap = sorted(accepted_ids & quarantined_ids)
    if overlap:
        raise ValueError(f"Quarantine IDs still occur in {accepted_path}: {overlap}")


def export(workspace: Path, output_root: Path) -> dict[str, Any]:
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"
    mcocr_records = _read_jsonl(processed / "mcocr_quarantine.jsonl")
    sroie_records = _read_jsonl(processed / "sroie_quarantine.jsonl")
    if len(mcocr_records) != 3 or len(sroie_records) != 2:
        raise ValueError("Expected the five reviewed T04 quarantine records")

    mcocr_ids = {record["document_id"] for record in mcocr_records}
    sroie_ids = {record["document_id"] for record in sroie_records}
    _assert_excluded(processed / "mcocr.jsonl", mcocr_ids)
    _assert_excluded(processed / "sroie.jsonl", sroie_ids)

    mcocr_rows: dict[str, dict[str, str]] = {}
    mcocr_csv = workspace / "dataset_hoadon" / "mcocr_train_df.csv"
    with mcocr_csv.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["img_id"] in mcocr_ids:
                mcocr_rows[row["img_id"]] = row
    if set(mcocr_rows) != mcocr_ids:
        raise ValueError("Could not find every MC-OCR quarantine row")

    documents: list[dict[str, Any]] = []
    for record in mcocr_records:
        document_id = record["document_id"]
        directory = output_root / "mcocr_2021" / Path(document_id).stem
        files = [
            _copy(
                workspace / "dataset_hoadon" / "train_images" / "train_images" / document_id,
                directory / document_id,
            ),
            _write_json(directory / "annotation_row.json", mcocr_rows[document_id]),
            _write_json(directory / "quarantine_record.json", record),
        ]
        documents.append({
            "dataset": "mcocr_2021",
            "document_id": document_id,
            "reason_codes": record["reason_codes"],
            "files": files,
        })

    sroie_root = workspace / "dataset_hoadon" / "SROIE2019"
    for record in sroie_records:
        document_id = record["document_id"]
        split = record["source_partition"]
        directory = output_root / "sroie_2019" / document_id
        files = [
            _copy(sroie_root / split / "img" / f"{document_id}.jpg", directory / f"{document_id}.jpg"),
            _copy(sroie_root / split / "box" / f"{document_id}.txt", directory / "ocr_boxes.txt"),
            _copy(sroie_root / split / "entities" / f"{document_id}.txt", directory / "entities.txt"),
            _write_json(directory / "quarantine_record.json", record),
        ]
        documents.append({
            "dataset": "sroie_2019",
            "document_id": document_id,
            "source_partition": split,
            "reason_codes": record["reason_codes"],
            "files": files,
        })

    for document in documents:
        for file_record in document["files"]:
            file_record["path"] = Path(file_record["path"]).relative_to(workspace).as_posix()
            if "source_path" in file_record:
                file_record["source_path"] = Path(file_record["source_path"]).relative_to(workspace).as_posix()
                if file_record["sha256"] != file_record["source_sha256"]:
                    raise ValueError(f"Copied file hash mismatch: {file_record['path']}")

    manifest = {
        "task": "T04",
        "package_version": "t04_v1",
        "status": "QUARANTINED_EXCLUDED_FROM_CANONICAL_DATA",
        "document_count": len(documents),
        "excluded_from": [
            "experiments/data/processed/t04_v1/mcocr.jsonl",
            "experiments/data/processed/t04_v1/sroie.jsonl",
        ],
        "source_files_moved": False,
        "copies_match_source_sha256": True,
        "documents": documents,
    }
    _write_json(output_root / "manifest.json", manifest)
    (output_root / "README.md").write_text(
        "# T04 quarantine package\n\n"
        "Thư mục này chứa bản sao của 5 tài liệu bị loại khỏi canonical dataset `t04_v1`. "
        "Các file nguồn vẫn được giữ nguyên. `manifest.json` ghi lý do, đường dẫn nguồn và SHA-256.\n\n"
        "Không dùng các tài liệu trong thư mục này cho train/validation/test cho đến khi QA sửa lỗi, "
        "ghi decision mới và chạy lại toàn bộ build/verification.\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output = (args.output or workspace / "experiments" / "data" / "quarantine" / "t04_v1").resolve()
    manifest = export(workspace, output)
    print(json.dumps({
        "status": manifest["status"],
        "document_count": manifest["document_count"],
        "output": output.as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
