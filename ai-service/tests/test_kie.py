from __future__ import annotations

import unittest
from pathlib import Path

from invoice_ai.kie.bio import (
    OcrLineInput,
    align_document,
    caption_prefix_length,
    char_width,
    match_key,
    oracle_document,
    split_line,
)
from invoice_ai.kie.build_bio import bio_is_valid
from invoice_ai.kie.data import LabeledDocument, Region
from invoice_ai.kie.geometry import order_rows, rotate_points, rotated_size
from invoice_ai.kie.grouping import (
    Entity,
    group_document,
    group_document_fields,
    group_line_items_anchored,
    looks_like_continuation,
)
from invoice_ai.kie.labels import BIO_LABELS, LABEL_TO_ID


def rect(x0: float, y0: float, x1: float, y1: float) -> tuple[tuple[float, float], ...]:
    return (x0, y0), (x1, y0), (x1, y1), (x0, y1)


def document(regions: list[tuple[str, str, tuple, int | None]], width: int = 400, height: int = 600, rotation: int = 0) -> LabeledDocument:
    return LabeledDocument(
        img_id="synthetic.jpg",
        split="train",
        image_path=Path("synthetic.jpg"),
        width=width,
        height=height,
        rotation_cw=rotation,
        regions=tuple(Region(i, label, text, poly, item) for i, (label, text, poly, item) in enumerate(regions)),
    )


def partition(groups) -> set[frozenset[int]]:
    return {frozenset(g.members) for g in groups}


class GeometryTests(unittest.TestCase):
    def test_clockwise_rotation_matches_labeler(self) -> None:
        self.assertEqual(rotated_size(100, 50, 90), (50, 100))
        (x, y), = rotate_points([(0, 0)], 100, 50, 90)
        self.assertAlmostEqual(x, 50)  # top-left corner goes to the top-right corner
        self.assertAlmostEqual(y, 0)
        self.assertEqual(rotate_points([(3, 4)], 100, 50, 0), ((3.0, 4.0),))

    def test_upright_image_warp_matches_point_rotation(self) -> None:
        import numpy as np

        from invoice_ai.datasets.build_upright import rotate_image

        image = np.full((370, 530, 3), 255, np.uint8)
        image[50:53, 100:103] = 0  # 3x3 block centred at (101.5, 51.5)
        for angle in (90, 180, 270, 7, 353):
            rotated, _ = rotate_image(image, angle)
            self.assertEqual((rotated.shape[1], rotated.shape[0]), rotated_size(530, 370, angle))
            darkness = 255.0 - rotated[..., 0]
            darkness[darkness < 30] = 0
            ys, xs = np.nonzero(darkness)
            weights = darkness[ys, xs]
            (x, y), = rotate_points([(101.5, 51.5)], 530, 370, angle)
            self.assertAlmostEqual(float(np.average(xs + 0.5, weights=weights)), x, delta=0.2)
            self.assertAlmostEqual(float(np.average(ys + 0.5, weights=weights)), y, delta=0.2)

    def test_rows_tolerate_small_offsets(self) -> None:
        boxes = [(200, 12, 260, 30), (10, 10, 80, 30), (10, 40, 80, 60)]
        self.assertEqual(order_rows(boxes), [[1, 0], [2]])


class BioTests(unittest.TestCase):
    def test_label_inventory(self) -> None:
        self.assertEqual(len(BIO_LABELS), 17)
        self.assertEqual(LABEL_TO_ID["O"], 0)

    def test_split_line_words_and_captions(self) -> None:
        words = split_line(OcrLineInput("Ngày:15/08/2020 10:41", rect(0, 0, 210, 10)))
        self.assertEqual([w for w, _ in words], ["Ngày:", "15/08/2020", "10:41"])
        first_quad = words[0][1]
        width = lambda text: sum(char_width(ch) for ch in text)
        self.assertAlmostEqual(first_quad[1][0], 210 * width("Ngày:") / width("Ngày:15/08/2020 10:41"))  # widths, not counts
        self.assertGreater(char_width("0"), char_width("a"))

    def test_text_check_keeps_first_item_word_after_barcode(self) -> None:
        # Barcode and item name share one detector box; the name region starts at "kem".
        doc = document([("ITEM_NAME", "kem tràng tiền sầu riêng", rect(130, 100, 400, 120), 0)])
        line = OcrLineInput("291010470000 kem tràng tiền sầu riêng", rect(0, 100, 400, 120))
        aligned = align_document(doc, [line], text_match=False, region_cover=2.0)
        tagged = [w.text for w in aligned.words if w.tag != "O"]
        aligned_text = align_document(doc, [line])
        self.assertEqual([(w.text, w.tag) for w in aligned_text.words][:3], [("291010470000", "O"), ("kem", "B-ITEM_NAME"), ("tràng", "I-ITEM_NAME")])
        self.assertEqual(aligned_text.regions[0].cer, 0.0)
        self.assertLessEqual(len(tagged), 5)

    def test_match_key_ignores_case_and_spaces_around_punctuation_only(self) -> None:
        self.assertEqual(match_key("P.Cẩm Bình, TP. Cẩm Phả"), match_key("p. cẩm bình,tp.cẩm phả"))
        self.assertNotEqual(match_key("Phan Huy Ích"), match_key("Phan Huyích"))  # merged words stay an error
        self.assertNotEqual(match_key("Thuỵ"), match_key("Thủy"))  # tone-mark placement is kept
        self.assertNotEqual(match_key("Cẩm Phả"), match_key("Cam Pha"))
        self.assertNotEqual(match_key("5,000"), match_key("5.000"))  # punctuation itself is kept

    def test_caption_prefix(self) -> None:
        self.assertEqual(caption_prefix_length(["ĐC:", "212", "Trần", "Phú"]), 1)
        self.assertEqual(caption_prefix_length(["Ngày", "bán:", "13/08/2020"]), 2)
        self.assertEqual(caption_prefix_length(["Ngày", "17", "tháng", "08"]), 0)
        self.assertEqual(caption_prefix_length(["Địa", "chỉ:"]), 0)  # nothing left after the caption

    def test_alignment_tags_each_gt_box_as_one_entity(self) -> None:
        doc = document(
            [
                ("ADDRESS", "ĐC: 12 Lê Lợi", rect(10, 10, 210, 30), None),
                ("ITEM_NAME", "Sữa chua", rect(10, 100, 150, 120), 1),
                ("QUANTITY", "1", rect(200, 100, 220, 120), 1),
                ("ITEM_NAME", "đam", rect(10, 125, 60, 145), 1),
            ]
        )
        ocr = [
            OcrLineInput("ĐC: 12 Lê Lợi", rect(10, 10, 210, 30)),
            OcrLineInput("Hotline 0909", rect(10, 50, 200, 70)),
            OcrLineInput("Sữa chua", rect(10, 100, 150, 120)),
            OcrLineInput("1", rect(200, 100, 220, 120)),
            OcrLineInput("đam", rect(10, 125, 60, 145)),
        ]
        aligned = align_document(doc, ocr)
        self.assertEqual(
            [(w.text, w.tag) for w in aligned.words],
            [
                ("ĐC:", "O"),
                ("12", "B-ADDRESS"),
                ("Lê", "I-ADDRESS"),
                ("Lợi", "I-ADDRESS"),
                ("Hotline", "O"),
                ("0909", "O"),
                ("Sữa", "B-ITEM_NAME"),
                ("chua", "I-ITEM_NAME"),
                ("1", "B-QUANTITY"),
                ("đam", "B-ITEM_NAME"),
            ],
        )
        self.assertEqual(aligned.words[-1].line_item_id, 1)
        self.assertTrue(all(r.matched for r in aligned.regions))
        self.assertEqual(aligned.regions[0].gt_text, "12 Lê Lợi")
        self.assertTrue(all(0 <= v <= 1000 for w in aligned.words for v in w.box))

    def test_partial_overlap_is_ignored_and_missing_region_reported(self) -> None:
        doc = document([("TOTAL_COST", "50.000", rect(100, 100, 160, 120), None), ("QUANTITY", "2", rect(10, 200, 20, 220), 1)])
        aligned = align_document(doc, [OcrLineInput("Tổng 50.000", rect(40, 100, 200, 120))])
        tags = {w.text: w.tag for w in aligned.words}
        self.assertEqual(tags["Tổng"], "O")
        self.assertIn(tags["50.000"], {"B-TOTAL_COST", "IGNORE"})
        self.assertFalse(aligned.regions[1].matched)

    def test_source_frame_ocr_is_rotated_to_upright(self) -> None:
        # Source 200x100 image whose text runs top-to-bottom; rotating 90° clockwise makes it upright.
        doc = document([("SELLER", "ABC", rect(40, 20, 60, 80), None)], width=200, height=100, rotation=90)
        aligned = align_document(doc, [OcrLineInput("ABC", ((60, 20), (60, 80), (40, 80), (40, 20)))], ocr_frame="source")
        self.assertEqual([w.tag for w in aligned.words], ["B-SELLER"])
        self.assertEqual((aligned.width, aligned.height), (100, 200))

    def test_stray_word_keeps_bio_valid(self) -> None:
        self.assertFalse(bio_is_valid(["O", "I-SELLER"]))
        self.assertTrue(bio_is_valid(["B-SELLER", "IGNORE", "I-SELLER"]))

    def test_small_region_takes_wide_free_word(self) -> None:
        # Detector box "| 10" is twice as wide as the GT quantity box: under 50% of the word is inside.
        doc = document([("QUANTITY", "10", rect(100, 100, 120, 120), 0), ("QUANTITY", "1", rect(100, 200, 110, 220), 1)])
        aligned = align_document(doc, [OcrLineInput("10", rect(85, 100, 122, 120)), OcrLineInput("VAT10%", rect(80, 200, 130, 220))])
        self.assertEqual([w.tag for w in aligned.words], ["B-QUANTITY", "IGNORE"])
        self.assertEqual([r.matched for r in aligned.regions], [True, False])  # "VAT10%" is too long for "1"

    def test_oracle_replaces_region_text(self) -> None:
        doc = document([("SELLER", "Nhà Sách", rect(10, 10, 110, 30), None)])
        aligned = align_document(doc, [OcrLineInput("Nha Sach", rect(10, 10, 110, 30)), OcrLineInput("Cảm ơn", rect(10, 60, 110, 80))])
        oracle = oracle_document(doc, aligned)
        self.assertEqual([(w.text, w.tag) for w in oracle.words], [("Nhà", "B-SELLER"), ("Sách", "I-SELLER"), ("Cảm", "O"), ("ơn", "O")])


class GroupingTests(unittest.TestCase):
    def test_document_fields_join_in_reading_order(self) -> None:
        entities = [
            Entity(0, "TIMESTAMP", "13:07", (300, 50, 360, 70)),
            Entity(1, "TIMESTAMP", "15/08/2020", (150, 50, 280, 70)),
            Entity(2, "ADDRESS", "TP. Cẩm Phả", (10, 40, 120, 55)),
            Entity(3, "ADDRESS", "Số 590 Trần Phú", (10, 20, 120, 35)),
        ]
        values, _ = group_document_fields(entities)
        self.assertEqual(values["TIMESTAMP"], "15/08/2020 13:07")
        self.assertEqual(values["ADDRESS"], "Số 590 Trần Phú TP. Cẩm Phả")
        self.assertIsNone(values["SELLER"])

    def test_inline_layout_with_wrapped_name(self) -> None:
        entities = [
            Entity(0, "ITEM_NAME", "Sữa chua nha", (10, 100, 150, 120)),
            Entity(1, "QUANTITY", "1", (200, 100, 210, 120)),
            Entity(2, "LINE_TOTAL", "30.000", (300, 100, 360, 120)),
            Entity(3, "ITEM_NAME", "đam", (10, 125, 50, 145)),
            Entity(4, "ITEM_NAME", "Sữa chua kiwi", (10, 150, 150, 170)),
            Entity(5, "QUANTITY", "1", (200, 150, 210, 170)),
            Entity(6, "LINE_TOTAL", "35.000", (300, 150, 360, 170)),
        ]
        groups, _ = group_line_items_anchored(entities)
        self.assertEqual(partition(groups), {frozenset({0, 1, 2, 3}), frozenset({4, 5, 6})})

    def test_stacked_layout_name_above_numbers(self) -> None:
        entities = []
        for k in range(3):
            y = 100 + 50 * k
            entities += [
                Entity(4 * k, "ITEM_NAME", f"Item {k}", (10, y, 200, y + 18)),
                Entity(4 * k + 1, "QUANTITY", "2", (60, y + 25, 70, y + 43)),
                Entity(4 * k + 2, "UNIT_PRICE", "5,000", (150, y + 25, 200, y + 43)),
                Entity(4 * k + 3, "LINE_TOTAL", "10,000", (300, y + 25, 360, y + 43)),
            ]
        groups, _ = group_line_items_anchored(entities)
        self.assertEqual(partition(groups), {frozenset(range(4 * k, 4 * k + 4)) for k in range(3)})

    def test_skewed_columns_are_aligned_by_order(self) -> None:
        # LINE_TOTAL drifts downwards by most of a row (perspective), names stay on their rows.
        entities = []
        for k in range(4):
            y = 100 + 40 * k
            entities += [
                Entity(3 * k, "ITEM_NAME", f"Item {k}", (10, y, 150, y + 18)),
                Entity(3 * k + 1, "QUANTITY", "1", (180, y + 6, 190, y + 24)),
                Entity(3 * k + 2, "LINE_TOTAL", "1,000", (300, y + 15, 360, y + 33)),
            ]
        groups, _ = group_line_items_anchored(entities)
        self.assertEqual(partition(groups), {frozenset(range(3 * k, 3 * k + 3)) for k in range(4)})

    def test_continuation_cue(self) -> None:
        self.assertTrue(looks_like_continuation("quất"))
        self.assertTrue(looks_like_continuation("(Vừa)"))
        self.assertFalse(looks_like_continuation("Sữa chua"))
        self.assertFalse(looks_like_continuation("75GR"))

    def test_group_document_outputs_items(self) -> None:
        entities = [
            Entity(0, "SELLER", "Cô Thỏ", (10, 10, 100, 30)),
            Entity(1, "ITEM_NAME", "Trà", (10, 100, 60, 120)),
            Entity(2, "LINE_TOTAL", "12,000", (300, 100, 360, 120)),
        ]
        result = group_document(entities)
        self.assertEqual(result.fields["SELLER"], "Cô Thỏ")
        self.assertEqual(result.line_items, [{"ITEM_NAME": "Trà", "QUANTITY": None, "UNIT_PRICE": None, "LINE_TOTAL": "12,000"}])


if __name__ == "__main__":
    unittest.main()
