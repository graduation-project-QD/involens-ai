#!/usr/bin/env python3
"""Collect a bounded, non-secret hardware and runtime inventory."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def command(args: list[str]) -> dict[str, Any]:
    executable = shutil.which(args[0])
    if executable is None:
        return {"command": args, "status": "NOT_FOUND", "stdout": "", "stderr": ""}
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=30)
    return {
        "command": args,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def main() -> None:
    output = Path(os.environ.get("T05_OUTPUT_DIR", "outputs"))
    output.mkdir(parents=True, exist_ok=True)
    inventory = {
        "schema_version": "t05_hardware_inventory_v1",
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "python_executable": sys.executable,
        },
        "commands": {
            "os_release": command(["cat", "/etc/os-release"]),
            "uname": command(["uname", "-a"]),
            "lscpu": command(["lscpu"]),
            "memory": command(["free", "-b"]),
            "disk": command(["df", "-B1", "."]),
            "nvidia_smi": command(["nvidia-smi"]),
            "gpu_query": command([
                "nvidia-smi",
                "--query-gpu=name,uuid,driver_version,memory.total,compute_cap",
                "--format=csv,noheader,nounits",
            ]),
            "nvcc": command(["nvcc", "--version"]),
        },
        "packages": {
            name: package_version(name)
            for name in (
                "torch", "torchvision", "transformers", "accelerate", "detectron2",
                "paddlepaddle-gpu", "paddlepaddle", "paddleocr", "Pillow", "numpy",
            )
        },
    }
    path = output / "hardware_inventory.json"
    path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(inventory, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
