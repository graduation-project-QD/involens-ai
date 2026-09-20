#!/usr/bin/env python3
"""Create the T05 runtime manifest from smoke outputs and pinned packages."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "MISSING", "path": path.name}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_candidate(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def distribution_evidence(distribution: importlib.metadata.Distribution) -> dict[str, Any]:
    evidence: dict[str, Any] = {"version": distribution.version}
    files = list(distribution.files or [])
    for filename in ("METADATA", "RECORD", "direct_url.json"):
        matches = [item for item in files if item.name == filename and ".dist-info" in str(item)]
        if not matches:
            continue
        path = Path(distribution.locate_file(matches[0]))
        if not path.is_file():
            continue
        evidence[f"{filename.lower().replace('.', '_')}_sha256"] = sha256_file(path)
        if filename == "direct_url.json":
            try:
                evidence["direct_url"] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                evidence["direct_url"] = "UNREADABLE"
    return evidence


def main() -> int:
    root = Path(os.environ.get("T05_ROOT", Path(__file__).resolve().parents[1]))
    output = Path(os.environ.get("T05_OUTPUT_DIR", root / "outputs"))
    output.mkdir(parents=True, exist_ok=True)
    hardware = read_json(output / "hardware_inventory.json")
    layoutxlm = read_json(output / "layoutxlm_smoke.json")
    paddleocr = read_json(output / "paddleocr_smoke.json")
    candidate_path = root / "candidate.env"
    candidate = parse_candidate(candidate_path)
    package_evidence = {
        distribution.metadata["Name"]: distribution_evidence(distribution)
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    input_files = [
        candidate_path,
        root / "requirements-candidate.txt",
        root / "fixtures" / "sample_invoice.jpg",
        *sorted((root / "scripts").glob("*")),
    ]
    input_manifest = {
        path.relative_to(root).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in input_files
        if path.is_file()
    }
    pass_status = layoutxlm.get("status") == "PASS" and paddleocr.get("status") == "PASS"
    manifest = {
        "schema_version": "t05_runtime_manifest_v1",
        "task": "T05",
        "status": "PASS" if pass_status else "FAIL",
        "candidate": candidate,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "python_executable": sys.executable,
        },
        "hardware_inventory": hardware,
        "smoke": {
            "layoutxlm": layoutxlm,
            "paddleocr": paddleocr,
        },
        "physical_batch": {
            "largest_tested_pass": layoutxlm.get("largest_tested_physical_batch"),
            "tested_values": [item.get("batch_size") for item in layoutxlm.get("batch_trials", [])],
            "scope": "T05 synthetic external-OCR fixture; T18 must retain gradient accumulation and monitor real units",
        },
        "installed_distributions": dict(sorted(package_evidence.items(), key=lambda item: item[0].lower())),
        "preparation_input_files": input_manifest,
        "large_saved_model_copy_policy": "Model files are hashed in layoutxlm_smoke.json but excluded from the result archive; reproduce from immutable model revision and final lock.",
    }
    path = output / "runtime_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "runtime_manifest": str(path),
        "physical_batch": manifest["physical_batch"],
    }, indent=2))
    return 0 if pass_status else 1


if __name__ == "__main__":
    sys.exit(main())
