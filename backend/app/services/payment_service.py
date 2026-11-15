
"""
ReceivAI UAE
Module 2 - Payment Collections

Payment Service

Responsibilities:
- Record manual payments
- Verify invoice eligibility
- Prevent payments exceeding outstanding balances
- Detect duplicate payment references
- Use database row locks to protect concurrent writes
- Maintain an administrative audit trail
- Return the updated receivable

Payments entered here are recorded payment entries.
They are NOT independently bank-verified.

This service does not call OpenAI.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.entities import (
    Invoice,
    Payment,
    AuditLog,
)

from app.schemas.payment_collection import (
    PaymentCreateSchema,
    PaymentRecordingResultSchema,
)

from app.services.receivables_service import (
    get_invoice_receivable,
)

# NEW: Shared eligibility for approved uploaded invoices
# and finalized manually generated invoices.
from app.services.invoice_eligibility import (
    evaluate_invoice_for_payment,
)


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


# =====================================================
# 1. DOMAIN ERRORS
# =====================================================

class PaymentServiceError(Exception):
    """Base payment service exception."""


class InvoiceNotFoundError(PaymentServiceError):
    pass


class InvoiceNotApprovedError(PaymentServiceError):
    pass


class PaymentAmountError(PaymentServiceError):
    pass


class DuplicatePaymentError(PaymentServiceError):
    pass


class UnsupportedCurrencyError(PaymentServiceError):
    pass


# =====================================================
# 2. MONEY HELPERS
# =====================================================

def to_money(value) -> Decimal:
    """Convert a financial amount to Decimal."""

    if value is None:
        raise PaymentAmountError(
            "A monetary amount is required."
        )

    try:
        amount = Decimal(str(value))

    except Exception as exc:
        raise PaymentAmountError(
            "Invalid monetary amount."
        ) from exc

    if not amount.is_finite():
        raise PaymentAmountError(
            "Monetary amount must be finite."
        )

    return amount.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


# =====================================================
# 3. EXISTING PAYMENT TOTAL
# =====================================================

def get_recorded_payment_total(
    db: Session,
    invoice_id: int,
    as_of_date: date | None = None,
) -> Decimal:
    """
    Calculate the sum of recorded payments.

    Only payment_date <= as_of_date is included.

    The current Payment model has no verification or
    reversal fields, so all matching rows are treated
    as recorded ledger payments.
    """

    today = as_of_date or date.today()

    statement = (
        select(
            func.coalesce(
                func.sum(Payment.amount_aed),
                ZERO,
            )
        )
        .where(
            Payment.invoice_id == invoice_id,
            Payment.payment_date <= today,
        )
    )

    result = db.execute(statement).scalar_one()

    return to_money(result)


# =====================================================
# 4. INVOICE ELIGIBILITY
# =====================================================

def validate_invoice_for_payment(
    invoice: Invoice,
) -> None:
    """
    Validate an invoice using the shared ReceivAI
    invoice eligibility policy.

    Supported:
    - Approved uploaded invoices
    - Corrected uploaded invoices
    - Finalized manually generated invoices

    Rejected:
    - Unapproved invoices
    - Cancelled, rejected or draft invoices
    - Foreign-currency invoices
    - Invalid invoice totals
    - Invoices without due dates

    This function preserves the existing payment
    exception classes so API routes can continue
    handling payment errors consistently.

    Outstanding balance and duplicate-payment checks
    remain in record_payment().
    """

    decision = evaluate_invoice_for_payment(
        invoice
    )

    # Invoice is eligible for payment recording.
    if decision.eligible:
        return

    # Invoice does not exist.
    if decision.code == "not_found":
        raise InvoiceNotFoundError(
            decision.message
        )

    # Invoice has not been finalized or approved.
    if decision.code in {
        "not_finalized",
        "inactive",
    }:
        raise InvoiceNotApprovedError(
            decision.message
        )

    # Foreign currencies are not supported.
    if decision.code == "unsupported_currency":
        raise UnsupportedCurrencyError(
            decision.message
        )

    # Invalid or non-positive invoice amount.
    if decision.code == "invalid_total":
        raise PaymentAmountError(
            decision.message
        )

    # Missing due date or future eligibility failures.
    # Fail closed rather than accepting an unknown state.
    raise PaymentServiceError(
        decision.message
    )


# =====================================================
# 5. DUPLICATE REFERENCE VALIDATION
# =====================================================

def check_duplicate_payment(
    db: Session,
    invoice_id: int,
    payment_reference: str,
) -> None:
    """
    Reject a payment reference already recorded
    against the same invoice.

    Concurrency is protected by the parent invoice
    row lock in record_payment().
    """

    statement = (
        select(Payment.id)
        .where(
            Payment.invoice_id == invoice_id,
            Payment.payment_reference
            == payment_reference,
        )
        .limit(1)
    )

    existing = db.execute(
        statement
    ).scalar_one_or_none()

    if existing is not None:
        raise DuplicatePaymentError(
            "A payment with this reference has "
            "already been recorded for this invoice."
        )


# =====================================================
# 6. RECORD PAYMENT
# =====================================================

def record_payment(
    db: Session,
    data: PaymentCreateSchema,
    admin_id: int,
) -> PaymentRecordingResultSchema:
    """
    Record a payment with transactional safety.

    Steps:
    1. Lock invoice row.
    2. Check approval and currency.
    3. Check duplicate reference.
    4. Calculate remaining balance.
    5. Reject overpayment.
    6. Insert payment.
    7. Insert audit record.
    8. Commit both records atomically.
    9. Return updated receivable.

    The caller must provide an authenticated admin_id.

    The Payment model has no payment-state column.
    A payment entered through this function therefore
    represents a recorded manual payment.
    """

    if admin_id is None or admin_id <= 0:
        raise PaymentServiceError(
            "An authenticated administrator is required."
        )

    # The current schema permits a missing reference.
    # Require one at service level for duplicate protection.
    reference = (
        data.payment_reference or ""
    ).strip()

    if not reference:
        raise PaymentServiceError(
            "Payment reference is required to prevent "
            "duplicate payment entries."
        )

    today = date.today()

    if data.payment_date > today:
        raise PaymentServiceError(
            "Future-dated payments cannot be recorded."
        )

    try:
        # SELECT FOR UPDATE serializes payment entries
        # against the same invoice.
        invoice = db.execute(
            select(Invoice)
            .where(
                Invoice.id == data.invoice_id
            )
            .with_for_update()
        ).scalar_one_or_none()

        if invoice is None:
            raise InvoiceNotFoundError(
                "The requested invoice does not exist."
            )

        # NEW: Unified approval/eligibility validation.
        #
        # Finalized generated invoices and approved
        # uploaded invoices are evaluated identically.
        validate_invoice_for_payment(
            invoice
        )

        # Existing duplicate-reference protection.
        check_duplicate_payment(
            db=db,
            invoice_id=invoice.id,
            payment_reference=reference,
        )

        total = to_money(
            invoice.amount_aed
        )

        recorded = get_recorded_payment_total(
            db=db,
            invoice_id=invoice.id,
            as_of_date=today,
        )

        # Also check all existing entries, including
        # any inconsistent future-dated legacy records,
        # before permitting another payment.
        all_recorded = db.execute(
            select(
                func.coalesce(
                    func.sum(Payment.amount_aed),
                    ZERO,
                )
            ).where(
                Payment.invoice_id == invoice.id
            )
        ).scalar_one()

        all_recorded = to_money(
            all_recorded
        )

        if all_recorded < ZERO:
            raise PaymentServiceError(
                "Existing payment records require review."
            )

        available = total - all_recorded

        if available <= ZERO:
            raise PaymentAmountError(
                "No outstanding invoice balance remains."
            )

        amount = to_money(
            data.amount_aed
        )

        if amount <= ZERO:
            raise PaymentAmountError(
                "Payment amount must be positive."
            )

        if amount > available:
            raise PaymentAmountError(
                "Payment amount exceeds the remaining "
                f"balance of AED {available:.2f}."
            )

        now = datetime.now(
            timezone.utc
        )

        payment = Payment(
            invoice_id=invoice.id,
            amount_aed=amount,
            payment_date=data.payment_date,
            payment_reference=reference,
            notes=data.notes,
            created_at=now,
        )

        db.add(payment)
        db.flush()

        # Preserve existing audit logging.
        audit = AuditLog(
            admin_id=admin_id,
            action="payment_recorded",
            entity_type="payment",
            entity_id=payment.id,
            details={
                "invoice_id": invoice.id,
                "payment_id": payment.id,
                "amount_aed": str(amount),
                "payment_date": (
                    data.payment_date.isoformat()
                ),
                # Avoid logging customer identities
                # or free-form payment notes.
            },
            created_at=now,
        )

        db.add(audit)
        db.flush()

        payment_response = {
            "id": payment.id,
            "invoice_id": payment.invoice_id,
            "amount_aed": payment.amount_aed,
            "payment_date": payment.payment_date,
            "payment_reference": (
                payment.payment_reference
            ),
            "notes": payment.notes,
            "created_at": payment.created_at,
        }

        # Both inserts must succeed before commit.
        db.commit()

    except Exception:
        db.rollback()
        raise

    # Read after commit using a fresh DB transaction.
    # A successful commit must not be reported as failed
    # merely because optional response enrichment fails.
    updated = get_invoice_receivable(
        db=db,
        invoice_id=data.invoice_id,
        as_of_date=today,
    )

    if updated is None:
        raise PaymentServiceError(
            "Payment was saved, but updated receivable "
            "information could not be retrieved."
        )

    return PaymentRecordingResultSchema.model_validate(
        {
            "success": True,
            "message": (
                "Payment recorded successfully."
            ),
            "payment": payment_response,
            "receivable": updated,
        }
    )


# =====================================================
# 7. LIST PAYMENTS
# =====================================================

def list_payments(
    db: Session,
    invoice_id: int,
) -> list[Payment]:
    """Return payment history for one invoice."""

    statement = (
        select(Payment)
        .where(
            Payment.invoice_id == invoice_id
        )
        .order_by(
            Payment.payment_date.desc(),
            Payment.id.desc(),
        )
    )

    return list(
        db.execute(statement).scalars().all()
    )
