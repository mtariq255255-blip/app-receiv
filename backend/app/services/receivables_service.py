
"""
ReceivAI UAE
Module 2 - Payment Collections

Receivables Service

Responsibilities:
- Read approved invoices from PostgreSQL
- Calculate recorded payments
- Calculate outstanding balances
- Derive payment status
- Calculate invoice aging
- Generate receivables dashboard summaries

This service:
- Does not call OpenAI
- Does not modify database records
- Does not assume bank verification
- Uses Decimal for financial calculations
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.models.entities import Invoice, Payment

from app.services.aging_service import (
    analyze_invoice_aging,
    summarize_aging,
)

# NEW: Shared invoice eligibility rules.
# Both uploaded approved invoices and manually
# generated finalized invoices use the same policy.
from app.services.invoice_eligibility import (
    receivables_sql_filters,
)


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Any) -> Decimal:
    """Convert a database amount into a two-decimal Decimal."""

    if value is None:
        return ZERO

    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError(
            "Invalid financial value in database."
        ) from exc

    if not amount.is_finite():
        raise ValueError(
            "Non-finite financial value in database."
        )

    return amount.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


def _money_string(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    )


def derive_payment_status(
    invoice_total: Decimal,
    paid_amount: Decimal,
    due_date: date,
    as_of_date: date,
) -> str:
    """
    Derive payment status from recorded payments.

    Possible values:
    paid
    partially_paid
    unpaid
    overdue
    partially_overdue
    overpaid

    This is a calculated status, not a database mutation.
    """

    if invoice_total <= ZERO:
        return "invalid_amount"

    if paid_amount > invoice_total:
        return "overpaid"

    if paid_amount == invoice_total:
        return "paid"

    overdue = due_date < as_of_date

    if paid_amount > ZERO:
        return (
            "partially_overdue"
            if overdue
            else "partially_paid"
        )

    return "overdue" if overdue else "unpaid"


def _build_receivable(
    invoice: Invoice,
    paid_amount: Decimal,
    payment_count: int,
    as_of_date: date,
) -> dict:
    """Build the financial snapshot for one invoice."""

    total = money(invoice.amount_aed)
    paid = money(paid_amount)

    if total <= ZERO:
        raise ValueError(
            f"Invoice ID {invoice.id} has an invalid total."
        )

    if paid < ZERO:
        raise ValueError(
            f"Invoice ID {invoice.id} has negative net payments."
        )

    raw_outstanding = total - paid

    # Outstanding receivables cannot be negative.
    # Preserve the overpayment as a separate exception.
    outstanding = max(
        raw_outstanding,
        ZERO,
    )

    overpayment = max(
        paid - total,
        ZERO,
    )

    status = derive_payment_status(
        invoice_total=total,
        paid_amount=paid,
        due_date=invoice.due_date,
        as_of_date=as_of_date,
    )

    aging = analyze_invoice_aging(
        invoice_id=invoice.id,
        due_date=invoice.due_date,
        outstanding_amount=outstanding,
        as_of_date=as_of_date,
    )

    warnings = []

    if overpayment > ZERO:
        warnings.append(
            "Recorded payments exceed the invoice total. "
            "Review payment records."
        )

    # The legacy Invoice.status may be changed manually without inserting
    # a Payment row. Do not treat that flag as a verified settlement.
    # Preserve the calculated outstanding amount for financial visibility,
    # but mark the record for manual reconciliation before collection.
    if str(invoice.status or "").strip().lower() == "paid" and paid < total:
        warnings.append(
            "RECONCILIATION_REQUIRED: Invoice is marked paid but "
            "recorded payments are less than the invoice total. "
            "Verify settlement before contacting the customer."
        )

    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "customer_name": invoice.customer_name,
        "customer_email": invoice.customer_email,
        "currency": "AED",
        "invoice_date": invoice.issue_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "invoice_total": _money_string(total),
        "paid_amount": _money_string(paid),
        "outstanding_amount": _money_string(outstanding),
        "overpayment_amount": _money_string(overpayment),
        "payment_count": payment_count,
        "payment_status": status,
        "days_overdue": aging["days_overdue"],
        "aging_bucket": aging["aging_bucket"],
        "aging_label": aging["aging_label"],
        "is_overdue": aging["is_overdue"],
        "due_soon": aging["due_soon"],
        "review_status": invoice.review_status,
        "warnings": warnings,
    }


def list_invoice_receivables(
    db: Session,
    as_of_date: date | None = None,
) -> list[dict]:
    """
    Read finalized and approved AED invoices and recorded payments.

    Includes:
    - Finalized manually generated invoices
    - Reviewed uploaded invoices
    - Corrected uploaded invoices
    - Approved uploaded invoices

    Excludes:
    - Pending or rejected invoices
    - Cancelled, voided or draft accounting records
    - Unsupported foreign currencies
    - Zero or negative invoice totals
    - Invoices without due dates

    Payment rows dated after as_of_date are excluded.

    Note:
    The current Payment model has no verification or
    reversal flags. Payment rows are treated as recorded
    ledger entries, not independently verified deposits.
    """

    today = as_of_date or date.today()

    statement = (
        select(
            Invoice,
            func.coalesce(
                func.sum(Payment.amount_aed),
                ZERO,
            ).label("paid_amount"),
            func.count(Payment.id).label("payment_count"),
        )
        .outerjoin(
            Payment,
            and_(
                Payment.invoice_id == Invoice.id,
                Payment.payment_date <= today,
            ),
        )

        # NEW:
        # Apply the shared eligibility policy.
        # This replaces duplicated hard-coded review
        # status and currency filters.
        .where(
            *receivables_sql_filters(),
        )

        .group_by(Invoice.id)
        .order_by(
            Invoice.due_date.asc(),
            Invoice.id.asc(),
        )
    )

    rows = db.execute(statement).all()

    results = []

    for invoice, paid_amount, payment_count in rows:
        results.append(
            _build_receivable(
                invoice=invoice,
                paid_amount=money(paid_amount),
                payment_count=int(payment_count),
                as_of_date=today,
            )
        )

    return results


def get_invoice_receivable(
    db: Session,
    invoice_id: int,
    as_of_date: date | None = None,
) -> dict | None:
    """
    Return one finalized, eligible AED invoice's receivables data.

    Works for:
    - Generated invoices finalized by the administrator
    - Approved uploaded invoices

    Returns None if the invoice is absent or
    not eligible for collection monitoring.
    """

    today = as_of_date or date.today()

    statement = (
        select(
            Invoice,
            func.coalesce(
                func.sum(Payment.amount_aed),
                ZERO,
            ),
            func.count(Payment.id),
        )
        .outerjoin(
            Payment,
            and_(
                Payment.invoice_id == Invoice.id,
                Payment.payment_date <= today,
            ),
        )
        .where(
            Invoice.id == invoice_id,

            # NEW:
            # Use exactly the same eligibility policy
            # as list_invoice_receivables().
            *receivables_sql_filters(),
        )
        .group_by(Invoice.id)
    )

    row = db.execute(statement).first()

    if row is None:
        return None

    invoice, paid_amount, payment_count = row

    return _build_receivable(
        invoice=invoice,
        paid_amount=money(paid_amount),
        payment_count=int(payment_count),
        as_of_date=today,
    )


def get_receivables_summary(
    db: Session,
    as_of_date: date | None = None,
) -> dict:
    """
    Generate dashboard summary values.

    Totals are derived from finalized and approved
    AED invoices and recorded payments.

    Both generated and uploaded approved invoices
    are included through list_invoice_receivables().

    Collection rate:
        Recorded paid amount / approved invoice amount

    Overpayments are excluded from collection-rate
    numerator to avoid rates above 100%.
    """

    today = as_of_date or date.today()

    invoices = list_invoice_receivables(
        db,
        as_of_date=today,
    )

    total_invoiced = ZERO
    total_recorded_payments = ZERO
    total_applied_payments = ZERO
    total_outstanding = ZERO
    total_overpayments = ZERO

    paid_count = 0
    partially_paid_count = 0
    unpaid_count = 0
    overdue_count = 0
    due_soon_count = 0

    aging_inputs = []

    for invoice in invoices:

        total = money(invoice["invoice_total"])
        paid = money(invoice["paid_amount"])
        outstanding = money(
            invoice["outstanding_amount"]
        )
        overpayment = money(
            invoice["overpayment_amount"]
        )

        total_invoiced += total
        total_recorded_payments += paid
        total_applied_payments += min(paid, total)
        total_outstanding += outstanding
        total_overpayments += overpayment

        status = invoice["payment_status"]

        if status == "paid":
            paid_count += 1

        elif status == "overpaid":
            paid_count += 1

        elif status in (
            "partially_paid",
            "partially_overdue",
        ):
            partially_paid_count += 1

        else:
            unpaid_count += 1

        if invoice["is_overdue"]:
            overdue_count += 1

        if invoice["due_soon"]:
            due_soon_count += 1

        aging_inputs.append(
            {
                "invoice_id": invoice["invoice_id"],
                "due_date": invoice["due_date"],
                "outstanding_amount": (
                    invoice["outstanding_amount"]
                ),
            }
        )

    if total_invoiced > ZERO:
        collection_rate = (
            total_applied_payments
            / total_invoiced
            * Decimal("100")
        ).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    else:
        collection_rate = ZERO

    aging = summarize_aging(
        aging_inputs,
        as_of_date=today,
    )

    return {
        "as_of_date": today.isoformat(),
        "currency": "AED",
        "total_invoices": len(invoices),
        "total_invoiced": _money_string(
            total_invoiced
        ),
        "total_recorded_payments": _money_string(
            total_recorded_payments
        ),
        "total_outstanding": _money_string(
            total_outstanding
        ),
        "total_overpayments": _money_string(
            total_overpayments
        ),
        "total_overdue": aging["total_overdue"],
        "total_due_soon": aging["total_due_soon"],
        "collection_rate_percent": str(
            collection_rate
        ),
        "paid_invoice_count": paid_count,
        "partially_paid_invoice_count": (
            partially_paid_count
        ),
        "unpaid_invoice_count": unpaid_count,
        "overdue_invoice_count": overdue_count,
        "due_soon_invoice_count": due_soon_count,
        "aging_buckets": aging["buckets"],
    }
