from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from invoice_ai.evaluation import (
    EVALUATOR_VERSION,
    EntityDocument,
    EntitySpan,
    EvaluationDocument,
    FieldGroundTruth,
    FieldPrediction,
    evaluate_entities,
    evaluate_fields,
    metrics_table_rows,
    write_metrics_csv,
)


def load_fixture() -> dict:
    path = Path(__file__).parent / "fixtures" / "evaluation_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def field_documents(fixture: dict) -> list[EvaluationDocument]:
    return [
        EvaluationDocument(
            document_id=item["document_id"],
            ground_truth={key: FieldGroundTruth(**value) for key, value in item["ground_truth"].items()},
            prediction={key: FieldPrediction(**value) for key, value in item["prediction"].items()},
        )
        for item in fixture["field_documents"]
    ]


def entity_documents(fixture: dict) -> list[EntityDocument]:
    return [
        EntityDocument(
            document_id=item["document_id"],
            ground_truth=[EntitySpan(**span) for span in item["ground_truth"]],
            prediction=[EntitySpan(**span) for span in item["prediction"]],
            evaluable_fields=frozenset(item["evaluable_fields"]),
        )
        for item in fixture["entity_documents"]
    ]


class FieldEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = load_fixture()
        cls.documents = field_documents(cls.fixture)

    def assert_expected_subset(self, actual: dict, expected: dict) -> None:
        for key, value in expected.items():
            self.assertEqual(actual[key], value, key)

    def test_raw_expected_counts_and_document_em(self) -> None:
        report = evaluate_fields(self.documents, "raw", {"split": "fixture"})
        expected = self.fixture["expected"]["raw"]
        self.assertEqual(report["evaluator_version"], EVALUATOR_VERSION)
        self.assert_expected_subset(report["micro"], expected["micro"])
        self.assert_expected_subset(report["document_exact_match"], expected["document_exact_match"])
        for field_name in ("company", "address", "date", "total"):
            self.assert_expected_subset(report["fields"][field_name], expected[field_name])
        self.assertAlmostEqual(report["micro"]["precision"], 9 / 13)
        self.assertAlmostEqual(report["micro"]["recall"], 9 / 13)
        self.assertAlmostEqual(report["micro"]["slot_exact_match"], 14 / 19)

    def test_normalized_masks_unresolved_gt_and_uses_independent_values(self) -> None:
        report = evaluate_fields(self.documents, "normalized")
        expected = self.fixture["expected"]["normalized"]
        self.assert_expected_subset(report["micro"], expected["micro"])
        self.assert_expected_subset(report["document_exact_match"], expected["document_exact_match"])
        self.assert_expected_subset(report["fields"]["date"], expected["date"])
        self.assertAlmostEqual(report["micro"]["f1"], 0.75)

    def test_missing_annotation_is_masked_not_absent(self) -> None:
        report = evaluate_fields(self.documents, "raw")
        company = report["fields"]["company"]
        self.assertEqual(company["masked_slots"], 1)
        self.assertEqual(company["fp"], 0)

    def test_zero_denominator_is_null(self) -> None:
        empty = EvaluationDocument(
            "empty",
            {field: FieldGroundTruth("absent", None) for field in ("company", "address", "date", "total")},
            {field: FieldPrediction() for field in ("company", "address", "date", "total")},
        )
        report = evaluate_fields([empty], "raw")
        self.assertIsNone(report["fields"]["company"]["precision"])
        self.assertIsNone(report["fields"]["company"]["recall"])
        self.assertIsNone(report["fields"]["company"]["f1"])
        json.dumps(report, allow_nan=False)

    def test_contract_requires_exactly_four_field_slots(self) -> None:
        document = self.documents[0]
        broken = EvaluationDocument(
            document.document_id,
            {key: value for key, value in document.ground_truth.items() if key != "total"},
            document.prediction,
        )
        with self.assertRaises(ValueError):
            evaluate_fields([broken])


class EntityEvaluationTests(unittest.TestCase):
    def test_exact_boundary_counts_wrong_boundary_as_fp_and_fn(self) -> None:
        fixture = load_fixture()
        report = evaluate_entities(entity_documents(fixture))
        expected = fixture["expected"]["entity"]
        for key, value in expected["micro"].items():
            self.assertEqual(report["micro"][key], value)
        for field_name in ("company", "address", "date", "total"):
            for key, value in expected[field_name].items():
                self.assertEqual(report["fields"][field_name][key], value)
        self.assertAlmostEqual(report["micro"]["f1"], 0.6)
        self.assertAlmostEqual(report["macro"]["f1"], 7 / 12)

    def test_invalid_boundary_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EntitySpan("company", 2, 2)


class MetricsExporterTests(unittest.TestCase):
    def test_csv_export_is_deterministic_and_has_no_nan(self) -> None:
        report = evaluate_fields(field_documents(load_fixture()), "raw")
        rows = metrics_table_rows(report, "field_raw")
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "first.csv"
            second = Path(temporary_directory) / "second.csv"
            write_metrics_csv(rows, first)
            write_metrics_csv(rows, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with first.open(encoding="utf-8") as stream:
                parsed = list(csv.DictReader(stream))
            self.assertEqual(len(parsed), 7)
            self.assertNotIn("nan", first.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
