
"""
ReceivAI UAE
Module 2 - Payment Collections

Pydantic Schemas

Responsibilities:
- Validate payment recording requests
- Represent receivables balances
- Represent invoice aging information
- Represent collection priority scores
- Structure dashboard API responses

Compatible with Pydantic v2.

This module does not:
- Execute database queries
- Record payments
- Send reminders
- Call OpenAI
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# =====================================================
# 1. SHARED TYPES
# =====================================================

PaymentStatus = Literal[
    "paid",
    "partially_paid",
    "unpaid",
    "overdue",
    "partially_overdue",
    "overpaid",
    "invalid_amount",
]

AgingBucket = Literal[
    "paid",
    "not_due",
    "overdue_1_30",
    "overdue_31_60",
    "overdue_61_90",
    "overdue_90_plus",
    "unknown_due_date",
]

PriorityLevel = Literal[
    "high",
    "medium",
    "low",
    "none",
    "review_required",
]

ReminderAction = Literal[
    "no_action",
    "monitor_invoice",
    "prepare_due_date_reminder",
    "prepare_friendly_reminder",
    "prepare_second_reminder",
    "prepare_firm_follow_up",
    "senior_finance_review",
    "review_invoice_data",
]

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")


# =====================================================
# 2. COMMON BASE SCHEMA
# =====================================================

class CollectionBaseSchema(BaseModel):
    """
    Shared configuration for collection API schemas.

    Decimal amounts remain Decimal internally.
    Pydantic serializes Decimal as strings in JSON.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


# =====================================================
# 3. PAYMENT CREATION
# =====================================================

class PaymentCreateSchema(CollectionBaseSchema):
    """
    Request body for manually recording a payment.

    The backend must additionally:
    - Verify the invoice exists
    - Verify the invoice is approved
    - Verify currency is AED
    - Validate the remaining balance
    - Prevent duplicate payment references
    - Record audit activity
    - Commit atomically

    Request validation alone is not sufficient.
    """

    invoice_id: int = Field(
        ...,
        gt=0,
        description="Existing approved invoice ID.",
    )

    amount_aed: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        description="Positive payment amount in AED.",
    )

    payment_date: date = Field(
        ...,
        description="Actual payment date.",
    )

    payment_reference: str | None = Field(
        default=None,
        max_length=150,
        description="Bank or internal payment reference.",
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional payment notes.",
    )

    @field_validator("amount_aed")
    @classmethod
    def validate_amount(
        cls,
        value: Decimal,
    ) -> Decimal:

        if not value.is_finite():
            raise ValueError(
                "Payment amount must be finite."
            )

        if value <= Decimal("0.00"):
            raise ValueError(
                "Payment amount must be positive."
            )

        if value > MAX_AMOUNT:
            raise ValueError(
                "Payment amount exceeds the allowed limit."
            )

        if value != value.quantize(CENT):
            raise ValueError(
                "Payment amount must have no more "
                "than two decimal places."
            )

        return value

    @field_validator("payment_reference")
    @classmethod
    def clean_reference(
        cls,
        value: str | None,
    ) -> str | None:

        if value is None:
            return None

        value = value.strip()

        return value or None

    @field_validator("notes")
    @classmethod
    def clean_notes(
        cls,
        value: str | None,
    ) -> str | None:

        if value is None:
            return None

        value = value.strip()

        return value or None

    @model_validator(mode="after")
    def validate_payment_date(self):

        if self.payment_date > date.today():
            raise ValueError(
                "Payment date cannot be in the future."
            )

        return self


# =====================================================
# 4. PAYMENT RESPONSE
# =====================================================

class PaymentResponseSchema(CollectionBaseSchema):
    """
    API response for a recorded payment.

    These fields match the existing Payment model.
    """

    id: int
    invoice_id: int

    amount_aed: Decimal

    payment_date: date

    payment_reference: str | None = None

    notes: str | None = None

    created_at: datetime


class PaymentListResponseSchema(CollectionBaseSchema):
    """Response containing recorded payments."""

    total: int = Field(ge=0)

    payments: list[PaymentResponseSchema] = Field(
        default_factory=list
    )


# =====================================================
# 5. INVOICE AGING
# =====================================================

class InvoiceAgingSchema(CollectionBaseSchema):
    """
    Aging result for one invoice.

    Matches aging_service.analyze_invoice_aging().
    """

    invoice_id: int

    due_date: date | None

    as_of_date: date

    outstanding_amount: Decimal

    days_overdue: int | None = Field(
        default=None,
        ge=0,
    )

    aging_bucket: AgingBucket

    aging_label: str

    is_overdue: bool

    due_soon: bool


class AgingBucketSummarySchema(CollectionBaseSchema):
    """
    One aging bucket from
    aging_service.summarize_aging().
    """

    key: str

    label: str

    amount: Decimal = Field(
        ge=Decimal("0.00")
    )

    invoice_count: int = Field(
        ge=0
    )


class AgingSummarySchema(CollectionBaseSchema):
    """Receivables aging summary."""

    as_of_date: date

    currency: Literal["AED"] = "AED"

    total_outstanding: Decimal = Field(
        ge=Decimal("0.00")
    )

    total_overdue: Decimal = Field(
        ge=Decimal("0.00")
    )

    total_due_soon: Decimal = Field(
        ge=Decimal("0.00")
    )

    buckets: list[AgingBucketSummarySchema] = Field(
        default_factory=list
    )


# =====================================================
# 6. RECEIVABLE RESPONSE
# =====================================================

class ReceivableSchema(CollectionBaseSchema):
    """
    Represents one invoice's receivables information.

    Matches the dictionary returned by:
    receivables_service._build_receivable()
    """

    invoice_id: int

    invoice_number: str

    customer_name: str

    customer_email: str | None = None

    currency: Literal["AED"] = "AED"

    invoice_date: date

    due_date: date

    invoice_total: Decimal

    paid_amount: Decimal

    outstanding_amount: Decimal

    overpayment_amount: Decimal = Decimal("0.00")

    payment_count: int = Field(
        default=0,
        ge=0,
    )

    payment_status: PaymentStatus

    days_overdue: int | None = Field(
        default=None,
        ge=0,
    )

    aging_bucket: AgingBucket

    aging_label: str

    is_overdue: bool

    due_soon: bool

    review_status: str

    warnings: list[str] = Field(
        default_factory=list
    )


class ReceivableListResponseSchema(CollectionBaseSchema):
    """API response for the receivables table."""

    total: int = Field(
        ge=0
    )

    receivables: list[ReceivableSchema] = Field(
        default_factory=list
    )


# =====================================================
# 7. RECEIVABLES DASHBOARD SUMMARY
# =====================================================

class ReceivablesSummarySchema(CollectionBaseSchema):
    """
    Matches:
    receivables_service.get_receivables_summary()
    """

    as_of_date: date

    currency: Literal["AED"] = "AED"

    total_invoices: int = Field(
        ge=0
    )

    total_invoiced: Decimal = Field(
        ge=Decimal("0.00")
    )

    total_recorded_payments: Decimal = Field(
        ge=Decimal("0.00")
    )

    total_outstanding: Decimal = Field(
        ge=Decimal("0.00")
    )

    total_overpayments: Decimal = Field(
        ge=Decimal("0.00")
    )

    total_overdue: Decimal = Field(
        ge=Decimal("0.00")
    )

    total_due_soon: Decimal = Field(
        ge=Decimal("0.00")
    )

    collection_rate_percent: Decimal = Field(
        ge=Decimal("0.00"),
        le=Decimal("100.00"),
    )

    paid_invoice_count: int = Field(
        ge=0
    )

    partially_paid_invoice_count: int = Field(
        ge=0
    )

    unpaid_invoice_count: int = Field(
        ge=0
    )

    overdue_invoice_count: int = Field(
        ge=0
    )

    due_soon_invoice_count: int = Field(
        ge=0
    )

    aging_buckets: list[AgingBucketSummarySchema] = Field(
        default_factory=list
    )


# =====================================================
# 8. COLLECTION PRIORITY
# =====================================================

class PriorityScoreBreakdownSchema(
    CollectionBaseSchema
):
    """Explain how the collection score was calculated."""

    overdue: int = Field(
        ge=0
    )

    upcoming: int = Field(
        ge=0
    )

    amount: int = Field(
        ge=0
    )

    payment_history: int = Field(
        ge=0
    )

    reminder_history: int = Field(
        ge=0
    )


class CollectionPrioritySchema(
    ReceivableSchema
):
    """
    Extended receivable model containing collection
    priority information.

    Matches collection_priority.score_receivable().
    """

    priority_score: int = Field(
        ge=0,
        le=100,
    )

    priority_level: PriorityLevel

    priority_label: str

    priority_reasons: list[str] = Field(
        default_factory=list
    )

    recommended_action: ReminderAction

    reminder_count: int = Field(
        default=0,
        ge=0,
    )

    collection_eligible: bool

    priority_warnings: list[str] = Field(
        default_factory=list
    )

    scoring_date: date

    # The scorer omits this for fully settled invoices
    # or invoices requiring data review.
    score_breakdown: (
        PriorityScoreBreakdownSchema | None
    ) = None


class CollectionQueueResponseSchema(
    CollectionBaseSchema
):
    """API response for prioritized collection invoices."""

    total: int = Field(
        ge=0
    )

    as_of_date: date

    currency: Literal["AED"] = "AED"

    invoices: list[CollectionPrioritySchema] = Field(
        default_factory=list
    )


# =====================================================
# 9. COLLECTION PRIORITY SUMMARY
# =====================================================

class PriorityCategorySummarySchema(
    CollectionBaseSchema
):
    """Summary information for one priority category."""

    priority: Literal[
        "high",
        "medium",
        "low",
        "review_required",
    ]

    label: str

    invoice_count: int = Field(
        ge=0
    )

    outstanding_amount: Decimal = Field(
        ge=Decimal("0.00")
    )


class CollectionPrioritySummarySchema(
    CollectionBaseSchema
):
    """
    Matches:
    collection_priority.summarize_collection_priorities()
    """

    as_of_date: date

    currency: Literal["AED"] = "AED"

    total_actionable_invoices: int = Field(
        ge=0
    )

    high_priority_count: int = Field(
        ge=0
    )

    medium_priority_count: int = Field(
        ge=0
    )

    low_priority_count: int = Field(
        ge=0
    )

    manual_review_count: int = Field(
        ge=0
    )

    categories: list[
        PriorityCategorySummarySchema
    ] = Field(
        default_factory=list
    )


# =====================================================
# 10. PAYMENT RECORDING RESULT
# =====================================================

class PaymentRecordingResultSchema(
    CollectionBaseSchema
):
    """
    Response after payment recording succeeds.

    The payment service must commit the transaction
    before returning a success response.
    """

    success: bool

    message: str

    payment: PaymentResponseSchema

    receivable: ReceivableSchema


# =====================================================
# 11. COMMON API ERROR
# =====================================================

class CollectionErrorSchema(
    CollectionBaseSchema
):
    """Consistent error details for collection APIs."""

    error_code: str

    message: str

    invoice_id: int | None = None

    details: list[str] = Field(
        default_factory=list
    )
