
"""
ReceivAI UAE
Module 2 - Payment Collections API

Protected routes for:
- Receivables summary
- Aging breakdown
- Outstanding invoice list
- Collection priority queue
- Individual invoice receivables
- Manual payment recording
- Payment history

Authentication and database dependencies are
provided when building the router.

Reminder generation uses the privacy-controlled AI gateway when enabled,
with a deterministic local fallback.
"""

from datetime import date
from typing import Callable

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from sqlalchemy.orm import Session

from app.schemas.payment_collection import (
    PaymentCreateSchema,
    PaymentRecordingResultSchema,
    PaymentResponseSchema,
    ReceivableSchema,
    ReceivableListResponseSchema,
    ReceivablesSummarySchema,
    AgingSummarySchema,
    CollectionQueueResponseSchema,
    CollectionPrioritySummarySchema,
)

from app.schemas.reminder_generation import (
    ReminderGenerateRequest,
    ReminderDraftResponse,
)

from app.agents.collection_agent import (
    CollectionAgent,
    CollectionInvoiceNotFound,
    CollectionInvoiceNotEligible,
    CollectionReminderError,
)

from app.services.receivables_service import (
    get_invoice_receivable,
    get_receivables_summary,
    list_invoice_receivables,
)

from app.core.config import settings
from app.services.privacy_filter import PrivacyContext
from app.services.private_ai_gateway import (
    generate_collection_template_with_ai,
)

from app.services.aging_service import summarize_aging

from app.services.collection_priority import (
    prioritize_receivables,
    summarize_collection_priorities,
)

from app.services.payment_service import (
    record_payment,
    list_payments,
    PaymentServiceError,
    InvoiceNotFoundError,
    InvoiceNotApprovedError,
    PaymentAmountError,
    DuplicatePaymentError,
    UnsupportedCurrencyError,
)


def create_collections_router(
    get_db_dependency: Callable,
    require_admin_dependency: Callable,
) -> APIRouter:
    """
    Build collections routes using existing app dependencies.

    get_db_dependency:
        An existing FastAPI dependency yielding Session.

    require_admin_dependency:
        An existing dependency that rejects unauthenticated
        requests and returns an authenticated admin object
        with an integer `id`.

    Do not pass a placeholder authentication function.
    """

    router = APIRouter(
        prefix="/api/collections",
        tags=["Payment Collections"],
        dependencies=[
            Depends(require_admin_dependency)
        ],
    )

    # =================================================
    # 1. RECEIVABLES SUMMARY
    # =================================================

    @router.get(
        "/summary",
        response_model=ReceivablesSummarySchema,
    )
    def collections_summary(
        as_of_date: date | None = Query(
            default=None
        ),
        db: Session = Depends(get_db_dependency),
    ):
        return get_receivables_summary(
            db=db,
            as_of_date=as_of_date,
        )

    # =================================================
    # 2. AGING SUMMARY
    # =================================================

    @router.get(
        "/aging",
        response_model=AgingSummarySchema,
    )
    def collections_aging(
        as_of_date: date | None = Query(
            default=None
        ),
        db: Session = Depends(get_db_dependency),
    ):
        today = as_of_date or date.today()

        receivables = list_invoice_receivables(
            db=db,
            as_of_date=today,
        )

        aging_inputs = [
            {
                "invoice_id": item["invoice_id"],
                "due_date": item["due_date"],
                "outstanding_amount": (
                    item["outstanding_amount"]
                ),
            }
            for item in receivables
        ]

        return summarize_aging(
            aging_inputs,
            as_of_date=today,
        )

    # =================================================
    # 3. RECEIVABLES LIST
    # =================================================

    @router.get(
        "/invoices",
        response_model=ReceivableListResponseSchema,
    )
    def collections_invoices(
        as_of_date: date | None = Query(
            default=None
        ),
        include_paid: bool = Query(
            default=False
        ),
        db: Session = Depends(get_db_dependency),
    ):
        receivables = list_invoice_receivables(
            db=db,
            as_of_date=as_of_date,
        )

        if not include_paid:
            receivables = [
                item
                for item in receivables
                if item["outstanding_amount"] != "0.00"
            ]

        return {
            "total": len(receivables),
            "receivables": receivables,
        }

    # =================================================
    # 4. COLLECTION PRIORITY QUEUE
    # =================================================

    @router.get(
        "/queue",
        response_model=CollectionQueueResponseSchema,
    )
    def collections_queue(
        as_of_date: date | None = Query(
            default=None
        ),
        db: Session = Depends(get_db_dependency),
    ):
        today = as_of_date or date.today()

        receivables = list_invoice_receivables(
            db=db,
            as_of_date=today,
        )

        # Reminder table has no confirmed delivery status.
        # Therefore do not count approved drafts as sent.
        queue = prioritize_receivables(
            receivables=receivables,
            reminder_counts={},
            as_of_date=today,
        )

        return {
            "total": len(queue),
            "as_of_date": today,
            "currency": "AED",
            "invoices": queue,
        }

    # =================================================
    # 5. PRIORITY SUMMARY
    # =================================================

    @router.get(
        "/priorities",
        response_model=CollectionPrioritySummarySchema,
    )
    def collections_priorities(
        as_of_date: date | None = Query(
            default=None
        ),
        db: Session = Depends(get_db_dependency),
    ):
        today = as_of_date or date.today()

        receivables = list_invoice_receivables(
            db=db,
            as_of_date=today,
        )

        return summarize_collection_priorities(
            receivables=receivables,
            as_of_date=today,
            reminder_counts={},
        )

    # =================================================
    # 6. SINGLE INVOICE
    # =================================================

    @router.get(
        "/invoices/{invoice_id}",
        response_model=ReceivableSchema,
    )
    def collections_invoice_details(
        invoice_id: int,
        db: Session = Depends(get_db_dependency),
    ):
        result = get_invoice_receivable(
            db=db,
            invoice_id=invoice_id,
        )

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Approved AED invoice not found."
                ),
            )

        return result

    # =================================================
    # 7. PAYMENT HISTORY
    # =================================================

    @router.get(
        "/invoices/{invoice_id}/payments",
        response_model=list[PaymentResponseSchema],
    )
    def collections_payment_history(
        invoice_id: int,
        db: Session = Depends(get_db_dependency),
    ):
        invoice = get_invoice_receivable(
            db=db,
            invoice_id=invoice_id,
        )

        if invoice is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Approved AED invoice not found."
                ),
            )

        return list_payments(
            db=db,
            invoice_id=invoice_id,
        )

    # =================================================
    # 8. RECORD PAYMENT
    # =================================================

    @router.post(
        "/payments",
        response_model=PaymentRecordingResultSchema,
        status_code=status.HTTP_201_CREATED,
    )
    def collections_record_payment(
        payload: PaymentCreateSchema,
        db: Session = Depends(get_db_dependency),
        admin=Depends(require_admin_dependency),
    ):
        """
        Record a manual payment.

        Authentication is required.
        The service validates balances and duplicates.
        """

        admin_id = (
            admin.get("id")
            if isinstance(admin, dict)
            else getattr(admin, "id", None)
        )

        if (
            not isinstance(admin_id, int)
            or isinstance(admin_id, bool)
            or admin_id <= 0
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "A valid administrator identity "
                    "is required."
                ),
            )

        try:
            return record_payment(
                db=db,
                data=payload,
                admin_id=admin_id,
            )

        except InvoiceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            ) from exc

        except DuplicatePaymentError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc

        except (
            InvoiceNotApprovedError,
            PaymentAmountError,
            UnsupportedCurrencyError,
        ) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        except PaymentServiceError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

    # =================================================
    # 9. GENERATE PAYMENT REMINDER DRAFT (LOCAL ONLY)
    # =================================================

    @router.post(
        "/reminders/generate",
        response_model=ReminderDraftResponse,
        summary="Generate a payment reminder draft",
        description=(
            "Prepare an administrator-reviewable reminder for an "
            "approved AED invoice. Does not save, approve or send it. "
            "Uses privacy-checked AI when enabled, otherwise "
            "a local template."
        ),
    )
    def collections_generate_reminder(
        payload: ReminderGenerateRequest,
        db: Session = Depends(get_db_dependency),
        admin=Depends(require_admin_dependency),
    ):
        # Use the authenticated AdminUser object from get_current_admin.
        admin_id = (
            admin.get("id")
            if isinstance(admin, dict)
            else getattr(admin, "id", None)
        )
        if (
            not isinstance(admin_id, int)
            or isinstance(admin_id, bool)
            or admin_id <= 0
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A valid administrator session is required.",
            )

        try:
            # The agent passes only SanitizedReminderContext.
            # A new context is used for this allowlisted request;
            # no original invoice fields enter the callback.
            def approved_ai_generator(safe_context):
                return generate_collection_template_with_ai(
                    safe_context=safe_context,
                    privacy_context=PrivacyContext(),
                )

            ai_generator = (
                approved_ai_generator
                if settings.ai_fallback_enabled and settings.openai_api_key
                else None
            )

            agent = CollectionAgent(
                db=db,
                ai_generator=ai_generator,
            )
            return agent.generate_draft(payload)
        except CollectionInvoiceNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except CollectionInvoiceNotEligible as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except CollectionReminderError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    return router
