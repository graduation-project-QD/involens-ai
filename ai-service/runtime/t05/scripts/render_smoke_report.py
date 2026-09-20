#!/usr/bin/env python3
"""Render a human-readable report from the machine-readable T05 manifest."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def value(item: Any) -> str:
    return "N/A" if item is None else str(item)


def main() -> None:
    root = Path(os.environ.get("T05_ROOT", Path(__file__).resolve().parents[1]))
    output = Path(os.environ.get("T05_OUTPUT_DIR", root / "outputs"))
    manifest = json.loads((output / "runtime_manifest.json").read_text(encoding="utf-8"))
    layout = manifest["smoke"]["layoutxlm"]
    paddle = manifest["smoke"]["paddleocr"]
    hardware = manifest["hardware_inventory"]
    gpu_query = hardware.get("commands", {}).get("gpu_query", {}).get("stdout", "N/A")
    lines = [
        "# T05 — Rented GPU runtime smoke",
        "",
        f"**Status:** `{manifest['status']}`  ",
        f"**Candidate:** `{manifest['candidate'].get('T05_CANDIDATE_ID', 'N/A')}`  ",
        f"**Host:** `{manifest['host']['hostname']}`  ",
        f"**GPU:** `{gpu_query}`",
        "",
        "## LayoutXLM",
        "",
        f"- Status: `{layout.get('status', 'MISSING')}`",
        f"- Model: `{layout.get('model_id', 'N/A')}`",
        f"- Revision: `{layout.get('revision', 'N/A')}`",
        f"- Load seconds: {value(layout.get('load_seconds'))}",
        f"- Largest tested physical batch: {value(layout.get('largest_tested_physical_batch'))}",
        f"- Reload parity: `{layout.get('reload_parity', {}).get('pass', False)}`",
        "",
        "| Batch | Status | Loss | Forward+backward seconds | Peak Torch allocated bytes | Peak GPU used MiB |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for trial in layout.get("batch_trials", []):
        lines.append(
            f"| {trial.get('batch_size')} | {trial.get('status')} | {value(trial.get('loss'))} | "
            f"{value(trial.get('forward_backward_seconds'))} | "
            f"{value(trial.get('peak_torch_allocated_bytes'))} | {value(trial.get('peak_gpu_used_mib'))} |"
        )
    lines.extend([
        "",
        "## PaddleOCR",
        "",
        f"- Status: `{paddle.get('status', 'MISSING')}`",
        f"- API variant: `{paddle.get('api_variant', 'N/A')}`",
        f"- Load + inference seconds: {value(paddle.get('elapsed_seconds_including_load'))}",
        f"- Recognized texts: {value(paddle.get('recognized_text_count'))}",
        f"- Polygons: {value(paddle.get('polygon_count'))}",
        f"- Peak process RAM bytes: {value(paddle.get('peak_process_rss_bytes'))}",
        f"- Peak GPU used MiB: {value(paddle.get('peak_gpu_used_mib'))}",
        "",
        "## Reproducibility",
        "",
        "The machine-readable `runtime_manifest.json`, dependency locks, pip inspect output, "
        "hardware inventory, logs and checksums are included in the result archive. The large "
        "saved model is intentionally excluded; its files are hashed and it is reproducible from "
        "the immutable LayoutXLM revision.",
        "",
        "T05 can be marked complete only when this report is PASS and the result archive has been "
        "copied to persistent/local storage before the rented instance is deleted.",
        "",
    ])
    (output / "runtime_smoke.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
