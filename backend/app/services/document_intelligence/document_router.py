
"""ReceivAI UAE - conservative native-to-Docling routing.

This module decides whether advanced layout extraction could help.

It does NOT approve invoices, establish VAT treatment,
infer due dates, or initiate posting and collections.

Public contract:
    route_document(native, *, force_docling=False)
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


# These indicate an extraction problem that advanced
# document layout processing may help resolve.
STRUCTURAL_SIGNALS = (
    "table not found",
    "line items not found",
    "unreadable text",
    "unrecognized layout",
    "unrecognised layout",
    "layout parsing failed",
    "text extraction failed",
    "scanned document",
    "columns misaligned",
    "table extraction failed",
    "missing table columns",
    "truncated extraction",
)


def _present(value: Any) -> bool:
    """Check whether a usable value was supplied."""

    return (
        value is not None
        and (
            not isinstance(value, str)
            or bool(value.strip())
        )
    )


def _amount(value: Any) -> Decimal | None:
    """Parse a total for extraction-quality checks.

    This is not a tax or financial reconciliation function.
    """

    if (
        value is None
        or isinstance(value, bool)
        or isinstance(value, float)
    ):
        return None

    raw = str(value).strip().replace(",", "")

    if raw.upper().startswith("AED "):
        raw = raw[4:].strip()

    try:
        result = Decimal(raw)

    except (InvalidOperation, ValueError):
        return None

    return (
        result
        if result.is_finite()
        else None
    )


def _notes(
    native: dict[str, Any],
    invoice: dict[str, Any],
) -> str:
    """Gather extraction diagnostics from native results."""

    parts: list[str] = []

    for source in (native, invoice):

        for key in (
            "extraction_notes",
            "warnings",
            "errors",
        ):
            value = source.get(key)

            if isinstance(value, list):
                parts.extend(
                    str(entry)
                    for entry in value
                )

            elif isinstance(value, str):
                parts.append(value)

    return " ".join(parts).casefold()


def _item_structure_problem(items: Any) -> bool:
    """Detect malformed provided line-item structures.

    Missing optional prices, VAT rates and discounts
    are not automatically structural failures.
    """

    if not isinstance(items, list):
        return True

    for item in items:

        if not isinstance(item, dict):
            return True

        description = item.get("description")

        if (
            not isinstance(description, str)
            or not description.strip()
        ):
            return True

        amount_keys = (
            "line_total_aed",
            "unit_price_aed",
            "taxable_value_aed",
        )

        if not any(
            _present(item.get(key))
            for key in amount_keys
        ):
            return True

    return False


def route_document(
    native: dict[str, Any] | None,
    *,
    force_docling: bool = False,
) -> dict[str, Any]:
    """Recommend whether advanced Docling extraction is needed.

    Returns:
        use_docling: bool
        reason: str
        reasons: list[str]

    The original use_docling and reason keys remain
    compatible with the existing orchestrator.

    A native-only decision does not mean the document
    is financially correct, validated or approved.
    """

    # --------------------------------------------------
    # 1. Explicitly requested advanced extraction
    # --------------------------------------------------

    if force_docling:

        reason = "Docling explicitly requested"

        return {
            "use_docling": True,
            "reason": reason,
            "reasons": [reason],
        }

    # --------------------------------------------------
    # 2. No usable native extraction
    # --------------------------------------------------

    if not isinstance(native, dict):

        reason = "No native invoice result"

        return {
            "use_docling": True,
            "reason": reason,
            "reasons": [reason],
        }

    invoices = native.get("invoices")

    if (
        not isinstance(invoices, list)
        or not invoices
    ):

        reason = "Native parser identified no invoices"

        return {
            "use_docling": True,
            "reason": reason,
            "reasons": [reason],
        }

    reasons: list[str] = []

    # --------------------------------------------------
    # 3. Examine each native invoice
    # --------------------------------------------------

    for index, invoice in enumerate(
        invoices,
        start=1,
    ):

        prefix = f"Invoice {index}"

        if not isinstance(invoice, dict):

            reasons.append(
                f"{prefix}: invalid native invoice structure"
            )

            continue

        # ----------------------------------------------
        # Identity extraction
        # ----------------------------------------------

        if not _present(
            invoice.get("invoice_number")
        ):
            reasons.append(
                f"{prefix}: invoice number was not extracted"
            )

        if not _present(
            invoice.get("customer_name")
        ):
            reasons.append(
                f"{prefix}: customer identity was not extracted"
            )

        # ----------------------------------------------
        # Invoice total extraction
        # ----------------------------------------------

        raw_total = invoice.get(
            "total_amount_aed"
        )

        if not _present(raw_total):

            reasons.append(
                f"{prefix}: printed invoice total "
                "was not extracted"
            )

        elif _amount(raw_total) is None:

            reasons.append(
                f"{prefix}: invoice total is not "
                "a valid number"
            )

        # ----------------------------------------------
        # Line-item table quality
        # ----------------------------------------------

        # Legacy parsers may not return an items key.
        # Its absence alone is not proof of failure.
        #
        # But an explicitly empty or malformed items
        # structure is a reason to attempt Docling.

        if "items" in invoice:

            items = invoice["items"]

            if (
                _item_structure_problem(items)
                or not items
            ):

                reasons.append(
                    f"{prefix}: line-item extraction "
                    "is incomplete"
                )

        # ----------------------------------------------
        # Structural extraction warnings
        # ----------------------------------------------

        notes = _notes(
            native,
            invoice,
        )

        if any(
            signal in notes
            for signal in STRUCTURAL_SIGNALS
        ):

            reasons.append(
                f"{prefix}: native parser reported "
                "structural uncertainty"
            )

        # Missing VAT, supplier identity and due dates
        # are intentionally not automatic Docling
        # triggers. They may be genuinely absent.

    # --------------------------------------------------
    # 4. Return advanced extraction decision
    # --------------------------------------------------

    reasons = list(
        dict.fromkeys(reasons)
    )

    if reasons:

        return {
            "use_docling": True,
            "reason": reasons[0],
            "reasons": reasons,
        }

    # --------------------------------------------------
    # 5. Native extraction is structurally usable
    # --------------------------------------------------

    reason = (
        "Native extraction is structurally usable; "
        "normal validation and review still apply"
    )

    return {
        "use_docling": False,
        "reason": reason,
        "reasons": [],
    }
