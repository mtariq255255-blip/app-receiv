
"""ReceivAI UAE — administrator-only, read-only audit history.

Uses the EXISTING app.models.AuditLog table and existing audit events.
Does not create events, change financial records, or expose raw audit JSON.

GET /api/audit-logs
GET /api/audit-logs/actions
GET /api/audit-logs/export
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_admin
from app.models import AdminUser, AuditLog


# ============================================================
# 1. ROUTER AND CONFIGURATION
# ============================================================

router = APIRouter(
    prefix="/api/audit-logs",
    tags=["Audit Logs"],
    dependencies=[Depends(get_current_admin)],
)

UAE_TZ = timezone(timedelta(hours=4))
MAX_EXPORT_ROWS = 10_000


# ============================================================
# 2. ALLOWED AUDIT DETAILS
# ============================================================

# Only selected metadata is exposed.
# Sensitive invoice values, addresses, TRNs, notes,
# tokens and raw document contents are not returned.

SAFE_DETAIL_KEYS = frozenset({
    "invoice_id",
    "document_id",
    "payment_id",
    "reminder_id",
    "invoice_number",
    "invoice_index",
    "payment_date",
    "amount_aed",
    "previous_status",
    "new_status",
    "old_status",
    "status",
    "review_status",
    "source_type",
    "file_type",
    "file_size",
    "validation_error_count",
    "validation_warning_count",
    "line_item_count",
    "is_valid",
    "error_count",
    "warning_count",
    "error_type",
    "method",
    "channel",
    "payment_count",
    "previous_approval_status",
    "new_approval_status",
    "sent",
})


# ============================================================
# 3. DATE VALIDATION
# ============================================================

def _validate_dates(
    start: date | None,
    end: date | None,
) -> None:

    if start and end and start > end:
        raise HTTPException(
            status_code=422,
            detail="Start date must be on or before end date.",
        )

    if end and end > datetime.now(UAE_TZ).date():
        raise HTTPException(
            status_code=422,
            detail="End date cannot be in the future (UAE time).",
        )


# ============================================================
# 4. BUILD AUDIT FILTERS
# ============================================================

def _where(
    *,
    start_date: date | None,
    end_date: date | None,
    action: str,
    entity_type: str,
    search: str,
):
    _validate_dates(start_date, end_date)

    filters = []

    # Start of day in UAE time.
    if start_date:
        begin = datetime.combine(
            start_date,
            time.min,
            tzinfo=UAE_TZ,
        )

        filters.append(
            AuditLog.created_at >= begin.astimezone(timezone.utc)
        )

    # Exclusive end of selected UAE day.
    if end_date:
        exclusive_end = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
            tzinfo=UAE_TZ,
        )

        filters.append(
            AuditLog.created_at <
            exclusive_end.astimezone(timezone.utc)
        )

    if action:
        filters.append(
            AuditLog.action == action
        )

    if entity_type:
        filters.append(
            AuditLog.entity_type == entity_type
        )

    if search:
        # Escape SQL wildcard characters.
        # Search is a literal substring.

        term = (
            search
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

        pattern = f"%{term}%"

        filters.append(
            or_(
                AuditLog.action.ilike(
                    pattern,
                    escape="\\",
                ),
                AuditLog.entity_type.ilike(
                    pattern,
                    escape="\\",
                ),
                cast(
                    AuditLog.entity_id,
                    String,
                ).ilike(
                    pattern,
                    escape="\\",
                ),
                AdminUser.email.ilike(
                    pattern,
                    escape="\\",
                ),
            )
        )

    return filters


# ============================================================
# 5. SANITIZE AUDIT DETAILS
# ============================================================

def _clean_details(raw: object) -> dict:
    """Return only non-sensitive, bounded event metadata."""

    if not isinstance(raw, dict):
        return {}

    safe = {}

    for key in sorted(SAFE_DETAIL_KEYS):
        value = raw.get(key)

        if isinstance(value, (bool, int)) or value is None:
            if key in raw:
                safe[key] = value

        elif isinstance(value, str):
            # Limit allowed metadata strings.
            safe[key] = value[:150]

    # Show names of changed fields only.
    # Never expose raw before/after values.

    changed = raw.get("corrected_fields")

    if isinstance(changed, dict):
        safe["changed_fields"] = [
            str(k)[:60]
            for k in list(changed)[:40]
        ]

    elif isinstance(changed, list):
        safe["changed_fields"] = [
            str(k)[:60]
            for k in changed[:40]
        ]

    elif isinstance(raw.get("after"), dict):
        safe["changed_fields"] = [
            str(k)[:60]
            for k in list(raw["after"])[:40]
        ]

    return safe


# ============================================================
# 6. SERIALIZE AUDIT EVENT
# ============================================================

def _to_item(
    audit: AuditLog,
    name: str | None,
    email: str | None,
) -> dict:

    dt = audit.created_at

    if dt and dt.tzinfo is None:
        # Legacy naive timestamps are treated as UTC.
        dt = dt.replace(tzinfo=timezone.utc)

    return {
        "id": audit.id,

        "created_at": (
            dt.isoformat()
            if dt
            else None
        ),

        "actor_name": (
            name
            or (
                "System"
                if audit.admin_id is None
                else "Unknown administrator"
            )
        ),

        "actor_email": email,

        "action": audit.action,

        "entity_type": audit.entity_type,

        "entity_id": audit.entity_id,

        "details": _clean_details(
            audit.details
        ),
    }


# ============================================================
# 7. BASE DATABASE QUERY
# ============================================================

def _base_query():
    return (
        select(
            AuditLog,
            AdminUser.full_name,
            AdminUser.email,
        )
        .outerjoin(
            AdminUser,
            AdminUser.id == AuditLog.admin_id,
        )
    )


# ============================================================
# 8. LIST AUDIT LOGS
# ============================================================

@router.get(
    "",
    summary="List recorded audit events",
)
def list_audit_logs(
    response: Response,

    start_date: date | None = None,
    end_date: date | None = None,

    action: Annotated[
        str,
        Query(max_length=150),
    ] = "",

    entity_type: Annotated[
        str,
        Query(max_length=100),
    ] = "",

    search: Annotated[
        str,
        Query(max_length=100),
    ] = "",

    page: Annotated[
        int,
        Query(ge=1, le=100000),
    ] = 1,

    page_size: Annotated[
        int,
        Query(ge=10, le=100),
    ] = 25,

    db: Session = Depends(get_db),
):
    response.headers[
        "Cache-Control"
    ] = "private, no-store"

    conditions = _where(
        start_date=start_date,
        end_date=end_date,
        action=action.strip(),
        entity_type=entity_type.strip(),
        search=search.strip(),
    )

    # --------------------------------------------------------
    # COUNT MATCHING EVENTS
    # --------------------------------------------------------

    common = (
        select(AuditLog.id)
        .outerjoin(
            AdminUser,
            AdminUser.id == AuditLog.admin_id,
        )
        .where(*conditions)
    )

    total = (
        db.scalar(
            select(func.count()).select_from(
                common.subquery()
            )
        )
        or 0
    )

    # --------------------------------------------------------
    # PAGINATED EVENTS
    # --------------------------------------------------------

    rows = db.execute(
        _base_query()
        .where(*conditions)
        .order_by(
            AuditLog.created_at.desc(),
            AuditLog.id.desc(),
        )
        .offset(
            (page - 1) * page_size
        )
        .limit(page_size)
    ).all()

    # --------------------------------------------------------
    # ACTION COUNTS
    # --------------------------------------------------------

    # Counts cover all filtered events, not just this page.

    action_rows = db.execute(
        select(
            AuditLog.action,
            func.count(AuditLog.id),
        )
        .outerjoin(
            AdminUser,
            AdminUser.id == AuditLog.admin_id,
        )
        .where(*conditions)
        .group_by(
            AuditLog.action
        )
        .order_by(
            func.count(AuditLog.id).desc(),
            AuditLog.action.asc(),
        )
        .limit(12)
    ).all()

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {
        "total": int(total),

        "page": page,

        "page_size": page_size,

        "has_next": (
            page * page_size < total
        ),

        "items": [
            _to_item(log, name, email)
            for log, name, email in rows
        ],

        "top_actions": [
            {
                "action": action_name,
                "count": int(count),
            }
            for action_name, count in action_rows
        ],

        "timezone": "Asia/Dubai",

        "read_only": True,

        "disclaimer": (
            "Shows recorded audit events only. "
            "Some older actions may not have been logged. "
            "Sensitive free-text details are intentionally omitted."
        ),
    }


# ============================================================
# 9. AVAILABLE AUDIT FILTERS
# ============================================================

@router.get(
    "/actions",
    summary="List known audit action and entity filters",
)
def audit_log_filters(
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers[
        "Cache-Control"
    ] = "private, no-store"

    actions = db.scalars(
        select(AuditLog.action)
        .distinct()
        .order_by(AuditLog.action)
        .limit(200)
    ).all()

    types = db.scalars(
        select(AuditLog.entity_type)
        .where(
            AuditLog.entity_type.is_not(None)
        )
        .distinct()
        .order_by(AuditLog.entity_type)
        .limit(100)
    ).all()

    return {
        "actions": actions,
        "entity_types": types,
    }


# ============================================================
# 10. CSV CELL SAFETY
# ============================================================

def _csv_cell(value: object) -> str:

    txt = (
        ""
        if value is None
        else str(value)
    )

    # Prevent CSV formula execution in spreadsheet apps.

    if txt.lstrip().startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ):
        return "'" + txt

    return txt


# ============================================================
# 11. EXPORT AUDIT LOGS AS CSV
# ============================================================

@router.get(
    "/export",
    summary="Export filtered audit history as CSV",
)
def export_audit_logs(
    start_date: date | None = None,
    end_date: date | None = None,

    action: Annotated[
        str,
        Query(max_length=150),
    ] = "",

    entity_type: Annotated[
        str,
        Query(max_length=100),
    ] = "",

    search: Annotated[
        str,
        Query(max_length=100),
    ] = "",

    db: Session = Depends(get_db),
):
    conditions = _where(
        start_date=start_date,
        end_date=end_date,
        action=action.strip(),
        entity_type=entity_type.strip(),
        search=search.strip(),
    )

    # --------------------------------------------------------
    # FETCH EXPORT ROWS
    # --------------------------------------------------------

    rows = db.execute(
        _base_query()
        .where(*conditions)
        .order_by(
            AuditLog.created_at.desc(),
            AuditLog.id.desc(),
        )
        .limit(
            MAX_EXPORT_ROWS + 1
        )
    ).all()

    truncated = (
        len(rows) > MAX_EXPORT_ROWS
    )

    # --------------------------------------------------------
    # BUILD CSV
    # --------------------------------------------------------

    output = io.StringIO(newline="")

    writer = csv.writer(output)

    writer.writerow([
        "id",
        "created_at_utc",
        "actor_name",
        "actor_email",
        "action",
        "entity_type",
        "entity_id",
        "safe_details",
    ])

    for log, name, email in rows[:MAX_EXPORT_ROWS]:
        item = _to_item(
            log,
            name,
            email,
        )

        writer.writerow([
            _csv_cell(item["id"]),

            _csv_cell(
                item["created_at"]
            ),

            _csv_cell(
                item["actor_name"]
            ),

            _csv_cell(
                item["actor_email"]
            ),

            _csv_cell(
                item["action"]
            ),

            _csv_cell(
                item["entity_type"]
            ),

            _csv_cell(
                item["entity_id"]
            ),

            _csv_cell(
                "; ".join(
                    f"{k}: {v}"
                    for k, v in item["details"].items()
                )
            ),
        ])

    # --------------------------------------------------------
    # DOWNLOAD RESPONSE
    # --------------------------------------------------------

    filename = (
        "receivai_audit_logs_"
        f"{datetime.now(UAE_TZ).date().isoformat()}.csv"
    )

    return Response(
        content=(
            "\ufeff" + output.getvalue()
        ).encode("utf-8"),

        media_type="text/csv; charset=utf-8",

        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            ),

            "Cache-Control": "private, no-store",

            "X-Audit-Export-Truncated": (
                "true"
                if truncated
                else "false"
            ),

            "X-Audit-Export-Limit": str(
                MAX_EXPORT_ROWS
            ),
        },
    )
