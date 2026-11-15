
"""ReceivAI UAE — protected reminder draft and approval workflow.

Approval is an internal authorization, NOT evidence of delivery.
No email, SMS, WhatsApp or OpenAI requests are made here.

Reminder text generation remains in the existing
/api/collections/reminders/generate endpoint.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_admin
from app.models import AuditLog, Invoice, Reminder

from app.services.receivables_service import (
    get_invoice_receivable,
)

from app.services.invoice_eligibility import (
    evaluate_invoice_for_receivables,
    evaluate_invoice_for_reminder,
)


# =====================================================
# 1. API ROUTER
# =====================================================

router = APIRouter(
    prefix="/api/reminders",
    tags=["Reminders"],
    dependencies=[Depends(get_current_admin)],
)


# =====================================================
# 2. REMINDER REQUEST SCHEMAS
# =====================================================

class ReminderDraftCreate(BaseModel):
    """Save text that an administrator has reviewed or edited."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    invoice_id: int = Field(gt=0)

    channel: str = Field(default="email")

    subject: str = Field(
        min_length=3,
        max_length=255,
    )

    message: str = Field(
        min_length=10,
        max_length=5000,
    )

    @field_validator("channel")
    @classmethod
    def email_only(cls, value: str) -> str:
        if value != "email":
            raise ValueError(
                "Only email drafts are supported."
            )
        return value

    @field_validator("subject", "message")
    @classmethod
    def validate_text(cls, value: str, info):
        if "{{" in value or "}}" in value:
            raise ValueError(
                "Unresolved template placeholders are not allowed."
            )

        if "\x00" in value or "\r" in value:
            raise ValueError(
                "Unsupported control characters are not allowed."
            )

        if info.field_name == "subject" and "\n" in value:
            raise ValueError(
                "A subject must be a single line."
            )

        return value


class ReminderDraftEdit(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    subject: str = Field(
        min_length=3,
        max_length=255,
    )

    message: str = Field(
        min_length=10,
        max_length=5000,
    )

    @field_validator("subject", "message")
    @classmethod
    def validate_text(cls, value: str, info):
        if "{{" in value or "}}" in value:
            raise ValueError(
                "Unresolved template placeholders are not allowed."
            )

        if "\x00" in value or "\r" in value:
            raise ValueError(
                "Unsupported control characters are not allowed."
            )

        if info.field_name == "subject" and "\n" in value:
            raise ValueError(
                "A subject must be a single line."
            )

        return value


class ReminderRejectRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    reason: str = Field(
        min_length=3,
        max_length=500,
    )


# =====================================================
# 3. ADMIN AUTHENTICATION HELPER
# =====================================================

def _admin_id(admin) -> int:

    value = getattr(
        admin,
        "id",
        None,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise HTTPException(
            status_code=403,
            detail="Valid administrator required.",
        )

    return value


# =====================================================
# 4. REMINDER SERIALIZATION
# =====================================================

def _serialize(reminder: Reminder) -> dict:

    return {
        "id": reminder.id,
        "invoice_id": reminder.invoice_id,
        "channel": reminder.channel,
        "subject": reminder.subject,
        "message": reminder.message,
        "approval_status": reminder.approval_status,
        "approved_at": reminder.approved_at,
        "created_at": reminder.created_at,

        # No delivery integration or sent-status field exists.
        "sent": False,
    }


# =====================================================
# 5. AUDIT LOG
# =====================================================

def _audit(
    db: Session,
    admin_id: int,
    action: str,
    reminder: Reminder,
    details: dict | None = None,
):

    db.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            entity_type="reminder",
            entity_id=reminder.id,
            details={
                "invoice_id": reminder.invoice_id,
                **(details or {}),
            },
            created_at=datetime.now(timezone.utc),
        )
    )


# =====================================================
# 6. SHARED INVOICE ELIGIBILITY
# =====================================================

def _eligible_invoice(
    db: Session,
    invoice_id: int,
) -> Invoice:
    """Check whether an invoice can receive a reminder.

    Supports:
    - Finalized manually generated invoices
    - Reviewed uploaded invoices
    - Corrected uploaded invoices
    - Approved uploaded invoices

    Rejects:
    - Pending and rejected invoices
    - Cancelled and voided invoices
    - Foreign-currency invoices
    - Fully paid invoices
    - Invoices with invalid financial totals
    - Invoices requiring payment reconciliation

    All balances are retrieved from PostgreSQL.
    No client-submitted financial values are trusted.
    """

    # Coordinate with the payment service, which
    # locks the same invoice before recording payments.
    invoice = db.execute(
        select(Invoice)
        .where(
            Invoice.id == invoice_id
        )
        .with_for_update()
    ).scalar_one_or_none()

    if invoice is None:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found.",
        )

    # ---------------------------------------------
    # Check shared invoice approval policy
    # ---------------------------------------------

    base = evaluate_invoice_for_receivables(
        invoice
    )

    if not base.eligible:
        raise HTTPException(
            status_code=422,
            detail=base.message,
        )

    # ---------------------------------------------
    # Retrieve authoritative outstanding balance
    # ---------------------------------------------

    receivable = get_invoice_receivable(
        db,
        invoice_id,
    )

    if receivable is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Invoice is not eligible for "
                "collection monitoring."
            ),
        )

    # ---------------------------------------------
    # Validate recorded financial values
    # ---------------------------------------------

    try:
        total = Decimal(
            str(receivable["invoice_total"])
        )

        paid = Decimal(
            str(receivable["paid_amount"])
        )

        outstanding = Decimal(
            str(receivable["outstanding_amount"])
        )

        overpayment = Decimal(
            str(receivable["overpayment_amount"])
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Invoice payment balance "
                "requires verification."
            ),
        ) from exc

    if not all(
        value.is_finite()
        for value in (
            total,
            paid,
            outstanding,
            overpayment,
        )
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Invoice payment balance "
                "requires verification."
            ),
        )

    # ---------------------------------------------
    # Detect reconciliation problems
    # ---------------------------------------------

    warnings = (
        receivable.get("warnings") or []
    )

    reconciliation_required = (
        paid < 0
        or overpayment > 0
        or paid > total
        or outstanding != max(
            total - paid,
            Decimal("0.00"),
        )
        or any(
            "RECONCILIATION_REQUIRED" in str(warning)
            for warning in warnings
        )
    )

    # ---------------------------------------------
    # Check shared reminder eligibility
    # ---------------------------------------------

    decision = evaluate_invoice_for_reminder(
        invoice,
        outstanding_amount=outstanding,
        reconciliation_required=reconciliation_required,
    )

    if not decision.eligible:
        raise HTTPException(
            status_code=422,
            detail=decision.message,
        )

    return invoice


# =====================================================
# 7. LOCK REMINDER RECORD
# =====================================================

def _get_locked_reminder(
    db: Session,
    reminder_id: int,
) -> Reminder:

    reminder = db.execute(
        select(Reminder)
        .where(
            Reminder.id == reminder_id
        )
        .with_for_update()
    ).scalar_one_or_none()

    if reminder is None:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found.",
        )

    return reminder


# =====================================================
# 8. COMMIT CHANGES
# =====================================================

def _commit_or_500(
    db: Session,
) -> None:

    try:
        db.commit()

    except SQLAlchemyError as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Could not save reminder changes.",
        ) from exc


# =====================================================
# 9. LIST ALL REMINDERS
# =====================================================

@router.get("")
def get_all_reminders(
    db: Session = Depends(get_db),
):
    """Return existing reminder records."""

    reminders = db.scalars(
        select(Reminder)
        .order_by(
            Reminder.created_at.desc()
        )
    ).all()

    return [
        _serialize(reminder)
        for reminder in reminders
    ]


# =====================================================
# 10. GET SINGLE REMINDER
# =====================================================

@router.get("/{reminder_id}")
def get_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
):

    reminder = db.get(
        Reminder,
        reminder_id,
    )

    if reminder is None:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found.",
        )

    return _serialize(reminder)


# =====================================================
# 11. SAVE REMINDER DRAFT
# =====================================================

@router.post(
    "/drafts",
    status_code=status.HTTP_201_CREATED,
)
def save_reminder_draft(
    payload: ReminderDraftCreate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save an admin-reviewed reminder draft.

    Works with eligible uploaded and generated invoices.

    The reminder is saved as pending.
    It is not approved or sent automatically.
    """

    admin_id = _admin_id(admin)

    try:
        _eligible_invoice(
            db,
            payload.invoice_id,
        )

        reminder = Reminder(
            invoice_id=payload.invoice_id,
            channel=payload.channel,
            subject=payload.subject,
            message=payload.message,
            approval_status="pending",
            approved_at=None,
            created_at=datetime.now(timezone.utc),
        )

        db.add(reminder)
        db.flush()

        _audit(
            db,
            admin_id,
            "reminder_draft_saved",
            reminder,
        )

        _commit_or_500(db)
        db.refresh(reminder)

        return _serialize(reminder)

    except Exception:
        db.rollback()
        raise


# =====================================================
# 12. EDIT REMINDER DRAFT
# =====================================================

@router.patch("/{reminder_id}")
def edit_reminder_draft(
    reminder_id: int,
    payload: ReminderDraftEdit,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):

    admin_id = _admin_id(admin)

    try:
        reminder = _get_locked_reminder(
            db,
            reminder_id,
        )

        if reminder.approval_status != "pending":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only pending drafts can be edited."
                ),
            )

        reminder.subject = payload.subject
        reminder.message = payload.message

        _audit(
            db,
            admin_id,
            "reminder_draft_edited",
            reminder,
        )

        _commit_or_500(db)
        db.refresh(reminder)

        return _serialize(reminder)

    except Exception:
        db.rollback()
        raise


# =====================================================
# 13. APPROVE REMINDER
# =====================================================

@router.post("/{reminder_id}/approve")
def approve_reminder_draft(
    reminder_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Approve a reminder internally.

    Approval does not send any messages.
    """

    admin_id = _admin_id(admin)

    try:
        reminder = _get_locked_reminder(
            db,
            reminder_id,
        )

        if reminder.approval_status != "pending":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only pending drafts can be approved."
                ),
            )

        # Revalidate the invoice at approval time.
        # It may have been paid since the draft was saved.
        _eligible_invoice(
            db,
            reminder.invoice_id,
        )

        reminder.approval_status = "approved"
        reminder.approved_at = datetime.now(timezone.utc)

        _audit(
            db,
            admin_id,
            "reminder_approved",
            reminder,
        )

        _commit_or_500(db)
        db.refresh(reminder)

        return _serialize(reminder)

    except Exception:
        db.rollback()
        raise


# =====================================================
# 14. REJECT REMINDER
# =====================================================

@router.post("/{reminder_id}/reject")
def reject_reminder_draft(
    reminder_id: int,
    payload: ReminderRejectRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):

    admin_id = _admin_id(admin)

    try:
        reminder = _get_locked_reminder(
            db,
            reminder_id,
        )

        if reminder.approval_status != "pending":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only pending drafts can be rejected."
                ),
            )

        reminder.approval_status = "rejected"
        reminder.approved_at = None

        # Keep the rejection reason in the audit log,
        # not in the customer-facing reminder.
        _audit(
            db,
            admin_id,
            "reminder_rejected",
            reminder,
            {
                "reason": payload.reason
            },
        )

        _commit_or_500(db)
        db.refresh(reminder)

        return _serialize(reminder)

    except Exception:
        db.rollback()
        raise
