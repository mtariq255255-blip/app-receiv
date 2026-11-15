
"""Reconstruct source-currency invoice item sections from Docling tables.

Public API:
    reconstruct_tables(layout) -> {
        "tables": list,
        "items": list,
        "warnings": list,
    }

This module accepts raw Docling grids and DataFrame-style tables.
It identifies embedded column headers, merges continuation rows and
preserves quantities, units, currency and original table references.

It does not convert currencies, invent missing values, calculate VAT
or approve invoices.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


MAX_TABLES = 100
MAX_ROWS = 500
MAX_COLUMNS = 40
MAX_ITEMS = 1000
MAX_DESCRIPTION_CHARS = 2000


NUMBER = re.compile(
    r"^[+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$"
)

MONEY = re.compile(
    r"^\s*"
    r"(?:(AED|USD|EUR|GBP|INR|د\.إ|US\$|\$|€|£|₹)\s*)?"
    r"([+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(AED|USD|EUR|GBP|INR|د\.إ|US\$|\$|€|£|₹)?"
    r"\s*$",
    re.I,
)


def _text(value: Any) -> str:
    return " ".join(
        str(
            value if value is not None else ""
        ).split()
    )


def _norm(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9%]+",
        " ",
        _text(value).casefold(),
    ).strip()


def _currency(value: Any) -> str | None:
    text = _text(value)

    patterns = (
        ("AED", r"\bAED\b|د\.إ"),
        ("USD", r"\bUSD\b|US\$|\$"),
        ("EUR", r"\bEUR\b|€"),
        ("GBP", r"\bGBP\b|£"),
        ("INR", r"\bINR\b|₹"),
    )

    for code, pattern in patterns:
        if re.search(pattern, text, re.I):
            return code

    return None


def _amount(value: Any) -> str | None:
    match = MONEY.fullmatch(
        _text(value)
    )

    if not match:
        return None

    try:
        number = Decimal(
            match.group(2).replace(",", "")
        )

        return (
            str(number)
            if number.is_finite()
            else None
        )

    except InvalidOperation:
        return None


def _header_kind(value: Any) -> str | None:
    label = _norm(value)

    if not label:
        return None

    # Description / service / product columns
    if (
        any(
            phrase in label
            for phrase in (
                "description",
                "particulars",
                "details of goods",
                "product name",
                "item name",
                "goods services",
            )
        )
        or label in {
            "item",
            "product",
            "service",
            "details",
        }
    ):
        return "description"

    if "container" in label:
        return "container"

    # Quantity
    if (
        "quantity" in label
        or re.fullmatch(
            r"qty\b.*",
            label,
        )
    ):
        return "quantity"

    # Unit of measure
    if (
        "unit of measure" in label
        or label in {
            "uom",
            "unit",
            "units",
        }
    ):
        return "unit"

    # Discount
    if (
        "discount" in label
        or re.fullmatch(
            r"disc\b.*",
            label,
        )
    ):
        if (
            "%" in label
            or "percent" in label
        ):
            return "discount_percent"

        return "discount"

    # VAT / tax
    if (
        "vat" in label
        or "tax" in label
    ):
        if (
            "%" in label
            or "rate" in label
        ):
            return "tax_percent"

        return "tax_unspecified"

    # Unit price
    if (
        any(
            phrase in label
            for phrase in (
                "unit price",
                "unit rate",
                "price per",
                "rate per",
                "fob rate",
                "rate in",
                "unit cost",
            )
        )
        or label in {
            "rate",
            "price",
        }
    ):
        return "unit_price"

    # Line amount / financial amount
    if (
        any(
            phrase in label
            for phrase in (
                "amount",
                "line total",
                "total price",
                "total value",
                "extended price",
                "gross value",
            )
        )
        and not any(
            phrase in label
            for phrase in (
                "taxable",
                "vat",
                "tax amount",
                "discount",
            )
        )
    ):
        return "line_amount"

    if (
        "taxable" in label
        or "net value" in label
    ):
        return "taxable_value"

    return None


def _header_mapping(
    row: list[str],
) -> dict[str, int] | None:
    """Identify source-backed invoice columns.

    A valid item table needs only two recognized fields:
    description and line_amount.

    This supports:
        Service | Amount
        Service | Amount (Dirhams)
        Description | Quantity | Rate | Amount

    Additional fields are optional.
    """

    mapping: dict[str, int] = {}

    for index, cell in enumerate(row):
        kind = _header_kind(cell)

        if (
            kind
            and kind not in mapping
        ):
            mapping[kind] = index

    # FIX:
    # Previously len(mapping) < 3 rejected valid
    # two-column service invoice tables.
    #
    # Both description and line_amount remain mandatory.
    if (
        "description" not in mapping
        or "line_amount" not in mapping
    ):
        return None

    return mapping


def _stop_row(row: list[str]) -> bool:
    meaningful = [
        _norm(value)
        for value in row
        if _text(value)
    ]

    joined = " ".join(meaningful)

    return bool(
        re.search(
            r"\b(?:"
            r"total fob value"
            r"|grand total"
            r"|total due"
            r"|amount due"
            r"|bank name"
            r"|account no"
            r"|swift no"
            r"|declaration"
            r"|authorized signatory"
            r"|shipment documents requirements"
            r")\b",
            joined,
        )
    )


def _continuation(text: str) -> bool:
    normalized = _norm(text)

    if (
        not normalized
        or _stop_row([text])
    ):
        return False

    if re.match(
        r"^(?:"
        r"tolerance"
        r"|packing"
        r"|shipment"
        r"|invoice with"
        r"|bill of lading"
        r"|gstp certificate"
        r"|note"
        r"|name"
        r"|bank"
        r"|account"
        r"|swift"
        r"|ifsc"
        r")\b",
        normalized,
    ):
        return False

    return True


def _table_grid(
    table: dict[str, Any],
) -> tuple[list[list[str]], str]:
    """Read Docling table into a normalized grid."""

    raw = table.get("raw_rows")

    # Prefer structured raw Docling rows when available.
    if (
        table.get("table_structure_available")
        and isinstance(raw, list)
        and raw
    ):
        return (
            [
                [
                    _text(cell)
                    for cell in row[:MAX_COLUMNS]
                ]
                for row in raw[:MAX_ROWS]
                if isinstance(
                    row,
                    (list, tuple),
                )
            ],
            "raw_rows",
        )

    # DataFrame-style fallback
    headers = table.get("headers") or []
    rows = table.get("rows") or []

    if (
        not isinstance(
            headers,
            (list, tuple),
        )
        or not isinstance(rows, list)
    ):
        return [], "invalid"

    result = [
        [
            _text(cell)
            for cell in headers[:MAX_COLUMNS]
        ]
    ]

    result.extend(
        [
            _text(cell)
            for cell in row[:MAX_COLUMNS]
        ]
        for row in rows[:MAX_ROWS]
        if isinstance(
            row,
            (list, tuple),
        )
    )

    return result, "dataframe"


def _row_value(
    row: list[str],
    index: int | None,
) -> str:
    if (
        index is None
        or index < 0
        or index >= len(row)
    ):
        return ""

    return _text(
        row[index]
    )


def reconstruct_tables(
    layout: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct invoice charge sections from Docling tables.

    Output amounts remain in their source currency.
    Table and grid-row references are zero-based.
    """

    if not isinstance(layout, dict):
        raise TypeError(
            "layout must be a dictionary"
        )

    source_tables = (
        layout.get("tables")
        or []
    )

    if not isinstance(source_tables, list):
        return {
            "tables": [],
            "items": [],
            "warnings": [
                "Invalid Docling tables structure."
            ],
        }

    warnings: list[str] = []

    if len(source_tables) > MAX_TABLES:
        warnings.append(
            "Table limit reached; "
            "extraction may be incomplete."
        )

    reconstructed: list[
        dict[str, Any]
    ] = []

    all_items: list[
        dict[str, Any]
    ] = []

    for table in source_tables[
        :MAX_TABLES
    ]:

        if not isinstance(
            table,
            dict,
        ):
            continue

        grid, representation = (
            _table_grid(table)
        )

        if not grid:
            continue

        table_id = table.get(
            "table_index"
        )

        active: dict[
            str, int
        ] | None = None

        active_heading_row: int | None = None

        section_items: list[
            dict[str, Any]
        ] = []

        section_currency: str | None = None

        current_index: int | None = None

        for index, row in enumerate(grid):

            # -----------------------------------------
            # 1. Detect a real item-heading row
            # -----------------------------------------

            mapping = _header_mapping(
                row
            )

            if mapping:
                active = mapping
                active_heading_row = index
                current_index = None

                discovered = {
                    _currency(value)
                    for value in row
                }

                discovered.discard(None)

                section_currency = (
                    next(iter(discovered))
                    if len(discovered) == 1
                    else None
                )

                if len(discovered) > 1:
                    warnings.append(
                        f"Table {table_id}: "
                        "conflicting currencies "
                        "in column headings."
                    )

                continue

            if active is None:
                continue

            # -----------------------------------------
            # 2. Stop at a new non-item section
            # -----------------------------------------

            if _stop_row(row):
                active = None
                current_index = None
                continue

            description = _row_value(
                row,
                active["description"],
            )

            amount_cell = _row_value(
                row,
                active["line_amount"],
            )

            amount = _amount(
                amount_cell
            )

            rate_cell = _row_value(
                row,
                active.get("unit_price"),
            )

            rate = _amount(
                rate_cell
            )

            quantity_cell = _row_value(
                row,
                active.get("quantity"),
            )

            container = _row_value(
                row,
                active.get("container"),
            )

            other_values = [
                _row_value(row, column)
                for key, column in active.items()
                if key != "description"
            ]

            # -----------------------------------------
            # 3. Merge a description-only continuation
            # -----------------------------------------

            if (
                description
                and not any(other_values)
            ):
                if (
                    current_index is not None
                    and _continuation(description)
                ):
                    previous = section_items[
                        current_index
                    ]

                    previous["description"] = (
                        previous["description"]
                        + " "
                        + description
                    )[:MAX_DESCRIPTION_CHARS]

                    previous[
                        "source_rows"
                    ].append(index)

                continue

            # -----------------------------------------
            # 4. Require source-backed amount
            # -----------------------------------------

            if (
                not description
                or amount is None
            ):
                if (
                    description
                    and any(other_values)
                    and not _stop_row(row)
                ):
                    warnings.append(
                        f"Table {table_id}, "
                        f"grid row {index + 1}: "
                        "incomplete charge row "
                        "retained in raw evidence."
                    )

                current_index = None
                continue

            # -----------------------------------------
            # 5. Determine source currency
            # -----------------------------------------

            item_currency = (
                _currency(amount_cell)
                or _currency(rate_cell)
                or section_currency
            )

            observed = {
                _currency(value)
                for value in (
                    amount_cell,
                    rate_cell,
                )
                if _currency(value)
            }

            if len(observed) > 1:
                warnings.append(
                    f"Table {table_id}, "
                    f"grid row {index + 1}: "
                    "conflicting currency symbols."
                )

                item_currency = None

            if (
                section_currency
                and item_currency
                and item_currency
                != section_currency
            ):
                warnings.append(
                    f"Table {table_id}, "
                    f"grid row {index + 1}: "
                    "currency changes within a table."
                )

            if (
                section_currency is None
                and item_currency
            ):
                section_currency = (
                    item_currency
                )

            # -----------------------------------------
            # 6. Keep billable and auxiliary quantities
            #    separate
            # -----------------------------------------

            quantity = (
                _amount(quantity_cell)
                if rate is not None
                else None
            )

            other_quantity = (
                quantity_cell
                if quantity_cell and quantity is None
                else None
            )

            # -----------------------------------------
            # 7. Preserve the source item and provenance
            # -----------------------------------------

            entry: dict[str, Any] = {
                "description": description[
                    :MAX_DESCRIPTION_CHARS
                ],

                "quantity": quantity,

                "unit": (
                    _row_value(
                        row,
                        active.get("unit"),
                    )
                    or None
                ),

                "unit_price": rate,

                "line_amount": amount,

                "currency": item_currency,

                "container": (
                    container or None
                ),

                "other_quantity_text": (
                    other_quantity
                ),

                "discount": _amount(
                    _row_value(
                        row,
                        active.get("discount"),
                    )
                ),

                "taxable_value": _amount(
                    _row_value(
                        row,
                        active.get("taxable_value"),
                    )
                ),

                "tax_rate_text": (
                    _row_value(
                        row,
                        active.get("tax_percent"),
                    )
                    or None
                ),

                "source_page": table.get(
                    "source_page"
                ),

                "source_table": table_id,

                "source_rows": [index],

                "source_representation": (
                    representation
                ),

                "source_bbox": (
                    table.get("bbox_top_left")
                    or table.get("bbox")
                ),
            }

            section_items.append(
                entry
            )

            all_items.append(
                entry
            )

            current_index = (
                len(section_items) - 1
            )

            if len(all_items) >= MAX_ITEMS:
                warnings.append(
                    "Item limit reached; "
                    "extraction may be incomplete."
                )
                break

        if section_items:
            reconstructed.append({
                "source_table": table_id,

                "source_page": table.get(
                    "source_page"
                ),

                "header_row": active_heading_row,

                "currency": section_currency,

                "items": section_items,

                "grid_source": representation,
            })

        if len(all_items) >= MAX_ITEMS:
            break

    return {
        "tables": reconstructed,
        "items": all_items,

        "warnings": list(
            dict.fromkeys(warnings)
        ),
    }
