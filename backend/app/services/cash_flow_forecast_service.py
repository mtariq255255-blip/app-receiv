"""ReceivAI UAE — deterministic, read-only receivables cash-in forecast.

Uses existing Invoice and Payment records. This forecasts *cash receipts*, not
net cash flow or verified bank deposits. No OpenAI calls, writes, or reminders.

Probability is a documented scenario assumption, NOT a measured prediction.
When enough settled-invoice history is available, its median payment delay
informs timing only (not the assumed collection probability).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median_low

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Invoice, Payment
from app.schemas.cash_flow_forecast import (
    ForecastAssumption,
    ForecastAssumptionsResponse,
    ForecastDashboardResponse,
    ForecastInsight,
    ForecastInsightsResponse,
    ForecastInvoiceListResponse,
    ForecastInvoiceProjection,
    ForecastMetadata,
    ForecastScenarioResult,
    ForecastScenariosResponse,
    ForecastSummaryMetrics,
    ForecastSummaryResponse,
    ForecastTimelinePoint,
    ForecastTimelineResponse,
)
from app.services.aging_service import get_aging_bucket
from app.services.collection_priority import get_recommended_action

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ONE = Decimal("1.00")
ALLOWED_HORIZONS = (7, 30, 60, 90)
SCENARIOS = ("conservative", "base", "optimistic")
GROUPS = ("day", "week", "month")
APPROVED_REVIEWS = frozenset(("reviewed", "corrected", "approved"))
BLOCKED_STATUSES = frozenset(
    ("draft", "pending", "rejected", "cancelled", "canceled", "void", "voided", "deleted")
)

# Explicit, uncalibrated MVP assumptions. Never label these as AI predictions.
# Probability applies to an outstanding invoice if its estimated receipt date
# falls inside the requested forecast window.
BASE_PROBABILITIES = {
    "not_due": Decimal("0.85"),
    "overdue_1_30": Decimal("0.65"),
    "overdue_31_60": Decimal("0.40"),
    "overdue_61_90": Decimal("0.22"),
    "overdue_90_plus": Decimal("0.10"),
}
RECOVERY_DAYS = {
    "overdue_1_30": 7,
    "overdue_31_60": 14,
    "overdue_61_90": 21,
    "overdue_90_plus": 30,
}
SCENARIO_FACTORS = {
    "conservative": Decimal("0.75"),
    "base": ONE,
    "optimistic": Decimal("1.15"),
}
SCENARIO_DELAY_DAYS = {"conservative": 7, "base": 0, "optimistic": -3}
MIN_CUSTOMER_SAMPLES = 3
MIN_PORTFOLIO_SAMPLES = 8
HISTORY_LOOKBACK_DAYS = 365
FALLBACK_NOT_DUE_DELAY_DAYS = 3


@dataclass(frozen=True)
class _InvoiceRow:
    invoice_id: int
    invoice_number: str
    customer_name: str
    total: Decimal
    paid: Decimal
    due_date: date | None
    status: str
    review_status: str
    currency: str
    source_type: str
    payment_count: int
    last_payment_date: date | None

    @property
    def outstanding(self) -> Decimal:
        return max(self.total - self.paid, ZERO)


@dataclass
class _Snapshot:
    metadata: ForecastMetadata
    invoices: list[_InvoiceRow]
    recorded_last_30: Decimal
    customer_delays: dict[str, list[int]]
    portfolio_delays: list[int]
    warnings: list[str]
    invalid_rows_skipped: int = 0


def _aed(value: object) -> Decimal:
    """Exact, nonnegative AED amount (never convert from float)."""
    try:
        result = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid monetary amount in the database") from exc
    if not result.is_finite() or result < ZERO:
        raise ValueError("Non-finite or negative monetary amount in the database")
    return result


def _sum(values) -> Decimal:
    return sum(values, ZERO).quantize(CENT, rounding=ROUND_HALF_UP)


def _today_uae() -> date:
    return datetime.now(timezone(timedelta(hours=4))).date()


def _validate_options(
    horizon_days: int, scenario: str = "base", group_by: str = "week"
) -> None:
    if type(horizon_days) is not int or horizon_days not in ALLOWED_HORIZONS:
        raise ValueError("horizon_days must be 7, 30, 60 or 90")
    if scenario not in SCENARIOS:
        raise ValueError("scenario must be conservative, base or optimistic")
    if group_by not in GROUPS:
        raise ValueError("group_by must be day, week or month")


def _metadata(as_of_date: date, horizon_days: int, scenario: str) -> ForecastMetadata:
    return ForecastMetadata(
        as_of_date=as_of_date,
        start_date=as_of_date,
        end_date=as_of_date + timedelta(days=horizon_days - 1),
        horizon_days=horizon_days,
        scenario=scenario,
        generated_at=datetime.now(timezone.utc),
        assumptions_used=True,
    )


def _eligible(row: _InvoiceRow) -> str | None:
    """Match the existing receivables rules, plus exclude demo source rows."""
    if row.source_type == "demo":
        return "Demo invoice; excluded from live cash forecasts."
    if row.review_status not in APPROVED_REVIEWS:
        return "Invoice has not passed document review."
    if row.status in BLOCKED_STATUSES:
        return f"Invoice accounting status '{row.status}' is not collectible."
    if row.currency != "AED":
        return "Only AED receivables are currently forecast."
    if row.total <= ZERO:
        return "Invoice amount must be positive."
    if row.due_date is None:
        return "Due date is missing."
    return None


def _read_snapshot(
    db: Session, horizon_days: int, as_of_date: date | None, scenario: str
) -> _Snapshot:
    _validate_options(horizon_days, scenario)
    today = as_of_date if as_of_date is not None else _today_uae()
    if not isinstance(today, date) or isinstance(today, datetime):
        raise ValueError("as_of_date must be a date")
    metadata = _metadata(today, horizon_days, scenario)

    # Aggregate payments as of the requested date BEFORE joining invoices,
    # so that invoice sums are never multiplied by their number of payments.
    payments = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.sum(Payment.amount_aed).label("paid"),
            func.count(Payment.id).label("payment_count"),
            func.max(Payment.payment_date).label("last_payment_date"),
        )
        .where(Payment.payment_date <= today)
        .group_by(Payment.invoice_id)
        .subquery()
    )
    statement = (
        select(
            Invoice.id,
            Invoice.invoice_number,
            Invoice.customer_name,
            Invoice.amount_aed,
            Invoice.due_date,
            Invoice.status,
            Invoice.review_status,
            Invoice.currency,
            Invoice.source_type,
            payments.c.paid,
            payments.c.payment_count,
            payments.c.last_payment_date,
        )
        .outerjoin(payments, payments.c.invoice_id == Invoice.id)
        .where(Invoice.issue_date <= today)
        .order_by(Invoice.due_date.asc(), Invoice.id.asc())
    )

    rows: list[_InvoiceRow] = []
    invalid_count = 0
    for raw in db.execute(statement).all():
        (
            invoice_id, number, customer, amount, due, status, review,
            currency, source, paid, count, last_payment,
        ) = raw
        try:
            total = _aed(amount)
            paid_amount = _aed(paid if paid is not None else ZERO)
        except ValueError:
            # Do not turn corrupt money into a fictitious zero-valued invoice.
            invalid_count += 1
            continue
        rows.append(_InvoiceRow(
            invoice_id=int(invoice_id),
            invoice_number=str(number or f"Invoice #{invoice_id}"),
            customer_name=str(customer or "Unknown customer"),
            total=total,
            paid=paid_amount,
            due_date=due,
            status=str(status or "").strip().lower(),
            review_status=str(review or "").strip().lower(),
            currency=str(currency or "AED").strip().upper(),
            source_type=str(source or "").strip().lower(),
            payment_count=int(count or 0),
            last_payment_date=last_payment,
        ))

    # Historical collection total is an observed *ledger entry* count, not a
    # forecast and not necessarily a verified bank deposit. Match currency
    # and review-status rules; do not count demo/void/rejected invoices.
    recent_start = today - timedelta(days=29)
    recorded_rows = db.execute(
        select(Payment.amount_aed, Invoice.review_status, Invoice.status,
               Invoice.currency, Invoice.source_type)
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(
            Payment.payment_date.between(recent_start, today),
            Invoice.issue_date <= today,
        )
    ).all()
    recorded_last_30 = ZERO
    for amount, review, status, currency, source in recorded_rows:
        if (str(review or "").strip().lower() in APPROVED_REVIEWS
                and str(status or "").strip().lower() not in BLOCKED_STATUSES
                and str(currency or "AED").strip().upper() == "AED"
                and str(source or "").strip().lower() != "demo"):
            try:
                recorded_last_30 += _aed(amount)
            except ValueError:
                invalid_count += 1

    customer_delays: dict[str, list[int]] = defaultdict(list)
    portfolio_delays: list[int] = []
    cutoff = today - timedelta(days=HISTORY_LOOKBACK_DAYS)
    for row in rows:
        # Use completed invoices only, settled in the historical lookback.
        if (_eligible(row) is not None or row.paid != row.total
                or row.last_payment_date is None
                or row.last_payment_date < cutoff
                or row.last_payment_date > today):
            continue
        lag = max(0, (row.last_payment_date - row.due_date).days)
        lag = min(lag, 365)
        customer_delays[row.customer_name.casefold()].append(lag)
        portfolio_delays.append(lag)

    warnings = [
        "Collection probabilities are documented scenario assumptions, "
        "not trained or calibrated predictions.",
        "Recorded payments are not independently bank verified.",
    ]
    if invalid_count:
        warnings.append(
            f"{invalid_count} invalid financial row(s) were omitted. "
            "Review their source records before relying on totals."
        )
    if as_of_date is not None and as_of_date < _today_uae():
        warnings.append(
            "Historical as-of reports use current invoice review/status fields; "
            "this is not an immutable historical ledger snapshot."
        )
    return _Snapshot(
        metadata=metadata,
        invoices=rows,
        recorded_last_30=recorded_last_30.quantize(CENT),
        customer_delays=dict(customer_delays),
        portfolio_delays=portfolio_delays,
        warnings=warnings,
        invalid_rows_skipped=invalid_count,
    )


def _delay_estimate(snapshot: _Snapshot, row: _InvoiceRow) -> tuple[int, str, int]:
    customer_samples = snapshot.customer_delays.get(row.customer_name.casefold(), [])
    if len(customer_samples) >= MIN_CUSTOMER_SAMPLES:
        return int(median_low(customer_samples)), "customer_history", len(customer_samples)
    if len(snapshot.portfolio_delays) >= MIN_PORTFOLIO_SAMPLES:
        return int(median_low(snapshot.portfolio_delays)), "portfolio_history", len(snapshot.portfolio_delays)
    return FALLBACK_NOT_DUE_DELAY_DAYS, "documented_fallback", 0


def _project_one(
    snapshot: _Snapshot, row: _InvoiceRow, scenario: str
) -> ForecastInvoiceProjection:
    asof = snapshot.metadata.as_of_date
    end = snapshot.metadata.end_date
    balance = row.outstanding
    overdue = max((asof - row.due_date).days, 0) if row.due_date else 0
    bucket = get_aging_bucket(row.due_date, balance, as_of_date=asof)
    reason = _eligible(row)
    forecast_status: str = "included"
    risk_reasons: list[str] = []
    if reason is not None:
        forecast_status = "excluded"
    elif row.paid > row.total:
        forecast_status = "reconciliation_required"
        reason = "Recorded payments exceed the invoice amount."
    elif row.status == "paid" and balance > ZERO:
        forecast_status = "reconciliation_required"
        reason = "Marked paid without matching recorded payments."
    elif balance <= ZERO:
        forecast_status = "excluded"
        reason = "Invoice is fully paid; no cash remains to forecast."

    if forecast_status != "included":
        return ForecastInvoiceProjection(
            invoice_id=row.invoice_id,
            invoice_number=row.invoice_number,
            customer_name=row.customer_name,
            due_date=row.due_date,
            invoice_total_aed=row.total,
            recorded_paid_aed=row.paid,
            outstanding_aed=balance,
            days_overdue=overdue,
            aging_bucket=bucket,
            payment_count=row.payment_count,
            forecast_status=forecast_status,
            risk_level="review_required" if forecast_status == "reconciliation_required" else "low",
            risk_reasons=[reason] if reason else [],
            recommended_action="review_invoice_data" if forecast_status == "reconciliation_required" else None,
            exclusion_reason=reason,
        )

    delay, basis, samples = _delay_estimate(snapshot, row)
    if overdue == 0:
        # Future contractual dues are never forecast before their due dates.
        delay = max(0, delay + SCENARIO_DELAY_DAYS[scenario])
        expected_date = row.due_date + timedelta(days=delay)
    else:
        # Historic due dates cannot be treated as *future* cash receipts.
        recovery = RECOVERY_DAYS[bucket] + SCENARIO_DELAY_DAYS[scenario]
        expected_date = asof + timedelta(days=max(1, recovery))

    likelihood = min(
        ONE,
        (BASE_PROBABILITIES[bucket] * SCENARIO_FACTORS[scenario]).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        ),
    )
    within = asof <= expected_date <= end
    estimate = (
        (balance * likelihood).quantize(CENT, rounding=ROUND_HALF_UP)
        if within else ZERO
    )

    if overdue > 90:
        risk_level = "high"
        risk_reasons.append("More than 90 days overdue.")
    elif overdue > 30:
        risk_level = "high" if overdue > 60 else "medium"
        risk_reasons.append(f"{overdue} days overdue.")
    elif overdue > 0:
        risk_level = "medium"
        risk_reasons.append(f"{overdue} days overdue.")
    else:
        risk_level = "low"
    if basis == "documented_fallback":
        risk_reasons.append("Insufficient completed-payment history; timing uses fallback assumptions.")

    action = get_recommended_action(
        days_overdue=overdue,
        outstanding_amount=balance,
        due_soon=(0 <= (row.due_date - asof).days <= 7),
    )
    return ForecastInvoiceProjection(
        invoice_id=row.invoice_id,
        invoice_number=row.invoice_number,
        customer_name=row.customer_name,
        due_date=row.due_date,
        invoice_total_aed=row.total,
        recorded_paid_aed=row.paid,
        outstanding_aed=balance,
        days_overdue=overdue,
        aging_bucket=bucket,
        payment_count=row.payment_count,
        forecast_status="included",
        expected_receipt_date=expected_date,
        within_horizon=within,
        collection_probability=likelihood,
        expected_collection_aed=estimate,
        basis=basis,
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        recommended_action=action,
    )


def _projections(snapshot: _Snapshot, scenario: str) -> list[ForecastInvoiceProjection]:
    return [_project_one(snapshot, row, scenario) for row in snapshot.invoices]


def _summary(
    snapshot: _Snapshot, projections: list[ForecastInvoiceProjection]
) -> ForecastSummaryResponse:
    included = [p for p in projections if p.forecast_status == "included"]
    reconciling = [p for p in projections if p.forecast_status == "reconciliation_required"]
    outstanding_scope = included + reconciling  # Include unreconciled exposure, but NEVER forecast it.
    end = snapshot.metadata.end_date
    start = snapshot.metadata.start_date
    metrics = ForecastSummaryMetrics(
        total_outstanding_aed=_sum(p.outstanding_aed for p in outstanding_scope),
        overdue_outstanding_aed=_sum(
            p.outstanding_aed for p in outstanding_scope
            if p.due_date is not None and p.due_date < start
        ),
        due_within_horizon_aed=_sum(
            p.outstanding_aed for p in included
            if p.due_date is not None and start <= p.due_date <= end
        ),
        expected_collections_aed=_sum(p.expected_collection_aed for p in included),
        at_risk_outstanding_aed=_sum(
            p.outstanding_aed for p in outstanding_scope
            if p.risk_level in ("medium", "high", "review_required")
        ),
        recorded_collections_last_30_days_aed=snapshot.recorded_last_30,
        eligible_invoice_count=len(included),
        forecast_invoice_count=sum(p.within_horizon for p in included),
        excluded_invoice_count=sum(p.forecast_status == "excluded" for p in projections)
        + snapshot.invalid_rows_skipped,
        reconciliation_required_count=len(reconciling),
    )
    return ForecastSummaryResponse(metadata=snapshot.metadata, metrics=metrics, warnings=list(snapshot.warnings))


def _timeline(
    snapshot: _Snapshot, projections: list[ForecastInvoiceProjection], group_by: str
) -> ForecastTimelineResponse:
    _validate_options(snapshot.metadata.horizon_days, snapshot.metadata.scenario, group_by)
    start, end = snapshot.metadata.start_date, snapshot.metadata.end_date
    points: list[ForecastTimelinePoint] = []
    cursor, cumulative = start, ZERO
    while cursor <= end:
        if group_by == "day":
            period_end = cursor
        elif group_by == "week":
            period_end = min(end, cursor + timedelta(days=6))
        else:
            first_next_month = (
                date(cursor.year + 1, 1, 1) if cursor.month == 12
                else date(cursor.year, cursor.month + 1, 1)
            )
            period_end = min(end, first_next_month - timedelta(days=1))
        receipts = [
            p for p in projections
            if p.forecast_status == "included" and p.within_horizon
            and p.expected_receipt_date is not None
            and cursor <= p.expected_receipt_date <= period_end
        ]
        amount = _sum(p.expected_collection_aed for p in receipts)
        cumulative += amount
        due = _sum(
            p.outstanding_aed for p in projections
            if p.forecast_status == "included" and p.due_date is not None
            and cursor <= p.due_date <= period_end
        )
        points.append(ForecastTimelinePoint(
            period_start=cursor,
            period_end=period_end,
            projected_collections_aed=amount,
            cumulative_projected_aed=cumulative,
            due_invoice_balance_aed=due,
            invoice_count=len(receipts),
        ))
        cursor = period_end + timedelta(days=1)
    return ForecastTimelineResponse(
        metadata=snapshot.metadata,
        group_by=group_by,
        points=points,
        projected_total_aed=cumulative,
        warnings=list(snapshot.warnings),
    )


def _assumptions(snapshot: _Snapshot, scenario: str) -> list[ForecastAssumption]:
    output: list[ForecastAssumption] = []
    for bucket, base_rate in BASE_PROBABILITIES.items():
        rate = min(ONE, (base_rate * SCENARIO_FACTORS[scenario]).quantize(Decimal("0.0001")))
        lag = (
            FALLBACK_NOT_DUE_DELAY_DAYS if bucket == "not_due" else RECOVERY_DAYS[bucket]
        )
        output.append(ForecastAssumption(
            label=bucket.replace("_", " ").title(),
            basis="documented_fallback",
            collection_probability=rate,
            expected_delay_days=max(0, lag + SCENARIO_DELAY_DAYS[scenario]),
            historical_sample_count=0,
            explanation=(
                "Uncalibrated MVP collection-likelihood assumption. "
                "Sufficient settled-payment history can override timing, NOT this rate. "
                "For overdue invoices, days indicate recovery time from the report date."
            ),
        ))
    return output


def _scenarios(snapshot: _Snapshot) -> ForecastScenariosResponse:
    projections = {scenario: _projections(snapshot, scenario) for scenario in SCENARIOS}
    totals = {
        scenario: _sum(p.expected_collection_aed for p in rows)
        for scenario, rows in projections.items()
    }
    results = []
    for scenario in SCENARIOS:
        results.append(ForecastScenarioResult(
            scenario=scenario,
            expected_collections_aed=totals[scenario],
            difference_from_base_aed=totals[scenario] - totals["base"],
            forecast_invoice_count=sum(p.within_horizon for p in projections[scenario]),
            assumptions=_assumptions(snapshot, scenario),
            explanation={
                "conservative": "Lower likelihoods and later assumed collection dates.",
                "base": "Baseline documented likelihoods; historical timing when samples suffice.",
                "optimistic": "Higher likelihoods and earlier assumed collection dates.",
            }[scenario],
        ))
    return ForecastScenariosResponse(
        metadata=snapshot.metadata.model_copy(update={"scenario": "base"}),
        scenarios=results,
        warnings=list(snapshot.warnings),
    )


def _insights(
    snapshot: _Snapshot, projections: list[ForecastInvoiceProjection]
) -> ForecastInsightsResponse:
    included = [p for p in projections if p.forecast_status == "included"]
    reconciling = [p for p in projections if p.forecast_status == "reconciliation_required"]
    insights: list[ForecastInsight] = []
    if reconciling:
        insights.append(ForecastInsight(
            code="PAYMENT_RECONCILIATION",
            severity="critical",
            title="Resolve payment reconciliation exceptions",
            description=(
                f"{len(reconciling)} invoice(s) have inconsistent payment/status records. "
                "Their unsettled amounts are not forecast as future cash."
            ),
            related_invoice_ids=[p.invoice_id for p in reconciling[:50]],
            affected_outstanding_aed=_sum(p.outstanding_aed for p in reconciling),
            recommended_action="Review recorded payments and invoice status before customer follow-up.",
        ))

    late = [p for p in included if p.days_overdue > 30]
    if late:
        insights.append(ForecastInsight(
            code="AGING_OVER_30_DAYS",
            severity="warning",
            title="Aged receivables threaten collections",
            description=f"{len(late)} outstanding invoice(s) are more than 30 days overdue.",
            related_invoice_ids=[p.invoice_id for p in late[:50]],
            affected_outstanding_aed=_sum(p.outstanding_aed for p in late),
            recommended_action="Prioritize the overdue collections queue; no reminders are sent automatically.",
        ))

    exposure = _sum(p.outstanding_aed for p in included)
    by_customer: dict[str, list[ForecastInvoiceProjection]] = defaultdict(list)
    for p in included:
        by_customer[p.customer_name.casefold()].append(p)
    if exposure > ZERO and by_customer:
        largest = max(by_customer.values(), key=lambda rows: _sum(p.outstanding_aed for p in rows))
        amount = _sum(p.outstanding_aed for p in largest)
        if amount / exposure >= Decimal("0.40") and len(by_customer) > 1:
            insights.append(ForecastInsight(
                code="CUSTOMER_CONCENTRATION",
                severity="warning",
                title="Outstanding receivables concentrated in one customer",
                description=(
                    f"{largest[0].customer_name} represents at least 40% of "
                    "eligible outstanding balances. Customer names are used as identifiers."
                ),
                related_invoice_ids=[p.invoice_id for p in largest[:50]],
                affected_outstanding_aed=amount,
                recommended_action="Review customer collection commitments and concentration risk.",
            ))

    if not included:
        insights.append(ForecastInsight(
            code="NO_ELIGIBLE_RECEIVABLES",
            severity="info",
            title="No eligible outstanding receivables",
            description="There are no eligible unpaid AED invoices to forecast for this snapshot.",
        ))
    if any(p.basis == "documented_fallback" for p in included):
        insights.append(ForecastInsight(
            code="ASSUMPTIONS_IN_USE",
            severity="info",
            title="Forecast uses disclosed default assumptions",
            description=(
                "Insufficient completed-invoice history for some payment timing estimates. "
                "All collection probabilities remain illustrative, uncalibrated assumptions."
            ),
            recommended_action="Compare forecasts with later recorded receipts before using them operationally.",
        ))

    return ForecastInsightsResponse(
        metadata=snapshot.metadata,
        insights=insights,
        warnings=list(snapshot.warnings),
    )


# ---------------------------------------------------------------------------
# Public service functions; API routes can call these directly.
# Every function is read-only and returns a validated Pydantic response.
# ---------------------------------------------------------------------------

def get_forecast_summary(
    db: Session, horizon_days: int = 30, as_of_date: date | None = None,
    scenario: str = "base",
) -> ForecastSummaryResponse:
    snapshot = _read_snapshot(db, horizon_days, as_of_date, scenario)
    return _summary(snapshot, _projections(snapshot, scenario))


def get_forecast_timeline(
    db: Session, horizon_days: int = 30, as_of_date: date | None = None,
    scenario: str = "base", group_by: str = "week",
) -> ForecastTimelineResponse:
    _validate_options(horizon_days, scenario, group_by)
    snapshot = _read_snapshot(db, horizon_days, as_of_date, scenario)
    return _timeline(snapshot, _projections(snapshot, scenario), group_by)


def get_forecast_invoices(
    db: Session, horizon_days: int = 30, as_of_date: date | None = None,
    scenario: str = "base", page: int = 1, page_size: int = 50,
    include_excluded: bool = False,
) -> ForecastInvoiceListResponse:
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
        raise ValueError("page must be >= 1 and page_size must be between 1 and 200")
    snapshot = _read_snapshot(db, horizon_days, as_of_date, scenario)
    all_rows = _projections(snapshot, scenario)
    if not include_excluded:
        all_rows = [p for p in all_rows if p.forecast_status == "included"]
    offset = (page - 1) * page_size
    return ForecastInvoiceListResponse(
        metadata=snapshot.metadata,
        invoices=all_rows[offset:offset + page_size],
        total=len(all_rows),
        page=page,
        page_size=page_size,
        warnings=list(snapshot.warnings),
    )


def get_forecast_scenarios(
    db: Session, horizon_days: int = 30, as_of_date: date | None = None,
) -> ForecastScenariosResponse:
    return _scenarios(_read_snapshot(db, horizon_days, as_of_date, "base"))


def get_forecast_assumptions(
    db: Session, horizon_days: int = 30, as_of_date: date | None = None,
    scenario: str = "base",
) -> ForecastAssumptionsResponse:
    snapshot = _read_snapshot(db, horizon_days, as_of_date, scenario)
    return ForecastAssumptionsResponse(
        metadata=snapshot.metadata,
        assumptions=_assumptions(snapshot, scenario),
        warnings=list(snapshot.warnings),
    )


def get_forecast_insights(
    db: Session, horizon_days: int = 30, as_of_date: date | None = None,
    scenario: str = "base",
) -> ForecastInsightsResponse:
    snapshot = _read_snapshot(db, horizon_days, as_of_date, scenario)
    return _insights(snapshot, _projections(snapshot, scenario))


def get_forecast_dashboard(
    db: Session, horizon_days: int = 30, as_of_date: date | None = None,
    scenario: str = "base", group_by: str = "week",
) -> ForecastDashboardResponse:
    """Single read/recomputation for consistent summary, chart, scenarios and insights."""
    _validate_options(horizon_days, scenario, group_by)
    snapshot = _read_snapshot(db, horizon_days, as_of_date, scenario)
    projections = _projections(snapshot, scenario)
    return ForecastDashboardResponse(
        summary=_summary(snapshot, projections),
        timeline=_timeline(snapshot, projections, group_by),
        scenarios=_scenarios(snapshot),
        insights=_insights(snapshot, projections),
    )
