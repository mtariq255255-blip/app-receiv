
"""Conservative Docling invoice table interpreter for ReceivAI UAE.

Public API:
    interpret_tables(layout) -> {
        "items": list,
        "item_evidence": list,
        "warnings": list,
    }

Maps source-backed Docling table cells into tentative invoice items.

Does not invent:
- Quantities
- Unit prices
- Discounts
- Tax rates
- VAT amounts
- Calculated line totals

Financial arithmetic and tax verification belong to financial_reconciler.py.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


MAX_TABLES = 100
MAX_ROWS_PER_TABLE = 500
MAX_ITEMS = 1000
MAX_DESCRIPTION_CHARS = 2000


FIELDS = (
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


MONEY_FIELDS = frozenset({
    "unit_price_aed",
    "discount_aed",
    "taxable_value_aed",
    "vat_amount_aed",
    "line_total_aed",
})


NUMERIC_FIELDS = frozenset(FIELDS) - {
    "description",
    "unit",
}


ALIASES: dict[str, tuple[str, ...]] = {
    "description": (
        "service description",
        "item description",
        "product description",
        "description",
        "particulars",
        "details",
        "service",
        "product",
        "item",
    ),

    "quantity": (
        "quantity",
        "qty",
        "qty.",
        "hours",
        "no of units",
    ),

    "unit": (
        "unit of measure",
        "uom",
        "unit",
    ),

    "unit_price_aed": (
        "unit price",
        "price per unit",
        "price/unit",
        "unit rate",
        "rate",
        "unit cost",
    ),

    "discount_aed": (
        "discount amount",
        "discount aed",
        "disc amount",
        "discount",
        "disc",
        "disc.",
    ),

    "taxable_value_aed": (
        "taxable value",
        "taxable amount",
        "net value",
        "net amount",
        "taxable",
        "net",
    ),

    "vat_rate": (
        "vat %",
        "vat%",
        "vat rate",
        "tax %",
        "tax rate",
        "gst %",
    ),

    "vat_amount_aed": (
        "vat aed",
        "vat (aed)",
        "vat amount",
        "vat value",
        "tax amount",
        "tax aed",
    ),

    "line_total_aed": (
        "line total",
        "total amount",
        "amount (aed)",
        "amount aed",
        "gross total",
        "line amount",
        "total",
        "amount",
    ),
}


NUMBER = re.compile(
    r"^[+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$"
)


SERIAL = re.compile(
    r"^(?:"
    r"s\.?\s*r\.?\s*n\.?"
    r"|s\.?\s*no\.?"
    r"|sr\.?\s*no\.?"
    r"|serial\s*(?:no|number)"
    r"|#"
    r")$",
    re.I,
)


SUMMARY = re.compile(
    r"^(?:"
    r"sub\s*total(?:\s+before\s+discount)?"
    r"|grand\s*total"
    r"|total(?:\s+(?:due|payable|amount))?"
    r"|vat(?:\s*\(?\d+(?:\.\d+)?%\)?)?"
    r"|tax(?:\s+amount)?"
    r"|discounts?"
    r"|balance\s+due"
    r"|amount\s+due"
    r"|taxable\s+(?:amount|value)"
    r"|net\s+amount"
    r"|gross\s+(?:total|subtotal)"
    r")\s*:?$",
    re.I,
)


def _cell(value: Any) -> str:
    """Normalize a source table cell without changing its meaning."""

    return " ".join(
        str(
            value if value is not None else ""
        ).split()
    )


def _normal(value: Any) -> str:
    """Normalize headings for matching."""

    raw = _cell(value).casefold()

    normalized = re.sub(
        r"[^a-z0-9%/ ]+",
        " ",
        raw,
    )

    return " ".join(
        normalized.split()
    )


def _column(name: Any) -> str | None:
    """Identify a table column using explicit heading evidence.

    An unqualified VAT heading needs cell-value inspection because
    it may represent a rate or an amount.
    """

    raw = _cell(name)
    label = _normal(raw)

    if not label:
        return None

    if SERIAL.fullmatch(raw):
        return None

    # Discount percentages are not monetary discounts.
    if re.search(
        r"\b(?:discount|disc)\s*%"
        r"|\b%\s*(?:discount|disc)\b",
        raw,
        re.I,
    ):
        return None

    # A bare VAT column is ambiguous until its cells are examined.
    if label in {
        "vat",
        "tax",
        "gst",
    }:
        return "ambiguous_vat"

    # A heading such as VAT (5%) normally identifies a monetary
    # tax column whose rate is stated in the heading.
    if re.fullmatch(
        r"(?:vat|tax|gst)\s+\d+(?:\.\d+)?%",
        label,
    ):
        return "vat_amount_aed"

    # Prefer exact aliases.
    for field, aliases in ALIASES.items():
        normalized_aliases = {
            _normal(alias)
            for alias in aliases
        }

        if label in normalized_aliases:
            return field

    # Accept explicit currency annotations.
    # Avoid broad substring matching, which can incorrectly
    # classify taxable amounts as grand totals.
    for field, aliases in ALIASES.items():
        for alias in aliases:
            token = _normal(alias)

            if len(token) < 4:
                continue

            if label in {
                f"{token} aed",
                f"{token} dhs",
                f"{token} dh",
            }:
                return field

    return None


def _numeric(
    value: Any,
    *,
    percent: bool = False,
) -> str | None:
    """Parse a source numeric cell conservatively.

    Returns a normalized numeric string, or None.
    Does not calculate or infer missing values.
    """

    raw = _cell(value)

    raw = re.sub(
        r"(?i)\bAED\b",
        "",
        raw,
    ).replace(
        "د.إ",
        "",
    ).strip()

    if percent and raw.endswith("%"):
        raw = raw[:-1].strip()

    elif raw.endswith("%"):
        # A monetary column cannot contain an
        # unqualified percentage.
        return None

    if not NUMBER.fullmatch(raw):
        return None

    normalized = raw.replace(",", "")

    try:
        number = Decimal(normalized)

        if not number.is_finite():
            return None

        if percent and not (
            Decimal("0")
            <= number
            <= Decimal("100")
        ):
            return None

    except InvalidOperation:
        return None

    return normalized


def _resolve_vat_column(
    rows: list,
    col: int,
) -> tuple[str | None, str | None]:
    """Disambiguate a generic VAT column from its actual cells.

    5%  -> VAT rate.
    15.00 under an unqualified VAT heading -> ambiguous.

    A bare numeric value is never automatically interpreted
    as a percentage.
    """

    values = [
        _cell(row[col])
        for row in rows[:MAX_ROWS_PER_TABLE]
        if (
            isinstance(row, (list, tuple))
            and col < len(row)
            and _cell(row[col])
        )
    ]

    if not values:
        return (
            None,
            "VAT column is empty; type cannot be determined.",
        )

    percentages = [
        value
        for value in values
        if value.strip().endswith("%")
    ]

    numeric = [
        value
        for value in values
        if _numeric(value) is not None
    ]

    if (
        len(percentages) == len(values)
        and all(
            _numeric(
                value,
                percent=True,
            ) is not None
            for value in values
        )
    ):
        return "vat_rate", None

    if len(numeric) == len(values):
        return (
            None,
            "Bare VAT column has unqualified numeric values; "
            "review whether they are amounts or rates.",
        )

    return (
        None,
        "VAT column contains mixed or unrecognized formats; "
        "review required.",
    )


def _summary_row(
    description: str,
) -> bool:
    """Check whether a row is an invoice summary, not an item."""

    return bool(
        SUMMARY.fullmatch(
            description.strip()
        )
    )


def _repeated_header(
    desc: str,
    row: list,
    mapping: dict[str, int],
) -> bool:
    """Detect a repeated table header inside the item rows."""

    if _column(desc) != "description":
        return False

    return any(
        col < len(row)
        and _column(row[col]) == field
        for field in (
            "quantity",
            "unit_price_aed",
            "vat_rate",
            "line_total_aed",
        )
        for col in [mapping.get(field)]
        if col is not None
    )


def interpret_tables(
    layout: dict[str, Any],
) -> dict[str, Any]:
    """Convert Docling tables into source-backed invoice items.

    Expected layout:
        {
            "tables": [
                {
                    "table_index": 1,
                    "headers": [...],
                    "rows": [...],
                    "source_page": 1,
                    "bbox": [...]
                }
            ]
        }

    Financial verification is handled separately.
    """

    if not isinstance(layout, dict):
        raise TypeError(
            "layout must be a dictionary"
        )

    items: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []

    tables = layout.get("tables") or []

    if not isinstance(tables, list):
        return {
            "items": [],
            "item_evidence": [],
            "warnings": [
                "Invalid Docling table structure."
            ],
        }

    if len(tables) > MAX_TABLES:
        warnings.append(
            f"Only the first {MAX_TABLES} "
            "tables were examined."
        )

    for table in tables[:MAX_TABLES]:

        if not isinstance(table, dict):
            continue

        table_id = table.get("table_index")

        headers = table.get("headers") or []
        rows = table.get("rows") or []

        if (
            not isinstance(headers, (list, tuple))
            or not isinstance(rows, list)
        ):
            warnings.append(
                f"Table {table_id}: unsupported "
                "headers or rows."
            )
            continue

        # ---------------------------------------------
        # 1. Identify columns
        # ---------------------------------------------

        mapping: dict[str, int] = {}

        for col_index, heading in enumerate(headers):
            field = _column(heading)

            if field == "ambiguous_vat":
                field, warning = _resolve_vat_column(
                    rows,
                    col_index,
                )

                if warning:
                    warnings.append(
                        f"Table {table_id}: {warning}"
                    )

            if (
                field is not None
                and field not in mapping
            ):
                mapping[field] = col_index

        # A valid line-item table needs a description
        # and at least one source monetary column.
        if (
            "description" not in mapping
            or not (
                MONEY_FIELDS & mapping.keys()
            )
        ):
            continue

        # ---------------------------------------------
        # 2. Check table completeness
        # ---------------------------------------------

        if (
            table.get("rows_truncated")
            or table.get("columns_truncated")
            or len(rows) > MAX_ROWS_PER_TABLE
        ):
            warnings.append(
                f"Table {table_id}: rows or columns "
                "may be truncated; review required."
            )

        if len(items) >= MAX_ITEMS:
            warnings.append(
                f"Global maximum of {MAX_ITEMS} "
                "items reached; extraction incomplete."
            )
            break

        last_item_index: int | None = None

        # ---------------------------------------------
        # 3. Interpret table rows
        # ---------------------------------------------

        for row_index, original_row in enumerate(
            rows[:MAX_ROWS_PER_TABLE],
            start=1,
        ):

            if len(items) >= MAX_ITEMS:
                warnings.append(
                    f"Global maximum of {MAX_ITEMS} "
                    "items reached; extraction incomplete."
                )
                break

            if not isinstance(
                original_row,
                (list, tuple),
            ):
                warnings.append(
                    f"Table {table_id}, row {row_index}: "
                    "invalid row structure."
                )
                continue

            row = list(original_row)

            description_column = mapping[
                "description"
            ]

            desc = (
                _cell(row[description_column])
                if description_column < len(row)
                else ""
            )

            # Do not create items from summary rows.
            if _summary_row(desc):
                last_item_index = None
                continue

            # Do not create items from repeated headings.
            if _repeated_header(
                desc,
                row,
                mapping,
            ):
                last_item_index = None
                continue

            # -----------------------------------------
            # 4. Initialize source-backed item
            # -----------------------------------------

            entry: dict[str, Any] = {
                key: None
                for key in FIELDS
            }

            entry["description"] = desc[
                :MAX_DESCRIPTION_CHARS
            ]

            entry["source_table"] = table_id
            entry["source_row"] = row_index

            raw_present: dict[str, bool] = {}
            bad_numeric = False

            # -----------------------------------------
            # 5. Interpret mapped cells
            # -----------------------------------------

            for field, col_index in mapping.items():

                if field == "description":
                    continue

                raw = (
                    _cell(row[col_index])
                    if col_index < len(row)
                    else ""
                )

                raw_present[field] = bool(raw)

                if field in NUMERIC_FIELDS:

                    parsed = (
                        _numeric(
                            raw,
                            percent=(
                                field == "vat_rate"
                            ),
                        )
                        if raw
                        else None
                    )

                    if raw and parsed is None:
                        bad_numeric = True

                        warnings.append(
                            f"Table {table_id}, "
                            f"row {row_index}: "
                            f"unrecognized {field}; "
                            "review source."
                        )

                    entry[field] = parsed

                else:
                    entry[field] = raw or None

            has_numeric_source = any(
                raw_present.get(field, False)
                for field in NUMERIC_FIELDS
            )

            # -----------------------------------------
            # 6. Merge continuation descriptions
            # -----------------------------------------

            if desc and not has_numeric_source:

                if last_item_index is not None:

                    previous = items[
                        last_item_index
                    ]

                    previous["description"] = (
                        previous["description"]
                        + " "
                        + desc
                    )[:MAX_DESCRIPTION_CHARS]

                    evidence[
                        last_item_index
                    ].setdefault(
                        "source_rows",
                        [previous["source_row"]],
                    ).append(
                        row_index
                    )

                continue

            # A numeric row without a description
            # cannot safely become a separate item.
            if not desc:

                if has_numeric_source:
                    warnings.append(
                        f"Table {table_id}, "
                        f"row {row_index}: "
                        "numeric row without description; "
                        "review."
                    )

                last_item_index = None
                continue

            # Require real monetary source evidence.
            if not any(
                entry.get(field) is not None
                for field in MONEY_FIELDS
            ):
                last_item_index = None
                continue

            # Never invent a missing quantity.
            if (
                entry.get("quantity") is None
                and entry.get(
                    "unit_price_aed"
                ) is not None
            ):
                warnings.append(
                    f"Table {table_id}, "
                    f"row {row_index}: "
                    "missing quantity; not inferred."
                )

            if bad_numeric:
                warnings.append(
                    f"Table {table_id}, "
                    f"row {row_index}: "
                    "partial numeric parsing."
                )

            # -----------------------------------------
            # 7. Save line item and provenance
            # -----------------------------------------

            items.append(entry)

            evidence.append({
                "source_page": table.get(
                    "source_page"
                ),
                "bbox": table.get("bbox"),
                "source_table": table_id,
                "source_row": row_index,
                "method": "docling_table",
                "confidence": 0.75,
            })

            last_item_index = (
                len(items) - 1
            )

    return {
        "items": items,
        "item_evidence": evidence,
        "warnings": list(
            dict.fromkeys(warnings)
        ),
    }
