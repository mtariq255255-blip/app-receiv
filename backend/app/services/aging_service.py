
"""
ReceivAI UAE
Module 2: Payment Collections

Service: Invoice Aging Analysis

Responsibilities:
- Calculate overdue days
- Identify invoices due soon
- Assign aging categories
- Produce receivables aging summaries

No OpenAI calls.
No database modifications.
All financial calculations use Decimal.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any


ZERO = Decimal("0.00")
CENT = Decimal("0.01")

AGING_BUCKETS = (
    "not_due",
    "overdue_1_30",
    "overdue_31_60",
    "overdue_61_90",
    "overdue_90_plus",
)


def parse_date(value: Any) -> date | None:
    """
    Convert supported date values into a Python date.

    Accepted:
    - date
    - datetime
    - ISO date string YYYY-MM-DD

    Invalid or ambiguous dates return None.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        value = value.strip()

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    return None


def parse_amount(value: Any) -> Decimal:
    """
    Safely convert monetary values to Decimal.

    Invalid monetary values raise ValueError rather
    than silently becoming zero.
    """

    if value is None:
        raise ValueError("Amount is required.")

    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError(
            "Invalid monetary amount."
        ) from exc

    if not amount.is_finite():
        raise ValueError(
            "Amount must be finite."
        )

    if amount < ZERO:
        raise ValueError(
            "Amount cannot be negative."
        )

    return amount.quantize(CENT)


def calculate_overdue_days(
    due_date: date | datetime | str | None,
    as_of_date: date | None = None,
) -> int:
    """
    Calculate days overdue.

    Returns:
        0 when invoice is not overdue.
        Positive integer when overdue.

    Missing or invalid due dates raise ValueError.
    """

    parsed_due_date = parse_date(due_date)

    if parsed_due_date is None:
        raise ValueError(
            "A valid due date is required."
        )

    today = as_of_date or date.today()

    days = (today - parsed_due_date).days

    return max(days, 0)


def calculate_days_until_due(
    due_date: date | datetime | str | None,
    as_of_date: date | None = None,
) -> int:
    """
    Return days remaining until an invoice is due.

    Positive: future due date
    Zero: due today
    Negative: overdue
    """

    parsed_due_date = parse_date(due_date)

    if parsed_due_date is None:
        raise ValueError(
            "A valid due date is required."
        )

    today = as_of_date or date.today()

    return (parsed_due_date - today).days


def get_aging_bucket(
    due_date: date | datetime | str | None,
    outstanding_amount: Any,
    as_of_date: date | None = None,
) -> str:
    """
    Categorize an invoice using its overdue duration.

    A fully paid invoice is assigned 'paid'.

    An invoice missing a due date is 'unknown_due_date'.
    """

    amount = parse_amount(outstanding_amount)

    if amount == ZERO:
        return "paid"

    parsed_due_date = parse_date(due_date)

    if parsed_due_date is None:
        return "unknown_due_date"

    days = calculate_overdue_days(
        parsed_due_date,
        as_of_date=as_of_date,
    )

    if days == 0:
        return "not_due"

    if days <= 30:
        return "overdue_1_30"

    if days <= 60:
        return "overdue_31_60"

    if days <= 90:
        return "overdue_61_90"

    return "overdue_90_plus"


def get_aging_label(bucket: str) -> str:
    """Return a readable label for the dashboard."""

    labels = {
        "paid": "Paid",
        "not_due": "Not Yet Due",
        "overdue_1_30": "1–30 Days Overdue",
        "overdue_31_60": "31–60 Days Overdue",
        "overdue_61_90": "61–90 Days Overdue",
        "overdue_90_plus": "More Than 90 Days Overdue",
        "unknown_due_date": "Due Date Missing",
    }

    return labels.get(bucket, "Unknown")


def is_due_soon(
    due_date: date | datetime | str | None,
    outstanding_amount: Any,
    days_ahead: int = 7,
    as_of_date: date | None = None,
) -> bool:
    """
    Return True for outstanding invoices due within
    the configured future window, including today.
    """

    if days_ahead < 0:
        raise ValueError(
            "days_ahead cannot be negative."
        )

    amount = parse_amount(outstanding_amount)

    if amount == ZERO:
        return False

    parsed_due_date = parse_date(due_date)

    if parsed_due_date is None:
        return False

    today = as_of_date or date.today()

    return (
        today <= parsed_due_date
        <= today + timedelta(days=days_ahead)
    )


def analyze_invoice_aging(
    invoice_id: int,
    due_date: date | datetime | str | None,
    outstanding_amount: Any,
    as_of_date: date | None = None,
) -> dict:
    """
    Return the aging analysis for one invoice.
    """

    today = as_of_date or date.today()

    amount = parse_amount(outstanding_amount)

    parsed_due_date = parse_date(due_date)

    bucket = get_aging_bucket(
        parsed_due_date,
        amount,
        as_of_date=today,
    )

    overdue_days = (
        calculate_overdue_days(
            parsed_due_date,
            as_of_date=today,
        )
        if parsed_due_date
        else None
    )

    return {
        "invoice_id": invoice_id,
        "due_date": (
            parsed_due_date.isoformat()
            if parsed_due_date
            else None
        ),
        "as_of_date": today.isoformat(),
        "outstanding_amount": str(amount),
        "days_overdue": overdue_days,
        "aging_bucket": bucket,
        "aging_label": get_aging_label(bucket),
        "is_overdue": (
            amount > ZERO
            and overdue_days is not None
            and overdue_days > 0
        ),
        "due_soon": is_due_soon(
            parsed_due_date,
            amount,
            as_of_date=today,
        ),
    }


def summarize_aging(
    invoices: list[dict],
    as_of_date: date | None = None,
) -> dict:
    """
    Aggregate outstanding balances into aging buckets.

    Expected invoice structure:

    {
        "invoice_id": 1,
        "due_date": "2026-11-01",
        "outstanding_amount": "5000.00"
    }

    Do not pass invoice totals here without first
    subtracting confirmed payments.
    """

    today = as_of_date or date.today()

    totals = {
        bucket: ZERO
        for bucket in AGING_BUCKETS
    }

    totals["unknown_due_date"] = ZERO

    counts = {
        bucket: 0
        for bucket in totals
    }

    total_outstanding = ZERO
    total_overdue = ZERO
    total_due_soon = ZERO

    for invoice in invoices:

        amount = parse_amount(
            invoice["outstanding_amount"]
        )

        if amount == ZERO:
            continue

        due_date = invoice.get("due_date")

        bucket = get_aging_bucket(
            due_date,
            amount,
            as_of_date=today,
        )

        totals[bucket] += amount
        counts[bucket] += 1

        total_outstanding += amount

        if bucket.startswith("overdue_"):
            total_overdue += amount

        if is_due_soon(
            due_date,
            amount,
            as_of_date=today,
        ):
            total_due_soon += amount

    return {
        "as_of_date": today.isoformat(),
        "currency": "AED",
        "total_outstanding": str(total_outstanding),
        "total_overdue": str(total_overdue),
        "total_due_soon": str(total_due_soon),
        "buckets": [
            {
                "key": bucket,
                "label": get_aging_label(bucket),
                "amount": str(totals[bucket]),
                "invoice_count": counts[bucket],
            }
            for bucket in totals
        ],
    }
