
"""
ReceivAI UAE
Module 2 - Payment Collections

Privacy-Safe Reminder Template Service

Responsibilities:
- Determine reminder stage
- Generate local fallback templates
- Validate AI template placeholders
- Reject unsupported or risky AI content
- Merge real invoice details locally

No database writes.
No emails are sent.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.reminder_generation import (
    AIReminderTemplate,
    SanitizedReminderContext,
)


ALLOWED_PLACEHOLDERS = frozenset({
    "customer_name",
    "invoice_number",
    "outstanding_amount",
    "due_date",
    "sender_name",
})

PLACEHOLDER_PATTERN = re.compile(
    r"\{\{([^{}]+)\}\}"
)

REQUIRED_BODY_PLACEHOLDERS = frozenset({
    "customer_name",
    "invoice_number",
    "outstanding_amount",
})

# Reject free-form braces rather than allowing
# unresolved expressions into the final message.
BRACE_PATTERN = re.compile(r"[{}]")

# Conservative policy: these statements must not
# be invented by an AI reminder generator.
BLOCKED_CONTENT_PATTERNS = (
    r"\blegal action\b",
    r"\bcourt proceedings?\b",
    r"\blawsuit\b",
    r"\bdebt collectors?\b",
    r"\bcredit bureau\b",
    r"\bcredit score\b",
    r"\bpenalt(?:y|ies)\b",
    r"\blate fees?\b",
    r"\binterest charges?\b",
    r"\baccount suspension\b",
    r"\bservices? (?:will be|has been) terminated\b",
    r"\bwithin \d+ (?:hours?|days?)\b",
)

CURRENCY_PATTERN = re.compile(
    r"\bAED\s*[\d,]+(?:\.\d+)?\b",
    re.IGNORECASE,
)


class ReminderTemplateError(ValueError):
    """Template is invalid or violates reminder policy."""


def derive_reminder_stage(
    days_overdue: int,
) -> str:
    """
    Determine the collection stage from verified
    overdue information.
    """

    if days_overdue < 0:
        raise ValueError(
            "days_overdue cannot be negative."
        )

    if days_overdue == 0:
        return "pre_due"

    if days_overdue <= 30:
        return "first"

    if days_overdue <= 60:
        return "second"

    return "final"


def derive_due_category(
    days_overdue: int,
) -> str:
    """Convert overdue days to a non-identifying category."""

    if days_overdue < 0:
        raise ValueError(
            "days_overdue cannot be negative."
        )

    if days_overdue == 0:
        return "due_soon"

    if days_overdue <= 7:
        return "overdue_1_7"

    if days_overdue <= 30:
        return "overdue_8_30"

    if days_overdue <= 60:
        return "overdue_31_60"

    if days_overdue <= 90:
        return "overdue_61_90"

    return "overdue_90_plus"


def build_sanitized_context(
    *,
    tone: str,
    days_overdue: int,
    paid_amount: Any,
) -> SanitizedReminderContext:
    """
    Build the complete allowlisted OpenAI input.

    Never pass customer data directly to this function.
    """

    try:
        paid = Decimal(str(paid_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            "Invalid recorded payment amount."
        )

    if not paid.is_finite() or paid < 0:
        raise ValueError(
            "Invalid recorded payment amount."
        )

    return SanitizedReminderContext(
        tone=tone,
        stage=derive_reminder_stage(days_overdue),
        due_category=derive_due_category(days_overdue),
        payment_category=(
            "partially_paid" if paid > 0 else "unpaid"
        ),
        currency="AED",
    )


def make_local_template(
    context: SanitizedReminderContext,
) -> AIReminderTemplate:
    """
    Produce a professional reminder without OpenAI.

    The same template validation applies to local
    and AI-generated content.
    """

    if context.stage == "pre_due":
        introduction = (
            "This is a courtesy reminder that payment "
            "for invoice {{invoice_number}} is due "
            "on {{due_date}}."
        )

        request = (
            "Please arrange payment of the outstanding "
            "balance of {{outstanding_amount}} by the "
            "due date, if it has not already been paid."
        )

    elif context.stage == "first":
        introduction = (
            "Our records indicate that invoice "
            "{{invoice_number}}, due on {{due_date}}, "
            "has an outstanding balance."
        )

        request = (
            "We would appreciate an update on payment "
            "of {{outstanding_amount}}."
        )

    elif context.stage == "second":
        introduction = (
            "We are following up regarding invoice "
            "{{invoice_number}}, which remains "
            "outstanding after its due date "
            "of {{due_date}}."
        )

        request = (
            "Please confirm the expected payment date "
            "for the remaining balance of "
            "{{outstanding_amount}}."
        )

    else:
        introduction = (
            "We are requesting an update regarding "
            "the outstanding payment for invoice "
            "{{invoice_number}}, originally due "
            "on {{due_date}}."
        )

        request = (
            "Please provide a payment update and "
            "an expected settlement date for "
            "{{outstanding_amount}}."
        )

    if context.payment_category == "partially_paid":
        request += (
            " We acknowledge that partial payment "
            "activity has been recorded."
        )

    if context.tone == "friendly":
        greeting = (
            "I hope you are doing well."
        )

        closing = (
            "Thank you for your time and cooperation."
        )

    elif context.tone == "firm":
        greeting = (
            "We are contacting you regarding "
            "an outstanding invoice."
        )

        closing = (
            "We request your prompt response."
        )

    else:
        greeting = (
            "I hope this message finds you well."
        )

        closing = (
            "Thank you for your attention "
            "to this matter."
        )

    subject = (
        "Payment follow-up - Invoice "
        "{{invoice_number}}"
    )

    if context.stage == "pre_due":
        subject = (
            "Upcoming payment - Invoice "
            "{{invoice_number}}"
        )

    body = (
        "Dear {{customer_name}},\n\n"
        f"{greeting}\n\n"
        f"{introduction}\n\n"
        f"{request}\n\n"
        "If payment has already been arranged, "
        "please disregard this reminder and "
        "share the payment reference if convenient.\n\n"
        f"{closing}\n\n"
        "Kind regards,\n"
        "{{sender_name}}"
    )

    template = AIReminderTemplate(
        subject=subject,
        body=body,
    )

    validate_reminder_template(template)

    return template


def validate_reminder_template(
    template: AIReminderTemplate,
) -> None:
    """
    Reject unsupported placeholders and risky claims.

    This is a conservative MVP policy, not a
    general-purpose legal-content classifier.
    """

    combined = (
        template.subject + "\n" + template.body
    )

    placeholders = {
        item.strip()
        for item in PLACEHOLDER_PATTERN.findall(
            combined
        )
    }

    unknown = placeholders - ALLOWED_PLACEHOLDERS

    if unknown:
        raise ReminderTemplateError(
            "Reminder contains unsupported placeholders."
        )

    body_placeholders = {
        item.strip()
        for item in PLACEHOLDER_PATTERN.findall(
            template.body
        )
    }

    missing = (
        REQUIRED_BODY_PLACEHOLDERS
        - body_placeholders
    )

    if missing:
        raise ReminderTemplateError(
            "Reminder is missing required placeholders."
        )

    # Remove validated placeholders and then reject
    # any stray braces or template expressions.
    without_placeholders = (
        PLACEHOLDER_PATTERN.sub("", combined)
    )

    if BRACE_PATTERN.search(without_placeholders):
        raise ReminderTemplateError(
            "Reminder contains unsupported template syntax."
        )

    if CURRENCY_PATTERN.search(combined):
        raise ReminderTemplateError(
            "Reminder contains a hardcoded AED amount."
        )

    for pattern in BLOCKED_CONTENT_PATTERNS:
        if re.search(
            pattern,
            combined,
            re.IGNORECASE,
        ):
            raise ReminderTemplateError(
                "Reminder contains an unapproved "
                "collection or enforcement statement."
            )

    if len(template.body) > 2000:
        raise ReminderTemplateError(
            "Reminder body is too long."
        )


def _safe_text(
    value: Any,
    *,
    fallback: str = "",
    max_length: int = 200,
) -> str:
    """Normalize text used in local substitution."""

    if value is None:
        return fallback

    text = str(value).strip()

    # Prevent newline-based body manipulation.
    text = " ".join(text.split())

    if not text:
        return fallback

    if len(text) > max_length:
        raise ReminderTemplateError(
            "A local invoice field is too long."
        )

    if any(character in text for character in "{}<>"):
        raise ReminderTemplateError(
            "A local invoice field contains "
            "unsupported characters."
        )

    return text


def _format_aed(value: Any) -> str:
    """Format a validated outstanding amount."""

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ReminderTemplateError(
            "Invalid outstanding amount."
        )

    if not amount.is_finite() or amount <= 0:
        raise ReminderTemplateError(
            "Outstanding amount must be positive."
        )

    return f"AED {amount:,.2f}"


def render_reminder_template(
    template: AIReminderTemplate,
    *,
    invoice_number: str,
    customer_name: str,
    outstanding_amount: Any,
    due_date: date | str,
    sender_name: str = "Accounts Receivable Team",
) -> dict:
    """
    Insert confidential invoice details locally.

    This method must only run after the AI response
    has returned to the trusted backend.
    """

    validate_reminder_template(template)

    if isinstance(due_date, date):
        due_text = due_date.isoformat()
    else:
        try:
            due_text = date.fromisoformat(
                str(due_date)
            ).isoformat()
        except ValueError as exc:
            raise ReminderTemplateError(
                "Invalid invoice due date."
            ) from exc

    replacements = {
        "customer_name": _safe_text(
            customer_name,
            max_length=180,
        ),
        "invoice_number": _safe_text(
            invoice_number,
            max_length=100,
        ),
        "outstanding_amount": _format_aed(
            outstanding_amount
        ),
        "due_date": due_text,
        "sender_name": _safe_text(
            sender_name,
            fallback="Accounts Receivable Team",
            max_length=150,
        ),
    }

    if not replacements["customer_name"]:
        raise ReminderTemplateError(
            "Customer name is required."
        )

    if not replacements["invoice_number"]:
        raise ReminderTemplateError(
            "Invoice number is required."
        )

    def replace(match: re.Match) -> str:
        key = match.group(1).strip()
        return replacements[key]

    subject = PLACEHOLDER_PATTERN.sub(
        replace,
        template.subject,
    )

    message = PLACEHOLDER_PATTERN.sub(
        replace,
        template.body,
    )

    return {
        "subject": subject,
        "message": message,
    }
