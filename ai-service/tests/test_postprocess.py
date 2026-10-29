from __future__ import annotations

import json
import unittest

from invoice_ai.kie.evaluate_e2e import comparison_key, pair_line_items
from invoice_ai.kie.postprocess import DocumentPrediction, FieldResult, collect_warnings, infer_quantity, postprocess_document
from invoice_ai.normalization.core import normalize_amount, normalize_quantity, normalize_timestamp


class AmountNormalizationTests(unittest.TestCase):
    def test_receipt_amount_formats(self):
        cases = {
            "79.500đ": "79500",
            "11.00O": "11000",  # OCR read the last 0 as O
            "36.600.00": "36600",  # cents written with the grouping separator
            "39,000.": "39000",
            "565,600.00": "565600",
            "39 000": "39000",
            "-1.000": "-1000",
            "1.250,00 VND": "1250",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_amount(raw, "line_total").normalized_value, expected)

    def test_two_numbers_stay_unresolved(self):
        result = normalize_amount("10.800 10.800", "total_cost")
        self.assertIsNone(result.normalized_value)
        self.assertEqual(result.field, "total_cost")


class QuantityNormalizationTests(unittest.TestCase):
    def test_decimal_quantities_drop_trailing_zeros(self):
        cases = {"1": "1", "1,00": "1", "0.670": "0.67", "10.000": "10", "24,000": "24", "0. 32": "0.32", "-1": "-1", "1O": "10"}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_quantity(raw).normalized_value, expected)

    def test_text_is_invalid(self):
        self.assertEqual(normalize_quantity("Phúc Anh").status, "invalid")


class TimestampNormalizationTests(unittest.TestCase):
    def test_date_and_time_layouts(self):
        cases = {
            "13/08/2020 17:39": "2020-08-13T17:39:00",
            "19:50:33 - 14/08/2020": "2020-08-14T19:50:33",
            "13 / 08 / 2020 - 22 : 00": "2020-08-13T22:00:00",
            "06.04.2019 12.16": "2019-04-06T12:16:00",
            "10/08/2020 (08:01 CH - 08:01 CH)": "2020-08-10T20:01:00",
            "31/1/2020 10:50:14AM": "2020-01-31T10:50:14",
            "Ngày 17 tháng 08 năm 2020": "2020-08-17T00:00:00",
            "2020-07-25 13:46:52": "2020-07-25T13:46:52",
            "8/14/2020": "2020-08-14T00:00:00",  # day-first impossible → month-first
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_timestamp(raw).normalized_value, expected)

    def test_first_of_two_timestamps_is_used(self):
        result = normalize_timestamp("04.10.2020 16.19 04.10.2020 16.21")
        self.assertEqual(result.normalized_value, "2020-10-04T16:19:00")
        self.assertIn("MULTIPLE_DATE_CANDIDATES", result.warnings)

    def test_missing_time_and_missing_date(self):
        self.assertIn("TIME_NOT_FOUND", normalize_timestamp("12-08-2020").warnings)
        self.assertEqual(normalize_timestamp("11:35:49").status, "invalid")


def item(quantity=None, unit_price=None, line_total=None) -> dict[str, FieldResult]:
    def cell(value):
        return FieldResult(value, value, 0.99, [[[0, 0], [1, 0], [1, 1], [0, 1]]] if value else [])

    return {"item_name": cell("Bút bi"), "quantity": cell(quantity), "unit_price": cell(unit_price), "line_total": cell(line_total)}


class QuantityInferenceTests(unittest.TestCase):
    def test_exact_division_is_inferred_with_evidence(self):
        inferred = infer_quantity(item(unit_price="4100", line_total="12300"))
        self.assertEqual(inferred.value, "3")
        self.assertTrue(inferred.inferred)
        self.assertEqual(len(inferred.evidence), 2)

    def test_weighed_goods_keep_three_decimals(self):
        self.assertEqual(infer_quantity(item(unit_price="48900", line_total="15745.8")).value, "0.322")

    def test_returned_goods_give_negative_quantity(self):
        self.assertEqual(infer_quantity(item(unit_price="25950", line_total="-25950")).value, "-1")

    def test_discounted_line_is_not_inferred(self):
        self.assertIsNone(infer_quantity(item(unit_price="9947", line_total="238008")))  # 23.928 × 9947 ≠ 238008

    def test_existing_or_incomplete_values_are_left_alone(self):
        self.assertIsNone(infer_quantity(item(quantity="2", unit_price="4000", line_total="8000")))
        self.assertIsNone(infer_quantity(item(line_total="8000")))


class WarningTests(unittest.TestCase):
    def test_absent_values_and_inferred_quantity_are_warned(self):
        fields = {"seller": FieldResult("A", "A", 1.0, [[[0, 0]]]), "timestamp": FieldResult(None, None, None)}
        inferred = item(unit_price="4000", line_total="8000")
        inferred["quantity"] = infer_quantity(inferred)
        warnings = collect_warnings(fields, [inferred, item(quantity="1", line_total="5000")])
        self.assertEqual(warnings, [
            {"code": "FIELD_ABSENT", "target": "fields.timestamp"},
            {"code": "QUANTITY_INFERRED", "target": "line_items[1].quantity"},
            {"code": "FIELD_ABSENT", "target": "line_items[2].unit_price"},
        ])


def receipt(tags: list[str]) -> DocumentPrediction:
    words = ["NHÀ", "SÁCH", "Bút", "bi", "4.000", "8.000đ", "Tổng:", "8.000đ"]
    boxes = [[100, 50, 200, 80], [210, 50, 300, 80], [100, 300, 150, 330], [155, 300, 190, 330],
             [500, 300, 600, 330], [800, 300, 900, 330], [100, 600, 200, 630], [800, 600, 900, 630]]
    return DocumentPrediction("receipt.jpg", words, boxes, [0, 0, 1, 1, 1, 1, 2, 2], tags, [0.99] * len(words), 500, 1000)


class PostprocessDocumentTests(unittest.TestCase):
    TAGS = ["B-SELLER", "I-SELLER", "B-ITEM_NAME", "I-ITEM_NAME", "B-UNIT_PRICE", "B-LINE_TOTAL", "O", "B-TOTAL_COST"]

    def test_backend_contract(self):
        result = postprocess_document(receipt(self.TAGS))
        message = result.to_contract("00000000-0000-0000-0000-000000000000")
        data = message["data"]
        self.assertEqual(data["fields"]["seller"]["value"], "NHÀ SÁCH")
        self.assertEqual(data["fields"]["total_cost"]["value"], "8000")
        self.assertEqual(data["fields"]["timestamp"]["status"], "absent")
        self.assertEqual(data["fields"]["timestamp"]["evidence"], [])
        line = data["line_items"][0]
        self.assertEqual((line["index"], line["item_name"]["value"], line["quantity"]["value"]), (1, "Bút bi", "2"))
        self.assertEqual(line["unit_price"]["evidence"][0]["polygon"], [[250, 300], [300, 300], [300, 330], [250, 330]])
        # needs_review is true exactly when warnings exist (backend contract)
        self.assertTrue(data["needs_review"])
        self.assertEqual({w["code"] for w in data["warnings"]}, {"FIELD_ABSENT", "QUANTITY_INFERRED"})
        json.dumps(message, ensure_ascii=False, allow_nan=False)

    def test_raw_mode_keeps_ocr_text(self):
        result = postprocess_document(receipt(self.TAGS), normalize=False, infer=False)
        self.assertEqual(result.fields["total_cost"].value, "8.000đ")
        self.assertIsNone(result.line_items[0]["quantity"].value)


class EvaluationHelperTests(unittest.TestCase):
    def test_comparison_key_ignores_case_and_punctuation_spacing_for_text_only(self):
        self.assertEqual(comparison_key("address", "P. Cẩm Thủy", "b11"), comparison_key("address", "p.cẩm thủy", "b11"))
        self.assertNotEqual(comparison_key("total_cost", "8000", "b11"), comparison_key("total_cost", "8.000", "b11"))

    def test_line_items_pair_by_shared_cells(self):
        gt = [{"item_name": "a", "quantity": "1", "unit_price": "5", "line_total": "5"},
              {"item_name": "b", "quantity": "2", "unit_price": "3", "line_total": "6"}]
        pred = [{"item_name": "b", "quantity": None, "unit_price": "3", "line_total": "6"},
                {"item_name": "x", "quantity": "9", "unit_price": "9", "line_total": "9"}]
        self.assertEqual(pair_line_items(gt, pred), [(0, None), (1, 0), (None, 1)])


if __name__ == "__main__":
    unittest.main()
