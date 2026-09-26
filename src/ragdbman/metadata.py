# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Deterministic, explicitly labeled facts and keyword vocabulary."""

import re
from datetime import datetime

STOPWORDS = set(
    "the and for with that this from have has are was were will would could should into "
    "your you our their its not".split()
)
CURRENCIES = {"€": "EUR", "$": "USD", "£": "GBP", "¥": "JPY"}
SYSTEM_FIELDS = {
    "price": ("currency", ["cost"]),
    "amount": ("currency", []),
    "total": ("currency", []),
    "discount_percent": ("percentage", ["discount"]),
    "tax_percent": ("percentage", ["tax"]),
    **{
        name: ("number", [])
        for name in ("rating", "score", "rank", "count", "quantity", "version", "weight", "length")
    },
    **{
        name: ("date", [])
        for name in ("date", "published_date", "event_date", "created_date", "updated_date")
    },
}


def candidate_terms(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            m.lower() for m in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text) if m.lower() not in STOPWORDS
        )
    )


def parse_number(text: str, de_style: bool = False) -> float:
    return float(text.replace(".", "").replace(",", ".") if de_style else text.replace(",", ""))


def extract_facts(text: str, locale: str = "en") -> list[dict]:
    facts = []
    de = locale.lower().startswith(("de", "hu"))

    def add(match, name, kind, number=None, date=None, currency=None, unit=None, confidence=0.9):
        facts.append(
            dict(
                field=name,
                kind=kind,
                raw_value=match[0].strip(),
                normalized_number=number,
                normalized_date_utc=date,
                currency_code=currency,
                unit=unit,
                confidence=confidence,
                char_start=match.start(),
                char_end=match.end(),
            )
        )

    for name, label in [("price", "price|cost"), ("amount", "amount"), ("total", "total")]:
        pattern = (
            rf"\b(?:{label})\s*[:=]?\s*([€$£¥])?\s*([0-9][0-9.,]*[0-9]|[0-9])\s*(EUR|USD|GBP|JPY|€|\$|£|¥)?"
        )
        for m in re.finditer(pattern, text, re.I):
            code = CURRENCIES.get(m[1]) or CURRENCIES.get(m[3]) or (m[3].upper() if m[3] else None)
            try:
                add(m, name, "currency", parse_number(m[2], de), currency=code)
            except ValueError:
                pass
    for label in ["discount", "tax"]:
        for m in re.finditer(rf"\b{label}\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*%", text, re.I):
            value = parse_number(m[1], de)
            add(m, label + "_percent", "percentage", value, unit=str(value / 100))
    for label in ["rating", "score", "rank", "count", "quantity", "version", "weight", "length"]:
        units = (
            r"(kg|g|lb|oz)\b"
            if label == "weight"
            else r"(mm|cm|km|m|in|ft)\b"
            if label == "length"
            else r"(?!x)"
        )
        for m in re.finditer(rf"\b{label}\s*[:=]?\s*[#v]?(\d+(?:[.,]\d+)*)(?:\s*{units})?", text, re.I):
            try:
                unit = m[2] if m.lastindex and m.lastindex >= 2 else None
                add(m, label, "number", parse_number(m[1], de), unit=unit, confidence=0.85)
            except ValueError:
                continue  # Multi-component versions are not scalar numbers.
    patterns = [
        (r"\b\d{4}-\d{2}-\d{2}\b", "%Y-%m-%d"),
        (r"\b\d{4}/\d{2}/\d{2}\b", "%Y/%m/%d"),
        (r"\b\d{1,2} [A-Z][a-z]+ \d{4}\b", "%d %B %Y"),
        (r"\b[A-Z][a-z]+ \d{1,2},? \d{4}\b", "%B %d %Y"),
    ]
    for pattern, fmt in patterns:
        for m in re.finditer(pattern, text):
            try:
                date = datetime.strptime(m[0].replace(",", ""), fmt).strftime("%Y-%m-%dT00:00:00Z")
            except ValueError:
                continue
            label = re.search(
                r"\b(published|event|created|updated)\s*(?:date)?\s*[:=]?\s*$",
                text[max(0, m.start() - 40) : m.start()],
                re.I,
            )
            add(m, label[1].lower() + "_date" if label else "date", "date", date=date, confidence=1)
    return facts
