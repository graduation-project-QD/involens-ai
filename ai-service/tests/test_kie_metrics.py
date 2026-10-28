from __future__ import annotations

import unittest

from invoice_ai.kie.kie_metrics import entities, entity_scores, merge_windows


class KieMetricsTests(unittest.TestCase):
    def test_entities_split_adjacent_items_and_accept_dangling_inside(self):
        tags = ["B-ITEM_NAME", "I-ITEM_NAME", "B-ITEM_NAME", "O", "I-TOTAL_COST", "B-QUANTITY"]
        self.assertEqual(entities(tags), {("ITEM_NAME", 0, 2), ("ITEM_NAME", 2, 3), ("TOTAL_COST", 4, 5), ("QUANTITY", 5, 6)})

    def test_scores_are_exact_span_matches_and_ignore_words_do_not_count(self):
        gold = ["B-SELLER", "I-SELLER", "O", "B-TOTAL_COST", "IGNORE"]
        predicted = ["B-SELLER", "O", "O", "B-TOTAL_COST", "B-ADDRESS"]  # seller cut short; noise on IGNORE word
        scores = entity_scores([(gold, predicted)])
        self.assertEqual(scores["SELLER"]["f1"], 0.0)
        self.assertEqual(scores["TOTAL_COST"]["f1"], 1.0)
        self.assertNotIn("ADDRESS", scores)
        self.assertEqual((scores["micro"]["precision"], scores["micro"]["recall"]), (0.5, 0.5))

    def test_merge_windows_prefers_the_window_where_the_word_is_central(self):
        windows = [
            {"word_range": [0, 10], "values": {w: "first" for w in range(10)}},
            {"word_range": [6, 16], "values": {w: "second" for w in range(6, 16)}},
        ]
        merged = merge_windows(windows)
        self.assertEqual((merged[5], merged[7], merged[9], merged[12]), ("first", "first", "second", "second"))
        self.assertEqual(len(merged), 16)


if __name__ == "__main__":
    unittest.main()
