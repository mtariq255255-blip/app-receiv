
"""ReceivAI UAE: conservative financial reconciliation.

No tax ruling, currency conversion, or fabricated values.

Public contract:
    reconcile_finances(invoice: dict) -> dict

Preserves existing return keys for the Phase 2 orchestrator.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

CENT = Decimal("0.01")

NUMBER = re.compile(
    r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
)

def _d(value: Any) -> Decimal | None:
    """Parse finite numeric values safely."""

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, float):
        return None

    raw = str(value).strip()

    raw = re.sub(
        r"(?i)^AED\s*",
        "",
        raw,
    ).strip()

    raw = re.sub(
        r"\s*(?:AED|د\.إ)$",
        "",
        raw,
        flags=re.I,
    ).strip()

    if not NUMBER.fullmatch(raw):
        return None

    try:
        number = Decimal(
            raw.replace(",", "")
        )

        return (
            number
            if number.is_finite()
            else None
        )

    except (InvalidOperation, ValueError):
        return None

def _cent(value: Decimal) -> Decimal:
    return value.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )

def _fmt(
    value: Decimal | None,
) -> str | None:
    return (
        str(_cent(value))
        if value is not None
        else None
    )

def _provided(
    item: dict[str, Any],
    key: str,
) -> bool:
    return item.get(key) not in (
        None,
        "",
    )

def reconcile_finances(
    invoice: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile printed totals, arithmetic and stated VAT.

    Verification values are tri-state:

    True:
        Checked successfully.

    False:
        Checked and contradicted.

    None:
        Insufficient evidence.

    Unknown VAT is never treated as zero VAT.
    """

    if not isinstance(invoice, dict):
        raise TypeError(
            "invoice must be a dictionary"
        )

    rows = invoice.get("items") or []

    if not isinstance(rows, list):
        rows = []

    issues: list[str] = []
    warnings: list[str] = []

    line_sum = Decimal("0")
    base_sum = Decimal("0")
    vat_sum = Decimal("0")

    line_complete = bool(rows)
    base_complete = bool(rows)
    vat_complete = bool(rows)

    line_math_checked = 0
    line_tax_checked = 0

    # --------------------------------------------------
    # 1. Validate individual line items
    # --------------------------------------------------

    for n, item in enumerate(rows, 1):

        if not isinstance(item, dict):
            issues.append(
                f"Row {n}: invalid line item structure."
            )

            line_complete = False
            base_complete = False
            vat_complete = False
            continue

        qty = _d(
            item.get("quantity")
        )

        price = _d(
            item.get("unit_price_aed")
        )

        stated_base = _d(
            item.get("taxable_value_aed")
        )

        rate = _d(
            item.get("vat_rate")
        )

        stated_tax = _d(
            item.get("vat_amount_aed")
        )

        stated_total = _d(
            item.get("line_total_aed")
        )

        if _provided(item, "discount_aed"):
            discount = _d(
                item.get("discount_aed")
            )
        else:
            discount = Decimal("0")

        # --------------------------------------------------
        # 2. Detect invalid numeric values
        # --------------------------------------------------

        for key, number in (
            ("quantity", qty),
            ("unit_price_aed", price),
            ("discount_aed", discount),
            ("taxable_value_aed", stated_base),
            ("vat_amount_aed", stated_tax),
            ("line_total_aed", stated_total),
        ):
            if (
                _provided(item, key)
                and number is None
            ):
                issues.append(
                    f"Row {n}: invalid {key} value."
                )

        if (
            _provided(item, "vat_rate")
            and rate is None
        ):
            issues.append(
                f"Row {n}: invalid VAT rate."
            )

        # --------------------------------------------------
        # 3. Preserve source-stated line totals
        # --------------------------------------------------

        if stated_total is None:
            line_complete = False

            warnings.append(
                f"Row {n}: source line total "
                "is unavailable."
            )

        elif stated_total < 0:
            line_complete = False

            issues.append(
                f"Row {n}: negative line total "
                "requires credit-note handling."
            )

        else:
            line_sum += _cent(
                stated_total
            )

        # --------------------------------------------------
        # 4. Validate numeric ranges
        # --------------------------------------------------

        if (
            qty is not None
            and qty <= 0
        ):
            issues.append(
                f"Row {n}: quantity must be positive."
            )

        if (
            price is not None
            and price < 0
        ):
            issues.append(
                f"Row {n}: unit price cannot be negative."
            )

        if (
            discount is None
            or discount < 0
        ):
            issues.append(
                f"Row {n}: discount is invalid."
            )

        if (
            stated_base is not None
            and stated_base < 0
        ):
            issues.append(
                f"Row {n}: taxable value is negative."
            )

        if (
            stated_tax is not None
            and stated_tax < 0
        ):
            issues.append(
                f"Row {n}: stated VAT is negative."
            )

        # --------------------------------------------------
        # 5. Calculate pre-tax base
        # --------------------------------------------------

        base: Decimal | None = None

        if (
            qty is not None
            and qty > 0
            and price is not None
            and price >= 0
            and discount is not None
            and discount >= 0
        ):
            candidate_base = _cent(
                qty * price - discount
            )

            if candidate_base < 0:
                issues.append(
                    f"Row {n}: discount exceeds "
                    "gross line price."
                )

            else:
                base = candidate_base
                base_sum += base

                if (
                    stated_base is not None
                    and stated_base >= 0
                    and _cent(stated_base) != base
                ):
                    issues.append(
                        f"Row {n}: stated taxable value "
                        "differs from quantity × price "
                        "− discount."
                    )

        else:
            base_complete = False

            warnings.append(
                f"Row {n}: quantity/price arithmetic "
                "cannot be checked."
            )

        if base is None:
            base_complete = False

        # --------------------------------------------------
        # 6. Calculate VAT when a rate exists
        # --------------------------------------------------

        if rate is None:
            vat_complete = False

            warnings.append(
                f"Row {n}: VAT rate is not established "
                "by source evidence."
            )

        elif not (
            Decimal("0")
            <= rate
            <= Decimal("100")
        ):
            vat_complete = False

            issues.append(
                f"Row {n}: VAT rate is outside 0-100%."
            )

        elif base is None:
            vat_complete = False

        else:
            tax = _cent(
                base * rate / Decimal("100")
            )

            vat_sum += tax

            # Compare calculated VAT against
            # the amount printed on the document.
            if stated_tax is not None:
                line_tax_checked += 1

                if _cent(stated_tax) != tax:
                    issues.append(
                        f"Row {n}: stated VAT differs "
                        "from recalculated VAT."
                    )

            else:
                warnings.append(
                    f"Row {n}: no source VAT amount "
                    "for independent tax comparison."
                )

            # These checks assume VAT-exclusive prices.
            # VAT-inclusive invoices require further handling.
            if (
                stated_total is not None
                and stated_total >= 0
            ):
                line_math_checked += 1

                if (
                    _cent(stated_total)
                    != _cent(base + tax)
                ):
                    issues.append(
                        f"Row {n}: source line total "
                        "differs from base plus VAT; "
                        "confirm price inclusivity "
                        "and discounts."
                    )

    # --------------------------------------------------
    # 7. Read source invoice summary
    # --------------------------------------------------

    source_total = _d(
        invoice.get("total_amount_aed")
    )

    source_subtotal = _d(
        invoice.get("subtotal_aed")
    )

    source_vat = _d(
        invoice.get("vat_amount_aed")
    )

    if _provided(invoice, "discount_aed"):
        source_discount = _d(
            invoice.get("discount_aed")
        )
    else:
        source_discount = None

    summary_fields = (
        (
            "invoice total",
            "total_amount_aed",
            source_total,
        ),
        (
            "subtotal",
            "subtotal_aed",
            source_subtotal,
        ),
        (
            "VAT",
            "vat_amount_aed",
            source_vat,
        ),
        (
            "invoice discount",
            "discount_aed",
            source_discount,
        ),
    )

    for name, key, number in summary_fields:

        if (
            _provided(invoice, key)
            and number is None
        ):
            issues.append(
                f"Invalid source {name}."
            )

        if (
            number is not None
            and number < 0
        ):
            issues.append(
                f"Negative source {name} "
                "requires review."
            )

    # --------------------------------------------------
    # 8. Compare source line totals with printed total
    # --------------------------------------------------

    source_total_reconciled: bool | None = None

    if (
        line_complete
        and source_total is not None
        and source_total >= 0
    ):
        source_total_reconciled = (
            _cent(line_sum)
            == _cent(source_total)
        )

        if not source_total_reconciled:
            issues.append(
                "Sum of source line totals differs "
                "from the printed invoice total."
            )

    else:
        warnings.append(
            "Cannot verify source line totals "
            "against a printed invoice total."
        )

    # --------------------------------------------------
    # 9. Compare calculated base and VAT with source
    # --------------------------------------------------

    if (
        base_complete
        and source_subtotal is not None
        and source_subtotal >= 0
    ):
        if (
            _cent(base_sum)
            != _cent(source_subtotal)
        ):
            issues.append(
                "Calculated pre-tax base differs "
                "from source subtotal; verify "
                "discounts and price inclusivity."
            )

    if (
        vat_complete
        and source_vat is not None
        and source_vat >= 0
    ):
        if (
            _cent(vat_sum)
            != _cent(source_vat)
        ):
            issues.append(
                "Calculated VAT differs from "
                "printed invoice VAT."
            )

    # --------------------------------------------------
    # 10. Reconcile gross and net subtotal conventions
    # --------------------------------------------------

    summary_reconciled: bool | None = None

    if all(
        value is not None
        and value >= 0
        for value in (
            source_subtotal,
            source_vat,
            source_total,
        )
    ):
        discount_value = (
            source_discount
            if source_discount is not None
            else Decimal("0")
        )

        if discount_value >= 0:

            # Some invoices display net subtotal after
            # line discounts:
            #
            # total = net subtotal + VAT
            #
            # Others display gross subtotal before
            # discount:
            #
            # total = gross subtotal - discount + VAT
            #
            # Check both without automatically subtracting
            # a line-level discount twice.

            net_subtotal_total = _cent(
                source_subtotal + source_vat
            )

            gross_subtotal_total = _cent(
                source_subtotal
                + source_vat
                - discount_value
            )

            summary_reconciled = (
                _cent(source_total)
                in {
                    net_subtotal_total,
                    gross_subtotal_total,
                }
            )

            if not summary_reconciled:
                issues.append(
                    "Printed subtotal, discount, VAT "
                    "and total do not reconcile under "
                    "gross or net subtotal conventions."
                )

    # --------------------------------------------------
    # 11. Independent VAT verification
    # --------------------------------------------------

    tax_calculation_verified: bool | None = None

    tax_contradiction = any(
        "VAT differs" in issue
        or "VAT rate" in issue
        for issue in issues
    )

    if tax_contradiction:
        tax_calculation_verified = False

    elif (
        vat_complete
        and (
            line_tax_checked == len(rows)
            or source_vat is not None
        )
    ):
        tax_calculation_verified = True

    # --------------------------------------------------
    # 12. Prepare final conservative result
    # --------------------------------------------------

    issues = list(
        dict.fromkeys(issues)
    )

    warnings = list(
        dict.fromkeys(warnings)
    )

    requires_review = bool(
        issues
        or warnings
        or not rows
        or not vat_complete
    )

    return {
        # Existing orchestrator-compatible fields.
        "calculated_pre_tax_base_aed": (
            _fmt(base_sum)
            if base_complete
            else None
        ),

        "calculated_vat_aed": (
            _fmt(vat_sum)
            if vat_complete
            else None
        ),

        "sum_of_source_line_totals_aed": (
            _fmt(line_sum)
            if line_complete
            else None
        ),

        "base_calculation_complete": base_complete,

        "tax_calculation_complete": vat_complete,

        "issues": issues,

        "requires_review": requires_review,

        "note": (
            "Recalculation compares VAT-exclusive "
            "unit-price arithmetic where source "
            "supports it; no legal VAT determination "
            "is inferred."
        ),

        # Independent verification results.
        "source_total_reconciled": (
            source_total_reconciled
        ),

        "source_summary_reconciled": (
            summary_reconciled
        ),

        "tax_calculation_verified": (
            tax_calculation_verified
        ),

        "line_arithmetic_checked_count": (
            line_math_checked
        ),

        "line_tax_checked_count": (
            line_tax_checked
        ),

        "warnings": warnings,
    }