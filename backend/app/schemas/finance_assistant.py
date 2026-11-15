"""Pydantic API contracts for ReceivAI UAE's read-only Finance Assistant.

This module defines transport schemas only. It does not access the database,
call an LLM, or perform financial calculations. The assistant service must
populate values from authorized existing finance services.

Monetary values are serialized as two-decimal strings to avoid precision loss
in JSON/JavaScript. For example: "29260.00", never a floating-point AED amount.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Use fixed two-decimal strings for any AED monetary field exposed to React.
# Forecasts and variances may be negative; invoice amounts generally cannot.
AEDAmount = Annotated[
    str,
    Field(
        pattern=r"^-?\d+\.\d{2}$",
        description="An AED amount as an exact string with two decimal places, e.g. '1234.50'.",
        examples=["29260.00"],
    ),
]


class AssistantSchema(BaseModel):
    """Default request/response validation policy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssistantIntent(str, Enum):
    GENERAL = "general"
    INVOICE_LOOKUP = "invoice_lookup"
    RECEIVABLES_SUMMARY = "receivables_summary"
    OVERDUE_ANALYSIS = "overdue_analysis"
    PAYMENT_HISTORY = "payment_history"
    RECONCILIATION = "reconciliation"
    COLLECTION_PRIORITIES = "collection_priorities"
    CASH_FLOW_FORECAST = "cash_flow_forecast"
    DOCUMENT_REVIEWS = "document_reviews"
    REMINDER_STATUS = "reminder_status"
    UNSUPPORTED = "unsupported"


class DataSource(str, Enum):
    DASHBOARD = "dashboard_summary"
    INVOICES = "invoice_register"
    PAYMENTS = "payment_ledger"
    COLLECTIONS = "payment_collections"
    FORECAST = "cash_flow_forecast"
    DOCUMENTS = "document_intelligence"
    REMINDERS = "collection_reminders"


class DataNature(str, Enum):
    """Make factual accounting data distinguishable from predictions."""

    RECORDED = "recorded"  # Stored invoice/payment/document facts
    CALCULATED = "calculated"  # Deterministic calculations over recorded facts
    ESTIMATED = "estimated"  # Assumption-based predictions


class ResponseStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"  # Some requested facts could not be retrieved
    NO_DATA = "no_data"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ValueType(str, Enum):
    AED = "aed"
    COUNT = "count"
    PERCENT = "percent"
    DATE = "date"
    TEXT = "text"


class FinanceChatHistoryMessage(AssistantSchema):
    """Optional recent chat context; never accepts system or tool roles."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class FinanceAssistantChatRequest(AssistantSchema):
    """Request body for POST /api/assistant/chat."""

    question: str = Field(
        min_length=3,
        max_length=2000,
        description="Finance question submitted by the signed-in administrator.",
    )
    session_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional client session identifier; not an authentication token.",
    )
    history: list[FinanceChatHistoryMessage] = Field(
        default_factory=list,
        max_length=10,
        description="Recent messages for follow-up context (oldest first).",
    )
    horizon_days: Literal[7, 30, 60, 90] = Field(
        default=30,
        description="Default forecast period when the question requests a cash forecast.",
    )


class FinanceMetric(AssistantSchema):
    """A value to render in an answer's financial KPI cards."""

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=100)
    value_type: ValueType = ValueType.TEXT
    nature: DataNature = DataNature.RECORDED
    description: str | None = Field(default=None, max_length=300)
    source: DataSource

    @model_validator(mode="after")
    def check_aed_format(self) -> "FinanceMetric":
        if self.value_type == ValueType.AED and not re.fullmatch(
            r"-?\d+\.\d{2}", self.value
        ):
            raise ValueError("AED metric values must be two-decimal strings")
        return self


class FinanceTableColumn(AssistantSchema):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    value_type: ValueType = ValueType.TEXT


# Finite, plain JSON-safe table cells. All money values must be AED strings.
TableCell = str | int | bool | None


class FinanceDataTable(AssistantSchema):
    title: str = Field(min_length=1, max_length=150)
    columns: list[FinanceTableColumn] = Field(min_length=1, max_length=12)
    rows: list[dict[str, TableCell]] = Field(default_factory=list, max_length=100)
    description: str | None = Field(default=None, max_length=350)
    nature: DataNature = DataNature.RECORDED
    source: DataSource
    total_rows: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_table_money_columns(self) -> "FinanceDataTable":
        money_keys = {column.key for column in self.columns if column.value_type == ValueType.AED}
        for row in self.rows:
            for key in money_keys:
                value = row.get(key)
                if value is not None and (
                    not isinstance(value, str)
                    or not re.fullmatch(r"-?\d+\.\d{2}", value)
                ):
                    raise ValueError(f"Table AED column '{key}' must contain two-decimal strings")
        return self


class FinanceInvoiceReference(AssistantSchema):
    """Optional invoice links in a response; no raw document contents."""

    invoice_id: int = Field(gt=0)
    invoice_number: str = Field(min_length=1, max_length=120)
    customer_name: str | None = Field(default=None, max_length=250)
    due_date: date | None = None
    invoice_status: str | None = Field(default=None, max_length=40)
    outstanding_aed: AEDAmount | None = None
    days_overdue: int | None = Field(default=None, ge=0)


class FinanceInsight(AssistantSchema):
    severity: Severity = Severity.INFO
    title: str = Field(min_length=1, max_length=150)
    explanation: str = Field(min_length=1, max_length=1500)
    recommended_action: str | None = Field(default=None, max_length=600)
    related_invoice_ids: list[int] = Field(default_factory=list, max_length=25)
    nature: DataNature = DataNature.CALCULATED


class FinanceNavigationAction(AssistantSchema):
    """Read-only links to existing pages; not instructions to mutate records."""

    label: str = Field(min_length=1, max_length=100)
    href: str = Field(min_length=1, max_length=350)
    description: str | None = Field(default=None, max_length=250)
    kind: Literal["navigate"] = "navigate"

    @field_validator("href")
    @classmethod
    def internal_navigation_only(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or any(char in value for char in ("\r", "\n", "\t"))
        ):
            raise ValueError("Navigation must use an internal relative URL path")
        return value


class FinanceEvidence(AssistantSchema):
    """Provenance displayed alongside answers to avoid unsupported claims."""

    source: DataSource
    description: str = Field(min_length=1, max_length=300)
    nature: DataNature
    as_of: datetime | None = None
    record_ids: list[int] = Field(default_factory=list, max_length=100)


class FinanceAssistantChatResponse(AssistantSchema):
    """Response body for POST /api/assistant/chat."""

    session_id: str | None = Field(default=None, max_length=128)
    question: str = Field(min_length=3, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)
    intent: AssistantIntent
    status: ResponseStatus = ResponseStatus.SUCCESS
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    data_as_of: datetime | None = None
    currency: Literal["AED"] = "AED"
    read_only: Literal[True] = True
    metrics: list[FinanceMetric] = Field(default_factory=list, max_length=20)
    tables: list[FinanceDataTable] = Field(default_factory=list, max_length=5)
    invoices: list[FinanceInvoiceReference] = Field(default_factory=list, max_length=100)
    insights: list[FinanceInsight] = Field(default_factory=list, max_length=20)
    actions: list[FinanceNavigationAction] = Field(default_factory=list, max_length=10)
    evidence: list[FinanceEvidence] = Field(default_factory=list, max_length=15)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=6)


class FinanceSuggestedQuestion(AssistantSchema):
    id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=3, max_length=250)
    category: AssistantIntent
    description: str | None = Field(default=None, max_length=200)


class FinanceAssistantSuggestionsResponse(AssistantSchema):
    """Response body for GET /api/assistant/suggestions."""

    suggestions: list[FinanceSuggestedQuestion] = Field(default_factory=list)


class FinanceAssistantCapability(AssistantSchema):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=350)
    available: bool
    sources: list[DataSource] = Field(default_factory=list)
    read_only: Literal[True] = True


class FinanceAssistantCapabilitiesResponse(AssistantSchema):
    """Response body for GET /api/assistant/capabilities."""

    capabilities: list[FinanceAssistantCapability] = Field(default_factory=list)
    supported_horizons_days: list[Literal[7, 30, 60, 90]] = Field(
        default_factory=lambda: [7, 30, 60, 90]
    )
    currency: Literal["AED"] = "AED"
    read_only: Literal[True] = True


class FinanceAssistantErrorResponse(AssistantSchema):
    """Optional structured error payload for authenticated route handlers."""

    error_code: Literal[
        "invalid_question",
        "unsupported_question",
        "data_unavailable",
        "service_error",
    ]
    message: str = Field(min_length=1, max_length=500)
    request_id: str | None = Field(default=None, max_length=128)
