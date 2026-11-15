# ReceivAI Invoice Generation - implementation pending.

"""ReceivAI UAE — manual invoice generation business service.

Creates, updates and cancels drafts without affecting uploaded documents.

Finalization validates the stored draft, uses the existing Decimal validator,
creates a normal Invoice/InvoiceItem ledger entry, renders a private PDF,
and commits the complete record as one PostgreSQL transaction.

Requires migration:
    backend/migrations/20261114_invoice_generation.sql

The invoice_pdf_service.py module must export:
    render_invoice_pdf_bytes(snapshot)

The caller provides an authenticated administrator ID, a SQLAlchemy Session,
and a unique idempotency key for finalization.

This service does not change uploaded-document or payment/reminder logic.
"""

from __future__ import annotations

import hashlib
import os
import uuid

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings

from app.models.entities import (
    AuditLog,
    GeneratedInvoiceDocument,
    Invoice,
    InvoiceDraft,
    InvoiceDraftItem,
    InvoiceItem,
)

from app.schemas.invoice_generation import (
    FinalizableInvoiceInput,
    InvoiceDraftCreate,
    InvoiceDraftListResponse,
    InvoiceDraftResponse,
    InvoiceDraftUpdate,
    InvoiceFinancialSummary,
    InvoiceGenerationInput,
    InvoiceGenerationResponse,
    InvoiceGenerationValidationResponse,
    InvoiceLineCalculation,
    InvoiceFinalizeRequest,
)

from app.services.invoice_number_service import (
    InvoiceNumberError,
    ensure_invoice_number_available,
    resolve_invoice_number,
)

from app.services.invoice_validator import (
    calculate_invoice_totals,
)


# =====================================================
# 1. CONSTANTS
# =====================================================

# Maximum supported amount for PostgreSQL NUMERIC(14, 2).
MAX_LEDGER_AMOUNT = Decimal("999999999999.99")


# =====================================================
# 2. CUSTOM EXCEPTIONS
# =====================================================

class InvoiceGenerationError(Exception):
    """Base business error for invoice generation."""


class DraftNotFoundError(InvoiceGenerationError):
    """Requested invoice draft does not exist."""


class DraftConflictError(InvoiceGenerationError):
    """Draft version or state conflicts with an operation."""


class InvoiceGenerationValidationError(InvoiceGenerationError):
    """Invoice cannot be finalized because validation failed."""


class InvoicePDFUnavailableError(InvoiceGenerationError):
    """Unable to generate a valid invoice PDF."""


# =====================================================
# 3. SHARED HELPERS
# =====================================================

def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def _invoice_input_from_draft(
    draft: InvoiceDraft,
) -> InvoiceGenerationInput:
    """Reconstruct complete invoice form data from a saved draft.

    Header information is stored as JSONB.

    Line items are stored in invoice_draft_items and restored
    in their original order.

    This preserves custom fields, company text-logo settings,
    bank details and line-item data.
    """

    data = dict(draft.form_data or {})

    data["items"] = [
        {
            "client_id": row.client_id,
            "description": row.description,
            "quantity": row.quantity,
            "unit": row.unit,
            "unit_price_aed": row.unit_price_aed,
            "discount_aed": row.discount_aed,
            "vat_rate": row.vat_rate,
            "sort_order": row.sort_order,
            "custom_values": row.custom_values or {},
            "custom_fields": row.custom_fields or [],
        }
        for row in sorted(
            draft.items,
            key=lambda item: (
                item.sort_order,
                item.id or 0,
            ),
        )
    ]

    return InvoiceGenerationInput.model_validate(data)


def _draft_response(
    draft: InvoiceDraft,
) -> InvoiceDraftResponse:
    """Convert a stored draft into the public API response."""

    return InvoiceDraftResponse(
        id=draft.id,
        version=draft.version,
        status=draft.status,
        data=_invoice_input_from_draft(draft),
        draft_title=draft.draft_title,
        finalized_invoice_id=draft.finalized_invoice_id,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _replace_draft_data(
    draft: InvoiceDraft,
    data: InvoiceGenerationInput,
    *,
    title: str | None,
) -> None:
    """Replace the draft's stored form and line items.

    Client-submitted financial totals are not persisted as
    trusted accounting values.

    The backend recalculates totals during validation.
    """

    draft.form_data = data.model_dump(
        mode="json",
        exclude={
            "items",
            "draft_title",
            "expected_version",
        },
    )

    draft.draft_title = title

    # Existing draft items are removed using the ORM's
    # delete-orphan relationship configuration.
    draft.items.clear()

    for item in data.items:

        draft_item = InvoiceDraftItem(
            client_id=item.client_id,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            unit_price_aed=item.unit_price_aed,
            discount_aed=item.discount_aed,
            vat_rate=item.vat_rate,
            sort_order=item.sort_order,
            custom_values=dict(item.custom_values),
            custom_fields=[
                field.model_dump(mode="json")
                for field in item.custom_fields
            ],
        )

        draft.items.append(draft_item)


def _load_draft(
    db: Session,
    draft_id: int,
    admin_id: int,
    *,
    lock: bool = False,
) -> InvoiceDraft:
    """Retrieve an administrator's draft.

    Row locking is used during updates and finalization
    to protect against simultaneous modifications.
    """

    statement = select(InvoiceDraft).where(
        InvoiceDraft.id == draft_id,
        InvoiceDraft.created_by_id == admin_id,
    )

    if lock:
        statement = statement.with_for_update(
            of=InvoiceDraft
        )

    draft = db.scalar(statement)

    if draft is None:
        raise DraftNotFoundError(
            "Invoice draft not found."
        )

    return draft


# =====================================================
# 4. CREATE INVOICE DRAFT
# =====================================================

def create_invoice_draft(
    db: Session,
    admin_id: int,
    payload: InvoiceDraftCreate,
) -> InvoiceDraftResponse:
    """Create an editable invoice draft.

    Incomplete invoice information is allowed.

    No invoice number is allocated.

    No record is added to the existing invoice register.
    """

    draft = InvoiceDraft(
        created_by_id=admin_id,
        status="draft",
        version=1,
    )

    _replace_draft_data(
        draft,
        payload,
        title=payload.draft_title,
    )

    db.add(draft)

    try:
        db.commit()
        db.refresh(draft)

        return _draft_response(draft)

    except Exception:
        db.rollback()
        raise


# =====================================================
# 5. GET INVOICE DRAFT
# =====================================================

def get_invoice_draft(
    db: Session,
    draft_id: int,
    admin_id: int,
) -> InvoiceDraftResponse:
    """Retrieve a draft with all its saved information."""

    draft = _load_draft(
        db,
        draft_id,
        admin_id,
    )

    return _draft_response(draft)


# =====================================================
# 6. LIST INVOICE DRAFTS
# =====================================================

def list_invoice_drafts(
    db: Session,
    admin_id: int,
    *,
    status: Literal[
        "draft",
        "finalized",
        "cancelled",
    ] | None = "draft",
    limit: int = 50,
    offset: int = 0,
) -> InvoiceDraftListResponse:
    """Return saved drafts with pagination.

    By default, only editable drafts are returned.

    Finalized and cancelled drafts can be requested
    explicitly when needed.
    """

    if not (1 <= limit <= 100) or offset < 0:
        raise InvoiceGenerationValidationError(
            "Invalid pagination parameters."
        )

    conditions = [
        InvoiceDraft.created_by_id == admin_id
    ]

    if status is not None:
        conditions.append(
            InvoiceDraft.status == status
        )

    count = db.scalar(
        select(func.count())
        .select_from(InvoiceDraft)
        .where(*conditions)
    ) or 0

    statement = (
        select(InvoiceDraft)
        .where(*conditions)
        .order_by(
            InvoiceDraft.updated_at.desc(),
            InvoiceDraft.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    drafts = db.scalars(statement).all()

    return InvoiceDraftListResponse(
        drafts=[
            _draft_response(draft)
            for draft in drafts
        ],
        total=count,
    )


# =====================================================
# 7. UPDATE INVOICE DRAFT
# =====================================================

def update_invoice_draft(
    db: Session,
    draft_id: int,
    admin_id: int,
    payload: InvoiceDraftUpdate,
) -> InvoiceDraftResponse:
    """Update an existing editable invoice draft.

    Uses optimistic version checking.

    If the draft changed since the administrator opened it,
    the update is rejected.
    """

    try:

        draft = _load_draft(
            db,
            draft_id,
            admin_id,
            lock=True,
        )

        if draft.status != "draft":
            raise DraftConflictError(
                "Only editable drafts can be updated."
            )

        if payload.expected_version != draft.version:
            raise DraftConflictError(
                "Draft changed since you opened it; "
                "reload before saving."
            )

        _replace_draft_data(
            draft,
            payload,
            title=payload.draft_title,
        )

        draft.version += 1
        draft.updated_by_id = admin_id
        draft.updated_at = _utcnow()

        db.commit()
        db.refresh(draft)

        return _draft_response(draft)

    except Exception:
        db.rollback()
        raise


# =====================================================
# 8. CANCEL INVOICE DRAFT
# =====================================================

def cancel_invoice_draft(
    db: Session,
    draft_id: int,
    admin_id: int,
) -> InvoiceDraftResponse:
    """Cancel an unfinished invoice draft.

    This is a soft-delete operation.

    Cancelled drafts remain in the database but do not
    enter the invoice register.

    Finalized invoices cannot be cancelled using this method.
    """

    try:

        draft = _load_draft(
            db,
            draft_id,
            admin_id,
            lock=True,
        )

        if draft.status == "finalized":
            raise DraftConflictError(
                "Finalized invoices cannot be cancelled as drafts."
            )

        if draft.status == "draft":

            draft.status = "cancelled"
            draft.version += 1
            draft.updated_at = _utcnow()
            draft.updated_by_id = admin_id

            db.commit()
            db.refresh(draft)

        return _draft_response(draft)

    except Exception:
        db.rollback()
        raise


# =====================================================
# 9. VALIDATE INVOICE AND CALCULATE TOTALS
# =====================================================

def validate_invoice_generation(
    data: InvoiceGenerationInput,
    *,
    db: Session | None = None,
    check_invoice_number: bool = True,
) -> InvoiceGenerationValidationResponse:
    """Validate manually entered invoice data.

    Uses the existing ReceivAI Decimal-based invoice validator.

    Calculates:
        - Gross line values
        - Line discounts
        - Taxable values
        - VAT amounts
        - Final line totals
        - Invoice grand total

    No client-submitted totals are trusted.

    Incomplete drafts return validation errors but remain saveable.
    """

    errors: list[str] = []
    warnings: list[str] = []

    # ---------------------------------------------
    # Validate required fields for finalization.
    # ---------------------------------------------

    try:

        FinalizableInvoiceInput.model_validate(
            data.model_dump(
                mode="python",
                exclude={
                    "draft_title",
                    "expected_version",
                },
            )
        )

    except ValidationError as exc:

        errors.extend(
            (
                f"{'.'.join(map(str, issue['loc']))}: "
                f"{issue['msg']}"
            )
            for issue in exc.errors()
        )

    # ---------------------------------------------
    # Calculate using existing financial functions.
    # ---------------------------------------------

    calculated = calculate_invoice_totals(
        [
            item.model_dump(mode="python")
            for item in data.items
        ]
    )

    rows: list[InvoiceLineCalculation] = []

    for number, item_result in enumerate(
        calculated["line_items"],
        start=1,
    ):

        values = item_result["calculated"]

        rows.append(
            InvoiceLineCalculation(
                description=item_result["description"],
                gross_value_aed=values["gross_value_aed"],
                discount_aed=values["discount_aed"],
                taxable_value_aed=values["taxable_value_aed"],
                vat_amount_aed=values["vat_amount_aed"],
                line_total_aed=values["line_total_aed"],
            )
        )

        errors.extend(
            f"Line {number}: {error}"
            for error in item_result["errors"]
        )

        warnings.extend(
            f"Line {number}: {warning}"
            for warning in item_result["warnings"]
        )

    warnings.extend(
        calculated["warnings"]
    )

    financial = InvoiceFinancialSummary(
        subtotal_aed=calculated["subtotal_aed"],
        discount_aed=calculated["discount_aed"],
        vat_amount_aed=calculated["vat_amount_aed"],
        total_amount_aed=calculated["total_amount_aed"],
        line_items=rows,
    )

    # ---------------------------------------------
    # Ensure the invoice total is complete.
    # ---------------------------------------------

    if (
        financial.total_amount_aed is None
        or financial.total_amount_aed <= 0
    ):
        errors.append(
            "Invoice total must be a positive, "
            "fully calculated AED amount."
        )

    # ---------------------------------------------
    # Check PostgreSQL NUMERIC(14,2) precision.
    # ---------------------------------------------

    for key in (
        "subtotal_aed",
        "discount_aed",
        "vat_amount_aed",
        "total_amount_aed",
    ):

        value = getattr(financial, key)

        if (
            value is not None
            and (
                value < 0
                or value > MAX_LEDGER_AMOUNT
            )
        ):
            errors.append(
                f"{key} is outside the supported "
                "ledger amount range."
            )

    for number, row in enumerate(
        rows,
        start=1,
    ):

        for key in (
            "gross_value_aed",
            "taxable_value_aed",
            "vat_amount_aed",
            "line_total_aed",
        ):

            value = getattr(row, key)

            if (
                value is not None
                and (
                    value < 0
                    or value > MAX_LEDGER_AMOUNT
                )
            ):
                errors.append(
                    f"Line {number}: {key} exceeds "
                    "database precision."
                )

    # ---------------------------------------------
    # Check manually entered invoice number.
    # ---------------------------------------------

    reference = data.invoice.invoice_number

    if (
        check_invoice_number
        and db is not None
        and reference
        and reference.strip()
    ):

        try:
            ensure_invoice_number_available(
                db,
                reference,
            )

        except InvoiceNumberError as exc:
            errors.append(str(exc))

    return InvoiceGenerationValidationResponse(
        is_valid=not errors,
        errors=list(dict.fromkeys(errors)),
        warnings=list(dict.fromkeys(warnings)),
        calculated=financial,
    )


# =====================================================
# 10. GENERATE PDF BYTES
# =====================================================

def _pdf_bytes(
    snapshot: dict,
) -> bytes:
    """Request the finalized PDF from the PDF rendering service.

    The PDF renderer is implemented separately.

    Required function:
        render_invoice_pdf_bytes(snapshot)

    The function must return complete PDF bytes.
    """

    try:

        from app.services.invoice_pdf_service import (
            render_invoice_pdf_bytes,
        )

    except ImportError as exc:

        raise InvoicePDFUnavailableError(
            "Invoice PDF service is not implemented. "
            "Finalization was not saved."
        ) from exc

    result = render_invoice_pdf_bytes(snapshot)

    if (
        not isinstance(result, bytes)
        or not result.startswith(b"%PDF-")
        or b"%%EOF" not in result[-1024:]
    ):
        raise InvoicePDFUnavailableError(
            "PDF service returned an invalid PDF file."
        )

    return result


# =====================================================
# 11. PRIVATE PDF STORAGE
# =====================================================

def _private_pdf_folder() -> Path:
    """Resolve the private directory for generated invoices.

    The folder is not located in the Next.js public directory.

    PDF downloads must be served through authenticated API routes.
    """

    storage = Path(
        settings.invoice_storage_dir
    ).expanduser()

    if not storage.is_absolute():

        # app/services -> app -> backend
        storage = (
            Path(__file__).resolve().parents[2]
            / storage
        )

    return storage / "generated"


def _write_pdf(
    data: bytes,
    invoice_id: int,
) -> tuple[Path, str]:
    """Write the PDF to private storage.

    A random file suffix prevents filename conflicts.

    The actual filename is independent of user-supplied
    invoice numbers.
    """

    directory = _private_pdf_folder()

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        f"invoice-{invoice_id}-"
        f"{uuid.uuid4().hex}.pdf"
    )

    path = directory / filename

    with path.open("xb") as handle:

        handle.write(data)
        handle.flush()

        os.fsync(
            handle.fileno()
        )

    return path, filename


# =====================================================
# 12. EXISTING FINALIZATION RESPONSE
# =====================================================

def _existing_finalized_response(
    db: Session,
    draft: InvoiceDraft,
) -> InvoiceGenerationResponse:
    """Return the original result of an idempotent retry.

    A previously finalized draft must never create
    a second invoice.
    """

    invoice = db.get(
        Invoice,
        draft.finalized_invoice_id,
    )

    if invoice is None:
        raise DraftConflictError(
            "Finalized draft refers to a missing invoice."
        )

    document = db.scalar(
        select(
            GeneratedInvoiceDocument.id
        ).where(
            GeneratedInvoiceDocument.invoice_id == invoice.id
        )
    )

    return InvoiceGenerationResponse(
        invoice_id=invoice.id,
        draft_id=draft.id,
        invoice_number=invoice.invoice_number,
        amount_aed=invoice.amount_aed,
        status=invoice.status,
        pdf_available=document is not None,
    )


# =====================================================
# 13. FINALIZE INVOICE
# =====================================================

def finalize_invoice_draft(
    db: Session,
    draft_id: int,
    admin_id: int,
    payload: InvoiceFinalizeRequest,
) -> InvoiceGenerationResponse:
    """Finalize a manually generated invoice.

    Workflow:

    1. Lock and retrieve the draft.
    2. Verify idempotency and draft version.
    3. Validate all mandatory information.
    4. Calculate financial values.
    5. Generate or validate invoice number.
    6. Create the existing Invoice record.
    7. Create the existing InvoiceItem records.
    8. Generate the final PDF.
    9. Save PDF metadata and invoice snapshot.
    10. Mark the draft finalized.
    11. Write an audit record.
    12. Commit the transaction.

    A database rollback is performed if any operation fails.

    The generated invoice enters the same Invoice Register
    used by approved uploaded invoices.

    The PDF folder must use persistent storage in production.
    """

    written_pdf: Path | None = None

    try:

        # ---------------------------------------------
        # Step 1: Lock the requested draft.
        # ---------------------------------------------

        draft = _load_draft(
            db,
            draft_id,
            admin_id,
            lock=True,
        )

        # ---------------------------------------------
        # Step 2: Idempotency protection.
        # ---------------------------------------------

        if draft.status == "finalized":

            if (
                payload.idempotency_key
                != draft.finalization_key
            ):
                raise DraftConflictError(
                    "This draft is already finalized."
                )

            return _existing_finalized_response(
                db,
                draft,
            )

        if draft.status != "draft":
            raise DraftConflictError(
                "Cancelled drafts cannot be finalized."
            )

        if draft.version != payload.expected_version:
            raise DraftConflictError(
                "Draft changed; reload before finalizing."
            )

        # ---------------------------------------------
        # Step 3: Reconstruct and validate invoice data.
        # ---------------------------------------------

        data = _invoice_input_from_draft(draft)

        check = validate_invoice_generation(
            data,
            db=db,
        )

        if (
            not check.is_valid
            or check.calculated is None
        ):
            raise InvoiceGenerationValidationError(
                "; ".join(check.errors)
            )

        financial = check.calculated

        # ---------------------------------------------
        # Step 4: Resolve the invoice number.
        # ---------------------------------------------

        number = resolve_invoice_number(
            db,
            issue_date=data.invoice.issue_date,
            requested_number=data.invoice.invoice_number,
        )

        # ---------------------------------------------
        # Step 5: Establish payment status.
        # ---------------------------------------------

        today = date.today()

        payment_status = (
            "overdue"
            if data.invoice.due_date < today
            else "unpaid"
        )

        # ---------------------------------------------
        # Step 6: Create the main invoice record.
        # ---------------------------------------------

        invoice = Invoice(
            invoice_number=number,

            customer_name=data.buyer.name,
            customer_email=data.buyer.email,

            amount_aed=financial.total_amount_aed,

            issue_date=data.invoice.issue_date,
            due_date=data.invoice.due_date,

            status=payment_status,

            source_type="manual",
            source_filename=None,
            extraction_confidence=None,

            # Existing payment service accepts "reviewed".
            review_status="reviewed",

            notes=data.notes,

            supplier_name=data.seller.name,
            supplier_address=data.seller.address,
            supplier_emirate=data.seller.emirate,
            supplier_trn=data.seller.trn,

            customer_address=data.buyer.address,
            customer_emirate=data.buyer.emirate,
            customer_trn=data.buyer.trn,

            place_of_supply=data.invoice.place_of_supply,
            supply_date=data.invoice.supply_date,

            currency="AED",

            subtotal_aed=financial.subtotal_aed,
            discount_aed=financial.discount_aed,
            vat_amount_aed=financial.vat_amount_aed,
            total_amount_aed=financial.total_amount_aed,

            declaration_text=data.declaration_text,
        )

        db.add(invoice)

        # Allocate the database ID without committing.
        db.flush()

        # ---------------------------------------------
        # Step 7: Create original invoice line items.
        # ---------------------------------------------

        for item, calculated in zip(
            data.items,
            financial.line_items,
        ):

            invoice.items.append(
                InvoiceItem(
                    description=item.description,
                    quantity=item.quantity,
                    unit=item.unit,

                    unit_price_aed=item.unit_price_aed,
                    discount_aed=item.discount_aed,

                    taxable_value_aed=(
                        calculated.taxable_value_aed
                    ),

                    vat_rate=item.vat_rate,

                    vat_amount_aed=(
                        calculated.vat_amount_aed
                    ),

                    line_total_aed=(
                        calculated.line_total_aed
                    ),
                )
            )

        db.flush()

        # ---------------------------------------------
        # Step 8: Build immutable invoice snapshot.
        # ---------------------------------------------

        snapshot = {
            "schema_version": "1",

            "invoice_id": invoice.id,

            "invoice_number": number,

            "form_data": data.model_dump(
                mode="json"
            ),

            "calculated": financial.model_dump(
                mode="json"
            ),
        }

        # ---------------------------------------------
        # Step 9: Generate professional PDF.
        # ---------------------------------------------

        pdf = _pdf_bytes(snapshot)

        written_pdf, pdf_filename = _write_pdf(
            pdf,
            invoice.id,
        )

        pdf_checksum = hashlib.sha256(
            pdf
        ).hexdigest()

        # ---------------------------------------------
        # Step 10: Save generated PDF metadata.
        # ---------------------------------------------

        db.add(
            GeneratedInvoiceDocument(
                invoice_id=invoice.id,
                draft_id=draft.id,
                created_by_id=admin_id,

                pdf_filename=pdf_filename,
                pdf_storage_path=str(written_pdf),

                pdf_size_bytes=len(pdf),
                pdf_sha256=pdf_checksum,

                invoice_snapshot=snapshot,

                template_version="v1",
            )
        )

        # ---------------------------------------------
        # Step 11: Mark draft finalized.
        # ---------------------------------------------

        draft.status = "finalized"

        draft.finalized_invoice_id = invoice.id

        draft.finalization_key = (
            payload.idempotency_key
        )

        draft.updated_by_id = admin_id
        draft.updated_at = _utcnow()

        # ---------------------------------------------
        # Step 12: Record administrator action.
        # ---------------------------------------------

        db.add(
            AuditLog(
                admin_id=admin_id,

                action="manual_invoice_finalized",

                entity_type="invoice",
                entity_id=invoice.id,

                details={
                    "draft_id": draft.id,

                    "source_type": "manual",

                    "invoice_number": number,

                    "amount_aed": str(
                        financial.total_amount_aed
                    ),

                    "pdf_sha256": pdf_checksum,
                },

                created_at=_utcnow(),
            )
        )

        # ---------------------------------------------
        # Step 13: Commit complete invoice transaction.
        # ---------------------------------------------

        db.commit()

        return InvoiceGenerationResponse(
            invoice_id=invoice.id,
            draft_id=draft.id,

            invoice_number=number,

            amount_aed=financial.total_amount_aed,

            status=payment_status,

            pdf_available=True,
        )

    # -------------------------------------------------
    # Handle database uniqueness conflicts.
    # -------------------------------------------------

    except IntegrityError as exc:

        db.rollback()

        if written_pdf is not None:
            written_pdf.unlink(
                missing_ok=True
            )

        raise DraftConflictError(
            "Invoice finalization conflicted with "
            "an existing number or request."
        ) from exc

    # -------------------------------------------------
    # Roll back other failures.
    # -------------------------------------------------

    except Exception:

        db.rollback()

        if written_pdf is not None:
            written_pdf.unlink(
                missing_ok=True
            )

        raise
