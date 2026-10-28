"""Post-processing: merge labeled entities into document fields and line items.

Input entities come from GT boxes (for tuning/evaluation) or from LayoutXLM BIO spans (inference).
Each entity is a single text box with one semantic label; this module decides which boxes belong
together:

* document fields: all boxes of one label joined in reading order (address lines, date + time);
* line items: rows of item boxes are walked top to bottom and attached to the current item or start
  a new one, using the receipt's layout (names inline with numbers vs. names above numbers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from invoice_ai.kie.geometry import order_rows
from invoice_ai.kie.labels import DOCUMENT_LABELS, LINE_ITEM_LABELS

GROUPING_VERSION = "kie_grouping_v1"
NUMERIC_LABELS = frozenset({"QUANTITY", "UNIT_PRICE", "LINE_TOTAL"})


@dataclass(frozen=True)
class Entity:
    ref: int
    label: str
    text: str
    box: tuple[float, float, float, float]  # upright pixels x0, y0, x1, y1
    score: float | None = None


@dataclass
class LineItem:
    members: list[int] = field(default_factory=list)  # entity refs
    labels: list[str] = field(default_factory=list)

    @property
    def has_name(self) -> bool:
        return "ITEM_NAME" in self.labels

    @property
    def numeric_labels(self) -> set[str]:
        return {label for label in self.labels if label in NUMERIC_LABELS}

    def add(self, entities: Sequence[Entity]) -> None:
        for entity in entities:
            self.members.append(entity.ref)
            self.labels.append(entity.label)


@dataclass(frozen=True)
class GroupedDocument:
    fields: dict[str, str | None]
    field_members: dict[str, list[int]]
    line_items: list[dict[str, str | None]]
    line_item_members: list[list[int]]
    layout: str
    grouping_version: str = GROUPING_VERSION


def _reading_order(entities: Sequence[Entity]) -> list[Entity]:
    rows = order_rows([e.box for e in entities])
    return [entities[i] for row in rows for i in row]


def group_document_fields(entities: Sequence[Entity]) -> tuple[dict[str, str | None], dict[str, list[int]]]:
    values: dict[str, str | None] = {}
    members: dict[str, list[int]] = {}
    for label in DOCUMENT_LABELS:
        candidates = [e for e in entities if e.label == label]
        if label == "TOTAL_COST" and len(candidates) > 1:
            # One amount, not a concatenation: keep the most confident box (first in reading order on ties).
            ordered = _reading_order(candidates)
            best = max(ordered, key=lambda e: (e.score if e.score is not None else 0.0, -ordered.index(e)))
            candidates = [best]
        ordered = _reading_order(candidates)
        values[label] = " ".join(e.text.strip() for e in ordered) or None
        members[label] = [e.ref for e in ordered]
    return values, members


def detect_layout(rows: Sequence[Sequence[Entity]]) -> str:
    """``inline`` when most name rows also carry numbers, otherwise ``stacked`` (name above numbers)."""
    name_rows = [row for row in rows if any(e.label == "ITEM_NAME" for e in row)]
    if not name_rows:
        return "inline"
    with_numbers = sum(any(e.label in NUMERIC_LABELS for e in row) for row in name_rows)
    return "inline" if with_numbers >= 0.5 * len(name_rows) else "stacked"


def group_line_items(entities: Sequence[Entity], *, row_overlap: float = 0.5) -> tuple[list[LineItem], str]:
    items = [e for e in entities if e.label in LINE_ITEM_LABELS]
    if not items:
        return [], "none"
    rows = [[items[i] for i in row] for row in order_rows([e.box for e in items], overlap=row_overlap)]
    layout = detect_layout(rows)
    groups: list[LineItem] = []
    current: LineItem | None = None

    def start(row_entities: Sequence[Entity]) -> LineItem:
        item = LineItem()
        item.add(row_entities)
        groups.append(item)
        return item

    for row in rows:
        names = [e for e in row if e.label == "ITEM_NAME"]
        numbers = [e for e in row if e.label in NUMERIC_LABELS]
        if current is None:
            current = start(row)
        elif names and numbers:
            if layout == "stacked" and current.has_name and not current.numeric_labels:
                current.add(row)  # last line of a stacked name together with its numbers
            else:
                current = start(row)
        elif names:
            if layout == "inline" or not current.numeric_labels:
                current.add(row)  # wrapped name line
            else:
                current = start(row)  # stacked layout: a name row opens the next item
        else:
            if current.numeric_labels.isdisjoint(e.label for e in numbers):
                current.add(row)  # e.g. unit price printed under the name row
            else:
                current = start(row)
    return groups, layout


def _center_y(e: Entity) -> float:
    return (e.box[1] + e.box[3]) / 2


def _align_to_anchors(anchor_y: Sequence[float], ys: Sequence[float], offset: float, unit: float, gap: float) -> dict[int, int]:
    """Monotonic alignment (edit-distance DP) of sorted ``ys`` onto sorted anchors; returns entity -> anchor."""
    n, m = len(ys), len(anchor_y)
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for k in range(m + 1):
            if cost[i][k] == inf:
                continue
            if i < n and cost[i][k] + gap < cost[i + 1][k]:
                cost[i + 1][k], back[i + 1][k] = cost[i][k] + gap, (i, k)
            if k < m and cost[i][k] + gap < cost[i][k + 1]:
                cost[i][k + 1], back[i][k + 1] = cost[i][k] + gap, (i, k)
            if i < n and k < m:
                value = cost[i][k] + abs(ys[i] - anchor_y[k] - offset) / unit
                if value < cost[i + 1][k + 1]:
                    cost[i + 1][k + 1], back[i + 1][k + 1] = value, (i, k)
    matches: dict[int, int] = {}
    i, k = n, m
    while (i, k) != (0, 0):
        previous = back[i][k]
        assert previous is not None
        if previous == (i - 1, k - 1):
            matches[i - 1] = k - 1
        i, k = previous
    return matches


def looks_like_continuation(text: str) -> bool:
    """Wrapped name lines usually start in lower case or with a bracket ("quất", "(Vừa)")."""
    stripped = text.strip()
    return bool(stripped) and (stripped[0].islower() or stripped[0] in "([")


def _segment_names(
    anchor_y: Sequence[float],
    name_y: Sequence[float],
    offset: float,
    unit: float,
    empty: float,
    max_lines: int,
    head_penalty: Sequence[float] | None = None,
) -> tuple[float, list[int]]:
    """Split sorted name lines into contiguous runs, one per anchor; the first line of a run is its head.

    Cost = distance of each head from ``anchor + offset`` (+ ``head_penalty`` of that line) plus
    ``empty`` for anchors without a name.
    Returns the total cost and the anchor index of every name line.
    """
    n, m = len(name_y), len(anchor_y)
    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for k in range(1, m + 1):
        for i in range(n + 1):
            best, arg = dp[i][k - 1] + empty, i
            for j in range(max(0, i - max_lines), i):
                if dp[j][k - 1] == inf:
                    continue
                value = dp[j][k - 1] + abs(name_y[j] - anchor_y[k - 1] - offset) / unit
                if head_penalty is not None:
                    value += head_penalty[j]
                if value < best:
                    best, arg = value, j
            dp[i][k], back[i][k] = best, arg
    owner = [0] * n
    i = n
    for k in range(m, 0, -1):
        j = back[i][k]
        for line in range(j, i):
            owner[line] = k - 1
        i = j
    return dp[n][m], owner


def group_line_items_anchored(
    entities: Sequence[Entity],
    *,
    gap: float = 2.5,
    empty: float = 4.0,
    max_lines: int = 4,
    continuation_penalty: float = 1.0,
) -> tuple[list[LineItem], str]:
    """Anchor-based grouping: one item per anchor box (normally LINE_TOTAL).

    Numeric boxes are aligned to anchors in vertical order with a per-document offset, which tolerates
    perspective/skew. Defaults were chosen on train GT only (2026-10-10 sweep); val is reported once. Name lines are split into contiguous runs whose head sits at a consistent offset
    from its anchor, which covers names above, beside or below the numbers and wrapped names.
    """
    items = [e for e in entities if e.label in LINE_ITEM_LABELS]
    numeric = [e for e in items if e.label in NUMERIC_LABELS]
    if not numeric:
        return group_line_items(entities)
    counts = {label: sum(e.label == label for e in numeric) for label in ("LINE_TOTAL", "UNIT_PRICE", "QUANTITY")}
    anchor_label = max(counts, key=lambda label: counts[label])  # ties keep LINE_TOTAL first
    anchors = sorted((e for e in numeric if e.label == anchor_label), key=_center_y)
    anchor_y = [_center_y(e) for e in anchors]
    heights = sorted(e.box[3] - e.box[1] for e in items)
    unit = max(1.0, heights[len(heights) // 2])

    groups = [LineItem() for _ in anchors]
    for group, anchor in zip(groups, anchors):
        group.add([anchor])
    extra: list[LineItem] = []

    def nearest_offsets(ys: Sequence[float]) -> list[float]:
        return [min((y - a for a in anchor_y), key=abs) for y in ys]

    for label in NUMERIC_LABELS - {anchor_label}:
        others = sorted((e for e in numeric if e.label == label), key=_center_y)
        if not others:
            continue
        ys = [_center_y(e) for e in others]
        deltas = sorted(nearest_offsets(ys))
        offset = deltas[len(deltas) // 2]
        matches = _align_to_anchors(anchor_y, ys, offset, unit, gap)
        for index, entity in enumerate(others):
            if index in matches:
                groups[matches[index]].add([entity])
            else:
                orphan = LineItem()
                orphan.add([entity])
                extra.append(orphan)

    names = [items[i] for row in order_rows([e.box for e in items]) for i in row if items[i].label == "ITEM_NAME"]
    if names:
        name_y = [_center_y(e) for e in names]
        candidates = sorted({round(d / (unit / 4)) * (unit / 4) for y in name_y for d in (y - a for a in anchor_y) if abs(d) <= 4 * unit})
        penalty = [continuation_penalty if looks_like_continuation(e.text) else 0.0 for e in names]
        best: tuple[float, float, list[int]] | None = None
        for offset in candidates or [0.0]:
            total, owner = _segment_names(anchor_y, name_y, offset, unit, empty, max_lines, penalty)
            if best is None or (total, abs(offset)) < (best[0], abs(best[1])):
                best = (total, offset, owner)
        assert best is not None
        for entity, owner in zip(names, best[2]):
            groups[owner].add([entity])
    return groups + extra, "anchored"


def group_document(entities: Sequence[Entity]) -> GroupedDocument:
    by_ref = {e.ref: e for e in entities}
    fields, field_members = group_document_fields(entities)
    groups, layout = group_line_items_anchored(entities)
    line_items = []
    for group in groups:
        members = _reading_order([by_ref[ref] for ref in group.members])
        line_items.append(
            {
                label: " ".join(e.text.strip() for e in members if e.label == label) or None
                for label in LINE_ITEM_LABELS
            }
        )
    return GroupedDocument(fields, field_members, line_items, [g.members for g in groups], layout)
