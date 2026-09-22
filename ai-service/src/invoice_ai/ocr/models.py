"""Hash and verify local PaddleOCR model artifacts without committing weights."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

from .config import OcrConfig
from .schema import OcrError, OcrRuntimeIdentity


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_files(model_dir: Path) -> list[dict[str, Any]]:
    if not model_dir.is_dir():
        raise OcrError("OCR_MODEL_MISSING", "PaddleOCR model directory is missing", path=str(model_dir))
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in model_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(model_dir)
        if ".cache" in relative.parts:
            continue
        records.append({
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    if not records:
        raise OcrError("OCR_MODEL_MISSING", "PaddleOCR model directory contains no files", path=str(model_dir))
    return records


def _current_model_manifest(config: OcrConfig, cache_root: Path) -> dict[str, Any]:
    official = cache_root / "official_models"
    models = {
        "detection": {
            "name": config.detection_model_name,
            "files": _model_files(official / config.detection_model_name),
        },
        "recognition": {
            "name": config.recognition_model_name,
            "files": _model_files(official / config.recognition_model_name),
        },
    }
    core = {
        "schema_version": "t10_paddleocr_model_manifest_v1",
        "engine": {
            "paddlepaddle": importlib.metadata.version("paddlepaddle"),
            "paddleocr": importlib.metadata.version("paddleocr"),
            "paddlex": importlib.metadata.version("paddlex"),
        },
        "models": models,
    }
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**core, "manifest_sha256": hashlib.sha256(canonical).hexdigest()}


def build_model_manifest(config: OcrConfig, cache_root: Path, output_path: Path) -> dict[str, Any]:
    payload = _current_model_manifest(config, cache_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_runtime_identity(config: OcrConfig, cache_root: Path, manifest_path: Path) -> OcrRuntimeIdentity:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = _current_model_manifest(config, cache_root)
    if payload.get("manifest_sha256") != expected["manifest_sha256"]:
        raise OcrError("OCR_MODEL_CHECKSUM_MISMATCH", "Local OCR model files differ from the frozen manifest")
    engine = expected["engine"]
    versions = {
        "paddlepaddle": config.paddlepaddle_version,
        "paddleocr": config.paddleocr_version,
        "paddlex": config.paddlex_version,
    }
    if engine != versions:
        raise OcrError("OCR_RUNTIME_VERSION_MISMATCH", "Installed OCR packages differ from T10 config", expected=versions, actual=engine)
    return OcrRuntimeIdentity(
        paddlepaddle_version=engine["paddlepaddle"],
        paddleocr_version=engine["paddleocr"],
        paddlex_version=engine["paddlex"],
        detection_model_name=config.detection_model_name,
        recognition_model_name=config.recognition_model_name,
        model_manifest_sha256=expected["manifest_sha256"],
    )
