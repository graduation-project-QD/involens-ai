from __future__ import annotations

import json
import unittest
from pathlib import Path

from invoice_ai.normalization import NORMALIZATION_VERSION, normalize_field, normalize_fields


class NormalizationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "normalization_v1.json"
        cls.fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_all_independent_fixtures(self) -> None:
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                result = normalize_field(fixture["field"], fixture["raw"], fixture["locale"])
                self.assertEqual(result.raw_value, fixture["raw"])
                self.assertEqual(result.normalized_value, fixture["normalized"])
                self.assertEqual(result.status, fixture["status"])
                self.assertEqual(result.warnings, fixture["warnings"])
                self.assertEqual(result.normalizer_version, NORMALIZATION_VERSION)
                json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False)

    def test_normalize_fields_requires_exact_contract_slots(self) -> None:
        values = {"company": "A", "address": "B", "date": "01/01/2026", "total": "1.000 đ"}
        results = normalize_fields(values)
        self.assertEqual(tuple(results), ("company", "address", "date", "total"))
        with self.assertRaises(ValueError):
            normalize_fields({"company": "A", "address": "B", "date": "01/01/2026"})
        with self.assertRaises(ValueError):
            normalize_fields({**values, "subtotal": "500"})

    def test_total_is_never_float(self) -> None:
        for raw in ("125.000 đ", "1.250,00 VND", "0", "-1.000 đ"):
            result = normalize_field("total", raw)
            self.assertTrue(result.normalized_value is None or isinstance(result.normalized_value, str))


if __name__ == "__main__":
    unittest.main()
