
"""Safe invoice-number selection for ReceivAI UAE.

Generated numbers use the PostgreSQL sequence created by
``20261114_invoice_generation.sql``. The sequence is shared by all workers;
calling ``nextval`` is concurrency-safe and does not require an application lock.

This module does not commit, flush, insert invoice rows, or reserve custom
numbers. The finalization service must insert an Invoice within its database
transaction and handle the existing invoice_number UNIQUE constraint.
"""

from __future__ import annotations

from datetime import date
from unicodedata import category

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.entities import Invoice


NUMBER_PREFIX = "RAI-GEN"
NUMBER_SEQUENCE = "receivai_generated_invoice_number_seq"

MAX_INVOICE_NUMBER_LENGTH = 100
MAX_SEQUENCE_ATTEMPTS = 1000


# PostgreSQL sequence created by the invoice-generation migration.
# This is fixed SQL, not assembled from user input.
_NEXT_NUMBER = text(
    "SELECT nextval('receivai_generated_invoice_number_seq'::regclass)"
)


# =====================================================
# 1. CUSTOM EXCEPTIONS
# =====================================================

class InvoiceNumberError(ValueError):
    """An invoice number is invalid or cannot be allocated."""


class InvoiceNumberConflictError(InvoiceNumberError):
    """The requested invoice number already exists."""


class InvoiceNumberAllocationError(InvoiceNumberError):
    """Unable to allocate an unused generated invoice number."""


# =====================================================
# 2. NORMALIZE INVOICE NUMBER
# =====================================================

def normalize_invoice_number(value: str) -> str:
    """Validate and normalize an administrator-entered number.

    Custom invoice numbers may contain spaces, hyphens, slashes
    and other standard business punctuation, consistent with
    the existing Invoice model.
    """

    if not isinstance(value, str):
        raise InvoiceNumberError(
            "Invoice number must be text."
        )

    normalized = value.strip()

    if not normalized:
        raise InvoiceNumberError(
            "Invoice number cannot be empty."
        )

    if len(normalized) > MAX_INVOICE_NUMBER_LENGTH:
        raise InvoiceNumberError(
            f"Invoice number cannot exceed "
            f"{MAX_INVOICE_NUMBER_LENGTH} characters."
        )

    if any(
        category(character).startswith("C")
        for character in normalized
    ):
        raise InvoiceNumberError(
            "Invoice number contains unsupported control characters."
        )

    return normalized


# =====================================================
# 3. CHECK EXISTING INVOICE NUMBERS
# =====================================================

def invoice_number_exists(
    db: Session,
    invoice_number: str,
    *,
    exclude_invoice_id: int | None = None,
) -> bool:
    """Check the existing Invoice Register for a duplicate.

    The comparison ignores letter case and surrounding spaces.

    The database UNIQUE constraint remains the final protection
    against concurrent inserts.
    """

    normalized = normalize_invoice_number(
        invoice_number
    )

    statement = select(Invoice.id).where(
        func.lower(
            func.trim(Invoice.invoice_number)
        ) == normalized.lower()
    )

    if exclude_invoice_id is not None:
        statement = statement.where(
            Invoice.id != exclude_invoice_id
        )

    existing_id = db.scalar(
        statement.limit(1)
    )

    return existing_id is not None


# =====================================================
# 4. VALIDATE MANUALLY ENTERED NUMBER
# =====================================================

def ensure_invoice_number_available(
    db: Session,
    invoice_number: str,
    *,
    exclude_invoice_id: int | None = None,
) -> str:
    """Ensure an administrator-entered invoice number is unused.

    Returns the normalized number when it is available.
    """

    normalized = normalize_invoice_number(
        invoice_number
    )

    if invoice_number_exists(
        db,
        normalized,
        exclude_invoice_id=exclude_invoice_id,
    ):
        raise InvoiceNumberConflictError(
            "This invoice number is already used "
            "in the Invoice Register."
        )

    return normalized


# =====================================================
# 5. AUTOMATIC INVOICE NUMBER GENERATION
# =====================================================

def generate_invoice_number(
    db: Session,
    *,
    issue_date: date,
) -> str:
    """Generate an invoice number using PostgreSQL nextval().

    Format:
        RAI-GEN-YYYY-NNNNNN

    Example:
        RAI-GEN-2026-000001

    The year comes from the invoice issue date.

    PostgreSQL sequence values are globally increasing
    and cannot be duplicated by simultaneous nextval()
    calls.

    Sequence values are not rolled back, so gaps are
    normal if a transaction fails or is cancelled.
    """

    if not isinstance(issue_date, date):
        raise InvoiceNumberError(
            "A valid invoice issue date is required."
        )

    for _ in range(MAX_SEQUENCE_ATTEMPTS):

        # Get the next sequence number from PostgreSQL.
        sequence_value = db.scalar(
            _NEXT_NUMBER
        )

        if (
            type(sequence_value) is not int
            or sequence_value < 1
        ):
            raise InvoiceNumberAllocationError(
                "PostgreSQL returned an invalid "
                "invoice-number sequence value."
            )

        # Build the invoice number.
        candidate = (
            f"{NUMBER_PREFIX}-"
            f"{issue_date.year:04d}-"
            f"{sequence_value:06d}"
        )

        if len(candidate) > MAX_INVOICE_NUMBER_LENGTH:
            raise InvoiceNumberAllocationError(
                "Generated invoice number exceeds "
                "the database column limit."
            )

        # Check against previously stored invoice numbers,
        # including numbers supplied manually or imported.
        if not invoice_number_exists(
            db,
            candidate,
        ):
            return candidate

    raise InvoiceNumberAllocationError(
        "Unable to find an unused invoice number; "
        "check the database sequence."
    )


# =====================================================
# 6. RESOLVE AUTOMATIC OR MANUAL NUMBER
# =====================================================

def resolve_invoice_number(
    db: Session,
    *,
    issue_date: date,
    requested_number: str | None = None,
) -> str:
    """Resolve the invoice number during finalization.

    If an administrator entered a number:
        Validate and use that number.

    If the invoice-number field is blank:
        Generate a new number using PostgreSQL.

    This function should be called during finalization,
    not while creating or previewing drafts.

    The calling service owns the database transaction.
    """

    if requested_number is not None:

        if not isinstance(requested_number, str):
            raise InvoiceNumberError(
                "Invoice number must be text."
            )

        if requested_number.strip():
            return ensure_invoice_number_available(
                db,
                requested_number,
            )

    return generate_invoice_number(
        db,
        issue_date=issue_date,
    )
