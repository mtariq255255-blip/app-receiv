

"""ReceivAI UAE document intelligence orchestrator.

Docling-primary interpretation with currency-neutral reconstruction.

Public APIs:

    interpret_layout(layout, native_invoice=None)

    process_pdf_document(

        pdf_path,

        *,

        native_result=None,

        force_docling=False,

        mode="accurate",

        artifacts_path=None,

    )

This module:

- Resolves source-backed invoice header candidates.

- Uses the existing AED table interpreter.

- Adds raw-table reconstruction for irregular invoices.

- Preserves source amounts in AED, USD or other currencies.

- Keeps native and Docling conflicts visible.

- Performs AED reconciliation only on appropriate AED data.

- Never approves invoices or converts currencies.

Production PDF conversion must use the authenticated private

Docling worker. process_pdf_document is a standalone local adapter.

"""

from __future__ import annotations

import os

import re

from copy import deepcopy

from datetime import datetime

from decimal import Decimal, InvalidOperation

from pathlib import Path

from typing import Any

from .document_router import route_document

from .evidence_resolver import resolve_fields

from .financial_reconciler import reconcile_finances

from .semantic_mapper import map_header_fields

from .table_interpreter import interpret_tables

from .table_reconstructor import reconstruct_tables

ALLOWED_FIELD_KEYS = (

    "invoice_number",

    "supplier_name",

    "supplier_trn",

    "customer_name",

    "customer_trn",

    "issue_date",

    "supply_date",

    "due_date",

    "payment_terms",

    "currency",

    "subtotal_aed",

    "discount_aed",

    "vat_amount_aed",

    "total_amount_aed",

)

AED_FIELDS = frozenset({

    "subtotal_aed",

    "subtotal_before_discount_aed",

    "discount_aed",

    "vat_amount_aed",

    "total_amount_aed",

})

ITEM_COMPARE_KEYS = (

    "description",

    "quantity",

    "unit",

    "unit_price_aed",

    "discount_aed",

    "taxable_value_aed",

    "vat_rate",

    "vat_amount_aed",

    "line_total_aed",

)

NUMERIC_ITEM_KEYS = frozenset(

    ITEM_COMPARE_KEYS

) - {"description", "unit"}

MAX_RAW_ROWS = 500

MAX_SOURCE_ITEMS = 1000

DATE_FORMATS = (

    "%d.%m.%Y",

    "%d/%m/%Y",

    "%d-%m-%Y",

    "%Y-%m-%d",

    "%d %b %Y",

    "%d %B %Y",

)

def _present(value: Any) -> bool:

    return (

        value is not None

        and value != ""

        and value != []

    )

def _text(value: Any) -> str:

    return " ".join(

        str(value if value is not None else "").split()

    )

def _uniq(values: list[Any]) -> list[str]:

    return list(dict.fromkeys(

        str(value).strip()

        for value in values

        if value is not None and str(value).strip()

    ))

def _decimal(value: Any) -> Decimal | None:

    if value is None or isinstance(value, (bool, float)):

        return None

    raw = _text(value).replace(",", "")

    raw = re.sub(

        r"^(?:AED|USD|US\$|\$|د\.إ)\s*",

        "",

        raw,

        flags=re.I,

    )

    try:

        number = Decimal(raw)

    except (InvalidOperation, ValueError):

        return None

    return number if number.is_finite() else None

def _normalize_date(value: str) -> str | None:

    raw = _text(value)

    for fmt in DATE_FORMATS:

        try:

            return datetime.strptime(

                raw, fmt

            ).date().isoformat()

        except ValueError:

            continue

    return None

def _native_candidate(

    field: str,

    value: Any,

) -> dict[str, Any]:

    return {

        "field": field,

        "value": value,

        "source_text": None,

        "source_page": None,

        "bbox": None,

        "method": "native_parser",

        "confidence": None,

    }

def _raw_candidate(

    field: str,

    value: Any,

    text: str,

    page: int | None,

) -> dict[str, Any]:

    return {

        "field": field,

        "value": value,

        "source_text": text[:2000],

        "source_page": page,

        "bbox": None,

        "method": "docling_raw_table",

        "confidence": None,

    }

def _comparison_value(

    key: str,

    value: Any,

) -> str | None:

    if not _present(value):

        return None

    raw = _text(value)

    if key in NUMERIC_ITEM_KEYS:

        number = _decimal(raw)

        if number is not None:

            return str(number.normalize())

    return raw.casefold()

def _compare_item_sets(

    native: list[dict[str, Any]],

    docling: list[dict[str, Any]],

) -> tuple[str, list[str]]:

    """Compare AED item rows without silently selecting a source."""

    if len(native) != len(docling):

        return (

            "conflicting",

            [

                "Line-item count differs: "

                f"native={len(native)}, Docling={len(docling)}."

            ],

        )

    differences: list[str] = []

    incomplete = False

    for number, (a, b) in enumerate(

        zip(native, docling),

        start=1,

    ):

        if not isinstance(a, dict) or not isinstance(b, dict):

            differences.append(

                f"Row {number}: invalid item structure."

            )

            continue

        for key in ITEM_COMPARE_KEYS:

            va = _comparison_value(key, a.get(key))

            vb = _comparison_value(key, b.get(key))

            if va is None or vb is None:

                if va != vb:

                    incomplete = True

                continue

            if va != vb:

                differences.append(

                    f"Row {number}: native and Docling "

                    f"disagree on {key}."

                )

    if differences:

        return "conflicting", differences

    if incomplete:

        return "incomplete", []

    return "consistent", []

def _currency_marker(value: Any) -> str | None:

    """Recognize explicit currency markers."""

    raw = _text(value)

    matches = set()

    patterns = (

        ("AED", r"\bAED\b|د\.إ"),

        ("USD", r"\bUSD\b|US\$|\$"),

        ("EUR", r"\bEUR\b|€"),

        ("GBP", r"\bGBP\b|£"),

        ("INR", r"\bINR\b|₹"),

    )

    for currency, pattern in patterns:

        if re.search(pattern, raw, re.I):

            matches.add(currency)

    return next(iter(matches)) if len(matches) == 1 else None

def _source_currency(

    items: list[dict[str, Any]],

    resolved: Any,

    native: Any,

) -> tuple[str | None, bool]:

    """Collect currency candidates without guessing."""

    values = set()

    for item in items:

        if isinstance(item, dict) and _present(item.get("currency")):

            values.add(_text(item["currency"]).upper())

    for candidate in (resolved, native):

        if _present(candidate):

            values.add(_text(candidate).upper())

    if len(values) == 1:

        return next(iter(values)), False

    return None, len(values) > 1

def _raw_table_rows(

    layout: dict[str, Any],

):

    """Yield bounded original rows, including internal headers."""

    for table in (layout.get("tables") or [])[:100]:

        if not isinstance(table, dict):

            continue

        page = table.get("source_page")

        raw = table.get("raw_rows")

        if not isinstance(raw, list) or not raw:

            headers = table.get("headers") or []

            rows = table.get("rows") or []

            raw = [headers] + list(rows)

        for index, values in enumerate(raw[:MAX_RAW_ROWS]):

            if not isinstance(values, (list, tuple)):

                continue

            yield (

                table.get("table_index"),

                page,

                index,

                [_text(value) for value in values],

            )

def _raw_header_candidates(

    layout: dict[str, Any],

) -> tuple[

    dict[str, list[dict[str, Any]]],

    dict[str, Any],

]:

    """Recover explicitly labelled fields from raw Docling grids.

    Never infer supplier, date, currency, tax or total from

    unrelated text. Preserve conflicting field candidates.

    """

    candidates: dict[

        str, list[dict[str, Any]]

    ] = {}

    details: dict[str, Any] = {

        "document_type": None,

        "source_total_amount": None,

        "source_total_evidence": [],

        "warnings": [],

    }

    all_rows = list(_raw_table_rows(layout))

    markdown = _text(layout.get("text", ""))

    if re.search(r"\bproforma\s+invoice\b", markdown, re.I):

        details["document_type"] = "proforma_invoice"

    elif re.search(r"\bcredit\s+note\b", markdown, re.I):

        details["document_type"] = "credit_note"

    elif re.search(r"\btax\s+invoice\b", markdown, re.I):

        details["document_type"] = "tax_invoice"

    def append(

        field: str,

        value: Any,

        source: str,

        page: int | None,

    ) -> None:

        if not _present(value):

            return

        candidates.setdefault(field, []).append(

            _raw_candidate(field, value, source, page)

        )

    for position, (

        table_index,

        page,

        row_index,

        cells,

    ) in enumerate(all_rows):

        joined = " | ".join(cells)

        lower = joined.casefold()

        # 1. Explicitly labelled exporter/supplier.

        for cell in cells:

            match = re.search(

                r"^\s*(?:exporter|supplier|seller|vendor)\s*"

                r"[:\-]\s*(.+)$",

                cell,

                re.I,

            )

            if match:

                append(

                    "supplier_name",

                    match.group(1).strip(),

                    cell,

                    page,

                )

        # 2. Explicit invoice or proforma identifier.

        for cell in cells:

            match = re.search(

                r"\b(?:proforma\s+invoice\s+no|"

                r"invoice\s*(?:number|no\.?|#)|"

                r"PI\s*no\.?)\s*[:\-]?\s*"

                r"([A-Z0-9][A-Z0-9/_\-.]{2,})",

                cell,

                re.I,

            )

            if match:

                value = match.group(1).strip()

                if value.upper() not in {

                    "NO", "NUMBER", "DATE", "TERMS"

                }:

                    append(

                        "invoice_number",

                        value,

                        cell,

                        page,

                    )

        # 3. Explicit date heading with aligned value below.

        if position + 1 < len(all_rows):

            (

                next_table,

                next_page,

                next_index,

                next_cells,

            ) = all_rows[position + 1]

            # Prevent crossing table boundaries.

            if next_page == page and next_table == table_index:

                for column, heading in enumerate(cells):

                    normalized = heading.strip().casefold()

                    if normalized not in {

                        "date",

                        "invoice date",

                        "issue date",

                        "pi date",

                    }:

                        continue

                    if column >= len(next_cells):

                        continue

                    parsed = _normalize_date(next_cells[column])

                    if parsed:

                        append(

                            "issue_date",

                            parsed,

                            next_cells[column],

                            page,

                        )

        # 4. Date directly labelled within one cell.

        for cell in cells:

            match = re.search(

                r"^(?:invoice date|issue date|PI date)"

                r"\s*[:\-]\s*(.+)$",

                cell,

                re.I,

            )

            if match:

                parsed = _normalize_date(match.group(1))

                if parsed:

                    append(

                        "issue_date",

                        parsed,

                        cell,

                        page,

                    )

        # 5. Terms written directly in a labelled cell.

        for cell in cells:

            match = re.search(

                r"^terms\s+of\s+payment\s*[:\-]\s*(.+)$",

                cell,

                re.I,

            )

            if match:

                append(

                    "payment_terms",

                    match.group(1).strip(),

                    cell,

                    page,

                )

        # 6. FIX: Terms below an aligned column heading.

        #

        # A merged heading may span several columns.

        # Docling stores its text at the anchor column.

        # We must read the next row at that SAME column,

        # not join the entire row with the supplier address.

        if (

            position + 1 < len(all_rows)

            and any(

                re.search(

                    r"\bterms\s+of\s+payment\b",

                    heading,

                    re.I,

                )

                for heading in cells

            )

        ):

            (

                next_table,

                next_page,

                next_index,

                next_cells,

            ) = all_rows[position + 1]

            if next_page == page and next_table == table_index:

                for column, heading in enumerate(cells):

                    if not re.search(

                        r"\bterms\s+of\s+payment\b",

                        heading,

                        re.I,

                    ):

                        continue

                    if column >= len(next_cells):

                        continue

                    terms = next_cells[column].strip()

                    if (

                        terms

                        and re.search(

                            r"\b(?:advance|against|days|receipt|"

                            r"credit|payment)\b",

                            terms,

                            re.I,

                        )

                    ):

                        append(

                            "payment_terms",

                            terms,

                            terms,

                            page,

                        )

        # 7. Explicit printed totals.

        if re.search(

            r"\b(?:total\s+fob\s+value|"

            r"grand\s+total|total\s+due|"

            r"amount\s+due)\b",

            lower,

            re.I,

        ):

            numeric_cells = []

            for cell in cells:

                money = re.search(

                    r"(?:(?:AED|USD|US\$|\$|د\.إ)\s*)?"

                    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|"

                    r"\d+(?:\.\d+)?)\s*$",

                    cell,

                    re.I,

                )

                if money:

                    value = _decimal(money.group(1))

                    if value is not None:

                        numeric_cells.append((cell, value))

            if numeric_cells:

                source, value = numeric_cells[-1]

                evidence = {

                    "value": str(value),

                    "source_text": joined[:2000],

                    "source_page": page,

                    "source_table": table_index,

                    "source_row": row_index,

                }

                details["source_total_evidence"].append(evidence)

                currency = _currency_marker(source)

                if currency:

                    append(

                        "currency",

                        currency,

                        source,

                        page,

                    )

        # 8. Currency explicitly written in item headings.

        if (

            "amount in" in lower

            or "rate in" in lower

            or "rate per" in lower

        ):

            for cell in cells:

                if re.search(

                    r"\b(?:amount|price|rate)\b",

                    cell,

                    re.I,

                ):

                    currency = _currency_marker(cell)

                    if currency:

                        append(

                            "currency",

                            currency,

                            cell,

                            page,

                        )

    printed_totals = {

        entry["value"]

        for entry in details["source_total_evidence"]

    }

    if len(printed_totals) == 1:

        details["source_total_amount"] = next(

            iter(printed_totals)

        )

    elif len(printed_totals) > 1:

        details["warnings"].append(

            "Multiple different printed totals were found; "

            "source total requires review."

        )

    for field, observations in candidates.items():

        unique = []

        seen = set()

        for candidate in observations:

            identity = (

                str(candidate["value"]).casefold(),

                candidate["source_page"],

                candidate["source_text"],

            )

            if identity not in seen:

                seen.add(identity)

                unique.append(candidate)

        candidates[field] = unique[:30]

    return candidates, details

# English amount-in-words values are independent documentary evidence.
# Never use this reader to guess missing VAT or unit prices.
_WORD_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

def _english_number_words(value: str) -> int | None:
    """Decode a bounded nonnegative integer expressed in English words."""
    words = re.findall(r"[a-z]+", value.casefold().replace("-", " "))
    if not words or len(words) > 35:
        return None
    total = group = 0
    saw_number = False
    for word in words:
        if word == "and":
            continue
        if word in _WORD_UNITS:
            group += _WORD_UNITS[word]
            saw_number = True
        elif word == "hundred":
            if group < 1 or group > 9:
                return None
            group *= 100
        elif word in {"thousand", "million"}:
            scale = 1000 if word == "thousand" else 1000000
            if group < 1 or total >= scale:
                return None
            total += group * scale
            group = 0
        else:
            return None
    return total + group if saw_number else None

def _written_amount_candidates(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Read explicitly labeled English amounts-in-words from Docling text.

    This is an evidence parser, not a generic invoice total detector.
    Unsupported words or ambiguous currency return no candidate.
    """
    segments: list[tuple[str, int | None]] = []
    if isinstance(layout.get("text"), str):
        segments.append((layout["text"], None))
    for block in (layout.get("text_blocks") or [])[:1500]:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            segments.append((block["text"], block.get("source_page")))

    found: dict[tuple[str, str], dict[str, Any]] = {}
    for text, page in segments:
        # Keep one line/paragraph. Avoid borrowing unrelated document text.
        for match in re.finditer(
            r"\bamount\s+in\s+words\s*[:\-]?\s*([^\n\r]{1,180})",
            text, re.I,
        ):
            source = _text(match.group(0))
            phrase = _text(match.group(1))
            phrase = re.split(r"\s*\|\s*|[.;]", phrase, maxsplit=1)[0]
            phrase = re.sub(r"\s+only\b.*$", "", phrase, flags=re.I).strip()
            prefix = re.match(
                r"^(?:uae\s+)?(dirhams?|aed|us\s+dollars?|usd|dollars?)\s+(.+)$",
                phrase, re.I,
            )
            if prefix:
                cur = "AED" if re.search(r"dirham|aed", prefix.group(1), re.I) else "USD"
                main_phrase = prefix.group(2)
            else:
                suffix = re.match(r"^(.+?)\s+(dirhams?|dollars?)\b(.*)$", phrase, re.I)
                if not suffix:
                    continue
                cur = "AED" if "dirham" in suffix.group(2).casefold() else "USD"
                main_phrase = suffix.group(1) + suffix.group(3)

            minor = 0
            minor_match = re.search(
                r"\s+and\s+(.+?)\s+(?:fils?|cents?)\b", main_phrase, re.I,
            )
            if minor_match:
                minor_value = _english_number_words(minor_match.group(1))
                if minor_value is None or not 0 <= minor_value < 100:
                    continue
                minor = minor_value
                main_phrase = main_phrase[:minor_match.start()].strip()
            else:
                main_phrase = re.sub(r"\s+and\s+no\s+(?:fils?|cents?)$", "", main_phrase, flags=re.I)

            major = _english_number_words(main_phrase)
            if major is None:
                continue
            amount = Decimal(major) + Decimal(minor) / Decimal(100)
            key = (cur, str(amount))
            found.setdefault(key, {
                "value": str(amount), "currency": cur,
                "source_text": source[:500], "source_page": page,
                "method": "amount_in_words",
            })
    return list(found.values())

def _single_line_total_evidence(
    layout: dict[str, Any],
    items: list[dict[str, Any]],
    currency: str | None,
    mixed_currency: bool,
) -> dict[str, Any] | None:
    """Propose source payable total when independent words match one line."""
    if mixed_currency or not currency or len(items) != 1:
        return None
    line = items[0]
    if not isinstance(line, dict) or _text(line.get("currency")).upper() != currency:
        return None
    amount = _decimal(line.get("line_amount"))
    if amount is None or amount <= 0:
        return None
    words = _written_amount_candidates(layout)
    # Multiple distinct written amounts/currencies are ambiguous.
    if len(words) != 1:
        return None
    evidence = words[0]
    if evidence["currency"] != currency or _decimal(evidence["value"]) != amount:
        return None
    return evidence

def _source_total_check(

    items: list[dict[str, Any]],

    printed_total: Any,

    currency: str | None,

    mixed_currency: bool,

) -> dict[str, Any]:

    """Reconcile source-currency line totals against printed total."""

    result = {

        "currency": currency,

        "sum_of_source_line_totals": None,

        "printed_total": (

            str(printed_total)

            if _present(printed_total)

            else None

        ),

        "reconciled": None,

        "complete": False,

        "issues": [],

    }

    if mixed_currency or not currency:

        result["issues"].append(

            "Source currency is missing or conflicting."

        )

        return result

    if not items:

        return result

    amounts = []

    for item in items:

        if not isinstance(item, dict):

            return result

        if _text(item.get("currency")).upper() != currency:

            result["issues"].append(

                "At least one charge has an unknown "

                "or different currency."

            )

            return result

        amount = _decimal(item.get("line_amount"))

        if amount is None:

            return result

        amounts.append(amount)

    total = sum(amounts, Decimal("0"))

    result["complete"] = True

    result["sum_of_source_line_totals"] = str(total)

    printed = _decimal(printed_total)

    if printed is not None:

        result["reconciled"] = (

            abs(total - printed) <= Decimal("0.01")

        )

        if not result["reconciled"]:

            result["issues"].append(

                "The sum of reconstructed charge rows "

                "does not match the printed source total."

            )

    return result

def interpret_layout(

    layout: dict[str, Any],

    native_invoice: dict[str, Any] | None = None,

) -> dict[str, Any]:

    """Interpret Docling layout without approving the invoice."""

    if not isinstance(layout, dict):

        raise TypeError("layout must be a dictionary")

    if (

        native_invoice is not None

        and not isinstance(native_invoice, dict)

    ):

        raise TypeError(

            "native_invoice must be a dictionary or None"

        )

    native_invoice = native_invoice or {}

    candidates = map_header_fields(layout)

    raw_candidates, raw_details = _raw_header_candidates(layout)

    for field, entries in raw_candidates.items():

        candidates.setdefault(field, []).extend(entries)

    for field in ALLOWED_FIELD_KEYS:

        value = native_invoice.get(field)

        if _present(value):

            candidates.setdefault(field, []).append(

                _native_candidate(field, value)

            )

    resolution = resolve_fields(candidates)

    values = deepcopy(native_invoice)

    values.update(resolution["fields"])

    unresolved = list(

        resolution.get("unresolved_fields") or []

    )

    field_status = dict(

        resolution.get("field_status") or {}

    )

    interpreted = interpret_tables(layout)

    reconstruction = reconstruct_tables(layout)

    docling_items = interpreted.get("items") or []

    source_items = [

        deepcopy(item)

        for item in (

            reconstruction.get("items") or []

        )[:MAX_SOURCE_ITEMS]

        if isinstance(item, dict)

    ]

    currency, mixed_currency = _source_currency(

        source_items,

        values.get("currency"),

        native_invoice.get("currency"),

    )

    if mixed_currency:

        unresolved.append("currency")

        values["currency"] = None

    elif currency:

        values["currency"] = currency

    values["source_items"] = source_items

    values["document_type"] = (

        raw_details.get("document_type")

        or values.get("document_type")

    )

    if not mixed_currency:

        values["source_total_amount"] = (

            raw_details.get("source_total_amount")

        )

    # One-line service invoices may state the payable amount only in words.
    # Require independent agreement with that source line, and do not
    # replace an explicit printed total or create AED accounting tax values.
    single_line_evidence = None
    if not _present(values.get("source_total_amount")):
        single_line_evidence = _single_line_total_evidence(
            layout, source_items, currency, mixed_currency,
        )
        if single_line_evidence is not None:
            values["source_total_amount"] = single_line_evidence["value"]
            raw_details["source_total_evidence"].append(
                deepcopy(single_line_evidence)
            )

    if currency and currency != "AED":

        for field in AED_FIELDS:

            values[field] = None

    native_items = native_invoice.get("items")

    if (

        native_items is not None

        and not isinstance(native_items, list)

    ):

        native_items = None

        unresolved.append("items")

    if not isinstance(docling_items, list):

        docling_items = []

        unresolved.append("items")

    item_comparison = "single_source"

    comparison_notes: list[str] = []

    if currency and currency != "AED":

        values["items"] = []

    elif native_items and docling_items:

        item_comparison, comparison_notes = _compare_item_sets(

            native_items,

            docling_items,

        )

        values["items"] = deepcopy(native_items)

        if item_comparison != "consistent":

            unresolved.append("items")

            if item_comparison == "incomplete":

                comparison_notes.append(

                    "Native and Docling rows differ in "

                    "field completeness; review required."

                )

    elif native_items:

        values["items"] = deepcopy(native_items)

    else:

        values["items"] = deepcopy(docling_items)

    if not _present(values.get("currency")):

        unresolved.append("currency")

        field_status.setdefault("currency", "unresolved")

    if not _present(values.get("supplier_name")):

        unresolved.append("supplier_name")

        field_status.setdefault(

            "supplier_name", "unresolved"

        )

    if not _present(values.get("due_date")):

        unresolved.append("due_date")

        field_status.setdefault("due_date", "unresolved")

    if not values.get("items") and not source_items:

        unresolved.append("items")

    if currency == "AED":

        if any(

            not isinstance(item, dict)

            or not _present(item.get("vat_rate"))

            for item in (values.get("items") or [])

        ):

            unresolved.append("items.vat_rate")

            field_status.setdefault(

                "items.vat_rate", "unresolved"

            )

    elif currency and currency != "AED":

        unresolved.append("tax_treatment")

    source_financials = _source_total_check(

        source_items,

        values.get("source_total_amount"),

        currency,

        mixed_currency,

    )

    values["source_totals_reconciled"] = (

        source_financials["reconciled"]

    )

    if currency and currency != "AED":

        financials = {

            "issues": [],

            "warnings": [

                "AED reconciliation not applicable "

                "to this source-currency document."

            ],

            "requires_review": True,

            "source_total_reconciled": None,

            "source_summary_reconciled": None,

            "tax_calculation_verified": None,

        }

    else:

        financials = reconcile_finances(values)

    financial_issues = list(

        financials.get("issues") or []

    )

    financial_warnings = list(

        financials.get("warnings") or []

    )

    if financial_issues:

        unresolved.append("financial_reconciliation")

    if source_financials["issues"]:

        unresolved.append("source_financial_reconciliation")

    notes = _uniq(

        list(layout.get("warnings") or [])

        + list(interpreted.get("warnings") or [])

        + list(reconstruction.get("warnings") or [])

        + list(

            resolution.get("resolution_notes") or []

        )

        + list(raw_details.get("warnings") or [])

        + comparison_notes

        + financial_issues

        + financial_warnings

        + source_financials["issues"]

        + ([
            "Single-line payable amount is supported by the source amount "
            "in words; administrator verification of VAT and invoice total "
            "is still required."
        ] if single_line_evidence is not None else [])

    )

    if mixed_currency:

        notes.append(

            "Conflicting source currencies; review required."

        )

    if currency and currency != "AED":

        notes.append(

            "Original amounts retained in source_items "

            "and source_total_amount. No AED conversion "

            "was performed."

        )

    notes = _uniq(notes)

    unknown = sorted(set(unresolved))

    if (

        item_comparison == "conflicting"

        or source_financials["reconciled"] is False

    ):

        financial_status = "discrepancy"

    elif currency and currency != "AED":

        financial_status = (

            "source_total_reconciled"

            if source_financials["reconciled"] is True

            else "source_currency_review_required"

        )

    elif (

        financial_issues

        or financials.get("source_total_reconciled") is False

    ):

        financial_status = "discrepancy"

    elif financials.get("requires_review"):

        financial_status = "partial_review_required"

    elif financials.get("source_total_reconciled") is True:

        financial_status = "source_total_reconciled"

    else:

        financial_status = "not_fully_verified"

    manual_review = bool(

        unknown

        or notes

        or financials.get("requires_review")

        or mixed_currency

    )

    return {

        "invoice": values,

        "field_evidence": resolution.get(

            "field_evidence", {}

        ),

        "item_evidence": interpreted.get(

            "item_evidence", []

        ),

        "unresolved_fields": unknown,

        "extraction_notes": notes,

        "financial_reconciliation": financials,

        "source_financial_reconciliation": source_financials,

        "manual_review_required": manual_review,

        "engine": layout.get("engine", "docling"),

        "page_count": layout.get("page_count"),

        "processing_seconds": layout.get("processing_seconds"),

        "field_status": field_status,

        "field_conflicts": resolution.get(

            "field_conflicts", {}

        ),

        "resolution_notes": list(

            resolution.get("resolution_notes") or []

        ),

        "financial_warnings": financial_warnings,

        "financial_issues": financial_issues,

        "item_comparison_status": item_comparison,

        "item_comparison_notes": comparison_notes,

        "alternative_items": (

            {

                "native": native_items,

                "docling": docling_items,

            }

            if (

                native_items

                and docling_items

                and item_comparison != "consistent"

            )

            else None

        ),

        "reconstruction": {

            "table_count": len(

                reconstruction.get("tables") or []

            ),

            "item_count": len(source_items),

            "warnings": reconstruction.get("warnings") or [],

        },

        "source_items": source_items,

        "source_currency": currency,

        "source_currency_conflict": mixed_currency,

        "source_total_evidence": raw_details.get(

            "source_total_evidence", []

        ),

        "source_total_origin": (
            "amount_in_words_single_line"
            if single_line_evidence is not None
            else "explicit_printed_total"
            if _present(raw_details.get("source_total_amount"))
            else None
        ),

        "extraction_status": (

            "review_required"

            if manual_review

            else "no_review_triggers"

        ),

        "financial_status": financial_status,

        "tax_calculation_verified": financials.get(

            "tax_calculation_verified"

        ),

        "ready_for_posting": None,

        "ready_for_collections": None,

    }

def process_pdf_document(

    pdf_path: str | Path,

    *,

    native_result: dict[str, Any] | None = None,

    force_docling: bool = False,

    mode: str = "accurate",

    artifacts_path: str | Path | None = None,

) -> dict[str, Any]:

    """Standalone local PDF adapter.

    Production uses the authenticated private Docling worker.

    """

    primary = os.getenv(

        "RECEIVAI_DOCLING_PRIMARY", "false"

    ).strip().lower() in {

        "1", "true", "yes", "on"

    }

    decision = route_document(

        native_result,

        force_docling=force_docling or primary,

    )

    if not decision.get("use_docling"):

        return {

            "processing_mode": "NATIVE",

            "route": decision,

            "native_result": native_result,

            "docling_used": False,

        }

    from .layout_engine import extract_pdf_layout

    layout = extract_pdf_layout(

        pdf_path,

        mode=mode,

        artifacts_path=artifacts_path,

    )

    invoices = (

        native_result.get("invoices", [])

        if isinstance(native_result, dict)

        else []

    )

    if not isinstance(invoices, list):

        invoices = []

    if len(invoices) > 1:

        return {

            "processing_mode": "REVIEW_REQUIRED",

            "route": decision,

            "docling_used": True,

            "layout": layout,

            "manual_review_required": True,

            "extraction_notes": [

                "Multiple native invoices detected; "

                "segmentation required before merging."

            ],

        }

    native_invoice = (

        invoices[0]

        if invoices and isinstance(invoices[0], dict)

        else None

    )

    interpretation = interpret_layout(

        layout,

        native_invoice,

    )

    return {

        "processing_mode": "DOCLING_LAYOUT",

        "route": decision,

        "docling_used": True,

        "interpretation": interpretation,

    }
