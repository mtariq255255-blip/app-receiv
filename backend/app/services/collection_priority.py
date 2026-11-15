
"""
ReceivAI UAE
Module 2: Payment Collections

Collection Priority Scoring Engine

Responsibilities:
- Analyze outstanding invoice balances
- Calculate overdue urgency
- Assign transparent priority scores
- Recommend collection follow-up actions
- Sort invoices by collection priority
- Summarize collection priority categories

No OpenAI calls.
No database modifications.
No automatic customer communication.

Scores are operational prioritization heuristics,
not validated predictions of non-payment.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.aging_service import (
    calculate_overdue_days,
    is_due_soon,
    parse_date,
)


ZERO = Decimal("0.00")
CENT = Decimal("0.01")

# Configurable operational thresholds, in AED.
AMOUNT_LOW = Decimal("1000.00")
AMOUNT_MEDIUM = Decimal("5000.00")
AMOUNT_HIGH = Decimal("10000.00")
AMOUNT_CRITICAL = Decimal("20000.00")

HIGH_PRIORITY_THRESHOLD = 60
MEDIUM_PRIORITY_THRESHOLD = 30


def _money(value: Any) -> Decimal:
    """
    Convert amount to Decimal.

    Reject malformed, negative, or non-finite amounts.
    """

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            "Invalid monetary amount for priority scoring."
        )

    if not amount.is_finite() or amount < ZERO:
        raise ValueError(
            "Amount must be finite and non-negative."
        )

    return amount.quantize(CENT)


def _nonnegative_int(value: Any, name: str) -> int:
    """Validate an integer count."""

    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be a non-negative integer."
        )

    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(
            f"{name} must be a non-negative integer."
        )

    if str(value).strip() != str(count) or count < 0:
        raise ValueError(
            f"{name} must be a non-negative integer."
        )

    return count


def calculate_overdue_score(days_overdue: int) -> int:
    """
    Score invoice urgency based on overdue duration.

    Maximum: 65 points.
    """

    if days_overdue < 0:
        raise ValueError(
            "days_overdue cannot be negative."
        )

    if days_overdue == 0:
        return 0

    if days_overdue <= 7:
        return 15

    if days_overdue <= 30:
        return 30

    if days_overdue <= 60:
        return 45

    if days_overdue <= 90:
        return 55

    return 65


def calculate_amount_score(
    outstanding_amount: Any,
) -> int:
    """
    Score financial exposure using AED thresholds.

    Maximum: 20 points.
    """

    amount = _money(outstanding_amount)

    if amount >= AMOUNT_CRITICAL:
        return 20

    if amount >= AMOUNT_HIGH:
        return 15

    if amount >= AMOUNT_MEDIUM:
        return 10

    if amount >= AMOUNT_LOW:
        return 5

    return 0


def calculate_payment_history_score(
    paid_amount: Any,
    outstanding_amount: Any,
    days_overdue: int,
) -> int:
    """
    Add a small operational adjustment for an overdue
    invoice with partial payment activity.

    This is not a prediction of customer risk.

    Maximum: 5 points.
    """

    paid = _money(paid_amount)
    outstanding = _money(outstanding_amount)

    if (
        paid > ZERO
        and outstanding > ZERO
        and days_overdue > 0
    ):
        return 5

    return 0


def calculate_reminder_score(
    reminder_count: int,
    days_overdue: int,
) -> int:
    """
    Add a small follow-up attention score when an
    overdue invoice has multiple prior reminders.

    Maximum: 5 points.

    Only actual approved/sent reminder activity
    should be counted when this is connected to DB.
    Unsent drafts must not count as contact attempts.
    """

    if reminder_count >= 2 and days_overdue > 0:
        return 5

    return 0


def get_priority_level(score: int) -> str:
    """Convert numeric score into priority category."""

    if not 0 <= score <= 100:
        raise ValueError(
            "Priority score must be between 0 and 100."
        )

    if score >= HIGH_PRIORITY_THRESHOLD:
        return "high"

    if score >= MEDIUM_PRIORITY_THRESHOLD:
        return "medium"

    return "low"


def get_priority_label(priority: str) -> str:
    """Return readable priority labels."""

    labels = {
        "high": "High Priority",
        "medium": "Medium Priority",
        "low": "Low Priority",
        "none": "No Collection Required",
        "review_required": "Manual Review Required",
    }

    return labels.get(priority, "Unknown Priority")


def get_recommended_action(
    days_overdue: int,
    outstanding_amount: Decimal,
    *,
    due_soon: bool = False,
    needs_review: bool = False,
) -> str:
    """
    Recommend a collection workflow action.

    Recommendations are suggestions only.
    No email, SMS or WhatsApp is sent.
    """

    if needs_review:
        return "review_invoice_data"

    if outstanding_amount <= ZERO:
        return "no_action"

    if days_overdue > 90:
        return "senior_finance_review"

    if days_overdue > 60:
        return "prepare_firm_follow_up"

    if days_overdue > 30:
        return "prepare_second_reminder"

    if days_overdue > 0:
        return "prepare_friendly_reminder"

    if due_soon:
        return "prepare_due_date_reminder"

    return "monitor_invoice"


def score_receivable(
    receivable: dict,
    reminder_count: int = 0,
    as_of_date: date | None = None,
) -> dict:
    """
    Score one receivable.

    Accepts a dictionary generated by:
    receivables_service.list_invoice_receivables()

    Expected keys:
    invoice_id
    invoice_number
    customer_name
    invoice_total
    paid_amount
    outstanding_amount
    due_date
    payment_status

    Returns:
    Original receivable data plus scoring information.
    """

    today = as_of_date or date.today()

    outstanding = _money(
        receivable["outstanding_amount"]
    )

    paid = _money(
        receivable.get("paid_amount", "0.00")
    )

    invoice_total = _money(
        receivable["invoice_total"]
    )

    reminders = _nonnegative_int(
        reminder_count,
        "reminder_count",
    )

    parsed_due_date = parse_date(
        receivable.get("due_date")
    )

    warnings = list(
        receivable.get("warnings") or []
    )

    reasons = []

    invoice_id = receivable["invoice_id"]

    # Invoices with no positive outstanding balance
    # do not require collection follow-up.
    if outstanding == ZERO:

        result = dict(receivable)

        result.update({
            "priority_score": 0,
            "priority_level": "none",
            "priority_label": (
                "No Collection Required"
            ),
            "priority_reasons": [
                "No outstanding balance remains."
            ],
            "recommended_action": "no_action",
            "reminder_count": reminders,
            "collection_eligible": False,
            "priority_warnings": warnings,
            "scoring_date": today.isoformat(),
        })

        return result

    needs_review = False

    if invoice_total <= ZERO:
        needs_review = True
        warnings.append(
            "Invoice total must be positive."
        )

    if paid > invoice_total:
        needs_review = True
        warnings.append(
            "Recorded payments exceed invoice total."
        )

    if parsed_due_date is None:
        needs_review = True
        warnings.append(
            "Invoice due date is missing or invalid."
        )

    # Do not prioritize collection of invoices that staff previously marked
    # paid when no matching payment ledger records exist. These remain
    # visible in the queue strictly as reconciliation exceptions.
    if any(
        "RECONCILIATION_REQUIRED:" in str(warning)
        for warning in warnings
    ):
        needs_review = True

    currency = str(
        receivable.get("currency") or ""
    ).upper()

    if currency != "AED":
        needs_review = True
        warnings.append(
            "Priority scoring supports AED invoices only."
        )

    if needs_review:

        result = dict(receivable)

        result.update({
            "priority_score": 0,
            "priority_level": "review_required",
            "priority_label": "Manual Review Required",
            "priority_reasons": [
                "The invoice requires data verification."
            ],
            "recommended_action": "review_invoice_data",
            "reminder_count": reminders,
            "collection_eligible": False,
            "priority_warnings": warnings,
            "scoring_date": today.isoformat(),
        })

        return result

    days_overdue = calculate_overdue_days(
        parsed_due_date,
        as_of_date=today,
    )

    due_soon = is_due_soon(
        parsed_due_date,
        outstanding,
        as_of_date=today,
    )

    overdue_score = calculate_overdue_score(
        days_overdue
    )

    # Upcoming invoices receive a small attention score,
    # but not the overdue penalty.
    upcoming_score = (
        8 if due_soon and days_overdue == 0 else 0
    )

    # Amount-based urgency applies only to overdue
    # invoices, avoiding high priorities solely because
    # a large invoice is not yet due.
    amount_score = (
        calculate_amount_score(outstanding)
        if days_overdue > 0
        else 0
    )

    payment_score = calculate_payment_history_score(
        paid,
        outstanding,
        days_overdue,
    )

    reminder_score = calculate_reminder_score(
        reminders,
        days_overdue,
    )

    score = min(
        100,
        overdue_score
        + upcoming_score
        + amount_score
        + payment_score
        + reminder_score,
    )

    priority = get_priority_level(score)

    if days_overdue > 0:
        reasons.append(
            f"Invoice is {days_overdue} day(s) overdue."
        )

    elif due_soon:
        reasons.append(
            "Invoice is due within the next seven days."
        )

    else:
        reasons.append(
            "Invoice is not yet due."
        )

    if amount_score > 0:
        reasons.append(
            "Outstanding balance meets an elevated "
            "collection amount threshold."
        )

    if payment_score > 0:
        reasons.append(
            "Invoice is overdue and has recorded "
            "partial payment activity."
        )

    if reminder_score > 0:
        reasons.append(
            "Multiple earlier reminder activities "
            "were recorded."
        )

    result = dict(receivable)

    result.update({
        "priority_score": score,
        "priority_level": priority,
        "priority_label": get_priority_label(
            priority
        ),
        "priority_reasons": reasons,
        "recommended_action": get_recommended_action(
            days_overdue,
            outstanding,
            due_soon=due_soon,
        ),
        "reminder_count": reminders,
        "collection_eligible": True,
        "priority_warnings": warnings,
        "scoring_date": today.isoformat(),
        "score_breakdown": {
            "overdue": overdue_score,
            "upcoming": upcoming_score,
            "amount": amount_score,
            "payment_history": payment_score,
            "reminder_history": reminder_score,
        },
    })

    return result


def prioritize_receivables(
    receivables: list[dict],
    reminder_counts: dict[int, int] | None = None,
    as_of_date: date | None = None,
    include_settled: bool = False,
) -> list[dict]:
    """
    Score and sort multiple invoices.

    reminder_counts:
        {
            invoice_id: count_of_actual_reminders
        }

    Draft reminders should not be included.

    High scores appear first.
    """

    reminder_counts = reminder_counts or {}

    results = []

    for receivable in receivables:

        invoice_id = receivable["invoice_id"]

        scored = score_receivable(
            receivable,
            reminder_count=reminder_counts.get(
                invoice_id, 0
            ),
            as_of_date=as_of_date,
        )

        if (
            not include_settled
            and scored["priority_level"] == "none"
        ):
            continue

        results.append(scored)

    # Manual-review exceptions go to the top of
    # the internal work queue so staff can resolve
    # them without sending collection messages.
    results.sort(
        key=lambda item: (
            0 if item["priority_level"] == "review_required" else 1,
            -item["priority_score"],
            -_money(item["outstanding_amount"]),
            item["invoice_id"],
        )
    )

    return results


def summarize_collection_priorities(
    receivables: list[dict],
    as_of_date: date | None = None,
    reminder_counts: dict[int, int] | None = None,
) -> dict:
    """
    Produce summary cards for the Payment Collections UI.

    Expected input:
    list_invoice_receivables() output.

    Only outstanding invoices are included in
    collection-priority counts.
    """

    scored = prioritize_receivables(
        receivables,
        reminder_counts=reminder_counts,
        as_of_date=as_of_date,
        include_settled=False,
    )

    categories = {
        "high": {
            "count": 0,
            "outstanding_amount": ZERO,
        },
        "medium": {
            "count": 0,
            "outstanding_amount": ZERO,
        },
        "low": {
            "count": 0,
            "outstanding_amount": ZERO,
        },
        "review_required": {
            "count": 0,
            "outstanding_amount": ZERO,
        },
    }

    for invoice in scored:

        priority = invoice["priority_level"]

        if priority not in categories:
            continue

        categories[priority]["count"] += 1

        categories[priority]["outstanding_amount"] += (
            _money(invoice["outstanding_amount"])
        )

    return {
        "as_of_date": (
            as_of_date or date.today()
        ).isoformat(),
        "currency": "AED",
        "total_actionable_invoices": len(scored),
        "high_priority_count": categories["high"]["count"],
        "medium_priority_count": categories["medium"]["count"],
        "low_priority_count": categories["low"]["count"],
        "manual_review_count": categories[
            "review_required"
        ]["count"],
        "categories": [
            {
                "priority": key,
                "label": get_priority_label(key),
                "invoice_count": value["count"],
                "outstanding_amount": str(
                    value["outstanding_amount"].quantize(
                        CENT
                    )
                ),
            }
            for key, value in categories.items()
        ],
    }
