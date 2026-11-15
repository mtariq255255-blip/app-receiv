
"""
ReceivAI UAE
Module 2 - Payment Collections

AI Reminder Generation Schemas

Pydantic v2.

No database access.
No direct OpenAI calls.
"""

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


ReminderTone = Literal[
    "friendly",
    "professional",
    "firm",
]

ReminderStage = Literal[
    "pre_due",
    "first",
    "second",
    "final",
]

ReminderChannel = Literal["email"]

DueCategory = Literal[
    "due_soon",
    "overdue_1_7",
    "overdue_8_30",
    "overdue_31_60",
    "overdue_61_90",
    "overdue_90_plus",
]

PaymentCategory = Literal[
    "unpaid",
    "partially_paid",
]


class ReminderBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class ReminderGenerateRequest(ReminderBase):
    """
    Administrator's reminder-generation request.

    The backend must look up the invoice using its ID.
    The client must never supply authoritative balances
    or overdue information.
    """

    invoice_id: int = Field(gt=0)

    tone: ReminderTone = "professional"

    channel: ReminderChannel = "email"


class SanitizedReminderContext(ReminderBase):
    """
    Exact fields permitted to reach OpenAI.

    No names, emails, invoice references,
    TRNs, addresses or exact monetary amounts.
    """

    task: Literal[
        "generate_payment_reminder"
    ] = "generate_payment_reminder"

    tone: ReminderTone

    stage: ReminderStage

    due_category: DueCategory

    payment_category: PaymentCategory

    currency: Literal["AED"] = "AED"

    permitted_placeholders: list[str] = Field(
        default_factory=lambda: [
            "customer_name",
            "invoice_number",
            "outstanding_amount",
            "due_date",
            "sender_name",
        ]
    )


class AIReminderTemplate(ReminderBase):
    """
    Structure of the AI response.

    The output must contain placeholders rather
    than real customer or invoice information.
    """

    subject: str = Field(
        min_length=5,
        max_length=180,
    )

    body: str = Field(
        min_length=40,
        max_length=2000,
    )

    @field_validator("subject", "body")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Reminder text cannot be empty."
            )

        return value


class ReminderDraftResponse(ReminderBase):
    """
    Result returned to an administrator.

    This is an in-memory draft, not proof that
    a reminder has been saved or sent.
    """

    invoice_id: int

    channel: ReminderChannel = "email"

    tone: ReminderTone

    stage: ReminderStage

    subject: str

    message: str

    generation_method: Literal[
        "openai",
        "local_template",
    ]

    ai_used: bool

    privacy_safe: bool = True

    approval_status: Literal[
        "draft"
    ] = "draft"

    requires_admin_approval: bool = True

    sent: bool = False

    created_at: datetime

    warnings: list[str] = Field(
        default_factory=list
    )
