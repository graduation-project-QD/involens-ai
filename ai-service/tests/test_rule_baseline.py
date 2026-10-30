from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from invoice_ai.kie.rule_baseline import (
    Tagger,
    assign_numbers,
    build_lines,
    fold,
    is_barcode,
    is_money_like,
    predict,
    tag_document,
    tag_timestamp,
)


def receipt() -> tuple[list[str], list[list[int]], list[int]]:
    """A small receipt: seller, address, timestamp, table header, two items, totals and cash lines."""
    rows = [
        (["NHÀ", "SÁCH", "GD-TC"], 300, 100, 30),
        (["ĐC:", "212", "Đường", "Trần", "Phú"], 200, 140, 20),
        (["ĐT", "0333863328"], 200, 170, 20),
        (["Thời", "gian:", "14:14:53", "-", "14/08/2020"], 200, 200, 20),
        (["Tên", "hàng", "SL", "Giá", "Thành", "tiền"], 200, 240, 20),
        (["Bút", "bi", "2", "4.000", "0", "8.000đ"], 200, 280, 20),
        (["Vở", "kẻ", "ngang", "1", "12.500", "0", "12.500đ"], 200, 320, 20),
        (["Tổng", "cộng", "3", "20.500đ"], 200, 360, 20),
        (["Tổng", "số", "thanh", "toán:", "20.500đ"], 200, 400, 20),
        (["Tiền", "khách", "đưa", "50.000đ"], 200, 440, 20),
    ]
    words, boxes, line_index = [], [], []
    for line, (tokens, x, y, height) in enumerate(rows):
        for position, token in enumerate(tokens):
            words.append(token)
            boxes.append([x + 70 * position, y, x + 70 * position + 60, y + height])
            line_index.append(line)
    return words, boxes, line_index


class PredicateTests(unittest.TestCase):
    def test_fold_removes_accents(self):
        self.assertEqual(fold("Tổng THANH TOÁN Đ"), "tong thanh toan d")

    def test_money_like_excludes_quantities_weights_phones(self):
        for word, expected in {"12.500đ": True, "25000": True, "40,599.00": True, "2": False, "0,498": False,
                               "0942787568": False, "1,00": False}.items():
            with self.subTest(word=word):
                self.assertEqual(is_money_like(word), expected)

    def test_barcode_with_ocr_letters(self):
        self.assertTrue(is_barcode("ODOOOOO2950156"))
        self.assertTrue(is_barcode("8935015716702"))
        self.assertFalse(is_barcode("12.500"))


class NumberRoleTests(unittest.TestCase):
    def test_product_check_assigns_quantity_and_price_and_skips_discount_zero(self):
        words = ["2", "10.500", "0", "21.000đ"]
        self.assertEqual(assign_numbers([0, 1, 2, 3], words), {3: "LINE_TOTAL", 0: "QUANTITY", 1: "UNIT_PRICE"})

    def test_row_without_money_gets_no_roles(self):
        self.assertEqual(assign_numbers([0], ["3"]), {})


class TimestampTests(unittest.TestCase):
    def test_date_and_time_split_into_words(self):
        words = ["Ngày:", "13", "/", "08", "/", "2020", "-", "22", ":", "00"]
        boxes = [[i * 50, 0, i * 50 + 40, 20] for i in range(len(words))]
        tagger = Tagger(len(words))
        tag_timestamp(build_lines(words, boxes, [0] * len(words)), words, tagger)
        self.assertEqual(tagger.tags, ["O", "B-TIMESTAMP"] + ["I-TIMESTAMP"] * 8)


class DocumentTests(unittest.TestCase):
    def test_receipt_fields_and_items(self):
        words, boxes, line_index = receipt()
        tagged = {}
        for word, tag in zip(words, tag_document(words, boxes, line_index)):
            tagged.setdefault(tag[2:] if tag != "O" else "O", []).append(word)
        self.assertEqual(tagged["SELLER"], ["NHÀ", "SÁCH", "GD-TC"])
        self.assertEqual(tagged["ADDRESS"], ["212", "Đường", "Trần", "Phú"])  # "ĐC:" label excluded
        self.assertEqual(tagged["TIMESTAMP"], ["14:14:53", "-", "14/08/2020"])
        self.assertEqual(tagged["TOTAL_COST"], ["20.500đ"])
        self.assertEqual(tagged["ITEM_NAME"], ["Bút", "bi", "Vở", "kẻ", "ngang"])
        self.assertEqual(tagged["QUANTITY"], ["2", "1"])
        self.assertEqual(tagged["UNIT_PRICE"], ["4.000", "12.500"])
        self.assertEqual(tagged["LINE_TOTAL"], ["8.000đ", "12.500đ"])
        self.assertNotIn("0333863328", tagged.get("SELLER", []) + tagged.get("ADDRESS", []))

    def test_predict_writes_layoutxlm_format(self):
        words, boxes, line_index = receipt()
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "val.ocr.jsonl", Path(tmp) / "pred.jsonl"
            record = {"img_id": "a.jpg", "words": words, "boxes": boxes, "line_index": line_index, "tags": ["O"] * len(words)}
            source.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(predict(source, target), 1)
            output = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(set(output), {"img_id", "gold", "pred", "score"})
        self.assertEqual(len(output["pred"]), len(words))
        self.assertIsNone(output["score"])


if __name__ == "__main__":
    unittest.main()
