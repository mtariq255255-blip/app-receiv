
"""Shared eligibility policy for ReceivAI UAE invoice collections.

The policy applies to both administrator-generated invoices and uploaded,
subsequently approved invoices. Drafts do not live in the Invoice table.

This module is read-only: no database sessions, commits, payments, reminders,
or status changes. Payment amount/balance checks remain the responsibility of
the existing payment and receivables services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

from app.models.entities import Invoice


# =====================================================
# 1. INVOICE APPROVAL AND STATUS RULES
# =====================================================

# These are the final-review values already used by
# ReceivAI's receivables service.
#
# Manually generated invoices finalize with "reviewed".

FINAL_REVIEW_STATUSES = frozenset({
    "reviewed",
    "corrected",
    "approved",
})


# A draft is never inserted into Invoice.
#
# However, reject invalid accounting states defensively
# if any invoice record is cancelled, voided or rejected.

NON_COLLECTIBLE_STATUSES = frozenset({
    "draft",
    "pending",
    "rejected",
    "cancelled",
    "canceled",
    "void",
    "voided",
    "deleted",
})


ZERO = Decimal("0.00")


# =====================================================
# 2. ELIGIBILITY RESULT
# =====================================================

@dataclass(frozen=True, slots=True)
class InvoiceEligibility:
    """Decision with a stable code for service/API handling."""

    eligible: bool

    code: str

    message: str


def _deny(
    code: str,
    message: str,
) -> InvoiceEligibility:
    """Return an unsuccessful eligibility decision."""

    return InvoiceEligibility(
        eligible=False,
        code=code,
        message=message,
    )


def _allow() -> InvoiceEligibility:
    """Return a successful eligibility decision."""

    return InvoiceEligibility(
        eligible=True,
        code="eligible",
        message="Invoice is eligible.",
    )


# =====================================================
# 3. FINANCIAL VALIDATION HELPER
# =====================================================

def _positive_amount(value: Any) -> bool:
    """Check a financial amount without rounding.

    Rejects:
        - Missing amounts
        - Invalid decimal values
        - Boolean values
        - Zero and negative amounts
        - NaN and Infinity
    """

    if value is None or isinstance(value, bool):
        return False

    try:
        amount = Decimal(str(value))

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        return False

    return (
        amount.is_finite()
        and amount > ZERO
    )


# =====================================================
# 4. RECEIVABLES ELIGIBILITY
# =====================================================

def evaluate_invoice_for_receivables(
    invoice: Invoice | None,
) -> InvoiceEligibility:
    """Check whether an invoice can enter receivables.

    Supports:
        - Approved uploaded invoices
        - Corrected uploaded invoices
        - Finalized manually generated invoices

    Rejects:
        - Unapproved invoices
        - Draft and cancelled accounting records
        - Foreign-currency invoices
        - Zero or invalid totals
        - Missing due dates

    A NULL currency is treated as AED for compatibility
    with existing legacy ReceivAI records.

    Explicit foreign currencies are always rejected.

    No currency conversion is performed.
    """

    # ---------------------------------------------
    # Check invoice existence
    # ---------------------------------------------

    if invoice is None:

        return _deny(
            "not_found",
            "Invoice not found.",
        )

    # ---------------------------------------------
    # Check approval/finalization status
    # ---------------------------------------------

    review_status = str(
        invoice.review_status or ""
    ).strip().lower()

    if review_status not in FINAL_REVIEW_STATUSES:

        return _deny(
            "not_finalized",
            "Invoice must be approved or finalized first.",
        )

    # ---------------------------------------------
    # Check accounting state
    # ---------------------------------------------

    ledger_status = str(
        invoice.status or ""
    ).strip().lower()

    if ledger_status in NON_COLLECTIBLE_STATUSES:

        return _deny(
            "inactive",
            "Cancelled, rejected or draft invoices "
            "are not collectible.",
        )

    # ---------------------------------------------
    # Check supported currency
    # ---------------------------------------------

    currency = (
        "AED"
        if invoice.currency is None
        else str(invoice.currency).strip().upper()
    )

    if currency != "AED":

        return _deny(
            "unsupported_currency",
            "Only AED invoices are supported "
            "for collections.",
        )

    # ---------------------------------------------
    # Check invoice total
    # ---------------------------------------------

    if not _positive_amount(
        invoice.amount_aed
    ):

        return _deny(
            "invalid_total",
            "Invoice must have a positive, "
            "valid AED total.",
        )

    # ---------------------------------------------
    # Check due date
    # ---------------------------------------------

    if not isinstance(
        invoice.due_date,
        date,
    ):

        return _deny(
            "missing_due_date",
            "Invoice due date is required.",
        )

    return _allow()


# =====================================================
# 5. PAYMENT ELIGIBILITY
# =====================================================

def evaluate_invoice_for_payment(
    invoice: Invoice | None,
) -> InvoiceEligibility:
    """Check eligibility before recording a payment.

    Both manually generated and approved uploaded
    invoices use the same validation.

    IMPORTANT:
    This function only verifies invoice eligibility.

    The payment service must still:
        - Lock the invoice database row
        - Check recorded payments
        - Calculate outstanding balance
        - Reject overpayments
        - Check duplicate payment references
        - Commit payment and audit records atomically
    """

    return evaluate_invoice_for_receivables(
        invoice
    )


# =====================================================
# 6. REMINDER ELIGIBILITY
# =====================================================

def evaluate_invoice_for_reminder(
    invoice: Invoice | None,
    *,
    outstanding_amount: Any,
    reconciliation_required: bool = False,
) -> InvoiceEligibility:
    """Check eligibility for creating a payment reminder.

    The outstanding amount must come from the
    ReceivAI receivables service.

    Never trust a client-submitted outstanding amount.

    Blocks reminders for:
        - Unapproved invoices
        - Foreign currency invoices
        - Zero outstanding balances
        - Invoices requiring reconciliation
        - Invoices manually marked as paid

    Reminder eligibility does not send email.
    """

    # ---------------------------------------------
    # Verify basic invoice eligibility
    # ---------------------------------------------

    base = evaluate_invoice_for_receivables(
        invoice
    )

    if not base.eligible:
        return base

    # ---------------------------------------------
    # Block unreconciled payments
    # ---------------------------------------------

    if reconciliation_required:

        return _deny(
            "reconciliation_required",
            "Invoice settlement requires reconciliation "
            "before reminders.",
        )

    # ---------------------------------------------
    # Block invoices marked as paid
    # ---------------------------------------------

    if str(
        invoice.status or ""
    ).strip().lower() == "paid":

        return _deny(
            "marked_paid",
            "Invoice is marked paid; verify settlement "
            "before reminders.",
        )

    # ---------------------------------------------
    # Verify outstanding balance
    # ---------------------------------------------

    if not _positive_amount(
        outstanding_amount
    ):

        return _deny(
            "no_outstanding_balance",
            "Invoice has no valid outstanding "
            "balance for a reminder.",
        )

    return _allow()


# =====================================================
# 7. SHARED SQLALCHEMY RECEIVABLES FILTERS
# =====================================================

def receivables_sql_filters() -> tuple[
    ColumnElement[bool],
    ...
]:
    """Create SQL filters matching invoice eligibility.

    This function is designed for the existing
    receivables_service.py SQL queries.

    Usage:

        statement = (
            select(Invoice)
            .where(
                *receivables_sql_filters()
            )
        )

    The existing payment aggregation, date filtering
    and outstanding-balance calculations must be retained.

    This function does not query the database itself.
    """

    return (

        # Finalized/approved invoice statuses
        func.lower(
            func.trim(
                Invoice.review_status
            )
        ).in_(
            tuple(
                sorted(
                    FINAL_REVIEW_STATUSES
                )
            )
        ),

        # Exclude cancelled, rejected and draft states
        func.lower(
            func.trim(
                Invoice.status
            )
        ).not_in(
            tuple(
                sorted(
                    NON_COLLECTIBLE_STATUSES
                )
            )
        ),

        # Only AED or legacy NULL-currency records
        func.upper(
            func.trim(
                func.coalesce(
                    Invoice.currency,
                    "AED",
                )
            )
        ) == "AED",

        # Positive invoice amount
        Invoice.amount_aed > ZERO,

        # Invoice must have a due date
        Invoice.due_date.is_not(None),
    )
