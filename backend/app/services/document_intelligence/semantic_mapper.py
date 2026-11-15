
"""ReceivAI UAE: source-grounded, layout-aware invoice header candidates.

Public contract (unchanged):

    map_header_fields(layout) -> dict[str, list[dict[str, Any]]]

Designed for the bounded layout produced by layout_engine.extract_pdf_layout().
No network/model calls, no guesses about tax, due dates, or supplier identity.

A candidate is evidence, NOT an approved invoice field. The evidence resolver
and finance validation policy make the final decisions.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


# Longer/more specific aliases before shorter ones.
# "Invoice for" identifies the buyer, not the supplier.
ALIASES: dict[str, tuple[str, ...]] = {
    "invoice_number": (
        "invoice number", "invoice no.", "invoice no",
        "invoice #", "invoice ref", "inv no.", "inv no", "inv #",
    ),
    "issue_date": (
        "date of issue", "invoice date", "issue date", "issued on",
    ),
    "due_date": (
        "payment due date", "payment due", "due date", "pay by",
    ),
    "payment_terms": (
        "payment terms", "terms of payment", "payment condition",
    ),
    "supplier_name": (
        "issued by", "supplier name", "supplier", "seller", "vendor",
    ),
    "customer_name": (
        "invoice for", "invoice to", "bill to", "billed to",
        "sold to", "customer name", "customer", "buyer",
    ),
    "supplier_trn": (
        "supplier trn", "seller trn", "vendor trn",
    ),
    "customer_trn": (
        "buyer trn", "customer trn",
    ),
    "subtotal_aed": (
        "sub total", "subtotal", "taxable amount", "taxable total",
    ),
    "vat_amount_aed": (
        "total vat", "vat total", "vat amount",
        "vat (5%)", "vat (0%)", "vat",
    ),
    "total_amount_aed": (
        "total due", "amount due", "grand total",
        "invoice total", "total payable", "balance due",
    ),
    "currency": ("currency",),
}


BARE_TOTAL = re.compile(
    r"^total\s*(?:[:=|]\s*|\s{2,})(.+)$",
    re.I,
)

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%d %b %Y",
    "%d %B %Y",
    "%d %b, %Y",
    "%d %B, %Y",
    "%Y/%m/%d",
)

MONEY_FIELDS = {
    "subtotal_aed",
    "vat_amount_aed",
    "total_amount_aed",
}

DATE_FIELDS = {
    "issue_date",
    "due_date",
}

IDENTITY_FIELDS = {
    "supplier_name",
    "customer_name",
}

# Payment terms must not be silently converted into calendar dates.
NON_CALENDAR_TERMS = re.compile(
    r"^(?:upon receipt|due on receipt|on receipt|immediately|"
    r"on demand|net\s*\d{1,3}\s*(?:days?)?|"
    r"within\s+\d{1,3}\s+days?)$",
    re.I,
)

COMPANY_LIKE = re.compile(
    r"\b(?:llc|l\.l\.c\.?|fze|fzco|fzc|ltd|limited|"
    r"inc|corp|company|consultancy|services|trading)\b",
    re.I,
)

TRN = re.compile(
    r"\bTRN\s*[:#-]?\s*(\d[\d -]{12,22}\d)\b",
    re.I,
)

INVOICE_REF = re.compile(
    r"\b(?:INV[-/][A-Z0-9][A-Z0-9/.-]*|"
    r"[A-Z]/\d{2}/\d{2,})\b",
    re.I,
)


def _norm(text: Any) -> str:
    return " ".join(str(text or "").strip().split())


def _box(
    raw: Any,
) -> tuple[float, float, float, float] | None:
    try:
        coords = tuple(float(x) for x in raw)

        if len(coords) != 4:
            return None

        if not all(abs(x) < 1e7 for x in coords):
            return None

        return coords  # type: ignore[return-value]

    except (TypeError, ValueError):
        return None


def _date(raw: str) -> str | None:
    cleaned = re.sub(
        r"\b(\d{1,2})(?:st|nd|rd|th)\b",
        r"\1",
        _norm(raw),
        flags=re.I,
    )

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(
                cleaned, fmt
            ).date().isoformat()
        except ValueError:
            pass

    return None


def _money(raw: str) -> str | None:
    clean = re.sub(
        r"(?i)\bAED\b|د\.إ",
        "",
        _norm(raw),
    )

    clean = clean.replace(",", "").strip()

    clean = re.sub(
        r"\s*\(\s*\d+(?:\.\d+)?%\s*\)",
        "",
        clean,
    ).strip()

    if not re.fullmatch(r"\d+(?:\.\d{1,3})?", clean):
        return None

    try:
        value = Decimal(clean)

        if value.is_finite() and value >= 0:
            return str(
                value.quantize(Decimal("0.01"))
            )

    except InvalidOperation:
        pass

    return None


def _valid(field: str, raw: str) -> str | None:
    raw = _norm(raw).strip("|:* ")

    if not raw or len(raw) > 200:
        return None

    if field in DATE_FIELDS:
        return _date(raw)

    if field in MONEY_FIELDS:
        return _money(raw)

    if field == "invoice_number":
        valid_number = re.fullmatch(
            r"(?=.*\d)[A-Z0-9][A-Z0-9/._-]{1,99}",
            raw,
            re.I,
        )

        return raw if valid_number else None

    if field == "currency":
        valid_currency = re.fullmatch(
            r"(?i)AED|UAE\s+dirhams?",
            raw,
        )

        return "AED" if valid_currency else None

    if field in ("customer_trn", "supplier_trn"):
        digits = re.sub(r"[\s-]", "", raw)

        if re.fullmatch(r"\d{15}", digits):
            return digits

        return None

    if field == "payment_terms":
        return raw if len(raw) <= 120 else None

    if field in IDENTITY_FIELDS:
        # Exclude contact details, addresses and banking fields.
        if re.search(
            r"@|https?://|\b(?:bank|iban|account|street|"
            r"tower|suite|office|dubai,|emirates)\b",
            raw,
            re.I,
        ):
            return None

        if re.fullmatch(r"[\d\W]+", raw):
            return None

        return raw

    return raw


def _candidate(
    field: str,
    raw: str,
    block: dict[str, Any],
    label: str,
    method: str,
    confidence: float,
) -> dict[str, Any] | None:

    value = _valid(field, raw)

    if value is None:
        return None

    return {
        "field": field,
        "value": value,
        "source_text": (
            f"{label}: {_norm(raw)}"
            if label
            else _norm(raw)
        ),
        "source_page": block.get("source_page"),
        "bbox": block.get("bbox"),
        "method": method,
        "confidence": confidence,
    }


def _source_blocks(
    layout: dict[str, Any],
) -> list[dict[str, Any]]:

    blocks: list[dict[str, Any]] = []

    # Prefer positioned Docling text blocks to Markdown.
    for block in layout.get("text_blocks") or []:
        if not isinstance(block, dict):
            continue

        text = str(
            block.get("text") or ""
        ).strip()

        if not text:
            continue

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        for line in lines[:15]:
            if len(line) <= 300:
                blocks.append({
                    "text": line,
                    "source_page": block.get("source_page"),
                    "bbox": block.get("bbox"),
                    "order": len(blocks),
                })

    if blocks:
        return blocks

    # Fallback when positioned blocks are unavailable.
    for line in str(
        layout.get("text") or ""
    ).splitlines()[:2500]:

        cleaned = line.strip().strip("#* ")

        if cleaned and len(cleaned) <= 300:
            blocks.append({
                "text": cleaned,
                "source_page": None,
                "bbox": None,
                "order": len(blocks),
            })

    return blocks


def _labels(
    line: str,
) -> list[tuple[str, str, str | None]]:

    """Return field, label and optional inline value."""

    matches: list[tuple[str, str, str | None]] = []

    for field, aliases in ALIASES.items():
        for alias in aliases:

            # Bare VAT must be a summary label, not an
            # arbitrary mention inside invoice descriptions.
            if alias == "vat":
                if not re.match(
                    r"(?i)^VAT\s*(?:\(\s*\d+%\s*\))?"
                    r"\s*(?:[:=|]|\s{2,}|$)",
                    line.strip(),
                ):
                    continue

            pattern = (
                rf"^{re.escape(alias)}"
                rf"(?=\s|[:=|]|$)"
                rf"(?:\s*\(\s*AED\s*\))?"
                rf"\s*(?:[:=|]\s*|\s{{2,}})?(.*)$"
            )

            match = re.match(
                pattern,
                line.strip().strip("|#* "),
                re.I,
            )

            if not match:
                continue

            tail = (
                match.group(1)
                .strip()
                .lstrip("-– ")
                .strip()
            )

            if tail and tail.casefold() == alias.casefold():
                tail = ""

            matches.append(
                (field, alias, tail or None)
            )

            break

    return matches


def _position_score(
    label: dict[str, Any],
    value: dict[str, Any],
    index_delta: int,
) -> float | None:

    lb = _box(label.get("bbox"))
    vb = _box(value.get("bbox"))

    if lb is None or vb is None:
        # No geometry: only consider adjacent next lines.
        return (
            float(index_delta)
            if index_delta <= 2
            else None
        )

    label_page = label.get("source_page")
    value_page = value.get("source_page")

    if (
        label_page is not None
        and value_page is not None
        and label_page != value_page
    ):
        return None

    lx = (lb[0] + lb[2]) / 2
    vx = (vb[0] + vb[2]) / 2

    x_gap = abs(lx - vx)

    ly = (lb[1] + lb[3]) / 2
    vy = (vb[1] + vb[3]) / 2

    y_gap = abs(ly - vy)

    left_gap = abs(lb[0] - vb[0])

    # Vertically aligned labels and values.
    if y_gap <= 60 and (
        left_gap <= 45 or x_gap <= 90
    ):
        return (
            y_gap
            + min(left_gap, x_gap) * 0.4
            + index_delta * 0.2
        )

    # Same-line label and value in separate blocks.
    if (
        y_gap <= 14
        and vb[0] >= lb[2] - 5
        and vb[0] - lb[2] <= 170
    ):
        return (
            15
            + vb[0] - lb[2]
            + index_delta
        )

    return None


def _is_label_only(text: str) -> bool:
    return (
        any(
            not tail
            for _, _, tail in _labels(text)
        )
        or bool(
            re.match(
                r"(?i)^TRN\s*:?$",
                text.strip(),
            )
        )
    )


def map_header_fields(
    layout: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:

    """Extract source-supported invoice header candidates.

    Uses text labels, positional relationships and explicit
    source context.

    Never invent:
      - Supplier legal identity
      - VAT treatment
      - Due dates
      - Invoice currency

    Intended for single-invoice PDFs.
    """

    found: dict[str, list[dict[str, Any]]] = {}

    blocks = _source_blocks(layout)

    anchors: list[
        tuple[str, dict[str, Any], int]
    ] = []

    def add(
        candidate: dict[str, Any] | None,
    ) -> None:

        if candidate is None:
            return

        field = str(candidate["field"])

        previous = found.setdefault(field, [])

        signature = (
            candidate["value"],
            candidate.get("source_page"),
            str(candidate.get("bbox")),
        )

        if all(
            (
                c["value"],
                c.get("source_page"),
                str(c.get("bbox")),
            ) != signature
            for c in previous
        ):
            previous.append(candidate)

    # --------------------------------------------------
    # First pass: inline labels and explicit source clues
    # --------------------------------------------------

    for i, block in enumerate(blocks):

        text = block["text"].strip()

        matches = _labels(text)

        for field, alias, tail in matches:

            if tail:
                if (
                    field == "due_date"
                    and NON_CALENDAR_TERMS.fullmatch(
                        _norm(tail)
                    )
                ):
                    add(_candidate(
                        "payment_terms",
                        tail,
                        block,
                        alias,
                        "docling_payment_term",
                        0.96,
                    ))
                else:
                    add(_candidate(
                        field,
                        tail,
                        block,
                        alias,
                        "docling_inline_label",
                        0.94,
                    ))

            else:
                anchors.append(
                    (field, block, i)
                )

        # Explicit currency statement.
        if re.search(
            r"(?i)\ball\s+amounts?\s+"
            r"(?:shown|stated|are|in)\s+"
            r"(?:in\s+)?AED\b",
            text,
        ):
            add(_candidate(
                "currency",
                "AED",
                block,
                "All amounts",
                "docling_currency_statement",
                0.98,
            ))

        # Written-out currency.
        if re.search(
            r"(?i)\bUAE\s+Dirhams?\b",
            text,
        ):
            add(_candidate(
                "currency",
                "AED",
                block,
                "Amount in words",
                "docling_currency_words",
                0.94,
            ))

        # Source heading such as AMOUNT (AED).
        if re.search(
            r"(?i)\b(?:amount|total|rate|price)"
            r"\s*\(\s*AED\s*\)",
            text,
        ):
            add(_candidate(
                "currency",
                "AED",
                block,
                "Amount (AED)",
                "docling_currency_header",
                0.90,
            ))

        # Explicit AED monetary amount.
        if re.search(
            r"(?i)\bAED\s*[\d,]+(?:\.\d+)?\b",
            text,
        ):
            add(_candidate(
                "currency",
                "AED",
                block,
                "AED amount",
                "docling_currency_amount",
                0.98,
            ))

        # Invoice reference beside an invoice heading.
        if INVOICE_REF.fullmatch(text) and i > 0:

            preceding = [
                b["text"]
                for b in blocks[
                    max(0, i - 3):i
                ]
            ]

            if any(
                re.search(
                    r"(?i)\b(?:tax\s+)?invoice\b",
                    p,
                )
                for p in preceding
            ):
                add(_candidate(
                    "invoice_number",
                    text,
                    block,
                    "Invoice heading",
                    "docling_invoice_heading",
                    0.85,
                ))

        # Bare TOTAL requires a same-row adjacent amount.
        # This avoids confusing table headings with totals.
        if re.fullmatch(
            r"(?i)TOTAL\s*:?",
            text,
        ):
            current_box = _box(
                block.get("bbox")
            )

            if current_box:
                for adjacent in blocks[
                    i + 1:i + 5
                ]:

                    other_box = _box(
                        adjacent.get("bbox")
                    )

                    if not other_box:
                        continue

                    if (
                        block.get("source_page")
                        != adjacent.get("source_page")
                    ):
                        continue

                    same_row = (
                        abs(
                            (
                                current_box[1]
                                + current_box[3]
                                - other_box[1]
                                - other_box[3]
                            ) / 2
                        ) <= 12
                    )

                    rightward = (
                        other_box[0]
                        >= current_box[2] - 5
                    )

                    close_enough = (
                        other_box[0]
                        - current_box[2]
                        <= 280
                    )

                    if (
                        same_row
                        and rightward
                        and close_enough
                    ):
                        add(_candidate(
                            "total_amount_aed",
                            adjacent["text"],
                            adjacent,
                            "TOTAL",
                            "docling_summary_position",
                            0.90,
                        ))

                        break

    # --------------------------------------------------
    # Second pass: positional label/value matching
    # --------------------------------------------------

    for field, anchor, index in anchors:

        alternatives: list[
            tuple[
                float,
                dict[str, Any],
                str,
            ]
        ] = []

        for j in range(
            index + 1,
            min(len(blocks), index + 14),
        ):

            block = blocks[j]
            text = block["text"]

            if _is_label_only(text):
                continue

            score = _position_score(
                anchor,
                block,
                j - index,
            )

            if score is None:
                continue

            if (
                field == "due_date"
                and NON_CALENDAR_TERMS.fullmatch(
                    _norm(text)
                )
            ):
                value_field = "payment_terms"
            else:
                value_field = field

            if _valid(value_field, text) is None:
                continue

            # Prevent unrelated identity blocks.
            if (
                field in IDENTITY_FIELDS
                and (
                    j - index > 7
                    or score > 80
                )
            ):
                continue

            alternatives.append(
                (score, block, value_field)
            )

        if alternatives:

            _, chosen, value_field = min(
                alternatives,
                key=lambda x: x[0],
            )

            add(_candidate(
                value_field,
                chosen["text"],
                chosen,
                anchor["text"],
                "docling_position",
                0.90,
            ))

    # --------------------------------------------------
    # Third pass: party-specific TRN attribution
    # --------------------------------------------------

    party_anchors = [
        (field, block, index)
        for field, block, index in anchors
        if field in IDENTITY_FIELDS
    ]

    for block in blocks:

        match = TRN.search(
            block["text"]
        )

        if not match:
            continue

        digits = re.sub(
            r"[\s-]",
            "",
            match.group(1),
        )

        if not re.fullmatch(
            r"\d{15}",
            digits,
        ):
            continue

        trn_box = _box(
            block.get("bbox")
        )

        ranked: list[
            tuple[float, str]
        ] = []

        for field, anchor, _ in party_anchors:

            anchor_box = _box(
                anchor.get("bbox")
            )

            if not (
                trn_box
                and anchor_box
            ):
                continue

            if (
                block.get("source_page") is not None
                and anchor.get("source_page") is not None
                and block["source_page"]
                != anchor["source_page"]
            ):
                continue

            x_diff = abs(
                trn_box[0]
                - anchor_box[0]
            )

            y_diff = abs(
                (
                    (
                        trn_box[1]
                        + trn_box[3]
                    ) / 2
                )
                - (
                    (
                        anchor_box[1]
                        + anchor_box[3]
                    ) / 2
                )
            )

            if (
                x_diff < 85
                and y_diff < 160
            ):
                ranked.append(
                    (
                        x_diff
                        + y_diff * 0.2,
                        field,
                    )
                )

        if ranked:

            ranked.sort()

            if (
                len(ranked) == 1
                or ranked[1][0]
                - ranked[0][0] > 20
            ):

                assigned = (
                    "supplier_trn"
                    if ranked[0][1]
                    == "supplier_name"
                    else "customer_trn"
                )

                add(_candidate(
                    assigned,
                    digits,
                    block,
                    "TRN",
                    "docling_party_region",
                    0.85,
                ))

    # --------------------------------------------------
    # Fourth pass: currency evidence from table headers
    # --------------------------------------------------

    for table in layout.get("tables") or []:

        if not isinstance(
            table,
            dict,
        ):
            continue

        for heading in table.get(
            "headers"
        ) or []:

            heading_text = str(
                heading
            )

            # IMPORTANT FIX:
            # VAT AED alone does not establish invoice currency.
            # General amount/total/price/rate headings do.
            if (
                re.search(
                    r"(?i)\bAED\b|"
                    r"\bUAE\s+Dirhams?\b",
                    heading_text,
                )
                and re.search(
                    r"(?i)\b(?:amount|total|price|rate)\b",
                    heading_text,
                )
                and not re.search(
                    r"(?i)\b(?:VAT|tax)\b",
                    heading_text,
                )
            ):

                add(_candidate(
                    "currency",
                    "AED",
                    table,
                    heading_text,
                    "docling_table_currency",
                    0.90,
                ))

                break

    # Return bounded candidate evidence.
    return {
        field: candidates[:20]
        for field, candidates in found.items()
        if candidates
    }
