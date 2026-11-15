
"""
ReceivAI UAE — Cash Flow Forecast API

Protected endpoints:
    GET /api/forecast/summary
    GET /api/forecast/timeline
    GET /api/forecast/invoices
    GET /api/forecast/scenarios
    GET /api/forecast/assumptions
    GET /api/forecast/insights
    GET /api/forecast/dashboard
    GET /api/forecast/agent-insights

All endpoints require the existing administrator JWT.

This module:
    - Reads approved AED receivables
    - Uses recorded payments
    - Returns forecast estimates
    - Provides collection-risk insights

It does NOT:
    - Modify invoices or payments
    - Send reminders
    - Create bank transactions
    - Forecast company expenses
"""

from __future__ import annotations

import logging

from datetime import date
from typing import Any, Callable, TypeVar

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_admin

from app.agents.forecast_agent import (
    ForecastAgentError,
    analyze_cash_flow_forecast,
)

from app.schemas.cash_flow_forecast import (
    ForecastAssumptionsResponse,
    ForecastDashboardResponse,
    ForecastGranularity,
    ForecastInsightsResponse,
    ForecastInvoiceListResponse,
    ForecastScenario,
    ForecastScenariosResponse,
    ForecastSummaryResponse,
    ForecastTimelineResponse,
)

from app.services.cash_flow_forecast_service import (
    get_forecast_assumptions,
    get_forecast_dashboard,
    get_forecast_insights,
    get_forecast_invoices,
    get_forecast_scenarios,
    get_forecast_summary,
    get_forecast_timeline,
)


# ============================================================
# 1. LOGGER
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# 2. PROTECTED API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/forecast",
    tags=["Cash Flow Forecast"],
    dependencies=[
        Depends(get_current_admin)
    ],
)


# ============================================================
# 3. SHARED ERROR HANDLING
# ============================================================

_Result = TypeVar("_Result")


def _run_forecast(
    operation: Callable[..., _Result],
    db: Session,
    **kwargs: Any,
) -> _Result:
    """
    Execute a read-only forecast operation.

    All input query parameters are validated by FastAPI.

    Database errors do not expose connection details
    or SQL statements to the frontend.

    Data inconsistencies are reported separately
    from invalid user inputs.
    """

    try:
        return operation(
            db,
            **kwargs,
        )

    except ForecastAgentError as exc:

        logger.warning(
            "Forecast analysis could not complete: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The forecast could not be analyzed "
                "consistently. Refresh the data "
                "or choose a shorter horizon."
            ),
        ) from exc

    except SQLAlchemyError as exc:

        logger.exception(
            "Forecast database read failed"
        )

        db.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Forecast database service is "
                "temporarily unavailable."
            ),
        ) from exc

    except ValueError as exc:

        logger.exception(
            "Forecast calculation or response "
            "validation failed"
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Forecast data could not be evaluated "
                "reliably. Check invoice and "
                "payment records."
            ),
        ) from exc


# ============================================================
# 4. VALIDATE FORECAST HORIZON
# ============================================================

def _allowed_horizon(
    horizon_days: int = Query(
        default=30,
        description=(
            "Forecast length: exactly 7, 30, "
            "60 or 90 calendar days."
        ),
    ),
) -> int:
    """
    Accept only supported forecast periods.

    Integer query strings are parsed before checking
    the accepted horizons.

    This avoids strict integer Literal validation
    rejecting valid query strings.
    """

    if horizon_days not in (
        7,
        30,
        60,
        90,
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "horizon_days must be one of "
                "7, 30, 60 or 90."
            ),
        )

    return horizon_days


# ============================================================
# 5. FORECAST SUMMARY
# ============================================================

@router.get(
    "/summary",
    response_model=ForecastSummaryResponse,
    summary="Receivables cash-in forecast KPIs",
)
def forecast_summary(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    scenario: ForecastScenario = Query(
        default="base"
    ),
    db: Session = Depends(get_db),
) -> ForecastSummaryResponse:
    """
    Return main forecast dashboard metrics.

    Includes:
        - Total outstanding receivables
        - Overdue outstanding amount
        - Expected collections
        - At-risk receivables
        - Recorded payments
        - Eligible invoice count

    The forecasting service uses the UAE-local
    date when as_of_date is omitted.
    """

    return _run_forecast(
        get_forecast_summary,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
    )


# ============================================================
# 6. FORECAST TIMELINE
# ============================================================

@router.get(
    "/timeline",
    response_model=ForecastTimelineResponse,
    summary="Expected cash receipts over time",
)
def forecast_timeline(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    scenario: ForecastScenario = Query(
        default="base"
    ),
    group_by: ForecastGranularity = Query(
        default="week"
    ),
    db: Session = Depends(get_db),
) -> ForecastTimelineResponse:
    """
    Return chart-ready cash collection projections.

    Supported grouping:
        day
        week
        month

    Includes:
        - Period start and end dates
        - Expected collections
        - Cumulative collections
        - Contractually due amounts
        - Invoice counts
    """

    return _run_forecast(
        get_forecast_timeline,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
        group_by=group_by,
    )


# ============================================================
# 7. INVOICE-LEVEL FORECASTS
# ============================================================

@router.get(
    "/invoices",
    response_model=ForecastInvoiceListResponse,
    summary="Paginated invoice-level forecast",
)
def forecast_invoices(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    scenario: ForecastScenario = Query(
        default="base"
    ),
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
    include_excluded: bool = Query(
        default=False
    ),
    db: Session = Depends(get_db),
) -> ForecastInvoiceListResponse:
    """
    Return detailed invoice-level projections.

    Each projection may contain:
        - Invoice number
        - Customer name
        - Outstanding amount
        - Recorded payment total
        - Days overdue
        - Expected receipt date
        - Collection probability assumption
        - Expected collection amount
        - Risk level
        - Exclusion or reconciliation reasons

    Excluded invoices contribute no projected cash.
    """

    return _run_forecast(
        get_forecast_invoices,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
        page=page,
        page_size=page_size,
        include_excluded=include_excluded,
    )


# ============================================================
# 8. SCENARIO COMPARISON
# ============================================================

@router.get(
    "/scenarios",
    response_model=ForecastScenariosResponse,
    summary=(
        "Compare conservative, base and "
        "optimistic forecasts"
    ),
)
def forecast_scenarios(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    db: Session = Depends(get_db),
) -> ForecastScenariosResponse:
    """
    Compare all three cash collection scenarios.

    Conservative:
        Lower or later expected collections.

    Base:
        Standard documented forecast assumptions.

    Optimistic:
        Earlier or higher expected collections.

    Values are calculated by the forecasting service,
    not generated by an AI language model.
    """

    return _run_forecast(
        get_forecast_scenarios,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
    )


# ============================================================
# 9. FORECAST ASSUMPTIONS
# ============================================================

@router.get(
    "/assumptions",
    response_model=ForecastAssumptionsResponse,
    summary=(
        "Disclose forecast assumptions and data sources"
    ),
)
def forecast_assumptions(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    scenario: ForecastScenario = Query(
        default="base"
    ),
    db: Session = Depends(get_db),
) -> ForecastAssumptionsResponse:
    """
    Explain how expected payment dates and
    collection likelihoods were estimated.

    Possible bases:
        - Customer payment history
        - Portfolio payment history
        - Documented fallback assumptions

    Historical timing estimates do not mean
    collection probabilities have been calibrated.
    """

    return _run_forecast(
        get_forecast_assumptions,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
    )


# ============================================================
# 10. STANDARD FORECAST INSIGHTS
# ============================================================

@router.get(
    "/insights",
    response_model=ForecastInsightsResponse,
    summary="Rule-based forecast risks and warnings",
)
def forecast_insights(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    scenario: ForecastScenario = Query(
        default="base"
    ),
    db: Session = Depends(get_db),
) -> ForecastInsightsResponse:
    """
    Return deterministic finance insights.

    Includes:
        - Overdue exposure
        - Payment timing risks
        - Reconciliation requirements
        - Forecast assumption warnings

    No reminder is generated or sent.
    """

    return _run_forecast(
        get_forecast_insights,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
    )


# ============================================================
# 11. COMBINED FORECAST DASHBOARD
# ============================================================

@router.get(
    "/dashboard",
    response_model=ForecastDashboardResponse,
    summary="Combined forecast dashboard response",
)
def forecast_dashboard(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    scenario: ForecastScenario = Query(
        default="base"
    ),
    group_by: ForecastGranularity = Query(
        default="week"
    ),
    db: Session = Depends(get_db),
) -> ForecastDashboardResponse:
    """
    Return all main dashboard information.

    Includes:
        - Summary metrics
        - Timeline chart
        - Three scenario projections
        - Standard forecast insights

    Uses the forecasting service's combined
    calculation to maintain consistency.
    """

    return _run_forecast(
        get_forecast_dashboard,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
        group_by=group_by,
    )


# ============================================================
# 12. FORECAST AGENT INSIGHTS
# ============================================================

@router.get(
    "/agent-insights",
    response_model=ForecastInsightsResponse,
    summary=(
        "Priority-ranked finance review recommendations"
    ),
)
def forecast_agent_insights(
    horizon_days: int = Depends(
        _allowed_horizon
    ),
    as_of_date: date | None = Query(
        default=None
    ),
    scenario: ForecastScenario = Query(
        default="base"
    ),
    group_by: ForecastGranularity = Query(
        default="week"
    ),
    max_actions: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
    db: Session = Depends(get_db),
) -> ForecastInsightsResponse:
    """
    Execute the Cash Flow Forecast Agent.

    It can:
        - Identify priority collection invoices
        - Explain expected receipt delays
        - Highlight overdue exposure
        - Explain scenario sensitivity
        - Suggest administrator review actions

    It cannot:
        - Send emails
        - Send WhatsApp messages
        - Generate automatic reminders
        - Approve collection drafts
        - Modify payment transactions
    """

    return _run_forecast(
        analyze_cash_flow_forecast,
        db,
        horizon_days=horizon_days,
        as_of_date=as_of_date,
        scenario=scenario,
        group_by=group_by,
        max_actions=max_actions,
    )
