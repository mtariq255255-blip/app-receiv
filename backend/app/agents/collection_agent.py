
"""
ReceivAI UAE
Module 2 - AI Collection Assistant

Responsibilities:
- Retrieve approved invoice receivables
- Validate collection eligibility
- Determine overdue stage and priority
- Build an allowlisted AI context
- Optionally request a template through a trusted
  privacy-approved AI gateway callback
- Validate the returned template
- Merge confidential invoice values locally
- Return a draft for administrator review

IMPORTANT:
- Does not modify the database.
- Does not create Reminder rows.
- Does not approve or send messages.
- Does not call OpenAI directly.
- All external AI calls must use the existing
  privacy-controlled gateway.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.models.entities import Invoice

from app.schemas.reminder_generation import (
    AIReminderTemplate,
    ReminderGenerateRequest,
    ReminderDraftResponse,
    SanitizedReminderContext,
)

from app.services.receivables_service import (
    get_invoice_receivable,
)

# NEW: Shared eligibility for approved uploaded invoices
# and finalized manually generated invoices.
from app.services.invoice_eligibility import (
    evaluate_invoice_for_receivables,
)

from app.services.collection_priority import (
    score_receivable,
)

from app.services.reminder_template_service import (
    build_sanitized_context,
    make_local_template,
    render_reminder_template,
    validate_reminder_template,
    ReminderTemplateError,
)


# AI callback must receive ONLY sanitized context.
# It must return a validated template or a dictionary
# with exactly the subject and body keys.
ReminderAIGenerator = Callable[
    [SanitizedReminderContext],
    AIReminderTemplate | dict,
]


class CollectionAgentError(Exception):
    """Base collection-agent error."""


class CollectionInvoiceNotFound(
    CollectionAgentError
):
    pass


class CollectionInvoiceNotEligible(
    CollectionAgentError
):
    pass


class CollectionReminderError(
    CollectionAgentError
):
    pass


class CollectionAgent:
    """
    AI-assisted payment reminder drafting.

    Requires a database session.

    ai_generator is optional. When absent, the agent
    uses deterministic local templates with zero
    OpenAI calls.

    Never inject an unrestricted AI function that
    forwards invoice or customer information.
    """

    def __init__(
        self,
        db: Session,
        ai_generator: ReminderAIGenerator | None = None,
        as_of_date: date | None = None,
    ):
        self.db = db
        self.ai_generator = ai_generator
        self.as_of_date = as_of_date or date.today()

    # =================================================
    # 1. RETRIEVE VERIFIED COLLECTION DATA
    # =================================================

    def _get_receivable(
        self,
        invoice_id: int,
    ) -> dict:

        receivable = get_invoice_receivable(
            db=self.db,
            invoice_id=invoice_id,
            as_of_date=self.as_of_date,
        )

        if receivable is None:
            raise CollectionInvoiceNotFound(
                "Approved AED invoice not found."
            )

        return receivable

    # =================================================
    # 2. VALIDATE COLLECTION ELIGIBILITY
    # =================================================

    def _validate_eligibility(
        self,
        receivable: dict,
    ) -> dict:
        """Block uncertain payments and ineligible collection attempts.

        Review state and invoice status are read from the actual Invoice
        row, not from a client-supplied or derived status.
        """

        invoice_id = receivable.get("invoice_id")

        invoice = self.db.scalar(
            select(Invoice).where(
                Invoice.id == invoice_id
            )
        )

        if invoice is None:
            raise CollectionInvoiceNotFound(
                "Invoice not found."
            )

        # =================================================
        # NEW: UNIFIED INVOICE ELIGIBILITY
        # =================================================
        #
        # The same policy is used by:
        # - Payment Service
        # - Receivables Service
        # - Reminder Approval Routes
        # - Collection Agent
        #
        # Supports:
        # - Uploaded invoices with "reviewed" status
        # - Uploaded invoices with "corrected" status
        # - Uploaded invoices with "approved" status
        # - Finalized manually generated invoices
        #
        # Rejects:
        # - Unapproved invoices
        # - Cancelled or voided invoices
        # - Foreign-currency invoices
        # - Invalid or zero-total invoices
        # - Invoices without valid due dates
        #
        # No currency conversion is performed.
        # =================================================

        decision = evaluate_invoice_for_receivables(
            invoice
        )

        if not decision.eligible:
            raise CollectionInvoiceNotEligible(
                decision.message
            )

        # =================================================
        # EXISTING FINANCIAL VALIDATION
        # =================================================

        def valid_amount(
            value: object,
            label: str,
        ) -> Decimal:

            try:
                result = Decimal(
                    str(value)
                )

            except (
                InvalidOperation,
                ValueError,
                TypeError,
            ) as exc:

                raise CollectionInvoiceNotEligible(
                    f"Invalid {label}."
                ) from exc

            if (
                not result.is_finite()
                or result < 0
            ):
                raise CollectionInvoiceNotEligible(
                    f"Invalid {label}."
                )

            return result

        total = valid_amount(
            receivable.get("invoice_total"),
            "invoice total",
        )

        paid = valid_amount(
            receivable.get("paid_amount"),
            "recorded payment total",
        )

        outstanding = valid_amount(
            receivable.get("outstanding_amount"),
            "outstanding balance",
        )

        if total <= 0 or outstanding <= 0:
            raise CollectionInvoiceNotEligible(
                "Invoice has no positive outstanding balance."
            )

        # =================================================
        # RECONCILIATION PROTECTION
        # =================================================
        #
        # Manual invoice.status changes do not create
        # Payment rows.
        #
        # Do not contact a customer about a paid-marked
        # invoice until Finance reconciles the recorded
        # payments and invoice status.
        # =================================================

        if (
            invoice.status == "paid"
            and paid < total
        ):
            raise CollectionInvoiceNotEligible(
                "Invoice is marked paid but recorded payments do not "
                "reconcile. Finance administrator review is required."
            )

        if (
            paid > total
            or (
                total - paid
            ).quantize(
                Decimal("0.01")
            ) != outstanding.quantize(
                Decimal("0.01")
            )
        ):
            raise CollectionInvoiceNotEligible(
                "Invoice balance requires reconciliation before contact."
            )

        if receivable.get("payment_status") in {
            "paid",
            "overpaid",
            "invalid_amount",
        }:
            raise CollectionInvoiceNotEligible(
                "Invoice payment status requires manual review."
            )

        # =================================================
        # DUE DATE VALIDATION
        # =================================================

        raw_due_date = receivable.get(
            "due_date"
        )

        if isinstance(
            raw_due_date,
            datetime,
        ):
            due_date = raw_due_date.date()

        elif isinstance(
            raw_due_date,
            date,
        ):
            due_date = raw_due_date

        elif isinstance(
            raw_due_date,
            str,
        ):

            try:
                due_date = date.fromisoformat(
                    raw_due_date
                )

            except ValueError as exc:
                raise CollectionInvoiceNotEligible(
                    "Invoice due date is invalid."
                ) from exc

        else:
            raise CollectionInvoiceNotEligible(
                "Invoice due date is missing."
            )

        # =================================================
        # SEVEN-DAY REMINDER WINDOW
        # =================================================
        #
        # A reminder can be generated when the invoice
        # is overdue or within seven days of its due date.
        #
        # This preserves your original timing policy.
        # =================================================

        if (
            due_date - self.as_of_date
        ).days > 7:
            raise CollectionInvoiceNotEligible(
                "Invoice is not yet within the seven-day reminder window."
            )

        # =================================================
        # EXISTING COLLECTION PRIORITY SCORING
        # =================================================

        scored = score_receivable(
            receivable,
            reminder_count=0,
            as_of_date=self.as_of_date,
        )

        if not scored.get(
            "collection_eligible",
            False,
        ):
            raise CollectionInvoiceNotEligible(
                "Invoice requires manual financial review before "
                "reminder generation."
            )

        return scored

    # =================================================
    # 3. GENERATE SAFE TEMPLATE
    # =================================================

    def _generate_template(
        self,
        context: SanitizedReminderContext,
    ) -> tuple[
        AIReminderTemplate,
        str,
        list[str],
    ]:
        """
        Attempt approved AI template generation.

        If unavailable, invalid or unsuccessful,
        use a deterministic local template.

        The AI callback receives only the Pydantic
        SanitizedReminderContext, never the invoice.
        """

        warnings = []

        # ---------------------------------------------
        # Deterministic local reminder generation
        # ---------------------------------------------

        if self.ai_generator is None:

            return (
                make_local_template(context),
                "local_template",
                warnings,
            )

        # ---------------------------------------------
        # Privacy-approved AI callback
        # ---------------------------------------------

        try:
            response = self.ai_generator(
                context
            )

            if isinstance(
                response,
                AIReminderTemplate,
            ):
                template = response

            else:
                template = (
                    AIReminderTemplate.model_validate(
                        response
                    )
                )

            validate_reminder_template(
                template
            )

            return (
                template,
                "openai",
                warnings,
            )

        except Exception:
            # Do not expose raw model output,
            # exceptions or sensitive data in the UI.
            warnings.append(
                "AI template generation was unavailable "
                "or did not pass safety validation. "
                "A local reminder template was used."
            )

            return (
                make_local_template(context),
                "local_template",
                warnings,
            )

    # =================================================
    # 4. BUILD A REMINDER DRAFT
    # =================================================

    def generate_draft(
        self,
        request: ReminderGenerateRequest,
    ) -> ReminderDraftResponse:
        """
        Generate one reminder draft.

        No database changes and no message delivery.
        """

        # ---------------------------------------------
        # Step 1: Retrieve approved receivable
        # ---------------------------------------------

        receivable = self._get_receivable(
            request.invoice_id
        )

        # ---------------------------------------------
        # Step 2: Validate collection eligibility
        # ---------------------------------------------

        scored = self._validate_eligibility(
            receivable
        )

        days_overdue = scored[
            "days_overdue"
        ]

        if days_overdue is None:
            raise CollectionInvoiceNotEligible(
                "Invoice due date is invalid."
            )

        # ---------------------------------------------
        # Step 3: Build sanitized AI context
        # ---------------------------------------------

        context = build_sanitized_context(
            tone=request.tone,
            days_overdue=days_overdue,
            paid_amount=receivable[
                "paid_amount"
            ],
        )

        # ---------------------------------------------
        # Step 4: Generate safe reminder template
        # ---------------------------------------------

        template, method, warnings = (
            self._generate_template(
                context
            )
        )

        # ---------------------------------------------
        # Step 5: Merge confidential values locally
        # ---------------------------------------------

        try:
            rendered = render_reminder_template(
                template,
                invoice_number=(
                    receivable[
                        "invoice_number"
                    ]
                ),
                customer_name=(
                    receivable[
                        "customer_name"
                    ]
                ),
                outstanding_amount=(
                    receivable[
                        "outstanding_amount"
                    ]
                ),
                due_date=(
                    receivable[
                        "due_date"
                    ]
                ),
            )

        except ReminderTemplateError as exc:
            raise CollectionReminderError(
                "Reminder could not be rendered "
                "from the approved invoice data."
            ) from exc

        # ---------------------------------------------
        # Step 6: Return admin-review draft
        # ---------------------------------------------

        return ReminderDraftResponse(
            invoice_id=request.invoice_id,
            channel=request.channel,
            tone=request.tone,
            stage=context.stage,
            subject=rendered["subject"],
            message=rendered["message"],
            generation_method=method,
            ai_used=(
                method == "openai"
            ),
            privacy_safe=True,
            approval_status="draft",
            requires_admin_approval=True,
            sent=False,
            created_at=datetime.now(
                timezone.utc
            ),
            warnings=warnings,
        )


# =====================================================
# 5. CONVENIENCE HELPER
# =====================================================

def generate_collection_reminder(
    *,
    db: Session,
    invoice_id: int,
    tone: str = "professional",
    ai_generator: ReminderAIGenerator | None = None,
    as_of_date: date | None = None,
) -> dict:
    """
    Convenience helper for generating a reminder.

    Returns JSON-compatible draft data.
    """

    request = ReminderGenerateRequest(
        invoice_id=invoice_id,
        tone=tone,
        channel="email",
    )

    agent = CollectionAgent(
        db=db,
        ai_generator=ai_generator,
        as_of_date=as_of_date,
    )

    draft = agent.generate_draft(
        request
    )

    return draft.model_dump(
        mode="json"
    )
