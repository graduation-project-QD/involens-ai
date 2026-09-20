#!/usr/bin/env python3
"""LayoutXLM load/forward/backward/save/reload smoke test on the rented GPU."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from PIL import Image

from resource_monitor import ResourceMonitor


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repeat_batch(batch: dict[str, Any], size: int, torch_module: Any) -> dict[str, Any]:
    repeated: dict[str, Any] = {}
    for key, value in batch.items():
        if torch_module.is_tensor(value):
            repeats = [size] + [1] * (value.ndim - 1)
            repeated[key] = value.repeat(*repeats)
        else:
            repeated[key] = value
    return repeated


def accepted_model_inputs(model: Any, batch: dict[str, Any]) -> dict[str, Any]:
    parameters = set(inspect.signature(model.forward).parameters)
    candidates = dict(batch)
    if "pixel_values" in candidates and "pixel_values" not in parameters and "image" in parameters:
        candidates["image"] = candidates.pop("pixel_values")
    filtered = {key: value for key, value in candidates.items() if key in parameters}
    return filtered


def main() -> int:
    output = Path(os.environ.get("T05_OUTPUT_DIR", "outputs"))
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "layoutxlm_smoke.json"
    saved_model = output / "layoutxlm_saved_model"
    if saved_model.exists():
        shutil.rmtree(saved_model)
    result: dict[str, Any] = {
        "schema_version": "t05_layoutxlm_smoke_v1",
        "status": "FAIL",
        "model_id": os.environ["LAYOUTXLM_MODEL_ID"],
        "revision": os.environ["LAYOUTXLM_REVISION"],
        "batch_trials": [],
    }
    try:
        import torch
        from transformers import AutoModelForTokenClassification, AutoProcessor, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("torch.cuda.is_available() is false")
        device = torch.device("cuda:0")
        sequence_length = int(os.environ.get("T05_SEQUENCE_LENGTH", "128"))
        batch_sizes = [int(item) for item in os.environ.get("T05_BATCH_SIZES", "1,2").split(",")]
        use_amp = os.environ.get("T05_MIXED_PRECISION", "1") == "1"
        result["torch"] = {
            "version": torch.__version__,
            "cuda_build": torch.version.cuda,
            "gpu_name": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
        }

        load_started = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(
            result["model_id"], revision=result["revision"], use_fast=True
        )
        processor = AutoProcessor.from_pretrained(
            result["model_id"], revision=result["revision"], apply_ocr=False
        )
        model = AutoModelForTokenClassification.from_pretrained(
            result["model_id"],
            revision=result["revision"],
            num_labels=9,
            ignore_mismatched_sizes=True,
        ).to(device)
        result["load_seconds"] = time.perf_counter() - load_started

        image_path = Path(os.environ["T05_FIXTURE_IMAGE"])
        image = Image.open(image_path).convert("RGB")
        words = ["CỬA", "HÀNG", "MẪU", "Ngày", "01/01/2026", "Tổng", "125.000", "đ"]
        boxes = [
            [50, 50, 160, 100], [170, 50, 300, 100], [310, 50, 410, 100],
            [50, 150, 130, 190], [140, 150, 300, 190], [50, 800, 140, 850],
            [600, 800, 760, 850], [770, 800, 800, 850],
        ]
        word_labels = [1, 2, 2, 5, 6, 7, 8, 8]
        # AutoProcessor resolves the checkpoint to LayoutLMv2TokenizerFast, while
        # LayoutXLM requires its own tokenizer for the XLM-R special token ids.
        # Build text/layout and visual inputs separately to preserve that pairing.
        encoded = tokenizer(
            [words],
            boxes=[boxes],
            word_labels=[word_labels],
            truncation=True,
            padding="max_length",
            max_length=sequence_length,
            return_tensors="pt",
        )
        visual = processor.image_processor(images=image, return_tensors="pt")
        for key, value in visual.items():
            encoded[key] = value
        encoded = {key: value.to(device) if torch.is_tensor(value) else value for key, value in encoded.items()}
        result["processor_keys"] = sorted(encoded)
        result["model_forward_parameters"] = sorted(inspect.signature(model.forward).parameters)

        largest_pass: int | None = None
        batch_one: dict[str, Any] | None = None
        for batch_size in batch_sizes:
            trial: dict[str, Any] = {"batch_size": batch_size, "status": "FAIL"}
            try:
                model.train()
                model.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats(device)
                batch = repeat_batch(encoded, batch_size, torch)
                inputs = accepted_model_inputs(model, batch)
                if batch_size == 1:
                    batch_one = inputs
                torch.cuda.synchronize(device)
                started = time.perf_counter()
                with ResourceMonitor() as monitor:
                    with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                        outputs = model(**inputs)
                        loss = outputs.loss
                    if loss is None or not math.isfinite(float(loss.detach().cpu())):
                        raise RuntimeError("LayoutXLM loss is missing or non-finite")
                    loss.backward()
                    torch.cuda.synchronize(device)
                trial.update({
                    "status": "PASS",
                    "loss": float(loss.detach().cpu()),
                    "forward_backward_seconds": time.perf_counter() - started,
                    "peak_torch_allocated_bytes": torch.cuda.max_memory_allocated(device),
                    "peak_torch_reserved_bytes": torch.cuda.max_memory_reserved(device),
                    "peak_process_rss_bytes": monitor.peak_process_rss_bytes,
                    "peak_gpu_used_mib": monitor.peak_gpu_used_mib,
                })
                largest_pass = batch_size
            except torch.cuda.OutOfMemoryError as error:
                trial["error_type"] = type(error).__name__
                trial["error"] = str(error)
                model.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
            result["batch_trials"].append(trial)
            if trial["status"] != "PASS":
                break

        if largest_pass is None or batch_one is None:
            raise RuntimeError("No physical batch completed forward/backward")
        result["largest_tested_physical_batch"] = largest_pass

        model.eval()
        with torch.inference_mode():
            reference_logits = model(**batch_one).logits.detach().float().cpu()
        save_started = time.perf_counter()
        model.save_pretrained(saved_model, safe_serialization=True)
        tokenizer.save_pretrained(saved_model)
        processor.save_pretrained(saved_model)
        result["save_seconds"] = time.perf_counter() - save_started
        del model
        torch.cuda.empty_cache()

        reload_started = time.perf_counter()
        reloaded = AutoModelForTokenClassification.from_pretrained(saved_model).to(device).eval()
        with torch.inference_mode():
            reloaded_logits = reloaded(**batch_one).logits.detach().float().cpu()
        result["reload_seconds"] = time.perf_counter() - reload_started
        max_abs_difference = float((reference_logits - reloaded_logits).abs().max())
        atol = float(os.environ.get("T05_RELOAD_ATOL", "0.0001"))
        rtol = float(os.environ.get("T05_RELOAD_RTOL", "0.0001"))
        reload_close = bool(torch.allclose(reference_logits, reloaded_logits, atol=atol, rtol=rtol))
        result["reload_parity"] = {
            "pass": reload_close,
            "max_abs_difference": max_abs_difference,
            "atol": atol,
            "rtol": rtol,
        }
        result["saved_model_files"] = {
            path.relative_to(saved_model).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(saved_model.rglob("*"))
            if path.is_file()
        }
        if not reload_close:
            raise RuntimeError("Saved/reloaded logits exceeded the configured tolerance")
        result["status"] = "PASS"
    except Exception as error:
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
