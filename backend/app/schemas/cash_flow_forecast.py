
"""
ReceivAI UAE — Cash-In Forecasting API Schemas

Purpose:
    Define request and response structures for forecasting
    expected collections from existing AED receivables.

Framework:
    FastAPI + Pydantic v2

Important:
    This module does not predict company-wide net cash flow.
    Expenses, payroll, supplier payments and bank balances
    are not part of the current forecasting scope.

    Forecasted receipts are estimates, not guaranteed payments.
    Recorded payments are not necessarily bank-verified receipts.

    This module performs validation and serialization only.
    It does not query PostgreSQL or calculate forecasts.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)


# ============================================================
# 1. SHARED FORECAST TYPES
# ============================================================

ForecastHorizon = Literal[
    7,
    30,
    60,
    90,
]

ForecastScenario = Literal[
    "conservative",
    "base",
    "optimistic",
]

ForecastGranularity = Literal[
    "day",
    "week",
    "month",
]

ForecastBasis = Literal[
    "customer_history",
    "portfolio_history",
    "documented_fallback",
]

ForecastStatus = Literal[
    "included",
    "excluded",
    "reconciliation_required",
]

ForecastRiskLevel = Literal[
    "low",
    "medium",
    "high",
    "review_required",
]

ForecastInsightSeverity = Literal[
    "info",
    "warning",
    "critical",
]

ForecastAgingBucket = Literal[
    "paid",
    "not_due",
    "overdue_1_30",
    "overdue_31_60",
    "overdue_61_90",
    "overdue_90_plus",
    "unknown_due_date",
]


# ============================================================
# 2. EXACT FINANCIAL DATA TYPES
# ============================================================

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _reject_floating_point(value: object) -> object:
    """
    Prevent floating-point values entering financial
    and probability calculations.

    Decimal strings are accepted:

        "2500.00"
        "0.7500"

    Floating-point inputs are rejected.
    """

    if isinstance(value, (float, bool)):
        raise ValueError(
            "Use an exact decimal string, "
            "not a floating-point number."
        )

    return value


AmountAED = Annotated[
    Decimal,
    BeforeValidator(_reject_floating_point),
    Field(
        ge=ZERO,
        max_digits=14,
        decimal_places=2,
        allow_inf_nan=False,
    ),
]


SignedAmountAED = Annotated[
    Decimal,
    BeforeValidator(_reject_floating_point),
    Field(
        max_digits=14,
        decimal_places=2,
        allow_inf_nan=False,
    ),
]


CollectionProbability = Annotated[
    Decimal,
    BeforeValidator(_reject_floating_point),
    Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        max_digits=5,
        decimal_places=4,
        allow_inf_nan=False,
    ),
]


# ============================================================
# 3. COMMON BASE SCHEMA
# ============================================================

class ForecastBaseSchema(BaseModel):
    """
    Shared validation configuration.

    Decimal amounts remain exact and serialize
    as strings in JSON responses.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


# ============================================================
# 4. FORECAST REQUEST PARAMETERS
# ============================================================

class ForecastQuery(ForecastBaseSchema):
    """
    Standard query parameters for cash-in forecasting.

    Supported horizons:
        7, 30, 60, 90 days

    Supported scenarios:
        conservative, base, optimistic

    When as_of_date is omitted, the forecasting service
    will use the current UAE-local calendar date.

    The forecast includes the as_of_date itself.
    """

    horizon_days: ForecastHorizon = 30

    as_of_date: date | None = None

    scenario: ForecastScenario = "base"


class ForecastTimelineQuery(ForecastQuery):
    """
    Forecast parameters including chart grouping.
    """

    group_by: ForecastGranularity = "week"


class ForecastInvoiceQuery(ForecastQuery):
    """
    Invoice-level forecast pagination and filtering.
    """

    page: int = Field(
        default=1,
        ge=1,
    )

    page_size: int = Field(
        default=50,
        ge=1,
        le=200,
    )

    include_excluded: bool = False


# ============================================================
# 5. FORECAST METADATA
# ============================================================

class ForecastMetadata(ForecastBaseSchema):
    """
    Describes when and how the forecast was calculated.

    Forecasting only covers expected AED collections
    from receivables.

    Payment records are not represented as bank
    verification evidence.
    """

    as_of_date: date

    start_date: date

    end_date: date

    horizon_days: ForecastHorizon

    scenario: ForecastScenario

    generated_at: datetime

    currency: Literal["AED"] = "AED"

    scope: Literal[
        "receivables_cash_in_only"
    ] = "receivables_cash_in_only"

    payment_evidence: Literal[
        "recorded_not_bank_verified"
    ] = "recorded_not_bank_verified"

    methodology: Literal[
        "deterministic_rules"
    ] = "deterministic_rules"

    assumptions_used: bool = False

    @model_validator(mode="after")
    def check_window(self) -> "ForecastMetadata":
        """
        Validate the forecast period and generation time.
        """

        if self.start_date != self.as_of_date:
            raise ValueError(
                "Forecast start_date must equal as_of_date."
            )

        window_days = (
            self.end_date - self.start_date
        ).days

        if window_days != self.horizon_days - 1:
            raise ValueError(
                "Forecast window must include exactly "
                "horizon_days calendar dates."
            )

        if (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset() is None
        ):
            raise ValueError(
                "generated_at must be timezone-aware."
            )

        return self


# ============================================================
# 6. TRANSPARENT FORECAST ASSUMPTIONS
# ============================================================

class ForecastAssumption(ForecastBaseSchema):
    """
    Represents one collection probability or delay assumption.

    Example:
        A customer has historically paid late.

    The forecasting service may use:
        - Customer payment history
        - Portfolio-level payment history
        - Documented fallback assumptions

    Fallback assumptions must not be described as
    measured customer probabilities.
    """

    label: str = Field(
        min_length=1,
        max_length=120,
    )

    basis: ForecastBasis

    collection_probability: CollectionProbability

    expected_delay_days: int = Field(
        ge=0,
        le=365,
    )

    historical_sample_count: int = Field(
        default=0,
        ge=0,
    )

    explanation: str = Field(
        min_length=1,
        max_length=1000,
    )


class ForecastAssumptionsResponse(ForecastBaseSchema):
    """
    Details assumptions used to calculate the forecast.
    """

    metadata: ForecastMetadata

    assumptions: list[ForecastAssumption] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# 7. FORECAST DASHBOARD METRICS
# ============================================================

class ForecastSummaryMetrics(ForecastBaseSchema):
    """
    Main numerical metrics for the forecast dashboard.

    total_outstanding_aed:
        Unpaid receivables as of the report date.

    overdue_outstanding_aed:
        Outstanding invoices already past due.

    due_within_horizon_aed:
        Outstanding balance contractually due within
        the selected forecasting period.

    expected_collections_aed:
        Probability-weighted collections expected
        within the forecast period.

    at_risk_outstanding_aed:
        Outstanding balance flagged by risk rules.

    recorded_collections_last_30_days_aed:
        Payments recorded in the previous 30 days.
        These are not bank-verified deposits.
    """

    total_outstanding_aed: AmountAED

    overdue_outstanding_aed: AmountAED

    due_within_horizon_aed: AmountAED

    expected_collections_aed: AmountAED

    at_risk_outstanding_aed: AmountAED

    recorded_collections_last_30_days_aed: AmountAED

    eligible_invoice_count: int = Field(
        ge=0,
    )

    forecast_invoice_count: int = Field(
        ge=0,
    )

    excluded_invoice_count: int = Field(
        ge=0,
    )

    reconciliation_required_count: int = Field(
        ge=0,
    )

    @model_validator(mode="after")
    def check_amount_relationships(
        self,
    ) -> "ForecastSummaryMetrics":
        """
        Prevent inconsistent dashboard metrics.
        """

        if (
            self.expected_collections_aed
            > self.total_outstanding_aed
        ):
            raise ValueError(
                "Expected collections cannot exceed "
                "total outstanding receivables."
            )

        if (
            self.overdue_outstanding_aed
            > self.total_outstanding_aed
        ):
            raise ValueError(
                "Overdue amount cannot exceed "
                "total outstanding receivables."
            )

        if (
            self.at_risk_outstanding_aed
            > self.total_outstanding_aed
        ):
            raise ValueError(
                "At-risk amount cannot exceed "
                "total outstanding receivables."
            )

        return self


class ForecastSummaryResponse(ForecastBaseSchema):
    """
    Response for:

    GET /api/forecast/summary
    """

    metadata: ForecastMetadata

    metrics: ForecastSummaryMetrics

    warnings: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# 8. FORECAST TIMELINE AND CHART DATA
# ============================================================

class ForecastTimelinePoint(ForecastBaseSchema):
    """
    One time period in the forecast timeline.

    Periods can represent:
        - One day
        - One week
        - One month

    Each point contains estimated collections
    and cumulative forecast amounts.
    """

    period_start: date

    period_end: date

    projected_collections_aed: AmountAED

    cumulative_projected_aed: AmountAED

    due_invoice_balance_aed: AmountAED

    invoice_count: int = Field(
        ge=0,
    )

    @model_validator(mode="after")
    def validate_period(
        self,
    ) -> "ForecastTimelinePoint":

        if self.period_end < self.period_start:
            raise ValueError(
                "Timeline period_end cannot precede "
                "period_start."
            )

        return self


class ForecastTimelineResponse(ForecastBaseSchema):
    """
    Response for:

    GET /api/forecast/timeline
    """

    metadata: ForecastMetadata

    group_by: ForecastGranularity

    points: list[ForecastTimelinePoint] = Field(
        default_factory=list,
    )

    projected_total_aed: AmountAED

    warnings: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# 9. INVOICE-LEVEL CASH-IN PROJECTIONS
# ============================================================

class ForecastInvoiceProjection(ForecastBaseSchema):
    """
    Forecast details for one invoice.

    Financial data must come from the existing
    Invoice and Payment records.

    The forecasting service must reuse the existing
    invoice eligibility and reconciliation rules.

    Excluded or unreconciled invoices must not
    contribute projected collections.
    """

    invoice_id: int = Field(
        gt=0,
    )

    invoice_number: str = Field(
        min_length=1,
        max_length=150,
    )

    customer_name: str = Field(
        min_length=1,
        max_length=200,
    )

    due_date: date | None

    invoice_total_aed: AmountAED

    recorded_paid_aed: AmountAED

    outstanding_aed: AmountAED

    days_overdue: int = Field(
        default=0,
        ge=0,
    )

    aging_bucket: ForecastAgingBucket

    payment_count: int = Field(
        default=0,
        ge=0,
    )

    forecast_status: ForecastStatus

    expected_receipt_date: date | None = None

    within_horizon: bool = False

    collection_probability: CollectionProbability | None = None

    expected_collection_aed: AmountAED = ZERO

    basis: ForecastBasis | None = None

    risk_level: ForecastRiskLevel = "low"

    risk_reasons: list[str] = Field(
        default_factory=list,
    )

    recommended_action: str | None = Field(
        default=None,
        max_length=300,
    )

    exclusion_reason: str | None = Field(
        default=None,
        max_length=500,
    )

    @model_validator(mode="after")
    def check_projection(
        self,
    ) -> "ForecastInvoiceProjection":
        """
        Ensure invoice forecast data is internally consistent.
        """

        if (
            self.outstanding_aed
            > self.invoice_total_aed
        ):
            raise ValueError(
                "Outstanding amount cannot exceed "
                "invoice total."
            )

        if (
            self.expected_collection_aed
            > self.outstanding_aed
        ):
            raise ValueError(
                "Projected collection cannot exceed "
                "outstanding amount."
            )

        if self.forecast_status != "included":

            if (
                self.expected_collection_aed != ZERO
                or self.within_horizon
            ):
                raise ValueError(
                    "Excluded or unreconciled invoices "
                    "cannot contribute to the forecast."
                )

            if not self.exclusion_reason:
                raise ValueError(
                    "Excluded invoices require an explanation."
                )

        elif (
            self.collection_probability is None
            or self.basis is None
        ):
            raise ValueError(
                "Included invoices require an explicit "
                "probability and source basis."
            )

        if (
            self.within_horizon
            and self.expected_receipt_date is None
        ):
            raise ValueError(
                "Forecasted in-window receipts require "
                "an expected receipt date."
            )

        return self


class ForecastInvoiceListResponse(ForecastBaseSchema):
    """
    Response for:

    GET /api/forecast/invoices

    Supports paginated invoice-level projections.
    """

    metadata: ForecastMetadata

    invoices: list[ForecastInvoiceProjection] = Field(
        default_factory=list,
    )

    total: int = Field(
        ge=0,
    )

    page: int = Field(
        ge=1,
    )

    page_size: int = Field(
        ge=1,
        le=200,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# 10. FORECAST SCENARIOS
# ============================================================

class ForecastScenarioResult(ForecastBaseSchema):
    """
    One forecast scenario.

    Conservative:
        Lower expected near-term collections.

    Base:
        Expected collection behavior based on
        available data and documented assumptions.

    Optimistic:
        Higher or earlier expected collections.

    Scenario amounts must be calculated by the
    forecasting service, not invented by an LLM.
    """

    scenario: ForecastScenario

    expected_collections_aed: AmountAED

    difference_from_base_aed: SignedAmountAED

    forecast_invoice_count: int = Field(
        ge=0,
    )

    assumptions: list[ForecastAssumption] = Field(
        default_factory=list,
    )

    explanation: str = Field(
        min_length=1,
        max_length=1000,
    )


class ForecastScenariosResponse(ForecastBaseSchema):
    """
    Response for:

    GET /api/forecast/scenarios
    """

    metadata: ForecastMetadata

    scenarios: list[ForecastScenarioResult] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def unique_scenario_names(
        self,
    ) -> "ForecastScenariosResponse":

        names = [
            scenario.scenario
            for scenario in self.scenarios
        ]

        if len(names) != len(set(names)):
            raise ValueError(
                "Each forecast scenario can appear only once."
            )

        return self


# ============================================================
# 11. FORECAST RISK INSIGHTS
# ============================================================

class ForecastInsight(ForecastBaseSchema):
    """
    A transparent, action-oriented forecasting insight.

    Examples:
        - High overdue exposure
        - Expected payment delay
        - Concentration in one customer
        - Insufficient payment history
        - Payment reconciliation required

    Insights are advisory only.
    They do not send messages or create payments.
    """

    code: str = Field(
        min_length=1,
        max_length=80,
    )

    severity: ForecastInsightSeverity

    title: str = Field(
        min_length=1,
        max_length=160,
    )

    description: str = Field(
        min_length=1,
        max_length=2000,
    )

    related_invoice_ids: list[int] = Field(
        default_factory=list,
    )

    affected_outstanding_aed: AmountAED | None = None

    recommended_action: str | None = Field(
        default=None,
        max_length=500,
    )


class ForecastInsightsResponse(ForecastBaseSchema):
    """
    Response for:

    GET /api/forecast/insights
    """

    metadata: ForecastMetadata

    insights: list[ForecastInsight] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# 12. COMBINED FORECAST DASHBOARD RESPONSE
# ============================================================

class ForecastDashboardResponse(ForecastBaseSchema):
    """
    Optional combined response for loading the
    complete frontend dashboard in one request.

    Includes:
        - Forecast summary
        - Timeline
        - Scenario comparison
        - Risk insights

    All values must come from the same calculation
    snapshot to ensure consistency.
    """

    summary: ForecastSummaryResponse

    timeline: ForecastTimelineResponse

    scenarios: ForecastScenariosResponse

    insights: ForecastInsightsResponse
