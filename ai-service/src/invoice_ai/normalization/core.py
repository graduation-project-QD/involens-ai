"""Versioned normalizers for the four canonical invoice fields."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

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
