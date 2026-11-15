
"""ReceivAI UAE — protected management reports and CSV exports.

GET /api/reports/dashboard?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&customer=
GET /api/reports/export?kind=aging|invoices|payments|reconciliation&...

Both endpoints are administrator-only and read-only; no report is persisted.
"""

from __future__ import annotations

import csv
import io
import logging

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
)

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_admin
from app.services.reports_service import get_financial_reports


# ============================================================
# 1. LOGGING AND ROUTER
# ============================================================

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reports",
    tags=["Financial Reports"],
    dependencies=[
        Depends(get_current_admin),
    ],
)


# ============================================================
# 2. FINANCIAL REPORT QUERY
# ============================================================

def _query_data(
    db: Session,
    start_date: date | None,
    end_date: date | None,
    customer: str,
):
    today_uae = datetime.now(
        timezone(timedelta(hours=4))
    ).date()

    if (
        (start_date and end_date and start_date > end_date)
        or (end_date and end_date > today_uae)
    ):
        raise HTTPException(
            status_code=422,
            detail="Invalid reporting date range.",
        )

    if len(customer) > 100:
        raise HTTPException(
            status_code=422,
            detail="Customer filter cannot exceed 100 characters.",
        )

    try:
        return get_financial_reports(
            db,
            start_date=start_date,
            end_date=end_date,
            customer=customer,
        )

    except ValueError as exc:
        logger.error(
            "Financial reports validation failure: %s",
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=422,
            detail=(
                "Invalid reporting range or "
                "unusable report data."
            ),
        ) from exc

    except SQLAlchemyError as exc:
        logger.exception(
            "Reports database query failed"
        )

        db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Financial reports temporarily unavailable."
            ),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Unexpected financial reporting error"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to prepare financial reports.",
        ) from exc


# ============================================================
# 3. REPORTS DASHBOARD API
# ============================================================

@router.get(
    "/dashboard",
    summary="Financial reporting dashboard",
)
def financial_reports_dashboard(
    response: Response,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    customer: str = Query("", max_length=100),
    db: Session = Depends(get_db),
):
    response.headers[
        "Cache-Control"
    ] = "private, no-store"

    return _query_data(
        db,
        start_date,
        end_date,
        customer,
    )


# ============================================================
# 4. SAFE CSV CELL FORMATTING
# ============================================================

# Never permit untrusted source strings to become
# spreadsheet formulas.

def _safe_csv_cell(value: object) -> str:
    if value is None:
        return ""

    text = str(value)

    if text.lstrip().startswith(
        ("=", "+", "-", "@")
    ):
        return "'" + text

    return text


# ============================================================
# 5. CSV REPORT EXPORT API
# ============================================================

@router.get(
    "/export",
    summary="Export displayed report rows as CSV",
)
def export_financial_reports(
    kind: Literal[
        "aging",
        "invoices",
        "payments",
        "reconciliation",
    ] = Query("aging"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    customer: str = Query("", max_length=100),
    db: Session = Depends(get_db),
):
    reports = _query_data(
        db,
        start_date,
        end_date,
        customer,
    )

    # --------------------------------------------------------
    # RECEIVABLES AGING
    # --------------------------------------------------------

    if kind == "aging":
        rows = reports["aging_invoices"]

        headers = [
            "invoice_number",
            "customer_name",
            "due_date",
            "total_aed",
            "recorded_paid_aed",
            "outstanding_aed",
            "days_overdue",
            "status",
        ]

    # --------------------------------------------------------
    # INVOICE REPORT
    # --------------------------------------------------------

    elif kind == "invoices":
        rows = reports["invoices"]

        headers = [
            "invoice_number",
            "customer_name",
            "issue_date",
            "due_date",
            "total_aed",
            "recorded_paid_aed",
            "outstanding_aed",
            "status",
        ]

    # --------------------------------------------------------
    # PAYMENT REPORT
    # --------------------------------------------------------

    elif kind == "payments":
        rows = reports["payments"]

        headers = [
            "date",
            "invoice_number",
            "customer_name",
            "amount_aed",
            "reference",
        ]

    # --------------------------------------------------------
    # RECONCILIATION REPORT
    # --------------------------------------------------------

    else:
        rows = [
            row
            for row in reports["aging_invoices"]
            if row["status"] == "Reconciliation required"
        ]

        headers = [
            "invoice_number",
            "customer_name",
            "due_date",
            "total_aed",
            "recorded_paid_aed",
            "outstanding_aed",
            "status",
        ]

    # --------------------------------------------------------
    # GENERATE CSV
    # --------------------------------------------------------

    output = io.StringIO(newline="")

    writer = csv.writer(output)

    writer.writerow(headers)

    for item in rows:
        writer.writerow(
            [
                _safe_csv_cell(item.get(key))
                for key in headers
            ]
        )

    # UTF-8 BOM improves Microsoft Excel compatibility.
    #
    # Export is bounded by the dashboard row limit.
    # The UI should indicate that only loaded rows export.

    payload = (
        "\ufeff" + output.getvalue()
    ).encode("utf-8")

    filename = (
        f'receivai_{kind}_{reports["as_of_date"]}.csv'
    )

    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            ),
            "Cache-Control": "private, no-store",
            "X-Report-Export-Scope": "loaded-rows-only",
        },
    )
