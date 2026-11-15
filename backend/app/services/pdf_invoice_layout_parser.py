
"""Position-aware, local-only invoice parser for machine-readable PDFs.

Consumes the ``layout_pages`` contract from ``pdf_extractor.extract_pdf`` and
returns ``(list[UAEInvoiceExtractionSchema dictionaries], notes)``.

This is a deterministic fast-path, NOT a universal document-understanding model.
Missing VAT, supplier identity, and ambiguous payment terms remain unknown.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.schemas.uae_invoice import UAEInvoiceExtractionSchema

CENT = Decimal("0.01")

TRN_RE = re.compile(r"(?<!\d)\d{15}(?!\d)")

EMAIL_RE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
)

INVOICE_ID_RE = re.compile(
    r"\b(?:INV|INVOICE|RAI)[-/ ]?\d{2,}(?:[-/]\w+)*\b",
    re.I,
)

AMOUNT_RE = re.compile(
    r"^\s*(?:AED\s*)?([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d{1,2})?)\s*(?:AED)?\s*$",
    re.I,
)

DATE_PATTERNS = (
    re.compile(
        r"\b\d{1,2}(?:st|nd|rd|th)?[ /-]+"
        r"[A-Za-z]{3,9},?[ /-]+\d{4}\b",
        re.I,
    ),
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"),
)

PARTIES = {
    "supplier": (
        "supplier",
        "seller",
        "vendor",
        "issued by",
        "from",
        "service provider",
    ),
    "customer": (
        "bill to",
        "billed to",
        "invoice to",
        "invoice for",
        "buyer",
        "customer",
        "client",
        "sold to",
    ),
}

DATE_LABELS = {
    "issue_date": (
        "invoice date",
        "date of issue",
        "issued on",
        "issue date",
        "date issued",
    ),
    "due_date": (
        "due date",
        "payment due date",
        "payment due",
        "due on",
    ),
    "supply_date": (
        "supply date",
        "date of supply",
    ),
}

TOTAL_LABELS = {
    "total_amount_aed": (
        "total amount due",
        "total due",
        "grand total",
        "amount due",
        "amount payable",
        "invoice total",
        "total payable",
        "total",
    ),
    "subtotal_aed": (
        "subtotal",
        "sub total",
        "taxable amount",
        "net taxable amount",
        "net amount",
    ),
    "discount_aed": (
        "total discount",
        "invoice discount",
        "less: discounts",
        "discounts",
        "discount",
    ),
    "vat_amount_aed": (
        "total vat",
        "vat amount",
        "vat (5%)",
        "vat 5%",
        "vat total",
        "vat",
    ),
}

COLUMN_ALIASES = {
    "description": (
        "description",
        "service description",
        "item description",
        "details",
        "particulars",
        "product",
        "services",
    ),
    "quantity": (
        "qty",
        "quantity",
        "units",
        "no of units",
    ),
    "unit_price_aed": (
        "unit price",
        "rate",
        "price",
        "unit rate",
    ),
    "discount_aed": (
        "discount",
        "disc",
        "disc.",
        "disc amount",
    ),
    "taxable_value_aed": (
        "taxable",
        "taxable amount",
        "taxable value",
        "net",
        "net amount",
    ),
    "vat_rate": (
        "vat %",
        "vat%",
        "tax %",
        "tax rate",
        "vat rate",
    ),
    "vat_amount_aed": (
        "vat",
        "vat aed",
        "vat amount",
        "tax aed",
        "tax amount",
    ),
    "line_total_aed": (
        "line total",
        "total aed",
        "amount",
        "amount (aed)",
        "total",
        "net total",
    ),
    "serial": (
        "sr",
        "sr no",
        "s no",
        "no",
        "#",
    ),
}

def _norm(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    ).casefold().rstrip(":")

def _money(value: Any) -> Decimal | None:
    match = AMOUNT_RE.fullmatch(str(value or ""))

    if not match:
        return None

    try:
        number = Decimal(
            match.group(1).replace(",", "")
        )

        return (
            number.quantize(
                CENT,
                rounding=ROUND_HALF_UP,
            )
            if number.is_finite()
            else None
        )

    except (InvalidOperation, ValueError):
        return None

def _quantity(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace(",", "")

    if not re.fullmatch(
        r"\d+(?:\.\d{1,3})?",
        text,
    ):
        return None

    try:
        result = Decimal(text)
        return result if result > 0 else None

    except InvalidOperation:
        return None

def _rate(value: Any) -> Decimal | None:
    match = re.fullmatch(
        r"\s*(\d{1,3}(?:\.\d{1,2})?)\s*%\s*",
        str(value or ""),
    )

    if not match:
        return None

    result = Decimal(match.group(1))

    return result if result <= 100 else None

def _date(value: Any) -> str | None:
    text = str(value or "")

    for expression in DATE_PATTERNS:
        match = expression.search(text)

        if not match:
            continue

        raw = re.sub(
            r"(?<=\d)(?:st|nd|rd|th)\b",
            "",
            match.group(),
            flags=re.I,
        )

        raw = raw.replace(",", "").strip()

        for fmt in (
            "%d %B %Y",
            "%d %b %Y",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%m/%d/%Y",
        ):
            try:
                return (
                    datetime.strptime(raw, fmt)
                    .date()
                    .isoformat()
                )
            except ValueError:
                continue

    return None

def _lines(pages: list[dict]) -> list[dict]:
    result = []

    for p in pages:
        page_no = int(p.get("page_number", 1))

        for raw in p.get("lines") or []:
            if (
                not isinstance(raw, dict)
                or not str(raw.get("text") or "").strip()
            ):
                continue

            bbox = raw.get("bbox")

            if (
                not isinstance(bbox, (tuple, list))
                or len(bbox) != 4
            ):
                continue

            result.append({
                "text": str(raw["text"]).strip(),
                "x": float(bbox[0]),
                "y": float(bbox[1]),
                "x2": float(bbox[2]),
                "y2": float(bbox[3]),
                "page": page_no,
            })

    return sorted(
        result,
        key=lambda l: (
            l["page"],
            l["y"],
            l["x"],
        ),
    )

def _label_match(
    text: str,
    aliases: tuple[str, ...],
) -> bool:
    normalized = _norm(text)

    return any(
        normalized == label
        or normalized.startswith(label + ":")
        or normalized.startswith(label + " (")
        for label in aliases
    )

def _value_near(
    lines: list[dict],
    anchor: dict,
    max_below: float = 40,
) -> str | None:
    same_page = [
        l
        for l in lines
        if l["page"] == anchor["page"]
        and l is not anchor
    ]

    same_row = [
        l
        for l in same_page
        if abs(l["y"] - anchor["y"]) < 8
        and l["x"] >= anchor["x2"] + 2
    ]

    below = [
        l
        for l in same_page
        if 3 <= l["y"] - anchor["y"] <= max_below
        and abs(l["x"] - anchor["x"]) < 38
    ]

    # Horizontal header grids may contain labels side by side.
    # Prefer a value directly underneath when available.
    if below:
        return min(
            below,
            key=lambda l: (
                l["y"],
                abs(l["x"] - anchor["x"]),
            ),
        )["text"]

    if same_row:
        return min(
            same_row,
            key=lambda l: l["x"],
        )["text"]

    return None

def _labeled_value(
    lines: list[dict],
    aliases: tuple[str, ...],
    *,
    accept=None,
) -> str | None:
    for line in lines:
        raw = line["text"]

        for alias in aliases:
            inline = re.match(
                r"^\s*"
                + re.escape(alias)
                + r"\s*[:#-]\s*(.+)$",
                raw,
                re.I,
            )

            if inline and (
                accept is None
                or accept(inline.group(1))
            ):
                return inline.group(1).strip()

        if _label_match(raw, aliases):
            same_row = sorted(
                (
                    l
                    for l in lines
                    if l["page"] == line["page"]
                    and abs(l["y"] - line["y"]) <= 8
                    and l["x"] > line["x2"] + 2
                ),
                key=lambda l: l["x"],
            )

            for near in same_row:
                if (
                    accept is None
                    or accept(near["text"])
                ):
                    return near["text"]

            value = _value_near(lines, line)

            if value and (
                accept is None
                or accept(value)
            ):
                return value

    return None

def _party(
    lines: list[dict],
    role: str,
) -> dict:
    aliases = PARTIES[role]

    anchors = [
        l
        for l in lines
        if _label_match(l["text"], aliases)
    ]

    empty = {
        "name": None,
        "address": None,
        "trn": None,
        "email": None,
    }

    if not anchors:
        return empty

    anchor = anchors[0]

    other_aliases = PARTIES[
        "customer"
        if role == "supplier"
        else "supplier"
    ]

    adjacent = [
        l
        for l in lines
        if l["page"] == anchor["page"]
        and abs(l["y"] - anchor["y"]) <= 12
        and _label_match(
            l["text"],
            other_aliases,
        )
    ]

    if adjacent:
        peer = adjacent[0]

        if peer["x"] > anchor["x"]:
            right = (
                anchor["x2"] + peer["x"]
            ) / 2

            def in_column(l):
                return (
                    anchor["x"] - 12
                    <= l["x"]
                    < right
                )

        else:
            left = (
                anchor["x"] + peer["x2"]
            ) / 2

            def in_column(l):
                return (
                    left
                    < l["x"]
                    < anchor["x"] + 260
                )

    else:
        nearby_right = [
            l["x"]
            for l in lines
            if l["page"] == anchor["page"]
            and l["x"] > anchor["x"] + 100
            and abs(l["y"] - anchor["y"]) <= 45
            and _label_match(
                l["text"],
                (
                    "invoice no",
                    "invoice no.",
                    "invoice number",
                    "date of issue",
                    "invoice date",
                ),
            )
        ]

        limit = (
            min(nearby_right) - 15
            if nearby_right
            else anchor["x"] + 280
        )

        def in_column(l):
            return (
                anchor["x"] - 12
                <= l["x"]
                < limit
            )

    candidates = sorted(
        (
            l
            for l in lines
            if l["page"] == anchor["page"]
            and anchor["y"] + 7
            < l["y"]
            < anchor["y"] + 105
            and in_column(l)
        ),
        key=lambda l: (
            l["y"],
            l["x"],
        ),
    )

    # Prefer an explicitly labeled inline party name.
    inline = re.match(
        r"^\s*(?:"
        + "|".join(
            re.escape(alias)
            for alias in aliases
        )
        + r")\s*:\s*(.+)$",
        anchor["text"],
        re.I,
    )

    regular = (
        [inline.group(1).strip()]
        if inline
        else []
    )

    trn = None
    email = None

    for line in candidates:
        text = line["text"]

        if _label_match(
            text,
            (
                "project",
                "service description",
                "description",
                "payment information",
            ),
        ):
            break

        match = TRN_RE.search(text)

        if match:
            trn = trn or match.group()

        if EMAIL_RE.search(text):
            email = (
                email
                or EMAIL_RE.search(text).group()
            )

        if (
            not match
            and not EMAIL_RE.search(text)
            and not re.match(
                r"^(?:phone|tel|mobile)\b",
                text,
                re.I,
            )
        ):
            regular.append(text)

    # Bank account holder alone is not supplier identity.
    return {
        "name": regular[0] if regular else None,
        "address": ", ".join(regular[1:]) or None,
        "trn": trn,
        "email": email,
    }

def _invoice_number(
    lines: list[dict],
) -> str | None:
    candidate = _labeled_value(
        lines,
        (
            "invoice no",
            "invoice no.",
            "invoice number",
            "invoice #",
            "invoice ref",
            "invoice reference",
        ),
        accept=lambda value: bool(
            re.fullmatch(
                r"[\w/-]{2,100}",
                value.strip(),
            )
            and any(
                ch.isdigit()
                for ch in value
            )
        ),
    )

    if candidate:
        candidate = candidate.strip().strip(":")

        if (
            re.fullmatch(
                r"[\w/-]{2,100}",
                candidate,
            )
            and any(
                c.isdigit()
                for c in candidate
            )
        ):
            return candidate

    first_page = [
        l
        for l in lines
        if l["page"] == 1
    ]

    for line in first_page:
        if line["y"] > 220:
            break

        match = INVOICE_ID_RE.search(
            line["text"]
        )

        if match and (
            line["text"] == match.group()
            or "invoice" in line["text"].lower()
        ):
            return match.group().strip()

        # Support prefixes such as INV-HB-2026-1187.
        if re.fullmatch(
            r"INV-[A-Z]{1,8}-\d{4}-[A-Z0-9/-]{2,40}",
            line["text"],
            re.I,
        ):
            return line["text"].strip()

    return None

def _date_field(
    lines: list[dict],
    key: str,
    notes: list[str],
) -> str | None:
    label = DATE_LABELS[key]

    for anchor in lines:
        if not _label_match(
            anchor["text"],
            label,
        ):
            continue

        right = sorted(
            (
                l
                for l in lines
                if l["page"] == anchor["page"]
                and abs(l["y"] - anchor["y"]) < 9
                and l["x"] > anchor["x2"] + 2
            ),
            key=lambda l: l["x"],
        )

        parsed = next(
            (
                _date(l["text"])
                for l in right
                if _date(l["text"])
            ),
            None,
        )

        if parsed:
            return parsed

        near = _value_near(
            lines,
            anchor,
            max_below=40,
        )

        parsed = _date(near)

        if parsed:
            return parsed

        if key == "due_date" and near:
            notes.append(
                f"Payment due is stated as '{near}', "
                "not a verified calendar date."
            )

    return None

def _column(text: str) -> str | None:
    normalized = _norm(text)

    normalized = re.sub(
        r"\s*\(aed\)\s*$",
        "",
        normalized,
    ).strip()

    # "VAT 5%" in a monetary heading is a VAT
    # amount column, not a percentage cell.
    if re.fullmatch(
        r"vat\s+\d{1,3}(?:\.\d+)?\s*%",
        normalized,
    ):
        return "vat_amount_aed"

    for key, aliases in COLUMN_ALIASES.items():
        if normalized in aliases:
            return key

    return None

def _table_headers(
    page_lines: list[dict],
) -> list[tuple[float, dict[str, dict]]]:
    groups = []

    for line in page_lines:
        if _column(line["text"]) != "description":
            continue

        neighbors = [
            l
            for l in page_lines
            if abs(l["y"] - line["y"]) <= 18
        ]

        mapped = {}

        for candidate in sorted(
            neighbors,
            key=lambda r: (
                abs(r["y"] - line["y"]),
                r["x"],
            ),
        ):
            key = _column(candidate["text"])

            if key and key not in mapped:
                mapped[key] = candidate

        if (
            "description" in mapped
            and "line_total_aed" in mapped
            and len(mapped) >= 3
        ):
            groups.append((
                max(
                    l["y"]
                    for l in mapped.values()
                ),
                mapped,
            ))

    return groups

def _table_items(
    pages: list[dict],
    notes: list[str],
) -> list[dict]:
    results = []

    for p in pages:
        page_no = int(p.get("page_number", 1))

        page_lines = [
            l
            for l in _lines([p])
            if l["page"] == page_no
        ]

        candidates = _table_headers(
            page_lines
        )

        if not candidates:
            continue

        header_y, headers = candidates[0]

        ordered = sorted(
            headers.items(),
            key=lambda pair: pair[1]["x"],
        )

        # Only use a uniquely stated document VAT rate.
        # Never infer the rate from a monetary VAT column.
        explicit_rates = set()

        for heading in page_lines:
            if (
                heading["y"] > header_y
                or header_y - heading["y"] > 180
            ):
                continue

            match = re.search(
                r"\bVAT\s*(?:charged\s+at\s*)?"
                r"(\d{1,3}(?:\.\d+)?)\s*%",
                heading["text"],
                re.I,
            )

            if match:
                rate_value = Decimal(
                    match.group(1)
                )

                if rate_value <= 100:
                    explicit_rates.add(
                        rate_value
                    )

        common_rate = (
            next(iter(explicit_rates))
            if len(explicit_rates) == 1
            else None
        )

        bounds = {}

        for index, (key, header) in enumerate(ordered):
            left = (
                (
                    ordered[index - 1][1]["x"]
                    + header["x"]
                ) / 2
                if index
                else header["x"] - 25
            )

            if (
                key == "description"
                and index
                and ordered[index - 1][0] == "serial"
            ):
                left = (
                    ordered[index - 1][1]["x2"]
                    + 4
                )

            right = (
                (
                    header["x"]
                    + ordered[index + 1][1]["x"]
                ) / 2
                if index + 1 < len(ordered)
                else float(p.get("width", 600)) + 10
            )

            bounds[key] = (left, right)

        tail = [
            l
            for l in page_lines
            if l["y"] > header_y + 16
            and _label_match(
                l["text"],
                (
                    "subtotal",
                    "sub total",
                    "grand total",
                    "total due",
                    "total amount due",
                    "total payable",
                    "total",
                    "gross before discount",
                    "gross services value",
                    "less: discounts",
                    "discounts",
                    "taxable amount",
                    "net taxable amount",
                    "vat (5%)",
                    "vat 5%",
                ),
            )
        ]

        end_y = min(
            (
                l["y"]
                for l in tail
            ),
            default=float(
                p.get("height", 800)
            ) - 15,
        )

        body = [
            l
            for l in page_lines
            if header_y + 8
            < l["y"]
            < end_y - 3
        ]

        amount_left, amount_right = (
            bounds["line_total_aed"]
        )

        amount_rows = sorted(
            [
                l
                for l in body
                if amount_left
                <= l["x"]
                < amount_right
                and _money(l["text"]) is not None
            ],
            key=lambda l: l["y"],
        )

        if not amount_rows:
            continue

        for idx, row in enumerate(amount_rows):
            start = row["y"] - 6

            stop = (
                amount_rows[idx + 1]["y"] - 6
                if idx + 1 < len(amount_rows)
                else end_y - 3
            )

            cells = [
                l
                for l in body
                if start <= l["y"] < stop
            ]

            grouped = {}

            for key, (left, right) in bounds.items():
                grouped[key] = sorted(
                    [
                        l
                        for l in cells
                        if left <= l["x"] < right
                    ],
                    key=lambda l: (
                        l["y"],
                        l["x"],
                    ),
                )

            descriptions = [
                l["text"]
                for l in grouped.get(
                    "description",
                    [],
                )
            ]

            descriptions = [
                x
                for x in descriptions
                if _column(x) != "description"
            ]

            description = " ".join(
                descriptions
            ).strip()

            def cell(key):
                found = grouped.get(key, [])
                return (
                    found[0]["text"]
                    if found
                    else None
                )

            total = _money(
                row["text"]
            )

            qty = (
                _quantity(cell("quantity"))
                if "quantity" in headers
                else Decimal("1")
            )

            price = (
                _money(cell("unit_price_aed"))
                if "unit_price_aed" in headers
                else None
            )

            discount = (
                _money(cell("discount_aed"))
                if "discount_aed" in headers
                else None
            )

            rate = (
                _rate(cell("vat_rate"))
                if "vat_rate" in headers
                else common_rate
            )

            vat = (
                _money(cell("vat_amount_aed"))
                if "vat_amount_aed" in headers
                else None
            )

            stated_base = (
                _money(cell("taxable_value_aed"))
                if "taxable_value_aed" in headers
                else None
            )

            if (
                not description
                or qty is None
                or total is None
            ):
                notes.append(
                    "Uncertain line-item row on page "
                    f"{page_no}; manual review required."
                )
                continue

            if (
                price is None
                and "unit_price_aed" not in headers
            ):
                # Arithmetic inference is not a source
                # statement of the unit price.
                candidate = (
                    total / qty
                ).quantize(
                    CENT,
                    rounding=ROUND_HALF_UP,
                )

                if candidate * qty == total:
                    price = candidate

            item = {
                "description": description,
                "quantity": qty,
                "line_total_aed": total,
            }

            if price is not None:
                item["unit_price_aed"] = price

            if discount is not None:
                item["discount_aed"] = discount

            if rate is not None:
                item["vat_rate"] = rate

            if vat is not None:
                item["vat_amount_aed"] = vat

            if stated_base is not None:
                item["taxable_value_aed"] = stated_base

            if (
                price is not None
                and rate is not None
            ):
                taxable = (
                    qty * price
                    - (discount or Decimal("0"))
                ).quantize(CENT)

                if (
                    stated_base is not None
                    and abs(
                        stated_base - taxable
                    ) > CENT
                ):
                    notes.append(
                        "Stated taxable amount differs "
                        "from line arithmetic on page "
                        f"{page_no}."
                    )

                elif stated_base is None:
                    item["taxable_value_aed"] = taxable

                computed_vat = (
                    taxable * rate / 100
                ).quantize(
                    CENT,
                    rounding=ROUND_HALF_UP,
                )

                if (
                    vat is not None
                    and abs(
                        computed_vat - vat
                    ) > CENT
                ):
                    notes.append(
                        "VAT amount disagreement "
                        "in line item on page "
                        f"{page_no}."
                    )

                if abs(
                    taxable
                    + (
                        vat
                        if vat is not None
                        else computed_vat
                    )
                    - total
                ) > CENT:
                    notes.append(
                        "Line total does not reconcile "
                        f"on page {page_no}."
                    )

            item["source_page"] = page_no
            results.append(item)

    return results

def _labeled_money(
    lines: list[dict],
    aliases: tuple[str, ...],
) -> Decimal | None:
    for anchor in sorted(
        lines,
        key=lambda l: (
            l["page"],
            -l["y"],
        ),
    ):
        if not _label_match(
            anchor["text"],
            aliases,
        ):
            continue

        for alias in aliases:
            inline = re.match(
                r"^\s*"
                + re.escape(alias)
                + r"\s*[: ]+\s*(AED\s*)?[\d,.]+",
                anchor["text"],
                re.I,
            )

            if inline:
                value = _money(
                    anchor["text"][
                        inline.start():
                    ].split(":")[-1].strip()
                )

                if value is not None:
                    return value

        same_row = [
            l
            for l in lines
            if l["page"] == anchor["page"]
            and abs(
                l["y"] - anchor["y"]
            ) <= 9
            and l["x"] > anchor["x2"] + 3
            and _money(l["text"]) is not None
        ]

        if same_row:
            return _money(
                max(
                    same_row,
                    key=lambda l: l["x"],
                )["text"]
            )

    return None

def parse_pdf_layout(
    raw_extraction: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Produce invoice candidates, preserving uncertainty.

    Multiple pages are treated as one invoice candidate.
    Multi-invoice splitting requires stronger evidence.
    """

    notes: list[str] = []

    pages = (
        raw_extraction.get("layout_pages")
        or []
    )

    if not isinstance(pages, list) or not pages:
        return [], [
            "No PDF layout coordinates are available."
        ]

    lines = _lines(pages)

    if not lines:
        return [], [
            "No positioned PDF text lines are available."
        ]

    supplier = _party(
        lines,
        "supplier",
    )

    buyer = _party(
        lines,
        "customer",
    )

    if not supplier["name"]:
        notes.append(
            "Supplier identity could not be verified "
            "from an issuer-labeled block."
        )

    number = _invoice_number(lines)

    issue = _date_field(
        lines,
        "issue_date",
        notes,
    )

    due = _date_field(
        lines,
        "due_date",
        notes,
    )

    supply = _date_field(
        lines,
        "supply_date",
        notes,
    )

    items = _table_items(
        pages,
        notes,
    )

    place_of_supply = None

    for line in lines:
        place_match = re.match(
            r"^\s*place\s+of\s+supply\s*:\s*(.+?)\s*$",
            line["text"],
            re.I,
        )

        if place_match:
            place_of_supply = (
                place_match.group(1).strip()
            )
            break

    if not items:
        notes.append(
            "Positioned line-item columns could not "
            "be identified; table review required."
        )

    total = _labeled_money(
        lines,
        TOTAL_LABELS["total_amount_aed"],
    )

    subtotal = _labeled_money(
        lines,
        TOTAL_LABELS["subtotal_aed"],
    )

    discount = _labeled_money(
        lines,
        TOTAL_LABELS["discount_aed"],
    )

    # Negative printed discounts represent deductions.
    if discount is not None and discount < 0:
        discount = -discount

    vat = _labeled_money(
        lines,
        TOTAL_LABELS["vat_amount_aed"],
    )

    currency = (
        "AED"
        if any(
            re.search(
                r"\bAED\b|\(AED\)",
                l["text"],
                re.I,
            )
            and (
                l["y"] < 650
                or _norm(
                    l["text"]
                ).startswith((
                    "total",
                    "amount",
                ))
            )
            for l in lines
        )
        else None
    )

    if not currency:
        notes.append(
            "Invoice currency not confirmed from "
            "an explicit financial label."
        )

    if items and total is not None:
        stated = sum(
            (
                Decimal(
                    str(i["line_total_aed"])
                )
                for i in items
            ),
            Decimal("0"),
        )

        if abs(stated - total) > CENT:
            notes.append(
                "Sum of stated line amounts differs "
                "from source grand total."
            )

    if items and any(
        "vat_rate" not in i
        for i in items
    ):
        notes.append(
            "VAT treatment is not specified for "
            "all items; do not assume 0%."
        )

    if len(pages) > 1:
        notes.append(
            "Multiple pages assembled as one invoice; "
            "confirm there is no second invoice."
        )

    fields = {
        "invoice_number": number,
        "supplier_name": supplier["name"],
        "supplier_address": supplier["address"],
        "supplier_trn": supplier["trn"],
        "customer_name": buyer["name"],
        "customer_address": buyer["address"],
        "customer_email": buyer["email"],
        "customer_trn": buyer["trn"],
        "issue_date": issue,
        "supply_date": supply,
        "due_date": due,
        "currency": currency,
        "place_of_supply": place_of_supply,
        "items": items,
        "subtotal_aed": subtotal,
        "discount_aed": discount,
        "vat_amount_aed": vat,
        "total_amount_aed": total,
        "document_classification": "single_invoice",
        "source_filename": raw_extraction.get(
            "filename"
        ),
        "source_page": int(
            pages[0].get(
                "page_number",
                1,
            )
        ),
    }

    required = (
        "invoice_number",
        "supplier_name",
        "customer_name",
        "issue_date",
        "due_date",
        "currency",
        "total_amount_aed",
    )

    missing = [
        name
        for name in required
        if not fields.get(name)
    ]

    if not items:
        missing.append("items")

    fields["missing_fields"] = missing

    fields["extraction_confidence"] = round(
        max(
            0,
            1 - len(missing) / 8,
        ),
        2,
    )

    if missing:
        notes.append(
            "Some invoice fields require "
            "administrator review."
        )

    fields["extraction_notes"] = list(
        dict.fromkeys(notes)
    )

    # The Pydantic schema filters unsupported extra fields.
    parsed = UAEInvoiceExtractionSchema.model_validate(
        fields
    )

    return [
        parsed.model_dump(mode="json")
    ], fields["extraction_notes"]