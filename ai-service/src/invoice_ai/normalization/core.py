"""Versioned normalizers for the four canonical invoice fields."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

logger = logging.getLogger(__name__)

NORMALIZATION_VERSION = "normalization_v1"
FIELDS = ("company", "address", "date", "total")

NormalizationStatus = Literal["ok", "missing", "invalid", "ambiguous"]


@dataclass(frozen=True)
class NormalizationResult:
    field: str
    raw_value: str | None
    normalized_value: str | None
    status: NormalizationStatus
    warnings: list[str] = field(default_factory=list)
    normalizer_version: str = NORMALIZATION_VERSION
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _missing_result(field_name: str, raw_value: str | None) -> NormalizationResult | None:
    if raw_value is None:
        return NormalizationResult(field_name, raw_value, None, "missing", ["MISSING_VALUE"])
    if raw_value.strip() == "":
        return NormalizationResult(field_name, raw_value, None, "missing", ["EMPTY_VALUE"])
    return None


def _normalize_text(field_name: str, raw_value: str | None, multiline: bool) -> NormalizationResult:
    missing = _missing_result(field_name, raw_value)
    if missing is not None:
        return missing
    assert raw_value is not None
    value = unicodedata.normalize("NFC", raw_value)
    if multiline:
        lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
        normalized = " ".join(line for line in lines if line)
    else:
        normalized = re.sub(r"\s+", " ", value).strip()
    if normalized == "":
        return NormalizationResult(field_name, raw_value, None, "missing", ["EMPTY_VALUE"])
    return NormalizationResult(field_name, raw_value, normalized, "ok")


_ISO_DATE_RE = re.compile(r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)")
_LOCAL_DATE_RE = re.compile(
    r"(?<!\d)(?P<first>\d{1,2})[./-](?P<second>\d{1,2})[./-](?P<year>\d{2}|\d{4})(?!\d)"
)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")


def _valid_iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_date(raw_value: str | None, locale: str | None = "vi-VN") -> NormalizationResult:
    missing = _missing_result("date", raw_value)
    if missing is not None:
        return missing
    assert raw_value is not None
    value = unicodedata.normalize("NFC", raw_value)
    candidates: list[tuple[str | None, str | None]] = []
    two_digit_year = False
    ambiguous_locale = False

    for match in _ISO_DATE_RE.finditer(value):
        normalized = _valid_iso(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        candidates.append((match.group(0), normalized))

    occupied = [match.span() for match in _ISO_DATE_RE.finditer(value)]
    for match in _LOCAL_DATE_RE.finditer(value):
        if any(match.start() < end and match.end() > start for start, end in occupied):
            continue
        year_text = match.group("year")
        if len(year_text) == 2:
            two_digit_year = True
            candidates.append((match.group(0), None))
            continue
        first, second, year = int(match.group("first")), int(match.group("second")), int(year_text)
        if locale == "vi-VN":
            candidates.append((match.group(0), _valid_iso(year, second, first)))
        elif locale == "en-US":
            candidates.append((match.group(0), _valid_iso(year, first, second)))
        else:
            day_first = _valid_iso(year, second, first)
            month_first = _valid_iso(year, first, second)
            possible = {item for item in (day_first, month_first) if item is not None}
            if len(possible) == 1:
                candidates.append((match.group(0), next(iter(possible))))
            elif len(possible) == 2:
                ambiguous_locale = True
                candidates.append((match.group(0), None))
            else:
                candidates.append((match.group(0), None))

    if not candidates:
        return NormalizationResult("date", raw_value, None, "invalid", ["INVALID_DATE"])
    if len(candidates) > 1:
        return NormalizationResult(
            "date", raw_value, None, "ambiguous", ["MULTIPLE_DATE_CANDIDATES"],
            details={"candidate_count": len(candidates)},
        )
    matched_text, normalized = candidates[0]
    if two_digit_year:
        return NormalizationResult("date", raw_value, None, "invalid", ["TWO_DIGIT_YEAR_UNSUPPORTED"])
    if ambiguous_locale:
        warnings = ["AMBIGUOUS_DATE"]
        if locale not in (None, ""):
            warnings.append("UNSUPPORTED_LOCALE")
        return NormalizationResult("date", raw_value, None, "ambiguous", warnings)
    if normalized is None:
        return NormalizationResult("date", raw_value, None, "invalid", ["INVALID_DATE"])
    details = {"matched_text": matched_text, "locale": locale}
    if _TIME_RE.search(value):
        details["time_component_removed"] = True
    return NormalizationResult("date", raw_value, normalized, "ok", details=details)


_AMOUNT_RE = re.compile(r"(?<![\d.,])[-+]?\d(?:[\d\s\u00a0.,]*\d)?(?![\d.,])")
_VND_RE = re.compile(r"(?i)(?:\bVND\b|\bVNĐ\b|₫|đ)")


def _grouped_integer(parts: list[str]) -> bool:
    return bool(parts) and 1 <= len(parts[0]) <= 3 and all(len(part) == 3 for part in parts[1:])


def _parse_amount_token(token: str, locale: str | None, explicit_vnd: bool) -> tuple[str | None, str | None]:
    compact = re.sub(r"[\s\u00a0]", "", token)
    sign = ""
    if compact.startswith(("-", "+")):
        sign, compact = compact[0], compact[1:]
    if not compact or not any(character.isdigit() for character in compact):
        return None, "INVALID_AMOUNT"
    dots, commas = compact.count("."), compact.count(",")

    integer_digits: str
    decimal_digits: str | None = None
    if dots and commas:
        decimal_separator = "." if compact.rfind(".") > compact.rfind(",") else ","
        grouping_separator = "," if decimal_separator == "." else "."
        integer_part, decimal_digits = compact.rsplit(decimal_separator, 1)
        groups = integer_part.split(grouping_separator)
        if not _grouped_integer(groups) or not decimal_digits.isdigit() or len(decimal_digits) not in (1, 2):
            return None, "INVALID_AMOUNT"
        integer_digits = "".join(groups)
    elif dots or commas:
        separator = "." if dots else ","
        parts = compact.split(separator)
        if not all(part.isdigit() for part in parts):
            return None, "INVALID_AMOUNT"
        if len(parts) > 2:
            if not _grouped_integer(parts):
                return None, "INVALID_AMOUNT"
            integer_digits = "".join(parts)
        else:
            trailing = len(parts[1])
            if trailing == 3:
                if locale in ("vi-VN", "en-US") or explicit_vnd:
                    integer_digits = "".join(parts)
                else:
                    return None, "AMBIGUOUS_AMOUNT"
            elif trailing in (1, 2):
                integer_digits, decimal_digits = parts
            else:
                return None, "INVALID_AMOUNT"
    else:
        if not compact.isdigit():
            return None, "INVALID_AMOUNT"
        integer_digits = compact

    integer_digits = integer_digits.lstrip("0") or "0"
    normalized = ("-" if sign == "-" else "") + integer_digits
    if decimal_digits is not None:
        normalized += "." + decimal_digits
    try:
        Decimal(normalized)
    except InvalidOperation:
        return None, "INVALID_AMOUNT"
    return normalized, None


def normalize_total(raw_value: str | None, locale: str | None = "vi-VN") -> NormalizationResult:
    missing = _missing_result("total", raw_value)
    if missing is not None:
        return missing
    assert raw_value is not None
    value = unicodedata.normalize("NFC", raw_value)
    matches = [match.group(0).strip() for match in _AMOUNT_RE.finditer(value)]
    if not matches:
        return NormalizationResult("total", raw_value, None, "invalid", ["INVALID_AMOUNT"])
    if len(matches) > 1:
        return NormalizationResult(
            "total", raw_value, None, "ambiguous", ["AMBIGUOUS_AMOUNT"],
            details={"candidate_count": len(matches)},
        )
    explicit_vnd = bool(_VND_RE.search(value))
    normalized, error = _parse_amount_token(matches[0], locale, explicit_vnd)
    if error is not None:
        status: NormalizationStatus = "ambiguous" if error == "AMBIGUOUS_AMOUNT" else "invalid"
        return NormalizationResult("total", raw_value, None, status, [error])
    assert normalized is not None
    warnings: list[str] = []
    parsed = Decimal(normalized)
    if "." in normalized and explicit_vnd:
        warnings.append("CURRENCY_FRACTION_UNEXPECTED")
    if parsed <= 0:
        warnings.append("NON_POSITIVE_TOTAL")
    return NormalizationResult(
        "total", raw_value, normalized, "ok", warnings,
        details={"matched_text": matches[0], "explicit_vnd": explicit_vnd, "locale": locale},
    )


def normalize_field(field_name: str, raw_value: str | None, locale: str | None = "vi-VN") -> NormalizationResult:
    if field_name == "company":
        return _normalize_text("company", raw_value, multiline=False)
    if field_name == "address":
        return _normalize_text("address", raw_value, multiline=True)
    if field_name == "date":
        return normalize_date(raw_value, locale)
    if field_name == "total":
        return normalize_total(raw_value, locale)
    raise ValueError(f"Unsupported canonical field: {field_name}")


def normalize_fields(raw_fields: dict[str, str | None], locale: str | None = "vi-VN") -> dict[str, NormalizationResult]:
    if set(raw_fields) != set(FIELDS):
        raise ValueError("raw_fields must contain exactly company, address, date and total")
    return {field_name: normalize_field(field_name, raw_fields[field_name], locale) for field_name in FIELDS}


# --- B11: line-item amounts, quantities and full timestamps (normalization of LayoutXLM/OCR output) ---

_OCR_DIGIT_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1"})
_NUMERIC_TOKEN_RE = re.compile(r"[\dOoDlI|.,]+")
_TRAILING_SEPARATOR_RE = re.compile(r"(?<=\d)[.,]+(?=\D*$)")
_REPEATED_SEPARATOR_DECIMAL_RE = re.compile(
    r"(?P<integer>[-+]?\d{1,3}(?:(?P<sep>[.,])\d{3})+)(?P=sep)(?P<decimals>\d{2})(?!\d)"
)


def _fix_numeric_ocr(value: str) -> str:
    """Replaces letters that OCR commonly reads instead of digits (O→0, l/I/|→1) inside number-like tokens.

    Only tokens that already contain a digit are touched, so words such as "Tổng" stay unchanged.
    """
    def fix(match: re.Match[str]) -> str:
        token = match.group(0)
        return token.translate(_OCR_DIGIT_CONFUSIONS) if any(character.isdigit() for character in token) else token

    fixed = _NUMERIC_TOKEN_RE.sub(fix, value)
    if fixed != value:
        logger.debug("Corrected OCR digit confusions in a numeric value")
    return fixed


def normalize_amount(raw_value: str | None, field_name: str = "amount", locale: str | None = "vi-VN") -> NormalizationResult:
    """Normalizes one money value (total, unit price or line total) to a plain decimal string such as ``"79500"``.

    Extends ``normalize_total`` for OCR output: fixes digit confusions, drops trailing separators ("39,000."),
    reads grouped amounts whose cent part uses the grouping separator ("36.600.00") and removes zero cents.
    Negative values (returns) are kept. Several numbers in one value stay ambiguous (no value).
    """
    logger.debug("Normalizing amount. field=%s", field_name)
    missing = _missing_result(field_name, raw_value)
    if missing is not None:
        return missing
    assert raw_value is not None
    cleaned = _TRAILING_SEPARATOR_RE.sub("", _fix_numeric_ocr(unicodedata.normalize("NFC", raw_value)))
    cleaned = _REPEATED_SEPARATOR_DECIMAL_RE.sub(
        lambda m: re.sub(r"[.,]", "", m["integer"]) + ("" if m["decimals"] == "00" else "." + m["decimals"]), cleaned
    )
    result = normalize_total(cleaned, locale)
    normalized = result.normalized_value
    if normalized is not None and "." in normalized and set(normalized.split(".", 1)[1]) == {"0"}:
        normalized = normalized.split(".", 1)[0]
    if result.status != "ok":
        logger.debug("Amount could not be normalized. field=%s, status=%s", field_name, result.status)
    return replace(result, field=field_name, raw_value=raw_value, normalized_value=normalized)


def normalize_quantity(raw_value: str | None) -> NormalizationResult:
    """Normalizes a line-item quantity to a decimal string without trailing zeros ("1,00" → "1", "0.670" → "0.67").

    A separator followed by 1–3 digits is a decimal point (receipts print weights such as "0,322" or "10.000").
    Negative quantities (returns) are kept; anything else is invalid.
    """
    logger.debug("Normalizing quantity")
    missing = _missing_result("quantity", raw_value)
    if missing is not None:
        return missing
    assert raw_value is not None
    compact = re.sub(r"\s+", "", _fix_numeric_ocr(unicodedata.normalize("NFC", raw_value))).rstrip(".,")
    if not re.fullmatch(r"[-+]?\d+(?:[.,]\d{1,3})?", compact):
        logger.debug("Quantity is not a number")
        return NormalizationResult("quantity", raw_value, None, "invalid", ["INVALID_QUANTITY"])
    value = Decimal(compact.replace(",", "."))
    normalized = format(value.normalize(), "f") if value != 0 else "0"
    return NormalizationResult("quantity", raw_value, normalized, "ok")


_TIMESTAMP_DATE_RE = re.compile(
    r"(?<![\d.,:])(?P<first>\d{1,2})\s*(?P<sep>[./-])\s*(?P<second>\d{1,2})\s*(?P=sep)\s*(?P<year>\d{4}|\d{2})(?!\d)"
    r"|ng[àa]y\s*(?P<vn_day>\d{1,2})\s*th[áa]ng\s*(?P<vn_month>\d{1,2})\s*n[ăa]m\s*(?P<vn_year>\d{4})"
    r"|(?<!\d)(?P<iso_year>\d{4})-(?P<iso_month>\d{1,2})-(?P<iso_day>\d{1,2})(?!\d)",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(
    r"(?<![\d.:,])(?P<hour>\d{1,2})(?:\s*:\s*|[.h])(?P<minute>\d{2})(?:(?:\s*:\s*|\.)(?P<second>\d{2}))?(?!\d)"
    r"\s*(?P<meridiem>AM|PM|SA|CH)?",
    re.IGNORECASE,
)


def _parse_calendar_date(match: re.Match[str]) -> date | None:
    """Reads a day-first Vietnamese date (numeric, "Ngày d tháng m năm yyyy" or ISO yyyy-mm-dd); falls back to
    month-first only when day-first is impossible ("8/14/2020")."""
    for year_group, month_group, day_group in (("vn_year", "vn_month", "vn_day"), ("iso_year", "iso_month", "iso_day")):
        if match[day_group]:
            try:
                return date(int(match[year_group]), int(match[month_group]), int(match[day_group]))
            except ValueError:
                return None
    first, second, year_text = int(match["first"]), int(match["second"]), match["year"]
    year = int(year_text) + (2000 if len(year_text) == 2 else 0)
    for day, month in ((first, second), (second, first)):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _parse_clock(match: re.Match[str]) -> tuple[int, int, int] | None:
    """Reads hh:mm[:ss] with an optional AM/PM or Vietnamese SA/CH marker; returns None for impossible times."""
    hour, minute, second = int(match["hour"]), int(match["minute"]), int(match["second"] or 0)
    meridiem = (match["meridiem"] or "").upper()
    if meridiem in ("PM", "CH") and hour < 12:
        hour += 12
    elif meridiem in ("AM", "SA") and hour == 12:
        hour = 0
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour, minute, second


def normalize_timestamp(raw_value: str | None) -> NormalizationResult:
    """Normalizes an invoice timestamp to ISO local date-time ``YYYY-MM-DDTHH:MM:SS`` for the backend contract.

    The value may join several labelled boxes in reading order ("13/08/2020 17:39", "19:50:33 - 14/08/2020",
    "04.10.2020 16.19 04.10.2020 16.21"). The first valid date is used (train GT labels the first or every
    timestamp when a receipt prints two); the time is the clock reading nearest to that date, preferring the
    one after it. Without a time the result uses 00:00:00 and the warning ``TIME_NOT_FOUND``.
    """
    logger.debug("Normalizing timestamp")
    missing = _missing_result("timestamp", raw_value)
    if missing is not None:
        return missing
    assert raw_value is not None
    value = unicodedata.normalize("NFC", raw_value)
    dates = [(match, parsed) for match in _TIMESTAMP_DATE_RE.finditer(value) if (parsed := _parse_calendar_date(match))]
    if not dates:
        logger.debug("Timestamp has no valid date")
        return NormalizationResult("timestamp", raw_value, None, "invalid", ["INVALID_DATE"])
    chosen_match, chosen_date = dates[0]
    without_dates = _TIMESTAMP_DATE_RE.sub(lambda m: " " * len(m.group(0)), value)
    clocks = [(match, parsed) for match in _CLOCK_RE.finditer(without_dates) if (parsed := _parse_clock(match))]
    warnings = ["MULTIPLE_DATE_CANDIDATES"] if len(dates) > 1 else []
    details: dict[str, Any] = {"matched_date": chosen_match.group(0)}
    hour = minute = second = 0
    if clocks:
        def distance(item: tuple[re.Match[str], tuple[int, int, int]]) -> tuple[int, bool]:
            start, end = item[0].start(), item[0].end()
            after = start >= chosen_match.end()
            return (start - chosen_match.end() if after else chosen_match.start() - end, not after)

        clock_match, (hour, minute, second) = min(clocks, key=distance)
        details["matched_time"] = clock_match.group(0).strip()
    else:
        warnings.append("TIME_NOT_FOUND")
    normalized = datetime(chosen_date.year, chosen_date.month, chosen_date.day, hour, minute, second).isoformat()
    return NormalizationResult("timestamp", raw_value, normalized, "ok", warnings, details=details)
