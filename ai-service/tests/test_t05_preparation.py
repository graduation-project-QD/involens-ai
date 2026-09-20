from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "runtime" / "t05"


def load_preflight_module():
    path = ROOT / "scripts" / "preflight.py"
    spec = importlib.util.spec_from_file_location("t05_preflight", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load T05 preflight module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class T05PreparationTests(unittest.TestCase):
    def test_preflight_passes_without_gpu_execution(self) -> None:
        report = load_preflight_module().run(ROOT)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertFalse(report["checks"]["gpu_execution_performed"])
        self.assertFalse(report["checks"]["full_dataset_in_bundle"])
        self.assertTrue(report["checks"]["layoutxlm_model_unchanged"])

    def test_fixture_is_from_frozen_validation_and_not_quarantine(self) -> None:
        provenance = json.loads(
            (ROOT / "fixtures" / "sample_invoice.provenance.json").read_text(encoding="utf-8")
        )
        digest = hashlib.sha256((ROOT / "fixtures" / "sample_invoice.jpg").read_bytes()).hexdigest()
        self.assertEqual(digest, provenance["sha256"])
        self.assertEqual(provenance["split"], "validation")
        self.assertFalse(provenance["quarantine"])

    def test_bundle_build_is_deterministic_and_dataset_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "first.zip"
            second = Path(temporary_directory) / "second.zip"
            command = [sys.executable, str(ROOT / "build_bundle.py"), "--output"]
            subprocess.run(command + [str(first)], check=True, capture_output=True, text=True)
            subprocess.run(command + [str(second)], check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertLess(first.stat().st_size, 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
