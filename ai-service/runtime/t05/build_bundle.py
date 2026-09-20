#!/usr/bin/env python3
"""Build a deterministic, dataset-free ZIP for upload to the rented VM."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from scripts.preflight import run


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    report = run(root)
    if report["status"] != "PASS":
        raise SystemExit(f"Preflight failed: {report['failures']}")
    manifest_path = root / "bundle_manifest.json"
    manifest = {
        "schema_version": "t05_prepared_bundle_v1",
        "stage": "LOCAL_PREPARATION_ONLY",
        "candidate_id": report["candidate_id"],
        "files": report["bundle_files"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [
        path for path in root.rglob("*")
        if path.is_file()
        and "outputs" not in path.parts
        and "__pycache__" not in path.parts
        and path != args.output.resolve()
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            relative = Path("t05_gpu_smoke") / path.relative_to(root)
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 9, 19, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix in {".sh", ".py"} else 0o644) << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    digest = sha256_file(args.output)
    checksum_path = args.output.with_suffix(args.output.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {args.output.name}\n", encoding="ascii")
    print(json.dumps({
        "status": "PASS",
        "bundle": str(args.output),
        "bundle_sha256": digest,
        "checksum_file": str(checksum_path),
        "files": len(files),
    }, indent=2))


if __name__ == "__main__":
    main()
