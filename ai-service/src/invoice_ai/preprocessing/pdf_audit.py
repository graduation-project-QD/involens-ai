"""Run the bounded synthetic-fixture audit for T09."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from .core import PreprocessingError, load_config
from .pdf_intake import intake_pdf_path, load_pdf_intake_config


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(workspace: Path) -> dict[str, Any]:
    preprocessing_path = workspace / "ai-service" / "configs" / "preprocessing" / "v1.json"
    pdf_config_path = workspace / "ai-service" / "configs" / "preprocessing" / "pdf_v1.json"
    fixtures = workspace / "ai-service" / "tests" / "fixtures" / "pdf"
    preprocessing_config = load_config(preprocessing_path)
    config = load_pdf_intake_config(pdf_config_path, preprocessing_config)
    fixture_paths = sorted(fixtures.glob("*.pdf"))
    hashes_before = {path.name: _sha256(path) for path in fixture_paths}

    valid_path = fixtures / "valid_one_page.pdf"
    valid_runs: list[dict[str, Any]] = []
    for _ in range(3):
        started = time.perf_counter()
        result = intake_pdf_path(valid_path, config, preprocessing_config)
        valid_runs.append({
            "end_to_end_ms": round((time.perf_counter() - started) * 1000, 3),
            "render_ms": result.render_ms,
            "peak_rss_bytes": result.peak_rss_bytes,
            "rendered_size": list(result.rendered_size),
            "t07_output_size": list(result.page.image.size),
            "pixel_sha256": result.page.pixel_sha256,
            "manifest": result.to_manifest(),
        })

    rejection_expectations = {
        "two_pages.pdf": "PDF_PAGE_COUNT_UNSUPPORTED",
        "encrypted.pdf": "PDF_ENCRYPTED",
        "corrupt.pdf": "PDF_DECODE_ERROR",
        "pixel_bomb.pdf": "PIXEL_LIMIT_EXCEEDED",
    }
    rejection_results: list[dict[str, Any]] = []
    for filename, expected in rejection_expectations.items():
        actual = "UNEXPECTED_PASS"
        details: dict[str, Any] = {}
        try:
            intake_pdf_path(fixtures / filename, config, preprocessing_config)
        except PreprocessingError as error:
            actual = error.code
            details = error.details
        rejection_results.append({
            "fixture": filename,
            "expected_code": expected,
            "actual_code": actual,
            "status": "PASS" if actual == expected else "FAIL",
            "details": details,
        })

    hashes_after = {path.name: _sha256(path) for path in fixture_paths}
    pixel_hashes = {item["pixel_sha256"] for item in valid_runs}
    render_times = [float(item["render_ms"]) for item in valid_runs]
    end_to_end_times = [float(item["end_to_end_ms"]) for item in valid_runs]
    peak_values = [int(item["peak_rss_bytes"]) for item in valid_runs if item["peak_rss_bytes"] is not None]
    status = "PASS" if (
        all(item["status"] == "PASS" for item in rejection_results)
        and len(pixel_hashes) == 1
        and hashes_before == hashes_after
        and len(peak_values) == len(valid_runs)
    ) else "FAIL"
    report = {
        "task": "T09",
        "status": status,
        "intake_version": config.intake_version,
        "policy": {
            "max_bytes": config.max_bytes,
            "max_pixels": config.max_pixels,
            "required_page_count": config.required_page_count,
            "reject_encrypted": config.reject_encrypted,
            "text_layer_used": config.use_text_layer,
            "renderer_dependency": config.renderer_dependency,
            "renderer_dpi": config.renderer_dpi,
            "renderer_timeout_seconds": config.renderer_timeout_seconds,
        },
        "valid_fixture": {
            "runs": len(valid_runs),
            "deterministic_pixel_hash": len(pixel_hashes) == 1,
            "pixel_sha256": next(iter(pixel_hashes)),
            "render_ms_median": statistics.median(render_times),
            "render_ms_max": max(render_times),
            "end_to_end_ms_median": statistics.median(end_to_end_times),
            "end_to_end_ms_max": max(end_to_end_times),
            "peak_rss_bytes_max": max(peak_values) if peak_values else None,
            "rendered_size": valid_runs[0]["rendered_size"],
            "t07_output_size": valid_runs[0]["t07_output_size"],
        },
        "rejection_correctness": {
            "pass": sum(item["status"] == "PASS" for item in rejection_results),
            "total": len(rejection_results),
            "cases": rejection_results,
        },
        "fixture_integrity": {
            "raw_sources_modified": hashes_before != hashes_after,
            "sha256": hashes_after,
        },
        "inputs": {
            "pdf_config": pdf_config_path.relative_to(workspace).as_posix(),
            "pdf_config_sha256": _sha256(pdf_config_path),
            "preprocessing_config_sha256": _sha256(preprocessing_path),
        },
    }
    output_path = workspace / "experiments" / "reports" / "t09_pdf_intake_audit.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace.resolve()), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
