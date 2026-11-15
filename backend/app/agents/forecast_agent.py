
"""
ReceivAI UAE — Cash Flow Forecast Analysis Agent

Responsibilities:
- Analyze calculated cash-in forecasts
- Prioritize eligible invoices for finance review
- Identify collection timing risks
- Explain differences between forecast scenarios
- Preserve invoice reconciliation warnings
- Return structured, actionable financial insights

IMPORTANT:
- No database modifications
- No automatic customer communications
- No reminders generated or approved
- No OpenAI API calls
- No fabricated financial predictions

Financial calculations are performed by:
    app.services.cash_flow_forecast_service

The agent analyzes validated results from that service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

from sqlalchemy.orm import Session

from app.schemas.cash_flow_forecast import (
    ForecastDashboardResponse,
    ForecastInsight,
    ForecastInsightsResponse,
    ForecastInvoiceProjection,
)

from app.services.cash_flow_forecast_service import (
    get_forecast_dashboard,
    get_forecast_invoices,
)

from app.services.collection_priority import (
    calculate_amount_score,
    calculate_overdue_score,
    calculate_payment_history_score,
)


# ============================================================
# 1. CONSTANTS
# ============================================================

ZERO = Decimal("0.00")

MAX_PAGE_SIZE = 200

MAX_ANALYSIS_INVOICES = 5000

DEFAULT_ACTION_LIMIT = 10


# ============================================================
# 2. AGENT EXCEPTIONS
# ============================================================

class ForecastAgentError(ValueError):
    """
    Raised when a forecast cannot be
    analyzed reliably.
    """


# ============================================================
# 3. UTILITY FUNCTIONS
# ============================================================

def _sum_aed(
    rows: Sequence[ForecastInvoiceProjection],
) -> Decimal:
    """
    Sum outstanding invoice balances using Decimal.
    """

    return sum(
        (
            row.outstanding_aed
            for row in rows
        ),
        ZERO,
    )


def _distinct_warnings(
    *groups: Sequence[str],
) -> list[str]:
    """
    Combine warning lists without duplicates.
    """

    return list(
        dict.fromkeys(
            message
            for group in groups
            for message in group
        )
    )


# ============================================================
# 4. COLLECTION PRIORITY SCORE
# ============================================================

def _priority_score(
    row: ForecastInvoiceProjection,
) -> int:
    """
    Calculate operational collection priority
    using the existing ReceivAI scoring rules.

    This is NOT a probability of payment.
    """

    overdue_score = calculate_overdue_score(
        row.days_overdue
    )

    amount_score = calculate_amount_score(
        row.outstanding_aed
    )

    history_score = calculate_payment_history_score(
        row.recorded_paid_aed,
        row.outstanding_aed,
        row.days_overdue,
    )

    return (
        overdue_score
        + amount_score
        + history_score
    )


# ============================================================
# 5. COLLECTION ACTION ELIGIBILITY
# ============================================================

def _actionable(
    row: ForecastInvoiceProjection,
    as_of_date: date,
) -> bool:
    """
    Identify invoices eligible for finance follow-up.

    An invoice is actionable when:
    - It passed forecasting eligibility checks
    - An outstanding amount remains
    - It is overdue or due within 7 days
    - The collection service recommends an action

    Reconciliation exceptions, excluded invoices and
    fully paid invoices cannot enter the action queue.

    No customer messages are sent.
    """

    return (
        row.forecast_status == "included"
        and row.outstanding_aed > ZERO
        and row.due_date is not None
        and row.due_date
        <= as_of_date + timedelta(days=7)
        and row.recommended_action not in (
            None,
            "no_action",
            "monitor_invoice",
        )
    )


# ============================================================
# 6. BUILD FINANCIAL INSIGHTS
# ============================================================

def build_forecast_agent_insights(
    dashboard: ForecastDashboardResponse,
    invoice_projections: Sequence[
        ForecastInvoiceProjection
    ],
    *,
    max_actions: int = DEFAULT_ACTION_LIMIT,
) -> ForecastInsightsResponse:
    """
    Enrich the forecast with explainable insights.

    Uses existing:
    - Forecast summary
    - Forecast scenarios
    - Invoice projections
    - Built-in forecasting warnings

    All projections must belong to the same
    forecast date, horizon and scenario.

    The function is read-only.
    """

    if (
        type(max_actions) is not int
        or not 1 <= max_actions <= 50
    ):
        raise ForecastAgentError(
            "max_actions must be between 1 and 50"
        )

    metadata = dashboard.summary.metadata

    # --------------------------------------------------------
    # VALIDATE DASHBOARD CONSISTENCY
    # --------------------------------------------------------

    if (
        dashboard.timeline.metadata.as_of_date
        != metadata.as_of_date
        or dashboard.timeline.metadata.horizon_days
        != metadata.horizon_days
        or dashboard.timeline.metadata.scenario
        != metadata.scenario
        or dashboard.insights.metadata.as_of_date
        != metadata.as_of_date
        or dashboard.insights.metadata.horizon_days
        != metadata.horizon_days
        or dashboard.insights.metadata.scenario
        != metadata.scenario
    ):
        raise ForecastAgentError(
            "Dashboard sections refer to different forecasts"
        )

    # --------------------------------------------------------
    # ELIGIBLE INVOICES
    # --------------------------------------------------------

    included = [
        row
        for row in invoice_projections
        if (
            row.forecast_status == "included"
            and row.outstanding_aed > ZERO
        )
    ]

    invoice_ids = [
        row.invoice_id
        for row in included
    ]

    if len(invoice_ids) != len(set(invoice_ids)):
        raise ForecastAgentError(
            "Duplicate invoice projections were supplied"
        )

    if (
        len(included)
        != dashboard.summary.metrics.eligible_invoice_count
    ):
        raise ForecastAgentError(
            "Full eligible invoice projections are required. "
            "A paginated or stale subset was supplied."
        )

    projected_total = sum(
        (
            row.expected_collection_aed
            for row in included
        ),
        ZERO,
    )

    if (
        projected_total
        != dashboard.summary.metrics.expected_collections_aed
    ):
        raise ForecastAgentError(
            "Invoice projections and dashboard "
            "expected collections disagree. "
            "Reload a consistent forecast."
        )

    as_of_date = metadata.as_of_date

    end_date = metadata.end_date

    additional_insights: list[ForecastInsight] = []

    # ========================================================
    # INSIGHT 1 — COLLECTION REVIEW QUEUE
    # ========================================================

    collection_queue = sorted(
        (
            row
            for row in included
            if _actionable(
                row,
                as_of_date,
            )
        ),
        key=lambda row: (
            -_priority_score(row),
            -row.days_overdue,
            -row.outstanding_aed,
            row.due_date or date.max,
            row.invoice_id,
        ),
    )

    if collection_queue:

        selected = collection_queue[:max_actions]

        overdue_count = sum(
            row.days_overdue > 0
            for row in collection_queue
        )

        due_soon_count = (
            len(collection_queue) - overdue_count
        )

        additional_insights.append(
            ForecastInsight(
                code="COLLECTION_REVIEW_QUEUE",

                severity=(
                    "warning"
                    if overdue_count
                    else "info"
                ),

                title=(
                    "Invoices ready for finance "
                    "follow-up review"
                ),

                description=(
                    f"{len(collection_queue)} eligible "
                    "outstanding invoice(s) fall within "
                    "the seven-day-before-due or overdue "
                    "follow-up window "
                    f"({overdue_count} overdue; "
                    f"{due_soon_count} due soon). "
                    f"The first {len(selected)} invoice "
                    "ID(s) are ranked using existing "
                    "operational priority rules."
                ),

                related_invoice_ids=[
                    row.invoice_id
                    for row in selected
                ],

                affected_outstanding_aed=_sum_aed(
                    collection_queue
                ),

                recommended_action=(
                    "Review ranked invoices in Payment "
                    "Collections. Draft reminders only "
                    "after eligibility checks and "
                    "administrator review. "
                    "No messages are sent automatically."
                ),
            )
        )

    # ========================================================
    # INSIGHT 2 — DUE DURING PERIOD, RECEIPT EXPECTED LATER
    # ========================================================

    expected_after_horizon = [
        row
        for row in included
        if (
            row.due_date is not None
            and as_of_date <= row.due_date <= end_date
            and row.expected_receipt_date is not None
            and row.expected_receipt_date > end_date
        )
    ]

    if expected_after_horizon:

        ranked = sorted(
            expected_after_horizon,
            key=lambda row: (
                -row.outstanding_aed,
                row.invoice_id,
            ),
        )

        additional_insights.append(
            ForecastInsight(
                code="DUE_WITHIN_HORIZON_RECEIPT_LATER",

                severity="warning",

                title=(
                    "Some upcoming dues are forecast "
                    "beyond this period"
                ),

                description=(
                    f"{len(expected_after_horizon)} "
                    "eligible invoice(s) are "
                    "contractually due during this "
                    "forecast window, but their "
                    "estimated receipt dates fall after "
                    "the window. This is a timing "
                    "scenario, not a confirmed default "
                    "or cash loss."
                ),

                related_invoice_ids=[
                    row.invoice_id
                    for row in ranked[:max_actions]
                ],

                affected_outstanding_aed=_sum_aed(
                    expected_after_horizon
                ),

                recommended_action=(
                    "Check payment terms and customer "
                    "commitments. Review future-dated "
                    "receipts in the next forecast horizon."
                ),
            )
        )

    # ========================================================
    # INSIGHT 3 — OVERDUE RECOVERY BEYOND FORECAST PERIOD
    # ========================================================

    overdue_outside = [
        row
        for row in included
        if (
            row.days_overdue > 0
            and row.expected_receipt_date is not None
            and row.expected_receipt_date > end_date
        )
    ]

    if overdue_outside:

        ranked = sorted(
            overdue_outside,
            key=lambda row: (
                -row.days_overdue,
                -row.outstanding_aed,
                row.invoice_id,
            ),
        )

        additional_insights.append(
            ForecastInsight(
                code="OVERDUE_RECOVERY_AFTER_HORIZON",

                severity="warning",

                title=(
                    "Some overdue balances may recover "
                    "after the forecast period"
                ),

                description=(
                    f"{len(overdue_outside)} overdue "
                    "eligible invoice(s) have estimated "
                    "receipt dates beyond the selected "
                    "forecast window. These dates come "
                    "from rules or assumptions, not "
                    "customer payment promises."
                ),

                related_invoice_ids=[
                    row.invoice_id
                    for row in ranked[:max_actions]
                ],

                affected_outstanding_aed=_sum_aed(
                    overdue_outside
                ),

                recommended_action=(
                    "Review overdue invoices and "
                    "update collection priorities."
                ),
            )
        )

    # ========================================================
    # INSIGHT 4 — FORECAST SCENARIO SENSITIVITY
    # ========================================================

    scenario_amounts = {
        item.scenario: item.expected_collections_aed
        for item in dashboard.scenarios.scenarios
    }

    base = scenario_amounts.get("base")

    conservative = scenario_amounts.get(
        "conservative"
    )

    optimistic = scenario_amounts.get(
        "optimistic"
    )

    if (
        base is not None
        and conservative is not None
        and optimistic is not None
    ):

        gap = base - conservative

        if gap > ZERO:

            significant_gap = (
                base > ZERO
                and gap / base >= Decimal("0.15")
            )

            additional_insights.append(
                ForecastInsight(
                    code="SCENARIO_SENSITIVITY",

                    severity=(
                        "warning"
                        if significant_gap
                        else "info"
                    ),

                    title=(
                        "Projected cash receipts depend "
                        "on scenario assumptions"
                    ),

                    description=(
                        "The conservative scenario "
                        f"projects AED {conservative:,.2f}, "
                        f"compared with AED {base:,.2f} "
                        "in the base scenario "
                        f"(AED {gap:,.2f} difference). "
                        "The optimistic scenario projects "
                        f"AED {optimistic:,.2f}. These are "
                        "model assumptions rather than "
                        "validated likelihoods or "
                        "committed payments."
                    ),

                    recommended_action=(
                        "Use conservative and base "
                        "estimates for planning and "
                        "compare outcomes against later "
                        "recorded payments."
                    ),
                )
            )

    # ========================================================
    # 7. PRESERVE EXISTING FORECAST INSIGHTS
    # ========================================================

    merged_insights = list(
        dashboard.insights.insights
    )

    existing_codes = {
        item.code
        for item in merged_insights
    }

    merged_insights.extend(
        item
        for item in additional_insights
        if item.code not in existing_codes
    )

    warnings = _distinct_warnings(
        dashboard.summary.warnings,
        dashboard.timeline.warnings,
        dashboard.scenarios.warnings,
        dashboard.insights.warnings,
    )

    return ForecastInsightsResponse(
        metadata=metadata,
        insights=merged_insights,
        warnings=warnings,
    )


# ============================================================
# 8. FORECAST AGENT
# ============================================================

@dataclass
class ForecastAgent:
    """
    Read-only forecast analysis coordinator.

    It retrieves the calculated forecast, loads
    eligible invoice projections, and produces
    structured recommendations.

    No automatic actions are performed.
    """

    db: Session

    max_analysis_invoices: int = MAX_ANALYSIS_INVOICES

    # ========================================================
    # MAIN AGENT EXECUTION
    # ========================================================

    def analyze(
        self,
        *,
        horizon_days: int = 30,
        as_of_date: date | None = None,
        scenario: str = "base",
        group_by: str = "week",
        max_actions: int = DEFAULT_ACTION_LIMIT,
    ) -> ForecastInsightsResponse:
        """
        Generate intelligent finance insights.

        Supported horizons:
            7, 30, 60, 90

        Supported scenarios:
            conservative, base, optimistic

        All outputs are advisory.
        """

        # ----------------------------------------------------
        # READ FORECAST DASHBOARD
        # ----------------------------------------------------

        dashboard = get_forecast_dashboard(
            self.db,
            horizon_days=horizon_days,
            as_of_date=as_of_date,
            scenario=scenario,
            group_by=group_by,
        )

        eligible_count = (
            dashboard.summary.metrics.eligible_invoice_count
        )

        # ----------------------------------------------------
        # SAFETY LIMIT
        # ----------------------------------------------------

        if (
            type(self.max_analysis_invoices) is not int
            or self.max_analysis_invoices < 1
        ):
            raise ForecastAgentError(
                "max_analysis_invoices must be positive"
            )

        if eligible_count > self.max_analysis_invoices:
            raise ForecastAgentError(
                f"Forecast contains {eligible_count} "
                "eligible invoices, exceeding the "
                "safe analysis limit of "
                f"{self.max_analysis_invoices}."
            )

        # ----------------------------------------------------
        # LOAD ALL ELIGIBLE INVOICE PROJECTIONS
        # ----------------------------------------------------

        projections: list[
            ForecastInvoiceProjection
        ] = []

        page = 1

        expected_pages = (
            eligible_count + MAX_PAGE_SIZE - 1
        ) // MAX_PAGE_SIZE

        for _ in range(expected_pages):

            batch = get_forecast_invoices(
                self.db,
                horizon_days=horizon_days,
                as_of_date=(
                    dashboard.summary.metadata.as_of_date
                ),
                scenario=scenario,
                page=page,
                page_size=MAX_PAGE_SIZE,
                include_excluded=False,
            )

            if (
                batch.metadata.as_of_date
                != dashboard.summary.metadata.as_of_date
                or batch.total != eligible_count
                or not batch.invoices
            ):
                raise ForecastAgentError(
                    "Forecast invoices changed while "
                    "being analyzed. Please retry."
                )

            projections.extend(
                batch.invoices
            )

            page += 1

        # ----------------------------------------------------
        # BUILD ACTIONABLE INSIGHTS
        # ----------------------------------------------------

        return build_forecast_agent_insights(
            dashboard,
            projections,
            max_actions=max_actions,
        )


# ============================================================
# 9. CONVENIENCE FUNCTION FOR API ROUTES
# ============================================================

def analyze_cash_flow_forecast(
    db: Session,
    horizon_days: int = 30,
    as_of_date: date | None = None,
    scenario: str = "base",
    group_by: str = "week",
    max_actions: int = DEFAULT_ACTION_LIMIT,
) -> ForecastInsightsResponse:
    """
    Execute the agent from a FastAPI route.

    Returns:
        ForecastInsightsResponse

    Does not send emails or alter database records.
    """

    agent = ForecastAgent(
        db=db,
    )

    return agent.analyze(
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
        group_by=group_by,
        max_actions=max_actions,
    )
