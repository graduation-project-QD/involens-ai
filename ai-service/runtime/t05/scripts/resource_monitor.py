"""Small polling monitor used by the rented-GPU smoke scripts."""

from __future__ import annotations

import os
import subprocess
import threading
import time

import psutil


class ResourceMonitor:
    def __init__(self, interval_seconds: float = 0.1) -> None:
        self.interval_seconds = interval_seconds
        self.peak_process_rss_bytes = 0
        self.peak_gpu_used_mib: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def _poll(self) -> None:
        process = psutil.Process(os.getpid())
        while not self._stop.is_set():
            try:
                self.peak_process_rss_bytes = max(
                    self.peak_process_rss_bytes, process.memory_info().rss
                )
            except (psutil.Error, OSError):
                pass
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                values = [int(line.strip()) for line in result.stdout.splitlines() if line.strip()]
                if values:
                    current = max(values)
                    self.peak_gpu_used_mib = max(self.peak_gpu_used_mib or 0, current)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            self._stop.wait(self.interval_seconds)

    def __enter__(self) -> "ResourceMonitor":
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
