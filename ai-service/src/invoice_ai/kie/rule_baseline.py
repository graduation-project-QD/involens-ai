"""B12 rule baseline: tags OCR words with the 8 KIE labels using keywords, regexes and layout only (no model).

The output is word-level BIO tags in the same ``predictions.jsonl`` format as LayoutXLM, so B11 post-processing
(``postprocess.py``) and ``evaluate_e2e.py`` run unchanged and the comparison differs only in the tagger.
Rules use generic keywords and positions; no store names are memorised. Keyword lists and priorities were
chosen on train (OCR of E2 + GT tags); val is reported.

Usage::

    python -m invoice_ai.kie.rule_baseline predict --ocr ../experiments/data/processed/kie_bio_v3/val.ocr.jsonl \
        --out ../experiments/reports/b12_rule_baseline_2026-10-29/predictions_val.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from invoice_ai.kie.geometry import order_rows
from invoice_ai.normalization.core import normalize_amount, normalize_quantity

logger = logging.getLogger(__name__)

RULE_BASELINE_VERSION = "ocr_rules_mcocr_v2"

DATE_RE = re.compile(r"\d{1,2}\s*([./-])\s*\d{1,2}\s*\1\s*(?:\d{4}|\d{2})(?!\d)")
_CLOCK = r"\d{1,2}\s*[:h.]\s*\d{2}(?:\s*:\s*\d{2})?(?:\s*(?:AM|PM|SA|CH))?"
CLOCK_AFTER_RE = re.compile(rf"[\s\-|–,(]*{_CLOCK}", re.IGNORECASE)
CLOCK_BEFORE_RE = re.compile(rf"(?P<clock>{_CLOCK})[\s\-|–,]*", re.IGNORECASE)
BARCODE_RE = re.compile(r"^\d{8,14}$")
OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "i": "1"})
JUNK_CODE_RE = re.compile(r"^(VAT\w*|\(\d+\)|#\d+)$", re.IGNORECASE)
UNIT_WORDS = frozenset({"kg", "g", "gr", "goi", "hop", "cai", "chai", "lon", "thung", "bich", "tui", "cuon", "lo", "vi", "hu",
                        "qua", "cha", "chiec", "doi", "bo", "ly", "coc", "phan", "suat", "dia", "to", "x", "dvt", "c", "l", "ml"})
LABEL_WORD_RE = re.compile(r"^[^\d]*:$")

# Folded (no diacritics, lower case) keywords. Order = priority.
TOTAL_KEYWORDS = (
    "tong so tien thanh toan", "tong so thanh toan", "tong thanh toan", "phai thanh toan", "phai t.toan", "can thanh toan", "khach phai tra",
    "thanh toan", "tong tien thanh toan", "tong cong", "tong tien", "cong tien hang", "tong", "total",
)
TOTAL_EXCLUDE = ("phuong thuc", "hinh thuc", "so luong", "khach dua", "khach tra", "tien mat", "tra lai", "tien thua", "giam", "chiet khau", "vat", "thue", "tich diem")
TABLE_HEADER_KEYWORDS = ("ten hang", "dvt", "stt", "mat hang", "san pham", "don gia", "so luong", "thanh tien", "t.tien", "sl", "dg", "gia", "mon")
ITEM_SKIP_KEYWORDS = ("gia goc", "vat", "giam gia", "chiet khau", "khuyen mai", "km", "thue")
ADDRESS_SIGNAL_RE = re.compile(
    r"(^|\W)(dc|d/c|dia chi|duong|phuong|quan|huyen|xa|thon|ngo|ngach|kiot|cho|khu|to dan pho|tp|thanh pho|tinh"
    r"|p\.|q\.|tt\.|p\d|q\d|so \d+)(\W|$)|^\W*\d+[a-z]?(/\d+)*\s+[a-z]|\s\d{1,4}[a-z]?\s+[a-z]{2,}\s+[a-z]{2,}",
)
ADDRESS_LABEL_RE = re.compile(r"^(đ/?c|địa chỉ|dc|đc)\s*:?$", re.IGNORECASE)
NON_SELLER_RE = re.compile(
    r"(hoa don|phieu|bien nhan|receipt|invoice|thu ngan|nhan vien|ma so thue|mst|hotline|dien thoai|website|www|wifi"
    r"|so hd|ma hd|ban hang|ngay|gio|khach hang|hot ?line|cskh|so the|quay|don gia|thanh tien|ten hang|so luong|(^|\W)(dt|tel|fax|sdt|sl|dvt)(\W|$))"
)


def fold(text: str) -> str:
    """Lower-cases and strips Vietnamese diacritics so keyword rules survive OCR accent errors."""
    decomposed = unicodedata.normalize("NFD", text.lower().replace("đ", "d").replace("Đ", "d"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


@dataclass
class Line:
    """One OCR detector line: its word indices, text and 0–1000 box."""

    index: int
    words: list[int]
    text: str
    box: tuple[float, float, float, float]

    @property
    def folded(self) -> str:
        return fold(self.text)

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


def build_lines(words: Sequence[str], boxes: Sequence[Sequence[float]], line_index: Sequence[int]) -> list[Line]:
    """Groups words into their OCR lines, ordered top to bottom."""
    grouped: dict[int, list[int]] = {}
    for word, line in enumerate(line_index):
        grouped.setdefault(line, []).append(word)
    lines = []
    for index, members in grouped.items():
        bs = [boxes[w] for w in members]
        box = (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))
        lines.append(Line(index, members, " ".join(words[w] for w in members), box))
    return sorted(lines, key=lambda line: (line.box[1], line.box[0]))


def build_rows(lines: Sequence[Line]) -> list[list[Line]]:
    """Groups lines that share a printed row (vertical overlap), each row left to right."""
    return [[lines[i] for i in row] for row in order_rows([line.box for line in lines])]


def amount_value(word: str) -> Decimal | None:
    """Money value of a word, or None when it is not a single amount."""
    result = normalize_amount(word, "amount")
    if result.normalized_value is None:
        return None
    try:
        return Decimal(result.normalized_value)
    except InvalidOperation:
        return None


def is_number_word(word: str) -> bool:
    """True for words that read as an amount or a quantity (digits with optional separators and currency)."""
    stripped = word.strip("đdĐ()").replace("VND", "")
    return bool(re.fullmatch(r"[-+]?[\dOo.,]*\d[\dOo.,]*", stripped)) and any(c.isdigit() for c in stripped)


def is_money_like(word: str) -> bool:
    """Amounts printed with thousands grouping or a currency mark, or plain 4–7 digit numbers not starting with 0
    (excludes quantities, weights such as "0,498", phone numbers and barcodes)."""
    if amount_value(word) is None:
        return False
    if re.search(r"(^|[^\d.,])[1-9]\d{0,2}([.,]\d{3})+", word) or "đ" in word.lower():
        return True
    digits = re.sub(r"\D", "", word)
    return word.strip("()").isdigit() and 4 <= len(digits) <= 7 and not digits.startswith("0")


def is_barcode(word: str) -> bool:
    """Product codes of 8–14 digits, also when OCR read some zeros/ones as letters ("ODOOOOO2950156")."""
    fixed = word.translate(OCR_DIGITS)
    return bool(BARCODE_RE.match(fixed)) and sum(c.isdigit() for c in word) >= 6


def is_junk_token(word: str) -> bool:
    """Tokens that are never part of a value in item rows: barcodes, VAT/tax codes, bracketed codes."""
    return is_barcode(word) or bool(JUNK_CODE_RE.match(word))


class Tagger:
    """Holds the BIO tags of one document while rules assign labels to word spans."""

    def __init__(self, size: int) -> None:
        self.tags = ["O"] * size

    def free(self, words: Sequence[int]) -> bool:
        return all(self.tags[w] == "O" for w in words)

    def span(self, words: Sequence[int], label: str) -> None:
        """Tags consecutive words as one entity (B- then I-)."""
        for position, word in enumerate(words):
            self.tags[word] = ("B-" if position == 0 else "I-") + label


def tag_timestamp(lines: Sequence[Line], words: Sequence[str], tagger: Tagger) -> Line | None:
    """Tags the first date in reading order together with the clock reading printed right before or after it.

    Matching runs on the line text, so dates and times split into several OCR words ("13 / 08 / 2020 - 22 : 00")
    are found; every word overlapping the matched characters is tagged.
    """
    for line in lines:
        text, offsets, position = "", [], 0
        for w in line.words:
            offsets.append((position, position + len(words[w])))
            text += words[w] + " "
            position += len(words[w]) + 1
        date = DATE_RE.search(text)
        if not date:
            continue
        start, end = date.span()
        after = CLOCK_AFTER_RE.match(text, end)
        if after:
            end = after.end()
        before = [m for m in CLOCK_BEFORE_RE.finditer(text[:start])]
        if before and before[-1].end() == start:
            start = before[-1].start("clock")
        span = [w for w, (a, b) in zip(line.words, offsets) if a < end and b > start]
        tagger.span(span, "TIMESTAMP")
        logger.debug("Timestamp tagged. line=%s", line.text)
        return line
    return None


def find_total(rows: Sequence[Sequence[Line]], words: Sequence[str]) -> tuple[int, int, int] | None:
    """Finds the payable total: highest-priority keyword row, then the rightmost amount on that row or the next row.

    Returns (row index, line index in row, word index) of the amount.
    """
    best: tuple[int, int, int, int] | None = None  # priority, row, line, word
    for r, row in enumerate(rows):
        text = " ".join(line.folded for line in row)
        priority = next((p for p, k in enumerate(TOTAL_KEYWORDS) if k in text), None)
        if priority is None or any(k in text for k in TOTAL_EXCLUDE if k not in TOTAL_KEYWORDS[priority]):
            continue
        for candidate_row in (r, r + 1):
            if candidate_row >= len(rows):
                break
            amounts = [(line_pos, w) for line_pos, line in enumerate(rows[candidate_row]) for w in line.words if is_money_like(words[w])]
            if amounts:
                line_pos, word = amounts[-1]
                if best is None or priority < best[0]:
                    best = (priority, candidate_row, line_pos, word)
                break
    return (best[1], best[2], best[3]) if best else None


def is_table_header(row: Sequence[Line]) -> bool:
    """A row naming at least two item columns ("Tên hàng", "SL", "Đơn giá", "Thành tiền", …)."""
    tokens = " " + " ".join(line.folded for line in row) + " "
    hits = sum(1 for k in TABLE_HEADER_KEYWORDS if re.search(rf"(^|\W){re.escape(k)}(\W|$)", tokens))
    return hits >= 2


def tag_header(lines: Sequence[Line], header_end: float, words: Sequence[str], tagger: Tagger) -> None:
    """Tags ADDRESS lines (address signals) and the SELLER line (tallest remaining header line) above ``header_end``."""
    header = [line for line in lines if line.box[1] < header_end and tagger.free(line.words)]
    address_lines = [
        line for line in header
        if ADDRESS_SIGNAL_RE.search(line.folded) and not DATE_RE.search(line.text) and not NON_SELLER_RE.search(line.folded)
    ]
    for line in address_lines:
        span = list(line.words)
        while span and (ADDRESS_LABEL_RE.match(words[span[0]]) or LABEL_WORD_RE.match(words[span[0]])):
            span.pop(0)
        if span:
            tagger.span(span, "ADDRESS")
    candidates = [
        line for line in header
        if line not in address_lines and not NON_SELLER_RE.search(line.folded) and not DATE_RE.search(line.text)
        and sum(c.isalpha() for c in line.text) >= 3 and sum(c.isdigit() for c in line.text) <= len(line.text) / 2
    ]
    if candidates:
        seller = max(candidates[:4], key=lambda line: (line.height, -line.box[1]))
        tagger.span(seller.words, "SELLER")
        logger.debug("Seller tagged. line=%s", seller.text)


def assign_numbers(numbers: list[int], words: Sequence[str]) -> dict[int, str]:
    """Gives roles to the numbers of one item row: rightmost money → LINE_TOTAL; the pair satisfying
    quantity × unit price ≈ line total → QUANTITY/UNIT_PRICE; otherwise a small number → QUANTITY and a money
    value → UNIT_PRICE. Zero values (discount column) are ignored. Rows without a money value get no roles."""
    values = {w: amount_value(words[w]) for w in numbers}
    money = [w for w in numbers if is_money_like(words[w]) and values[w]]
    if not money:
        return {}  # a lone small number is usually a row index or count; B11 infers missing quantities
    total = money[-1]
    roles = {total: "LINE_TOTAL"}
    rest = [w for w in numbers if w != total and values[w] not in (None, Decimal(0))]
    total_value = values[total]
    assert total_value is not None
    for q in rest:
        quantity = normalize_quantity(words[q]).normalized_value
        if quantity is None:
            continue
        for p in rest:
            if p != q and values[p] and abs(Decimal(quantity) * values[p] - total_value) <= 1:
                roles[q], roles[p] = "QUANTITY", "UNIT_PRICE"
                return roles
    small = [w for w in rest if not is_money_like(words[w]) and normalize_quantity(words[w]).normalized_value is not None]
    prices = [w for w in rest if is_money_like(words[w])]
    if small:
        roles[small[0]] = "QUANTITY"
    if prices:
        roles[prices[-1]] = "UNIT_PRICE"
    return roles


def tag_line_items(rows: Sequence[Sequence[Line]], start: int, end: int, words: Sequence[str], tagger: Tagger) -> None:
    """Tags item rows between the table header (or header region) and the total row.

    Text before the first number of a row is ITEM_NAME (numbers left of text are row indexes); text-only rows are
    item names of stacked layouts; barcodes, discount, VAT and original-price rows are skipped.
    """
    for row in rows[start:end]:
        row_words = [w for line in row for w in line.words if tagger.free([w])]
        text = " ".join(fold(words[w]) for w in row_words)
        if not row_words or any(re.search(rf"(^|\W){re.escape(k)}(\W|$)", text) for k in ITEM_SKIP_KEYWORDS):
            continue
        tokens = [w for w in row_words if not is_junk_token(words[w])]
        numbers = [w for w in tokens if is_number_word(words[w])]
        name = []
        for w in tokens:
            if is_number_word(words[w]):
                if name:
                    break
                continue
            name.append(w)
        name = [w for w in name if sum(c.isalnum() for c in words[w]) > 0]
        while name and fold(words[name[-1]]).strip(".:") in UNIT_WORDS:
            name.pop()
        if name and all(fold(words[w]).strip(".:") in UNIT_WORDS for w in name):
            name = []
        if name and sum(sum(c.isalpha() for c in words[w]) for w in name) >= 2:
            tagger.span(name, "ITEM_NAME")
        for word, role in assign_numbers([w for w in numbers if w not in name], words).items():
            tagger.span([word], role)


def tag_document(words: Sequence[str], boxes: Sequence[Sequence[float]], line_index: Sequence[int]) -> list[str]:
    """Applies all rules to one document and returns one BIO tag per word."""
    tagger = Tagger(len(words))
    lines = build_lines(words, boxes, line_index)
    if not lines:
        return tagger.tags
    rows = build_rows(lines)
    total = find_total(rows, words)
    if total is not None:
        tagger.span([total[2]], "TOTAL_COST")
    table_row = next((r for r, row in enumerate(rows) if is_table_header(row)), None)
    timestamp_line = tag_timestamp(lines, words, tagger)
    total_row = total[0] if total is not None else len(rows)
    first_total_row = next(
        (r for r, row in enumerate(rows) if r > (table_row or 0) and any(k in " ".join(l.folded for l in row) for k in ("tong", "cong tien", "thanh toan", "total"))),
        total_row,
    )
    first_money_row = next((r for r, row in enumerate(rows) if any(is_money_like(words[w]) for l in row for w in l.words)), len(rows))
    if table_row is not None and table_row <= first_money_row:
        header_end, items_start = rows[table_row][0].box[1], table_row + 1
    else:
        anchors = [rows[first_money_row][0].box[1]] if first_money_row < len(rows) else []
        if timestamp_line is not None:
            anchors.append(timestamp_line.box[3])
        header_end = min(anchors) if anchors else lines[0].box[1] + 0.3 * (lines[-1].box[3] - lines[0].box[1])
        items_start = next((r for r, row in enumerate(rows) if row[0].box[1] >= header_end), len(rows))
    tag_header(lines, header_end, words, tagger)
    tag_line_items(rows, items_start, min(first_total_row, total_row), words, tagger)
    return tagger.tags


def predict(ocr_path: Path, out_path: Path) -> int:
    """Tags every document of a BIO record file and writes LayoutXLM-format predictions (score = null)."""
    logger.info("Rule baseline prediction started. version=%s, ocr=%s", RULE_BASELINE_VERSION, ocr_path)
    written = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with ocr_path.open(encoding="utf-8") as source, out_path.open("w", encoding="utf-8") as target:
        for line in source:
            record = json.loads(line)
            try:
                tags = tag_document(record["words"], record["boxes"], record["line_index"])
            except Exception:
                logger.error("Rule tagging failed. img_id=%s", record["img_id"], exc_info=True)
                raise
            target.write(json.dumps({"img_id": record["img_id"], "gold": record.get("tags"), "pred": tags, "score": None},
                                    ensure_ascii=False) + "\n")
            written += 1
    logger.info("Rule baseline prediction completed. documents=%d, out=%s", written, out_path)
    return written


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--ocr", type=Path, required=True, help="BIO record file (kie_bio_v3/{split}.ocr.jsonl)")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    predict(args.ocr, args.out)


if __name__ == "__main__":
    main()
