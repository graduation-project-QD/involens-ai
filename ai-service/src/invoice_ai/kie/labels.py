"""Label inventory shared by BIO conversion, LayoutXLM training and grouping."""

from __future__ import annotations

DOCUMENT_LABELS: tuple[str, ...] = ("SELLER", "ADDRESS", "TIMESTAMP", "TOTAL_COST")
LINE_ITEM_LABELS: tuple[str, ...] = ("ITEM_NAME", "QUANTITY", "UNIT_PRICE", "LINE_TOTAL")
SEMANTIC_LABELS: tuple[str, ...] = DOCUMENT_LABELS + LINE_ITEM_LABELS

# Category ids written by apps/mcocr-labeler (MC-OCR extended schema).
LABEL_TO_CATEGORY: dict[str, int] = {
    "SELLER": 15,
    "ADDRESS": 16,
    "TIMESTAMP": 17,
    "TOTAL_COST": 18,
    "ITEM_NAME": 19,
    "QUANTITY": 20,
    "UNIT_PRICE": 21,
    "LINE_TOTAL": 22,
}

BIO_LABELS: tuple[str, ...] = ("O",) + tuple(
    f"{prefix}-{label}" for label in SEMANTIC_LABELS for prefix in ("B", "I")
)
LABEL_TO_ID: dict[str, int] = {label: index for index, label in enumerate(BIO_LABELS)}
ID_TO_LABEL: dict[int, str] = {index: label for label, index in LABEL_TO_ID.items()}

# Words whose supervision is ambiguous (partial overlap with a GT region) are excluded from the loss.
IGNORE_INDEX = -100
IGNORE_TAG = "IGNORE"
