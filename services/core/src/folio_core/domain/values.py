"""Parsing and normalising attribute values by schema type (date, money, email, ...)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .errors import InvalidInput

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

_MONTH = r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?P<year>\d{4})"

DATE_PATTERNS = [
    re.compile(r"\b(?P<year>\d{4})-(?P<m>\d{2})-(?P<day>\d{2})\b"),
    re.compile(rf"\b{_MONTH}\s+{_DAY}(?:,?\s+{_YEAR})?\b", re.I),
    re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH}(?:,?\s+{_YEAR})?\b", re.I),
    re.compile(rf"\b{_MONTH}\s+{_YEAR}\b", re.I),
]

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"https?://\S+")
MONEY = re.compile(r"(?P<cur>[$€£₹]|USD|EUR|GBP|INR|Rs\.?)\s?(?P<amt>\d[\d,]*(?:\.\d+)?)\s?(?P<mult>k|m|mn|million|lakh|crore)?", re.I)


def find_dates(text: str, today: date | None = None) -> list[tuple[str, int, int]]:
    """Return [(iso_date, start, end)] for every date-like span in ``text``."""
    today = today or date.today()
    found: list[tuple[str, int, int]] = []
    taken: list[tuple[int, int]] = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            iso = _to_iso(m.groupdict(), today)
            if iso:
                found.append((iso, m.start(), m.end()))
                taken.append((m.start(), m.end()))
    return sorted(found, key=lambda t: t[1])


def _to_iso(g: dict[str, str | None], today: date) -> str | None:
    try:
        year = int(g["year"]) if g.get("year") else today.year
        if g.get("m"):
            month = int(g["m"])  # type: ignore[arg-type]
        else:
            mon = (g.get("mon") or "").lower().rstrip(".")
            month = MONTHS.get(mon) or MONTHS[mon[:3]]
        day = int(g["day"]) if g.get("day") else 1
        return date(year, month, day).isoformat()
    except (KeyError, ValueError, TypeError):
        return None


def parse_date(text: str, today: date | None = None) -> str | None:
    hits = find_dates(text, today)
    return hits[0][0] if hits else None


def coerce(attr_type: str, raw: Any) -> Any:
    """Validate/normalise a raw value for an attribute type. Raises InvalidInput."""
    if raw is None:
        raise InvalidInput("value is required")
    text = str(raw).strip()
    if attr_type == "date":
        iso = parse_date(text)
        if not iso:
            raise InvalidInput(f"'{text}' is not a date")
        return iso
    if attr_type == "number":
        try:
            return float(text.replace(",", ""))
        except ValueError as exc:
            raise InvalidInput(f"'{text}' is not a number") from exc
    if attr_type == "email":
        m = EMAIL.search(text)
        if not m:
            raise InvalidInput(f"'{text}' is not an email address")
        return m.group(0).lower()
    if attr_type == "url":
        if not URL.match(text):
            raise InvalidInput(f"'{text}' is not a URL")
        return text
    if attr_type == "money":
        if not MONEY.search(text) and not re.fullmatch(r"\d[\d,]*(\.\d+)?", text):
            raise InvalidInput(f"'{text}' is not an amount")
        return text
    if not text:
        raise InvalidInput("value is empty")
    return text
