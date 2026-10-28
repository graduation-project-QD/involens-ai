from __future__ import annotations

import unittest

from invoice_ai.kie.labels import IGNORE_INDEX, LABEL_TO_ID
from invoice_ai.kie.tokenize_layoutxlm import check_sample, encode_document, plan_windows


class _Encoding(dict):
    def __init__(self, ids, bbox, word_ids):
        super().__init__(input_ids=ids, bbox=bbox)
        self._word_ids = word_ids

    def word_ids(self):
        return self._word_ids


class StubTokenizer:
    """SentencePiece-like: a word splits into a bare "▁" plus 2-char pieces when it starts with a capital."""

    def tokenize(self, word):
        pieces = [word[i : i + 2] for i in range(0, len(word), 2)]
        return ["▁"] + pieces if word[:1].isupper() else ["▁" + pieces[0]] + pieces[1:]

    def __call__(self, words, boxes, truncation=True, max_length=512):
        ids, bbox, word_ids = [0], [[0, 0, 0, 0]], [None]
        for index, (word, box) in enumerate(zip(words, boxes)):
            for _ in self.tokenize(word):
                ids.append(1)
                bbox.append(list(box))
                word_ids.append(index)
        ids.append(2)
        bbox.append([1000, 1000, 1000, 1000])
        word_ids.append(None)
        return _Encoding(ids[:max_length], bbox[:max_length], word_ids[:max_length])


class TokenizeTests(unittest.TestCase):
    def test_windows_cover_all_words_with_overlap(self):
        windows = plan_windows([3] * 10, max_tokens=12, overlap=6)
        self.assertEqual(windows[0], (0, 4))
        self.assertEqual(windows[1][0], 2)  # two words (6 tokens) of shared context
        covered = {w for start, end in windows for w in range(start, end)}
        self.assertEqual(covered, set(range(10)))
        self.assertEqual(plan_windows([3] * 4, 12, 6), [(0, 4)])
        self.assertEqual(plan_windows([20, 1], 12, 6), [(0, 1), (1, 2)])  # oversized word alone

    def test_only_first_sub_token_is_labelled(self):
        record = {
            "img_id": "x.jpg",
            "words": ["PONTE", "sườn", "noise"],
            "boxes": [[1, 1, 2, 2], [3, 3, 4, 4], [5, 5, 6, 6]],
            "tags": ["B-ITEM_NAME", "I-ITEM_NAME", "IGNORE"],
        }
        (sample,) = encode_document(StubTokenizer(), record, max_length=512, overlap=128)
        item_b, item_i = LABEL_TO_ID["B-ITEM_NAME"], LABEL_TO_ID["I-ITEM_NAME"]
        # <s>, ▁ PO NT E, ▁sư ờn, ▁no is e, </s>
        self.assertEqual(sample["labels"], [IGNORE_INDEX, item_b, IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX, item_i, IGNORE_INDEX] + [IGNORE_INDEX] * 4)
        self.assertEqual(check_sample(sample, record), [])


if __name__ == "__main__":
    unittest.main()
