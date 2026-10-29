"""B11 post-processing: LayoutXLM word tags → fields and line items → normalized values → backend result JSON.

Input is one document as LayoutXLM sees it: OCR words, word boxes on the 0–1000 LayoutXLM scale, the OCR line of
each word, predicted BIO tags and per-word confidence. Steps:

1. BIO tags → entities (``kie_metrics.entities``), one entity per span.
2. Entities → document fields and line items (``grouping.group_document``).
3. Values are normalized (amounts, quantity, ISO timestamp, whitespace for text).
4. A missing quantity is inferred as ``line_total / unit_price`` when the division is (almost) exact.
5. Warnings: ``FIELD_ABSENT`` for an empty or unreadable value, ``QUANTITY_INFERRED`` for an inferred quantity.
   ``needs_review`` is true exactly when there is a warning (backend contract).

Rules were chosen on train GT (see ``experiments/reports/b11_postprocess_2026-10-29``); E2 val predictions are
only used for error analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from statistics import mean
from typing import Any, Sequence

from invoice_ai.kie.grouping import Entity, group_document
from invoice_ai.kie.kie_metrics import entities
from invoice_ai.kie.labels import DOCUMENT_LABELS, LINE_ITEM_LABELS
from invoice_ai.normalization.core import (
    NormalizationResult,
    normalize_amount,
    normalize_field,
    normalize_quantity,
    normalize_timestamp,
)

logger = logging.getLogger(__name__)

POSTPROCESS_VERSION = "kie_postprocess_v1"
CONTRACT_KEYS: dict[str, str] = {
    "SELLER": "seller",
    "ADDRESS": "address",
    "TIMESTAMP": "timestamp",
    "TOTAL_COST": "total_cost",
    "ITEM_NAME": "item_name",
    "QUANTITY": "quantity",
    "UNIT_PRICE": "unit_price",
    "LINE_TOTAL": "line_total",
}
CURRENCY = "VND"
# Chosen on train GT: weighed goods print 3 decimals ("0,322") and line totals are exact to the đồng, so a
# quantity is accepted only if it reproduces the line total within 1 VND (a relative tolerance accepts discounts).
MAX_INFERRED_QUANTITY_DECIMALS = 3
MAX_INFERRED_QUANTITY_ERROR_VND = Decimal("1")


@dataclass(frozen=True)
class DocumentPrediction:
    """One document with OCR words, 0–1000 word boxes, OCR line index per word, BIO tags and word confidence."""

    img_id: str
    words: Sequence[str]
    boxes: Sequence[Sequence[float]]
    line_index: Sequence[int]
    tags: Sequence[str]
    scores: Sequence[float] | None
    width: int
    height: int


@dataclass(frozen=True)
class FieldResult:
    """One extracted value in contract form: normalized value, raw OCR text, confidence and evidence polygons."""

    value: str | None
    raw_text: str | None
    confidence: float | None
    evidence: list[list[list[int]]] = field(default_factory=list)
    inferred: bool = False

    @property
    def status(self) -> str:
        return "found" if self.value is not None else "absent"

    def to_contract(self) -> dict[str, Any]:
        """Serializes the value as the backend ``FieldValue`` (absent values carry no evidence)."""
        return {
            "value": self.value,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "status": self.status,
            "evidence": [{"polygon": polygon} for polygon in self.evidence] if self.value is not None else [],
        }


@dataclass(frozen=True)
class PostprocessResult:
    """Fields, line items, warnings and confidence of one document after B11 post-processing."""

    img_id: str
    fields: dict[str, FieldResult]
    line_items: list[dict[str, FieldResult]]
    warnings: list[dict[str, str]]
    overall_confidence: float
    width: int
    height: int

    @property
    def needs_review(self) -> bool:
        return bool(self.warnings)

    def to_contract(self, document_id: str, processing_ms: int | None = None, model_version: str = "layoutxlm-e2-b10",
                    ocr_version: str = "ocr_v2") -> dict[str, Any]:
        """Builds the success message the backend reads from the result queue (``AiExtractionResultMessage``)."""
        logger.info("Building backend result message. img_id=%s, documentId=%s", self.img_id, document_id)
        return {
            "status": 0,
            "error": None,
            "data": {
                "id": document_id,
                "fields": {key: value.to_contract() for key, value in self.fields.items()},
                "line_items": [
                    {"index": index, **{key: value.to_contract() for key, value in item.items()}}
                    for index, item in enumerate(self.line_items, start=1)
                ],
                "currency": CURRENCY,
                "overall_confidence": self.overall_confidence,
                "needs_review": self.needs_review,
                "warnings": self.warnings,
                "image": {"width": self.width, "height": self.height, "rotation_applied": 0},
                "meta": {
                    "schema_version": "1.0",
                    "model_version": model_version,
                    "ocr_version": ocr_version,
                    "postprocess_version": POSTPROCESS_VERSION,
                    "processing_ms": processing_ms,
                },
            },
        }


def decode_entities(document: DocumentPrediction) -> tuple[list[Entity], dict[int, range]]:
    """Turns predicted BIO tags into entities (one per span) with their box and the words they cover.

    The entity confidence is the lowest word confidence in the span, so one uncertain word lowers the field.
    """
    logger.debug("Decoding BIO spans. img_id=%s", document.img_id)
    decoded: list[Entity] = []
    words_of: dict[int, range] = {}
    for ref, (label, start, end) in enumerate(sorted(entities(list(document.tags)), key=lambda span: span[1])):
        boxes = document.boxes[start:end]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        score = min(document.scores[start:end]) if document.scores else None
        decoded.append(Entity(ref, label, " ".join(document.words[start:end]), box, score))
        words_of[ref] = range(start, end)
    return decoded, words_of


def evidence_polygons(document: DocumentPrediction, word_indices: Sequence[int]) -> list[list[list[int]]]:
    """Returns one pixel rectangle per OCR line covered by the words, as the image region supporting a value."""
    by_line: dict[int, list[Sequence[float]]] = {}
    for index in word_indices:
        by_line.setdefault(document.line_index[index], []).append(document.boxes[index])
    polygons = []
    sx, sy = document.width / 1000, document.height / 1000
    for boxes in by_line.values():
        x0, y0 = round(min(b[0] for b in boxes) * sx), round(min(b[1] for b in boxes) * sy)
        x1, y1 = round(max(b[2] for b in boxes) * sx), round(max(b[3] for b in boxes) * sy)
        polygons.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    return polygons


def normalize_value(label: str, raw_text: str) -> NormalizationResult:
    """Applies the normalizer of a semantic label to the joined raw text of its entities."""
    if label in ("TOTAL_COST", "UNIT_PRICE", "LINE_TOTAL"):
        return normalize_amount(raw_text, CONTRACT_KEYS[label])
    if label == "QUANTITY":
        return normalize_quantity(raw_text)
    if label == "TIMESTAMP":
        return normalize_timestamp(raw_text)
    return normalize_field("address" if label == "ADDRESS" else "company", raw_text)


def build_field(document: DocumentPrediction, label: str, members: Sequence[Entity], words_of: dict[int, range],
                normalize: bool) -> FieldResult:
    """Joins the entities of one field in reading order and normalizes the value (or keeps raw text when disabled).

    A value that cannot be normalized becomes absent but keeps its raw text so a reviewer can see what was read.
    """
    if not members:
        return FieldResult(None, None, None)
    ordered = sorted(members, key=lambda e: (e.box[1], e.box[0]))
    raw_text = " ".join(e.text.strip() for e in ordered)
    if normalize:
        value = normalize_value(label, raw_text).normalized_value
    else:
        value = raw_text.strip() or None
    scores = [e.score for e in ordered if e.score is not None]
    confidence = round(min(scores), 4) if scores else None
    words = [w for e in ordered for w in words_of[e.ref]]
    if value is None:
        logger.debug("Value could not be normalized. img_id=%s, label=%s", document.img_id, label)
        return FieldResult(None, raw_text, confidence)
    return FieldResult(value, raw_text, confidence, evidence_polygons(document, words))


def infer_quantity(item: dict[str, FieldResult]) -> FieldResult | None:
    """Infers a missing quantity as line_total / unit_price when the result is (almost) exact.

    Accepted when the quotient rounded to three decimals is non-zero and reproduces the line total within 1 VND.
    A negative line total with a positive price gives a negative quantity (returned goods).
    The evidence is the unit price and line total the value was computed from.
    """
    unit_price, line_total = item["unit_price"].value, item["line_total"].value
    if item["quantity"].value is not None or unit_price is None or line_total is None:
        return None
    try:
        price, total = Decimal(unit_price), Decimal(line_total)
    except InvalidOperation:
        return None
    if price <= 0 or total == 0:
        return None
    quantity = (total / price).quantize(Decimal(1).scaleb(-MAX_INFERRED_QUANTITY_DECIMALS))
    if quantity == 0 or abs(quantity * price - total) > MAX_INFERRED_QUANTITY_ERROR_VND:
        logger.debug("Quantity not inferred: division is not exact. unit_price=%s, line_total=%s", unit_price, line_total)
        return None
    value = format(quantity.normalize(), "f")
    return FieldResult(value, None, None, item["unit_price"].evidence + item["line_total"].evidence, inferred=True)


def collect_warnings(fields: dict[str, FieldResult], line_items: list[dict[str, FieldResult]]) -> list[dict[str, str]]:
    """Lists FIELD_ABSENT for every empty value and QUANTITY_INFERRED for every computed quantity."""
    warnings = [{"code": "FIELD_ABSENT", "target": f"fields.{key}"} for key, value in fields.items() if value.value is None]
    for index, item in enumerate(line_items, start=1):
        for key, value in item.items():
            target = f"line_items[{index}].{key}"
            if value.inferred:
                warnings.append({"code": "QUANTITY_INFERRED", "target": target})
            elif value.value is None:
                warnings.append({"code": "FIELD_ABSENT", "target": target})
    return warnings


def postprocess_document(document: DocumentPrediction, normalize: bool = True, infer: bool = True) -> PostprocessResult:
    """Runs B11 on one document: decode spans, group fields and line items, normalize, infer quantity, warn.

    ``normalize``/``infer`` exist for the ablation in ``evaluate_e2e`` (raw grouped text vs. full B11).
    """
    logger.info("Post-processing document. img_id=%s, words=%d", document.img_id, len(document.words))
    try:
        decoded, words_of = decode_entities(document)
        by_ref = {e.ref: e for e in decoded}
        grouped = group_document(decoded)
        fields = {
            CONTRACT_KEYS[label]: build_field(document, label, [by_ref[r] for r in grouped.field_members[label]], words_of, normalize)
            for label in DOCUMENT_LABELS
        }
        line_items = []
        for members in grouped.line_item_members:
            item_entities = [by_ref[r] for r in members]
            item = {
                CONTRACT_KEYS[label]: build_field(document, label, [e for e in item_entities if e.label == label], words_of, normalize)
                for label in LINE_ITEM_LABELS
            }
            inferred = infer_quantity(item) if infer and normalize else None
            if inferred is not None:
                item["quantity"] = inferred
                logger.info("Quantity inferred. img_id=%s, quantity=%s", document.img_id, inferred.value)
            line_items.append(item)
        warnings = collect_warnings(fields, line_items)
        labelled = [s for s, t in zip(document.scores or [], document.tags) if t not in ("O", "IGNORE")]
        result = PostprocessResult(
            document.img_id, fields, line_items, warnings,
            round(mean(labelled), 4) if labelled else 0.0, document.width, document.height,
        )
    except Exception:
        logger.error("Post-processing failed. img_id=%s", document.img_id, exc_info=True)
        raise
    logger.info(
        "Post-processing completed. img_id=%s, line_items=%d, warnings=%d, needs_review=%s",
        document.img_id, len(line_items), len(warnings), result.needs_review,
    )
    return result
