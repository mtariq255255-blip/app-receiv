
"""ReceivAI UAE — read-only financial management reporting.

All outstanding/aging figures are current ledger-derived AED snapshots.
The selected period applies to issue/payment/reminder/document activity only.

Only approved, non-demo AED invoices are included in live financial
figures. Recorded payment entries are NOT independently bank-verified.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Invoice,
    InvoiceDocument,
    Payment,
    Reminder,
)

from app.services.cash_flow_forecast_service import (
    get_forecast_summary,
)


# ============================================================
# 1. CONSTANTS
# ============================================================

AED = Decimal("0.00")
CENT = Decimal("0.01")
UAE_TZ = timezone(timedelta(hours=4))

APPROVED = (
    "reviewed",
    "corrected",
    "approved",
)

BLOCKED = (
    "draft",
    "pending",
    "rejected",
    "cancelled",
    "canceled",
    "void",
    "voided",
    "deleted",
)

MAX_DISPLAY = 300


# ============================================================
# 2. FINANCIAL AMOUNT HELPERS
# ============================================================

def _amount(raw: Any) -> Decimal:
    if raw is None:
        return AED

    if isinstance(raw, (float, bool)):
        raise ValueError(
            "Financial records contain unsupported amount types"
        )

    try:
        value = Decimal(str(raw)).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(
            "Financial records contain an invalid amount"
        ) from exc

    if not value.is_finite() or value < AED:
        raise ValueError(
            "Financial records contain a non-finite or negative amount"
        )

    return value


def _money(value: Decimal | str) -> str:
    return f"{_amount(value):.2f}"


# ============================================================
# 3. DATE RANGE VALIDATION
# ============================================================

def _period(
    start: date | None,
    end: date | None,
    as_of: date,
) -> tuple[date, date]:

    end = end or as_of
    start = start or (end - timedelta(days=29))

    if start > end:
        raise ValueError(
            "Start date cannot be after end date"
        )

    if end > as_of:
        raise ValueError(
            "End date cannot be in the future (UAE time)"
        )

    if (end - start).days > 730:
        raise ValueError(
            "Maximum reporting range is 731 days"
        )

    return start, end


# ============================================================
# 4. ELIGIBLE INVOICE CONDITIONS
# ============================================================

def _eligible_conditions(as_of: date):
    return (
        func.lower(
            func.coalesce(Invoice.source_type, "")
        ) != "demo",

        func.lower(
            func.coalesce(Invoice.review_status, "")
        ).in_(APPROVED),

        func.upper(
            func.coalesce(Invoice.currency, "AED")
        ) == "AED",

        Invoice.issue_date <= as_of,

        ~func.lower(
            func.coalesce(Invoice.status, "")
        ).in_(BLOCKED),
    )


# ============================================================
# 5. MAIN FINANCIAL REPORT GENERATOR
# ============================================================

def get_financial_reports(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    customer: str = "",
) -> dict[str, Any]:
    """Build financial reports using read-only database queries."""

    as_of = datetime.now(UAE_TZ).date()

    start, end = _period(
        start_date,
        end_date,
        as_of,
    )

    customer = customer.strip()

    if len(customer) > 100:
        raise ValueError(
            "Customer filter is too long"
        )

    customer_condition = None

    # Escape SQL wildcard characters.
    if customer:
        customer_condition = Invoice.customer_name.ilike(
            "%"
            + customer
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            + "%",
            escape="\\",
        )

    # ========================================================
    # 6. PAYMENT LEDGER AGGREGATION
    # ========================================================

    payment_subquery = (
        select(
            Payment.invoice_id.label("invoice_id"),

            func.sum(
                Payment.amount_aed
            ).label("paid"),

            func.count(
                Payment.id
            ).label("payment_count"),
        )
        .where(
            Payment.payment_date <= as_of
        )
        .group_by(
            Payment.invoice_id
        )
        .subquery()
    )

    conditions = list(
        _eligible_conditions(as_of)
    )

    if customer_condition is not None:
        conditions.append(customer_condition)

    # ========================================================
    # 7. FETCH APPROVED INVOICES
    # ========================================================

    invoice_rows = db.execute(
        select(
            Invoice.id,
            Invoice.invoice_number,
            Invoice.customer_name,
            Invoice.issue_date,
            Invoice.due_date,
            Invoice.status,
            Invoice.amount_aed,
            payment_subquery.c.paid,
            payment_subquery.c.payment_count,
        )
        .outerjoin(
            payment_subquery,
            payment_subquery.c.invoice_id == Invoice.id,
        )
        .where(*conditions)
        .order_by(
            Invoice.due_date.asc(),
            Invoice.id.asc(),
        )
    ).all()

    # ========================================================
    # 8. RECEIVABLES AGING BUCKETS
    # ========================================================

    aging_keys = (
        ("not_due", "Not yet due"),
        ("1_30", "1–30 days overdue"),
        ("31_60", "31–60 days overdue"),
        ("61_90", "61–90 days overdue"),
        ("90_plus", "Over 90 days overdue"),
    )

    aging = {
        key: {
            "key": key,
            "label": label,
            "count": 0,
            "amount_aed": AED,
        }
        for key, label in aging_keys
    }

    status_counts: Counter[str] = Counter()

    invoices = []
    receivables = []

    outstanding = AED
    overdue = AED
    invoice_value_in_period = AED
    reconciliation_amount = AED

    open_count = 0
    reconciliations = 0
    issued_count = 0

    # ========================================================
    # 9. CALCULATE INVOICE BALANCES
    # ========================================================

    for item in invoice_rows:
        (
            inv_id,
            number,
            name,
            issue,
            due,
            status,
            total_raw,
            paid_raw,
            payment_count,
        ) = item

        total = _amount(total_raw)
        paid = _amount(paid_raw)

        balance = max(
            AED,
            total - paid,
        )

        discrepancy = (
            status
            and str(status).lower() == "paid"
            and paid < total
        )

        if discrepancy:
            reconciliations += 1
            reconciliation_amount += balance

        if issue and start <= issue <= end:
            issued_count += 1
            invoice_value_in_period += total

        days_overdue = (
            max(0, (as_of - due).days)
            if due
            else 0
        )

        if balance > AED:
            open_count += 1
            outstanding += balance

            if days_overdue > 0:
                overdue += balance

            if days_overdue == 0:
                bucket = "not_due"
            elif days_overdue <= 30:
                bucket = "1_30"
            elif days_overdue <= 60:
                bucket = "31_60"
            elif days_overdue <= 90:
                bucket = "61_90"
            else:
                bucket = "90_plus"

            aging[bucket]["count"] += 1
            aging[bucket]["amount_aed"] += balance

            status_counts[
                "Needs reconciliation"
                if discrepancy
                else "Partially paid"
                if paid > AED
                else "Overdue"
                if days_overdue
                else "Not yet due"
            ] += 1

        else:
            status_counts["Settled (ledger)"] += 1

        row = {
            "invoice_id": int(inv_id),
            "invoice_number": str(number),
            "customer_name": str(name or ""),

            "issue_date": (
                issue.isoformat()
                if issue
                else None
            ),

            "due_date": (
                due.isoformat()
                if due
                else None
            ),

            "total_aed": _money(total),
            "recorded_paid_aed": _money(paid),
            "outstanding_aed": _money(balance),

            "days_overdue": days_overdue,

            "status": (
                "Reconciliation required"
                if discrepancy
                else "Settled"
                if balance == AED
                else "Partially paid"
                if paid
                else "Overdue"
                if days_overdue
                else "Not yet due"
            ),
        }

        if balance > AED:
            receivables.append(row)

        if issue and start <= issue <= end:
            invoices.append(row)

    # ========================================================
    # 10. PAYMENT HISTORY REPORT
    # ========================================================

    pay_conditions = [
        *_eligible_conditions(as_of),

        Payment.payment_date.between(
            start,
            end,
        ),
    ]

    if customer_condition is not None:
        pay_conditions.append(
            customer_condition
        )

    payment_rows = db.execute(
        select(
            Payment.id,
            Payment.invoice_id,
            Payment.payment_date,
            Payment.amount_aed,
            Payment.payment_reference,
            Invoice.invoice_number,
            Invoice.customer_name,
        )
        .join(
            Invoice,
            Payment.invoice_id == Invoice.id,
        )
        .where(*pay_conditions)
        .order_by(
            Payment.payment_date.desc(),
            Payment.id.desc(),
        )
    ).all()

    payment_total = AED
    payments = []

    daily = defaultdict(
        lambda: {
            "amount": AED,
            "count": 0,
        }
    )

    for p in payment_rows:
        (
            p_id,
            inv_id,
            p_date,
            raw_amount,
            reference,
            inv_num,
            name,
        ) = p

        amount = _amount(raw_amount)

        payment_total += amount

        bucket = (
            p_date.isoformat()
            if (end - start).days <= 45
            else p_date.strftime("%Y-%m")
        )

        daily[bucket]["amount"] += amount
        daily[bucket]["count"] += 1

        if len(payments) < MAX_DISPLAY:
            payments.append({
                "id": int(p_id),
                "invoice_id": int(inv_id),
                "date": p_date.isoformat(),
                "invoice_number": str(inv_num),
                "customer_name": str(name or ""),
                "amount_aed": _money(amount),
                "reference": str(reference or ""),
            })

    # ========================================================
    # 11. COLLECTION REMINDER REPORT
    # ========================================================

    begin_dt = datetime.combine(
        start,
        datetime.min.time(),
        tzinfo=UAE_TZ,
    )

    end_dt = datetime.combine(
        end + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UAE_TZ,
    )

    reminder_query = (
        select(
            Reminder.approval_status,
            func.count(Reminder.id),
        )
        .join(
            Invoice,
            Invoice.id == Reminder.invoice_id,
        )
        .where(
            *conditions,
            Reminder.created_at >= begin_dt,
            Reminder.created_at < end_dt,
        )
        .group_by(
            Reminder.approval_status
        )
    )

    reminders = [
        {
            "status": str(state or "unknown"),
            "count": int(n),
        }
        for state, n in db.execute(
            reminder_query
        ).all()
    ]

    # ========================================================
    # 12. DOCUMENT PROCESSING REPORT
    # ========================================================

    doc_counts = db.execute(
        select(
            InvoiceDocument.processing_status,
            func.count(InvoiceDocument.id),
        )
        .where(
            InvoiceDocument.uploaded_at >= begin_dt,
            InvoiceDocument.uploaded_at < end_dt,
        )
        .group_by(
            InvoiceDocument.processing_status
        )
    ).all()

    documents = [
        {
            "status": str(state or "unknown"),
            "count": int(n),
        }
        for state, n in doc_counts
    ]

    # ========================================================
    # 13. CASH FLOW FORECAST REPORT
    # ========================================================

    # Reuse the forecast engine.
    # Customer-filtered reporting does not show the
    # portfolio-wide forecast as customer-specific data.

    forecasts = []

    if not customer:
        for horizon in (7, 30, 60, 90):
            projection = get_forecast_summary(
                db=db,
                horizon_days=horizon,
                as_of_date=as_of,
                scenario="base",
            )

            forecasts.append({
                "horizon_days": horizon,

                "expected_receipts_aed": _money(
                    projection.metrics.expected_collections_aed
                ),

                "forecast_invoice_count": (
                    projection.metrics.forecast_invoice_count
                ),
            })

    # ========================================================
    # 14. REPORT WARNINGS
    # ========================================================

    warnings = [
        (
            "Outstanding, overdue and aging are current "
            "UAE-date ledger snapshots; date filters apply "
            "to activity and newly issued invoices."
        ),
        (
            "Recorded payments are administrative ledger "
            "entries, not independently bank-verified deposits."
        ),
        (
            "Cash receipts forecasts use documented assumptions "
            "and are not guaranteed collections."
        ),
    ]

    if customer:
        warnings.append(
            "Customer filter applies to invoice and payment "
            "records. Portfolio-wide forecasts are omitted."
        )

    for label, rows in (
        ("Invoice", invoices),
        ("Aging", receivables),
        ("Payment", payment_rows),
    ):
        if len(rows) > MAX_DISPLAY:
            warnings.append(
                f"{label} table is limited to {MAX_DISPLAY} rows; "
                "summary totals cover all matching records."
            )

    # ========================================================
    # 15. FINAL REPORT RESPONSE
    # ========================================================

    return {
        "currency": "AED",
        "read_only": True,

        "as_of_date": as_of.isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "customer_filter": customer,

        "summary": {
            "total_outstanding_aed": _money(outstanding),

            "overdue_outstanding_aed": _money(overdue),

            "recorded_collections_period_aed": _money(
                payment_total
            ),

            "open_invoice_count": open_count,

            "reconciliation_required_count": reconciliations,

            "reconciliation_amount_aed": _money(
                reconciliation_amount
            ),

            "invoices_issued_in_period": issued_count,

            "invoiced_value_in_period_aed": _money(
                invoice_value_in_period
            ),

            "recorded_payment_count": len(payment_rows),
        },

        "aging": [
            dict(
                value,
                amount_aed=_money(
                    value["amount_aed"]
                ),
            )
            for value in aging.values()
        ],

        "ledger_status": [
            {
                "label": key,
                "count": value,
            }
            for key, value in sorted(
                status_counts.items()
            )
        ],

        "recorded_collections_timeline": [
            {
                "period": key,
                "amount_aed": _money(
                    value["amount"]
                ),
                "count": value["count"],
            }
            for key, value in sorted(
                daily.items()
            )
        ],

        "invoices": invoices[:MAX_DISPLAY],

        "aging_invoices": receivables[:MAX_DISPLAY],

        "payments": payments,

        "reminders": reminders,

        "documents": documents,

        "forecasts": forecasts,

        "warnings": warnings,

        "totals_cover_all_matching_records": True,
    }
