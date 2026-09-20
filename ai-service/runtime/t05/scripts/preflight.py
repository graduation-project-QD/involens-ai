#!/usr/bin/env python3
"""Local, GPU-free verification of the prepared T05 bundle."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from PIL import Image


REQUIRED_FILES = (
    "candidate.env",
    "requirements-candidate.txt",
    "fixtures/sample_invoice.jpg",
    "fixtures/sample_invoice.provenance.json",
    "scripts/bootstrap_ubuntu.sh",
    "scripts/run_smoke.sh",
    "scripts/package_results.sh",
    "scripts/hardware_inventory.py",
    "scripts/resource_monitor.py",
    "scripts/smoke_layoutxlm.py",
    "scripts/smoke_paddleocr.py",
    "scripts/finalize_runtime.py",
    "scripts/render_smoke_report.py",
)
REQUIRED_ENV = (
    "T05_CANDIDATE_ID", "PYTHON_MIN", "PYTHON_MAX", "TORCH_VERSION",
    "TORCHVISION_VERSION", "TORCH_INDEX_URL", "TRANSFORMERS_VERSION",
    "PADDLE_VERSION", "PADDLE_PACKAGE", "PADDLE_DEVICE", "PADDLE_INDEX_URL",
    "PADDLEOCR_VERSION",
    "LAYOUTXLM_MODEL_ID", "LAYOUTXLM_REVISION", "T05_BATCH_SIZES",
)
EXPECTED_FIXTURE_SHA256 = "e5a349bfce39e5f54eea871b56bd1e1cb61a18ff78478342729364db5d803dc0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if not re.fullmatch(r"[A-Z0-9_]+=[^\s]+", stripped):
                raise ValueError(f"Invalid candidate.env line: {line!r}")
            key, value = stripped.split("=", 1)
            values[key] = value
    return values


def run(root: Path) -> dict[str, Any]:
    failures: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            failures.append(f"missing required file: {relative}")
    candidate: dict[str, str] = {}
    try:
        candidate = parse_env(root / "candidate.env")
    except (OSError, ValueError) as error:
        failures.append(str(error))
    missing_env = sorted(set(REQUIRED_ENV) - set(candidate))
    if missing_env:
        failures.append(f"candidate.env missing keys: {missing_env}")
    if candidate.get("LAYOUTXLM_MODEL_ID") != "microsoft/layoutxlm-base":
        failures.append("candidate changes the required LayoutXLM model")
    fixture = root / "fixtures" / "sample_invoice.jpg"
    if fixture.is_file() and sha256_file(fixture) != EXPECTED_FIXTURE_SHA256:
        failures.append("fixture hash differs from the accepted T06 validation document")
    if fixture.is_file() and fixture.stat().st_size > 10 * 1024 * 1024:
        failures.append("fixture exceeds the v1 10 MiB limit")
    if fixture.is_file():
        try:
            with Image.open(fixture) as image:
                width, height = image.size
                if width * height > 20_000_000:
                    failures.append("fixture exceeds the v1 20 MP limit")
                if image.format not in {"JPEG", "PNG"}:
                    failures.append(f"unsupported fixture format: {image.format}")
        except OSError as error:
            failures.append(f"fixture cannot be decoded: {error}")
    for script in sorted((root / "scripts").glob("*.py")):
        try:
            ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        except (SyntaxError, UnicodeDecodeError) as error:
            failures.append(f"invalid Python script {script.name}: {error}")
    for script in sorted((root / "scripts").glob("*.sh")):
        payload = script.read_bytes()
        if b"\r\n" in payload:
            failures.append(f"shell script has CRLF line endings: {script.name}")
        if not payload.startswith(b"#!/usr/bin/env bash\n"):
            failures.append(f"shell script has an invalid shebang: {script.name}")
    package_files = [
        path for path in root.rglob("*")
        if path.is_file() and "outputs" not in path.parts and "__pycache__" not in path.parts
    ]
    manifest = {
        path.relative_to(root).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(package_files)
        if path.name != "bundle_manifest.json"
    }
    return {
        "task": "T05",
        "stage": "LOCAL_PREPARATION_ONLY",
        "status": "PASS" if not failures else "FAIL",
        "candidate_id": candidate.get("T05_CANDIDATE_ID"),
        "checks": {
            "required_files": len(REQUIRED_FILES),
            "fixture_sha256": sha256_file(fixture) if fixture.is_file() else None,
            "python_scripts_parsed": len(list((root / "scripts").glob("*.py"))),
            "shell_scripts_lf": not any("CRLF" in failure for failure in failures),
            "layoutxlm_model_unchanged": candidate.get("LAYOUTXLM_MODEL_ID") == "microsoft/layoutxlm-base",
            "full_dataset_in_bundle": False,
            "gpu_execution_performed": False,
        },
        "bundle_files": manifest,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.root.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
