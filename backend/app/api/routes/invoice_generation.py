
"""Authenticated FastAPI endpoints for ReceivAI's manual invoice generator.

All routes require the existing single administrator login. Drafts and PDFs
remain separate from the existing uploaded-document processing endpoints.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_admin
from app.models.entities import AdminUser, GeneratedInvoiceDocument, Invoice
from app.schemas.invoice_generation import (
    InvoiceDraftCreate,
    InvoiceDraftListResponse,
    InvoiceDraftResponse,
    InvoiceDraftUpdate,
    InvoiceFinalizeRequest,
    InvoiceGenerationResponse,
    InvoiceGenerationValidationResponse,
    InvoiceGenerationInput,
    InvoicePreviewRequest,
)
from app.services import invoice_generation_service as service
from app.services.invoice_generation_service import (
    DraftConflictError,
    DraftNotFoundError,
    InvoiceGenerationValidationError,
    InvoicePDFUnavailableError,
)
from app.services.invoice_number_service import (
    InvoiceNumberAllocationError,
    InvoiceNumberConflictError,
    InvoiceNumberError,
)
from app.services.invoice_pdf_service import (
    InvoicePDFError,
    render_invoice_pdf_bytes,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/invoice-generation",
    tags=["Invoice Generation"],
    dependencies=[Depends(get_current_admin)],
)


# Finalized PDF files should be small; this limit protects disk reads.
MAX_PDF_DOWNLOAD_BYTES = 20 * 1024 * 1024


# =====================================================
# 1. BUSINESS ERROR HANDLING
# =====================================================

def _call_service(
    session: Session,
    operation,
    *args,
    **kwargs,
):
    """Translate business exceptions into safe HTTP responses."""

    try:
        return operation(*args, **kwargs)

    except DraftNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except (
        DraftConflictError,
        InvoiceNumberConflictError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except (
        InvoiceGenerationValidationError,
        InvoiceNumberError,
    ) as exc:

        if isinstance(exc, InvoiceNumberAllocationError):
            logger.exception(
                "Invoice number allocation unavailable"
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Invoice numbering is "
                    "temporarily unavailable."
                ),
            ) from exc

        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except (
        InvoicePDFUnavailableError,
        InvoicePDFError,
        OSError,
    ) as exc:

        session.rollback()

        logger.exception(
            "Invoice document operation unavailable"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Invoice PDF service or private "
                "storage is unavailable."
            ),
        ) from exc

    except SQLAlchemyError as exc:

        session.rollback()

        logger.exception(
            "Invoice generation database operation failed"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Invoice database service is "
                "temporarily unavailable."
            ),
        ) from exc

    except Exception as exc:

        session.rollback()

        logger.exception(
            "Unexpected invoice generation failure"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to complete the invoice operation.",
        ) from exc


# =====================================================
# 2. INVOICE PDF PREVIEW HELPER
# =====================================================

def _preview_pdf(
    data: InvoiceGenerationInput,
) -> Response:
    """Render a visible DRAFT PDF without saving database records."""

    snapshot = {
        "schema_version": "1",

        "invoice_number": (
            data.invoice.invoice_number or ""
        ),

        "form_data": data.model_dump(
            mode="json",
            exclude={
                "watermark",
                "draft_title",
                "expected_version",
            },
        ),

        "watermark": "DRAFT",
    }

    try:
        pdf = render_invoice_pdf_bytes(snapshot)

    except (
        InvoicePDFError,
        ValueError,
    ) as exc:

        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        logger.exception(
            "Invoice draft PDF rendering failed"
        )

        raise HTTPException(
            status_code=503,
            detail="PDF preview is temporarily unavailable.",
        ) from exc

    if (
        not isinstance(pdf, bytes)
        or not pdf.startswith(b"%PDF-")
    ):

        logger.error(
            "Invoice preview renderer returned an invalid PDF"
        )

        raise HTTPException(
            status_code=503,
            detail="PDF preview is unavailable.",
        )

    return Response(
        content=pdf,

        media_type="application/pdf",

        headers={
            "Content-Disposition": (
                'inline; filename="receivai-draft-preview.pdf"'
            ),

            "Cache-Control": "no-store, private",

            "X-Content-Type-Options": "nosniff",
        },
    )


# =====================================================
# 3. CREATE INVOICE DRAFT
# =====================================================

@router.post(
    "/drafts",
    response_model=InvoiceDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(
    payload: InvoiceDraftCreate,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Save an incomplete invoice outside the receivables register."""

    return _call_service(
        db,
        service.create_invoice_draft,
        db,
        admin.id,
        payload,
    )


# =====================================================
# 4. LIST INVOICE DRAFTS
# =====================================================

@router.get(
    "/drafts",
    response_model=InvoiceDraftListResponse,
)
def list_drafts(
    draft_status: Literal[
        "draft",
        "finalized",
        "cancelled",
        "all",
    ] = Query(
        default="draft",
        alias="status",
    ),

    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),

    offset: int = Query(
        default=0,
        ge=0,
    ),

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """List the current administrator's saved invoice drafts."""

    effective_status = (
        None
        if draft_status == "all"
        else draft_status
    )

    return _call_service(
        db,
        service.list_invoice_drafts,
        db,
        admin.id,
        status=effective_status,
        limit=limit,
        offset=offset,
    )


# =====================================================
# 5. GET SINGLE DRAFT
# =====================================================

@router.get(
    "/drafts/{draft_id}",
    response_model=InvoiceDraftResponse,
)
def get_draft(
    draft_id: int,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Retrieve an invoice draft belonging to the administrator."""

    return _call_service(
        db,
        service.get_invoice_draft,
        db,
        draft_id,
        admin.id,
    )


# =====================================================
# 6. UPDATE INVOICE DRAFT
# =====================================================

@router.put(
    "/drafts/{draft_id}",
    response_model=InvoiceDraftResponse,
)
def update_draft(
    draft_id: int,

    payload: InvoiceDraftUpdate,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Update draft data with optimistic version protection."""

    return _call_service(
        db,
        service.update_invoice_draft,
        db,
        draft_id,
        admin.id,
        payload,
    )


# =====================================================
# 7. CANCEL INVOICE DRAFT
# =====================================================

@router.delete(
    "/drafts/{draft_id}",
    response_model=InvoiceDraftResponse,
)
def cancel_draft(
    draft_id: int,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Cancel an unfinished draft without deleting accounting data."""

    return _call_service(
        db,
        service.cancel_invoice_draft,
        db,
        draft_id,
        admin.id,
    )


# =====================================================
# 8. VALIDATE STORED DRAFT
# =====================================================

@router.post(
    "/drafts/{draft_id}/validate",
    response_model=InvoiceGenerationValidationResponse,
)
def validate_saved_draft(
    draft_id: int,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Validate saved draft data and calculate AED financial totals."""

    saved = _call_service(
        db,
        service.get_invoice_draft,
        db,
        draft_id,
        admin.id,
    )

    return _call_service(
        db,
        service.validate_invoice_generation,
        saved.data,
        db=db,
    )


# =====================================================
# 9. VALIDATE UNSAVED FORM
# =====================================================

@router.post(
    "/validate",
    response_model=InvoiceGenerationValidationResponse,
)
def validate_unsaved_form(
    payload: InvoiceGenerationInput,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Validate entered invoice details without creating a draft."""

    return _call_service(
        db,
        service.validate_invoice_generation,
        payload,
        db=db,
    )


# =====================================================
# 10. PREVIEW UNSAVED INVOICE
# =====================================================

@router.post(
    "/preview",
    response_class=Response,
)
def preview_unsaved_form(
    payload: InvoicePreviewRequest,

    admin: AdminUser = Depends(get_current_admin),
):
    """Create a watermarked PDF preview of unsaved form data."""

    return _preview_pdf(payload)


# =====================================================
# 11. PREVIEW SAVED DRAFT
# =====================================================

@router.post(
    "/drafts/{draft_id}/preview",
    response_class=Response,
)
def preview_saved_draft(
    draft_id: int,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Generate a PDF preview from the stored draft."""

    saved = _call_service(
        db,
        service.get_invoice_draft,
        db,
        draft_id,
        admin.id,
    )

    return _preview_pdf(saved.data)


# =====================================================
# 12. FINALIZE INVOICE
# =====================================================

@router.post(
    "/drafts/{draft_id}/finalize",
    response_model=InvoiceGenerationResponse,
)
def finalize_draft(
    draft_id: int,

    payload: InvoiceFinalizeRequest,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Finalize invoice and insert it into the existing Invoice Register."""

    return _call_service(
        db,
        service.finalize_invoice_draft,
        db,
        draft_id,
        admin.id,
        payload,
    )


# =====================================================
# 13. DOWNLOAD FINALIZED INVOICE PDF
# =====================================================

@router.get(
    "/invoices/{invoice_id}/pdf",
    response_class=Response,
)
def download_finalized_invoice_pdf(
    invoice_id: int,

    db: Session = Depends(get_db),

    admin: AdminUser = Depends(get_current_admin),
):
    """Securely download a generated invoice PDF.

    Security checks:
      - Existing administrator authentication
      - Generated invoice belongs to the administrator
      - Invoice source type is manual
      - File stays inside configured private storage
      - PDF size matches database metadata
      - PDF SHA-256 matches database metadata

    A client cannot supply an arbitrary storage path.
    """

    try:

        record = db.execute(
            select(
                GeneratedInvoiceDocument,
                Invoice,
            )
            .join(
                Invoice,
                Invoice.id
                == GeneratedInvoiceDocument.invoice_id,
            )
            .where(
                GeneratedInvoiceDocument.invoice_id
                == invoice_id,

                GeneratedInvoiceDocument.created_by_id
                == admin.id,

                Invoice.source_type == "manual",
            )
        ).first()

    except SQLAlchemyError as exc:

        logger.exception(
            "Invoice PDF lookup failed"
        )

        raise HTTPException(
            status_code=503,
            detail="PDF lookup unavailable.",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Generated invoice PDF not found.",
        )

    document, invoice = record

    # Resolve the configured private PDF storage directory.
    storage_root = (
        service._private_pdf_folder().resolve()
    )

    path = Path(
        document.pdf_storage_path
    ).resolve()

    # Prevent path traversal and unexpected file types.
    if (
        not path.is_relative_to(storage_root)
        or path.suffix.lower() != ".pdf"
    ):

        logger.error(
            "Invalid invoice PDF storage path for invoice %s",
            invoice_id,
        )

        raise HTTPException(
            status_code=503,
            detail="Stored invoice PDF is unavailable.",
        )

    try:

        file_size = path.stat().st_size

        if (
            file_size <= 0
            or file_size > MAX_PDF_DOWNLOAD_BYTES
            or file_size != document.pdf_size_bytes
        ):
            raise ValueError(
                "Invoice PDF size mismatch"
            )

        pdf = path.read_bytes()

        if (
            not pdf.startswith(b"%PDF-")
            or hashlib.sha256(pdf).hexdigest().lower()
            != document.pdf_sha256.lower()
        ):
            raise ValueError(
                "Invoice PDF integrity mismatch"
            )

    except (
        OSError,
        ValueError,
    ) as exc:

        logger.warning(
            "Generated PDF missing or changed for invoice %s: %s",
            invoice_id,
            exc,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Stored invoice PDF is missing or "
                "failed integrity verification."
            ),
        ) from exc

    return Response(
        content=pdf,

        media_type="application/pdf",

        headers={
            "Content-Disposition": (
                f'attachment; filename="invoice-{invoice.id}.pdf"'
            ),

            "Cache-Control": "no-store, private",

            "X-Content-Type-Options": "nosniff",
        },
    )
