"""GT region <-> OCR word alignment and BIO tagging for LayoutXLM.

Policy (decided 2026-10-10):

* Every GT box is one entity: the first aligned word gets ``B-``, the remaining words ``I-``.
  Multi-line names, address lines and date+time are merged later by ``grouping``.
* A word belongs to the GT region covering at least ``assign_threshold`` of its area.
  Partial overlaps between ``ignore_threshold`` and ``assign_threshold`` become ``IGNORE`` (-100).
* Leading caption tokens inside ADDRESS/TIMESTAMP boxes ("ĐC:", "Ngày bán:") are tagged ``O``
  because the annotations are inconsistent about including them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from invoice_ai.kie.data import LabeledDocument, Region
from invoice_ai.kie.geometry import Polygon, area, bbox, intersection_area, interpolate_quad, order_rows
from invoice_ai.kie.labels import IGNORE_TAG

BIO_VERSION = "kie_bio_v3"  # v2: rescue small regions; v3: char-width word boxes + text check
CAPTION_LABELS = frozenset({"ADDRESS", "TIMESTAMP"})
_WORD = re.compile(r"\S+")
# "Ngày:15/08/2020" -> "Ngày:" + "15/08/2020"; "10:41" stays one token.
_CAPTION_SPLIT = re.compile(r"(?<=[^\W\d_]:)(?=\S)")


@dataclass(frozen=True)
class OcrLineInput:
    text: str
    polygon: Polygon  # 4 points tl, tr, br, bl
    score: float | None = None


@dataclass(frozen=True)
class AlignedWord:
    text: str
    quad: Polygon  # upright frame
    box: tuple[int, int, int, int]  # upright frame, 0..1000
    tag: str
    region_index: int | None
    line_item_id: int | None
    line_index: int
    ocr_score: float | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quad"] = [[round(x, 1), round(y, 1)] for x, y in self.quad]
        return payload


@dataclass(frozen=True)
class RegionAlignment:
    region_index: int
    label: str
    gt_text: str
    ocr_text: str
    word_count: int
    cer: float | None

    @property
    def matched(self) -> bool:
        return self.word_count > 0


@dataclass(frozen=True)
class AlignedDocument:
    img_id: str
    split: str
    width: int  # upright
    height: int
    words: tuple[AlignedWord, ...]
    regions: tuple[RegionAlignment, ...]
    source: str  # "ocr" or "oracle"
    bio_version: str = BIO_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "img_id": self.img_id,
            "split": self.split,
            "width": self.width,
            "height": self.height,
            "source": self.source,
            "bio_version": self.bio_version,
            "words": [w.text for w in self.words],
            "boxes": [list(w.box) for w in self.words],
            "tags": [w.tag for w in self.words],
            "region_index": [w.region_index for w in self.words],
            "line_item_ids": [w.line_item_id for w in self.words],
            "line_index": [w.line_index for w in self.words],
            "ocr_scores": [w.ocr_score for w in self.words],
        }


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


_SPACE_AROUND_PUNCT = re.compile(r"\s*([.,\-+:/()])\s*")


def match_key(text: str) -> str:
    """Evaluation key for field text (decided 2026-10-23, fixed before any test run).

    Case-insensitive and ignores spaces around punctuation ("P.Cẩm" == "P. Cẩm"); keeps spaces between
    words, Vietnamese diacritics, tone-mark placement and the punctuation itself.
    """
    return _SPACE_AROUND_PUNCT.sub(r"\1", normalize_text(text))


def char_error_rate(reference: str, hypothesis: str) -> float | None:
    if not reference:
        return None
    previous = list(range(len(hypothesis) + 1))
    for i, ref_char in enumerate(reference, 1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_char != hyp_char)))
        previous = current
    return previous[-1] / len(reference)


def caption_prefix_length(tokens: Sequence[str], max_tokens: int = 3) -> int:
    """Number of leading caption tokens such as ``ĐC:``, ``Địa chỉ:``, ``Ngày bán:``.

    A caption is a run of at most ``max_tokens`` digit-free tokens ending with a token that ends in ``:``.
    """
    for index, token in enumerate(tokens[:max_tokens]):
        if any(ch.isdigit() for ch in token):
            return 0
        if token.endswith(":"):
            return index + 1 if index + 1 < len(tokens) else 0
    return 0


def _box_1000(quad: Polygon, width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox(quad)

    def scale(value: float, size: int) -> int:
        return max(0, min(1000, int(round(1000 * value / size))))

    return scale(x0, width), scale(y0, height), scale(x1, width), scale(y1, height)


_NARROW = frozenset("iljI.,:;'|!()[]/-")
_WIDE = frozenset("mwMW")


def char_width(ch: str) -> float:
    """Relative advance width of a printed character (Arial-like proportions, em = 1)."""
    base = unicodedata.normalize("NFD", ch)[0]
    if base == " ":
        return 0.28
    if base in _NARROW:
        return 0.28
    if base in _WIDE:
        return 0.85
    if base.isdigit():
        return 0.56
    if base.isupper():
        return 0.68
    return 0.53


def split_line(line: OcrLineInput) -> list[tuple[str, Polygon]]:
    """Split an OCR line into words with boxes estimated from character widths.

    Digits and capitals are wider than lower-case letters and spaces, so a uniform split shifts the
    words after a barcode ("291010470000 kem tràng tiền") to the left.
    """
    text = line.text
    if not text.strip():
        return []
    quad = line.polygon if len(line.polygon) == 4 else _quad_from_bbox(line.polygon)
    offsets = [0.0]
    for ch in text:
        offsets.append(offsets[-1] + char_width(ch))
    total = offsets[-1]
    words = []
    for match in _WORD.finditer(text):
        start = match.start()
        for piece in _CAPTION_SPLIT.split(match.group()):
            words.append((piece, interpolate_quad(quad, offsets[start] / total, offsets[start + len(piece)] / total)))
            start += len(piece)
    return words


def substring_alignment(reference: str, hypothesis: str) -> tuple[int, int, int]:
    """Best match of ``reference`` inside ``hypothesis``: (edit distance, start, end) in ``hypothesis``."""
    n = len(hypothesis)
    previous, starts = [0] * (n + 1), list(range(n + 1))  # free start anywhere
    for i, ref_char in enumerate(reference, 1):
        current, current_starts = [i], [0]
        for j, hyp_char in enumerate(hypothesis, 1):
            options = (
                (previous[j - 1] + (ref_char != hyp_char), starts[j - 1]),
                (previous[j] + 1, starts[j]),
                (current[j - 1] + 1, current_starts[j - 1]),
            )
            cost, start = min(options)
            current.append(cost)
            current_starts.append(start)
        previous, starts = current, current_starts
    end = min(range(n + 1), key=lambda j: (previous[j], -j))
    return previous[end], starts[end], end


def _quad_from_bbox(points: Polygon) -> Polygon:
    x0, y0, x1, y1 = bbox(points)
    return (x0, y0), (x1, y0), (x1, y1), (x0, y1)


def _overlap_smaller(quad: Polygon, polygon: Polygon, polygon_area: float) -> float:
    smaller = min(area(quad), polygon_area)
    return intersection_area(quad, polygon) / smaller if smaller > 0 else 0.0


def _assign(word_quad: Polygon, regions: Sequence[tuple[Region, Polygon]], assign: float, ignore: float) -> tuple[int | None, bool]:
    word_area = area(word_quad)
    if word_area <= 0:
        return None, True
    best_index, best_cover = None, 0.0
    for position, (_, polygon) in enumerate(regions):
        cover = intersection_area(word_quad, polygon) / word_area
        if cover > best_cover:
            best_index, best_cover = position, cover
    if best_cover >= assign:
        return best_index, False
    return None, best_cover >= ignore


def align_document(
    document: LabeledDocument,
    ocr_lines: Sequence[OcrLineInput],
    *,
    ocr_frame: str = "upright",
    assign_threshold: float = 0.5,
    ignore_threshold: float = 0.2,
    region_cover: float = 0.5,
    text_match: bool = True,
    max_text_cer: float = 0.34,
) -> AlignedDocument:
    """Tag OCR words with BIO labels from the GT regions of ``document``.

    ``ocr_frame`` is ``"upright"`` when OCR ran on the rotated (upright) image, which is the intended
    pipeline, or ``"source"`` when it ran on the original file (e.g. the old T10 cache).
    """
    if ocr_frame not in {"upright", "source"}:
        raise ValueError("ocr_frame must be 'upright' or 'source'")
    width, height = document.upright_size
    regions = [(region, document.upright(region.polygon)) for region in document.regions]

    raw_words: list[tuple[str, Polygon, int, float | None]] = []
    for line_index, line in enumerate(ocr_lines):
        for text, quad in split_line(line):
            if ocr_frame == "source":
                quad = document.upright(quad)
            raw_words.append((text, quad, line_index, line.score))

    # Reading order in the upright frame: rows of OCR lines, words keep their in-line order.
    line_boxes: dict[int, list[Polygon]] = {}
    for _, quad, line_index, _ in raw_words:
        line_boxes.setdefault(line_index, []).append(quad)
    line_ids = list(line_boxes)
    boxes = [bbox([p for quad in line_boxes[i] for p in quad]) for i in line_ids]
    line_rank = {line_ids[i]: rank for rank, i in enumerate(i for row in order_rows(boxes) for i in row)}
    ordered = sorted(range(len(raw_words)), key=lambda k: (line_rank[raw_words[k][2]], k))

    assigned: dict[int, list[int]] = {}
    word_region: dict[int, int | None] = {}
    word_ignored: dict[int, bool] = {}
    for k in ordered:
        position, ignored = _assign(raw_words[k][1], regions, assign_threshold, ignore_threshold)
        word_region[k], word_ignored[k] = position, ignored
        if position is not None:
            assigned.setdefault(position, []).append(k)

    # Text check: a detector box holding text outside the region (barcode + item name, "Thời gian:
    # <date> Số HĐ: ...", house number + street) makes the estimated word boxes drift, so the first or
    # last word of the region falls outside. Within the OCR lines that overlap the region, take the
    # words spelling the GT text instead, when that matches the GT better than the geometric choice.
    if text_match:
        line_words: dict[int, list[int]] = {}
        for k in ordered:
            line_words.setdefault(raw_words[k][2], []).append(k)
        line_quads = {i: document.upright(line.polygon) if ocr_frame == "source" else line.polygon for i, line in enumerate(ocr_lines)}
        for position, (region, polygon) in enumerate(regions):
            reference = normalize_text(region.text)
            current = assigned.get(position, [])
            if not reference or normalize_text(" ".join(raw_words[k][0] for k in current)) == reference:
                continue
            region_area = area(polygon)
            lines = [i for i in line_words if _overlap_smaller(line_quads[i], polygon, region_area) >= 0.5]
            candidates = [k for k in ordered if raw_words[k][2] in lines]
            if not candidates:
                continue
            spans, text = [], ""
            for k in candidates:
                piece = normalize_text(raw_words[k][0])
                if text:
                    text += " "
                spans.append((len(text), len(text) + len(piece)))
                text += piece
            distance, start, end = substring_alignment(reference, text)
            chosen = [k for k, (a, b) in zip(candidates, spans) if min(b, end) - max(a, start) >= (b - a) / 2]
            if not chosen or any(word_region[k] not in (None, position) for k in chosen):
                continue
            old_cer = char_error_rate(reference, normalize_text(" ".join(raw_words[k][0] for k in current))) if current else 1.0
            if distance / len(reference) >= min(old_cer, max_text_cer):
                continue
            for k in current:
                if k not in chosen:
                    word_region[k], word_ignored[k] = None, False
            for k in chosen:
                word_region[k], word_ignored[k] = position, False
            assigned[position] = chosen

    # A detector box wider than its text (e.g. "| 10" for a quantity) leaves a small region with no
    # word above the threshold. Give such a region the free word that covers most of it, unless the
    # word is much longer than the GT text (e.g. "VAT10%" next to a quantity "1").
    for position, (region, polygon) in enumerate(regions):
        if position in assigned or (region_area := area(polygon)) <= 0:
            continue
        max_length = 2 * len(region.text.replace(" ", "")) + 2
        best_k, best_cover = None, region_cover
        for k in ordered:
            if word_region[k] is None and len(raw_words[k][0]) <= max_length:
                cover = intersection_area(raw_words[k][1], polygon) / region_area
                if cover >= best_cover:
                    best_k, best_cover = k, cover
        if best_k is not None:
            word_region[best_k], word_ignored[best_k] = position, False
            assigned[position] = [best_k]

    tags: dict[int, str] = {}
    for position, members in assigned.items():
        region = regions[position][0]
        skip = caption_prefix_length([raw_words[k][0] for k in members]) if region.label in CAPTION_LABELS else 0
        for rank, k in enumerate(members):
            if rank < skip:
                tags[k] = "O"
                word_region[k] = None
            else:
                tags[k] = ("B-" if rank == skip else "I-") + region.label

    words = []
    previous_region: int | None = None
    for k in ordered:
        text, quad, line_index, score = raw_words[k]
        position = word_region[k]
        region = regions[position][0] if position is not None else None
        tag = tags.get(k) or (IGNORE_TAG if word_ignored[k] else "O")
        if tag.startswith("I-") and previous_region != position:
            tag = "B-" + tag[2:]  # a stray word interrupted the region: keep the sequence valid BIO
        if tag != IGNORE_TAG:
            previous_region = position if tag[:2] in {"B-", "I-"} else None
        words.append(
            AlignedWord(
                text=text,
                quad=quad,
                box=_box_1000(quad, width, height),
                tag=tag,
                region_index=region.index if region else None,
                line_item_id=region.line_item_id if region else None,
                line_index=line_rank[line_index],
                ocr_score=score,
            )
        )

    region_stats = []
    for position, (region, _) in enumerate(regions):
        members = [k for k in assigned.get(position, []) if tags.get(k, "O") != "O"]
        ocr_text = " ".join(raw_words[k][0] for k in members)
        gt_tokens = region.text.split()
        gt_skip = caption_prefix_length(gt_tokens) if region.label in CAPTION_LABELS else 0
        gt_text = " ".join(gt_tokens[gt_skip:])
        region_stats.append(
            RegionAlignment(
                region_index=region.index,
                label=region.label,
                gt_text=gt_text,
                ocr_text=ocr_text,
                word_count=len(members),
                cer=char_error_rate(normalize_text(gt_text), normalize_text(ocr_text)) if members else None,
            )
        )
    return AlignedDocument(document.img_id, document.split, width, height, tuple(words), tuple(region_stats), "ocr")


def oracle_document(document: LabeledDocument, aligned: AlignedDocument) -> AlignedDocument:
    """GT-text oracle: OCR words outside GT regions stay as ``O``; every GT region is replaced by its GT text.

    This keeps the realistic background (``O``) tokens while assuming perfect detection and recognition
    for labeled fields, which is the comparison point for the "OCR vs KIE" error attribution.
    """
    width, height = aligned.width, aligned.height
    region_quads = [document.upright(region.polygon) for region in document.regions]

    def inside_region(word: AlignedWord) -> bool:
        word_area = area(word.quad)
        return word_area > 0 and any(intersection_area(word.quad, q) >= 0.5 * word_area for q in region_quads)

    # Caption tokens ("ĐC:") are O in the OCR view but come back from the GT text below.
    background = [w for w in aligned.words if w.tag == "O" and not inside_region(w)]
    entries: list[tuple[tuple[float, float, float, float], list[AlignedWord]]] = []
    for word in background:
        entries.append((bbox(word.quad), [word]))
    for region in document.regions:
        gt_tokens = region.text.split()
        skip = caption_prefix_length(gt_tokens) if region.label in CAPTION_LABELS else 0
        quad = _quad_from_bbox(document.upright(region.polygon))
        pieces = split_line(OcrLineInput(region.text, quad))
        region_words = []
        for rank, (text, word_quad) in enumerate(pieces):
            tag = "O" if rank < skip else ("B-" if rank == skip else "I-") + region.label
            region_words.append(
                AlignedWord(
                    text=text,
                    quad=word_quad,
                    box=_box_1000(word_quad, width, height),
                    tag=tag,
                    region_index=None if rank < skip else region.index,
                    line_item_id=None if rank < skip else region.line_item_id,
                    line_index=0,
                    ocr_score=None,
                )
            )
        if region_words:
            entries.append((bbox(quad), region_words))
    rows = order_rows([entry[0] for entry in entries])
    words = []
    for rank, index in enumerate(i for row in rows for i in row):
        for word in entries[index][1]:
            words.append(AlignedWord(**{**word.__dict__, "line_index": rank}))
    regions = tuple(
        RegionAlignment(r.index, r.label, r.text, r.text, len(r.text.split()), 0.0) for r in document.regions
    )
    return AlignedDocument(document.img_id, document.split, width, height, tuple(words), regions, "oracle")
