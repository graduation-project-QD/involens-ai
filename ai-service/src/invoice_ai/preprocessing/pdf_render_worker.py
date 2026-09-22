"""Isolated PDFium worker used by T09 so rendering has a hard timeout."""

from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image


def _write_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"status": "ERROR", "error": {"code": code, "message": message, "details": details}}


def _to_rgb(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (*background, 255))
        return Image.alpha_composite(base, rgba).convert("RGB")
    return image.convert("RGB")


def _peak_rss_bytes() -> int | None:
    """Return process peak RSS using only the standard library."""
    if os.name == "nt":
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
        return None
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, OSError, ValueError):
        return None


def render(
    input_path: Path,
    output_path: Path,
    *,
    dpi: int,
    max_pixels: int,
    required_page_count: int,
    background: tuple[int, int, int],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_raw
        from pypdfium2._helpers.misc import PdfiumError
    except (ImportError, ModuleNotFoundError) as error:
        return _error("PDF_RENDERER_UNAVAILABLE", "The locked PDF renderer is not installed", error=str(error))

    renderer_version = importlib.metadata.version("pypdfium2")
    try:
        document = pdfium.PdfDocument(input_path)
    except PdfiumError as error:
        if error.err_code == pdfium_raw.FPDF_ERR_PASSWORD:
            return _error("PDF_ENCRYPTED", "Encrypted or password-protected PDFs are not accepted")
        return _error("PDF_DECODE_ERROR", "PDF structure cannot be decoded", pdfium_error_code=error.err_code)
    except Exception as error:
        return _error("PDF_DECODE_ERROR", "PDF structure cannot be decoded", error_type=type(error).__name__)

    try:
        page_count = len(document)
        security_revision = int(pdfium_raw.FPDF_GetSecurityHandlerRevision(document.raw))
        if security_revision >= 0:
            return _error(
                "PDF_ENCRYPTED",
                "Encrypted or password-protected PDFs are not accepted",
                security_handler_revision=security_revision,
            )
        if page_count != required_page_count:
            return _error(
                "PDF_PAGE_COUNT_UNSUPPORTED",
                "PDF must contain exactly one page",
                page_count=page_count,
                required_page_count=required_page_count,
            )
        page = document[0]
        try:
            width_points, height_points = (float(value) for value in page.get_size())
            if not all(math.isfinite(value) and value > 0 for value in (width_points, height_points)):
                return _error("PDF_INVALID_PAGE_GEOMETRY", "PDF page dimensions are invalid")
            scale = dpi / 72.0
            predicted_width = max(1, math.ceil(width_points * scale))
            predicted_height = max(1, math.ceil(height_points * scale))
            predicted_pixels = predicted_width * predicted_height
            if predicted_pixels > max_pixels:
                return _error(
                    "PIXEL_LIMIT_EXCEEDED",
                    "Rendered PDF page would exceed the v1 pixel limit",
                    predicted_size=[predicted_width, predicted_height],
                    predicted_pixels=predicted_pixels,
                    max_pixels=max_pixels,
                )
            bitmap = page.render(scale=scale, rotation=0)
            try:
                image = _to_rgb(bitmap.to_pil().copy(), background)
            finally:
                bitmap.close()
            rendered_pixels = image.width * image.height
            if rendered_pixels > max_pixels:
                return _error(
                    "PIXEL_LIMIT_EXCEEDED",
                    "Rendered PDF page exceeds the v1 pixel limit",
                    rendered_size=list(image.size),
                    rendered_pixels=rendered_pixels,
                    max_pixels=max_pixels,
                )
            image.save(output_path, format="PNG", optimize=False)
            return {
                "status": "PASS",
                "page_count": page_count,
                "page_size_points": [width_points, height_points],
                "rendered_size": list(image.size),
                "rendered_pixels": rendered_pixels,
                "dpi": dpi,
                "renderer": "pypdfium2",
                "renderer_version": renderer_version,
                "text_layer_used": False,
                "render_ms": round((time.perf_counter() - started) * 1000, 3),
                "peak_rss_bytes": _peak_rss_bytes(),
            }
        finally:
            page.close()
    except Exception as error:
        return _error("PDF_RENDER_ERROR", "PDF page rendering failed", error_type=type(error).__name__)
    finally:
        document.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--dpi", type=int, required=True)
    parser.add_argument("--max-pixels", type=int, required=True)
    parser.add_argument("--required-page-count", type=int, required=True)
    parser.add_argument("--background", type=int, nargs=3, required=True)
    args = parser.parse_args()
    try:
        payload = render(
            args.input,
            args.output,
            dpi=args.dpi,
            max_pixels=args.max_pixels,
            required_page_count=args.required_page_count,
            background=tuple(args.background),
        )
    except Exception as error:
        payload = _error("PDF_RENDER_ERROR", "PDF renderer failed unexpectedly", error_type=type(error).__name__)
    _write_metadata(args.metadata, payload)
    raise SystemExit(0 if payload["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
