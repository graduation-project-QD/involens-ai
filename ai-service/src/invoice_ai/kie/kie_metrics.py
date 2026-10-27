"""Word-level helpers for LayoutXLM training and evaluation (no torch needed, unit-tested).

* ``merge_windows``: a long document is split into overlapping windows (``tokenize_layoutxlm``); each
  word takes the prediction of the window where it sits farthest from the window edges.
* ``entity_scores``: entity-level precision/recall/F1 from BIO tags (seqeval-style, lenient: an ``I-X``
  after a different label starts a new entity). Gold ``IGNORE`` words are scored as ``O`` and the
  prediction at those positions is ignored, so ambiguous words never create or break an entity.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Sequence

from invoice_ai.kie.labels import IGNORE_TAG, SEMANTIC_LABELS


def merge_windows(windows: Sequence[dict[str, Any]]) -> dict[int, Any]:
    """{word index: value}. ``windows`` items have ``word_range`` [start, end) and ``values`` {word: value}."""
    best: dict[int, tuple[int, Any]] = {}
    for window in windows:
        start, end = window["word_range"]
        for word, value in window["values"].items():
            margin = min(word - start, end - 1 - word)
            if word not in best or margin > best[word][0]:
                best[word] = (margin, value)
    return {word: value for word, (_, value) in best.items()}


def entities(tags: Sequence[str]) -> set[tuple[str, int, int]]:
    """(label, start, end) spans of a BIO sequence; end is exclusive."""
    spans, label, start = set(), None, 0
    for index, tag in enumerate(list(tags) + ["O"]):
        kind, name = (tag[:1], tag[2:]) if tag[:2] in ("B-", "I-") else ("O", None)
        if label is not None and (kind != "I" or name != label):
            spans.add((label, start, index))
            label = None
        if kind == "B" or (kind == "I" and label is None):
            label, start = name, index
    return spans


def entity_scores(pairs: Iterable[tuple[Sequence[str], Sequence[str]]]) -> dict[str, dict[str, float]]:
    """Micro and per-label scores over (gold tags, predicted tags) pairs of the same length."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # true positives, predicted, gold
    for gold, predicted in pairs:
        gold_clean = ["O" if g == IGNORE_TAG else g for g in gold]
        predicted_clean = ["O" if g == IGNORE_TAG else p for g, p in zip(gold, predicted)]
        gold_spans, predicted_spans = entities(gold_clean), entities(predicted_clean)
        for label, *_ in gold_spans:
            counts[label][2] += 1
        for span in predicted_spans:
            counts[span[0]][1] += 1
            counts[span[0]][0] += span in gold_spans

    def score(tp: int, predicted: int, gold: int) -> dict[str, float]:
        precision = tp / predicted if predicted else 0.0
        recall = tp / gold if gold else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "support": gold}

    result = {label: score(*counts[label]) for label in SEMANTIC_LABELS if counts[label][2] or counts[label][1]}
    total = [sum(counts[label][i] for label in counts) for i in range(3)]
    result["micro"] = score(*total)
    return result
