#!/usr/bin/env python3
"""PaddlePaddle/PaddleOCR smoke test on one accepted MC-OCR fixture."""

from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from resource_monitor import ResourceMonitor


def jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def result_payload(value: Any) -> Any:
    candidate = getattr(value, "json", value)
    if callable(candidate):
        candidate = candidate()
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return jsonable(candidate)


def collect_key(payload: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(payload, dict):
        for current_key, value in payload.items():
            if current_key == key and isinstance(value, list):
                found.extend(value)
            found.extend(collect_key(value, key))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(collect_key(value, key))
    return found


def parse_legacy(payload: Any) -> tuple[list[str], list[float], list[Any]]:
    texts: list[str] = []
    scores: list[float] = []
    polygons: list[Any] = []
    pages = payload if isinstance(payload, list) else []
    for page in pages:
        if not isinstance(page, list):
            continue
        for line in page:
            if not isinstance(line, list) or len(line) != 2:
                continue
            box, recognition = line
            if isinstance(recognition, (list, tuple)) and len(recognition) >= 2:
                texts.append(str(recognition[0]))
                scores.append(float(recognition[1]))
                polygons.append(box)
    return texts, scores, polygons


def main() -> int:
    output = Path(os.environ.get("T05_OUTPUT_DIR", "outputs"))
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "paddleocr_smoke.json"
    result: dict[str, Any] = {"schema_version": "t05_paddleocr_smoke_v1", "status": "FAIL"}
    try:
        import paddle
        import torch
        from paddleocr import PaddleOCR

        paddle_device = os.environ.get("PADDLE_DEVICE", "gpu:0")
        if paddle_device.startswith("gpu") and not paddle.device.is_compiled_with_cuda():
            raise RuntimeError("PaddlePaddle is not compiled with CUDA")
        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch CUDA became unavailable in the shared environment")
        paddle.set_device(paddle_device)
        torch_probe = torch.ones(1, device="cuda")
        paddle_probe = paddle.ones([1], dtype="float32")
        result["shared_environment"] = {
            "torch_version": torch.__version__,
            "torch_cuda_build": torch.version.cuda,
            "paddle_version": paddle.__version__,
            "paddle_device": str(paddle_probe.place),
            "paddle_execution_device": paddle_device,
            "torch_probe": float(torch_probe.cpu()),
            "paddle_probe": float(paddle_probe.numpy()[0]),
        }
        del torch_probe, paddle_probe

        image_path = Path(os.environ["T05_FIXTURE_IMAGE"])
        started = time.perf_counter()
        with ResourceMonitor() as monitor:
            api_variant = "paddleocr_3_predict"
            try:
                engine = PaddleOCR(
                    lang="vi",
                    device=paddle_device,
                    enable_mkldnn=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
                raw_results = list(engine.predict(input=str(image_path)))
            except TypeError:
                api_variant = "paddleocr_legacy_ocr"
                engine = PaddleOCR(
                    lang="vi",
                    use_angle_cls=False,
                    use_gpu=paddle_device.startswith("gpu"),
                    show_log=True,
                )
                raw_results = engine.ocr(str(image_path), cls=False)
        elapsed = time.perf_counter() - started
        payloads = [result_payload(item) for item in raw_results]
        texts = [str(item) for payload in payloads for item in collect_key(payload, "rec_texts")]
        scores = [float(item) for payload in payloads for item in collect_key(payload, "rec_scores")]
        polygons = [item for payload in payloads for item in collect_key(payload, "dt_polys")]
        if not polygons:
            polygons = [item for payload in payloads for item in collect_key(payload, "rec_polys")]
        if not texts:
            texts, scores, polygons = parse_legacy(payloads)
        non_empty = [text for text in texts if text.strip()]
        if not non_empty:
            raise RuntimeError("PaddleOCR returned no non-empty recognized text")
        if not scores:
            raise RuntimeError("PaddleOCR returned no recognition scores")
        if scores and any(not math.isfinite(score) or score < 0 or score > 1 for score in scores):
            raise RuntimeError("PaddleOCR returned a non-finite or out-of-range recognition score")
        if not polygons:
            raise RuntimeError("PaddleOCR returned no detection polygons")
        result.update({
            "status": "PASS",
            "api_variant": api_variant,
            "elapsed_seconds_including_load": elapsed,
            "recognized_text_count": len(non_empty),
            "score_count": len(scores),
            "polygon_count": len(polygons),
            "sample_texts": non_empty[:20],
            "sample_scores": scores[:20],
            "peak_process_rss_bytes": monitor.peak_process_rss_bytes,
            "peak_gpu_used_mib": monitor.peak_gpu_used_mib,
        })
    except Exception as error:
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
