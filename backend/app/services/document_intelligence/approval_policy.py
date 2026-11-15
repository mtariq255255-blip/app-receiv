
"""Conservative, side-effect-free invoice readiness policy for ReceivAI UAE.

The extractor and finance reconciler do not grant financial approval.
This module evaluates readiness; it never writes to a ledger, approves a
record, sends reminders, or replaces the existing invoice validator.

Only trusted backend code may supply review, duplicate_check, and collections.
Never use raw client-provided booleans as proof of approval.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


BLOCKING_DUPLICATE_STATUSES = frozenset({
    "duplicate",
    "duplicate_upload",
    "same_invoice",
    "conflicting_number",
    "ambiguous",
})

CLEAR_DUPLICATE_STATUSES = frozenset({
    "clear",
    "no_duplicate",
    "unique",
})

MATERIAL_UNRESOLVED_PREFIXES = (
    "invoice_number",
    "supplier_name",
    "customer_name",
    "issue_date",
    "due_date",
    "currency",
    "total_amount_aed",
    "subtotal_aed",
    "vat_amount_aed",
    "items",
    "financial_reconciliation",
    "supplier_trn",
    "customer_trn",
)


def _present(value: Any) -> bool:
    return (
        value is not None
        and not (
            isinstance(value, str)
            and not value.strip()
        )
    )


def _positive_money(value: Any) -> bool:
    if value is None or isinstance(value, (bool, float)):
        return False

    try:
        raw = str(value).strip().replace(",", "")

        if raw.upper().startswith("AED "):
            raw = raw[4:].strip()

        number = Decimal(raw)

        return number.is_finite() and number > 0

    except (InvalidOperation, TypeError, ValueError):
        return False


def _calendar_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        return None

    try:
        return date.fromisoformat(value.strip())

    except ValueError:
        return None


def _unique(messages: list[str]) -> list[str]:
    return list(dict.fromkeys(messages))


def evaluate_approval_policy(
    interpretation: Mapping[str, Any],
    *,
    validation: Mapping[str, Any] | None = None,
    review: Mapping[str, Any] | None = None,
    duplicate_check: Mapping[str, Any] | None = None,
    collections: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate invoice readiness for review, posting and collections.

    All actions default to blocked without independent evidence.

    The existing validate_invoice() output must come from trusted
    backend code.

    Review must represent a persisted administrator approval record.

    Duplicate checking must use trusted database results.

    Collections information must come from verified customer records.

    Returned values are eligibility assessments only.
    Actual permissions and state changes belong to the application.
    """

    if not isinstance(interpretation, Mapping):
        raise TypeError(
            "interpretation must be a mapping"
        )

    for name, obj in (
        ("validation", validation),
        ("review", review),
        ("duplicate_check", duplicate_check),
        ("collections", collections),
    ):
        if obj is not None and not isinstance(obj, Mapping):
            raise TypeError(
                f"{name} must be a mapping or None"
            )

    invoice = interpretation.get("invoice")

    if not isinstance(invoice, Mapping):
        invoice = {}

    finance = interpretation.get(
        "financial_reconciliation"
    )

    if not isinstance(finance, Mapping):
        finance = {}

    validation = validation or {}
    review = review or {}
    duplicate_check = duplicate_check or {}
    collections = collections or {}

    unresolved = (
        interpretation.get("unresolved_fields") or []
    )

    if not isinstance(unresolved, (list, tuple, set)):
        unresolved = ["invalid_unresolved_fields"]

    unresolved = [str(x) for x in unresolved]

    extraction_reasons: list[str] = []
    posting_reasons: list[str] = []
    collections_reasons: list[str] = []
    tax_reasons: list[str] = []

    # -------------------------------------------------
    # 1. Check required invoice identity fields
    # -------------------------------------------------

    required_fields = (
        "invoice_number",
        "supplier_name",
        "customer_name",
        "issue_date",
        "currency",
        "total_amount_aed",
    )

    for field in required_fields:
        if not _present(invoice.get(field)):
            extraction_reasons.append(
                f"Missing invoice field: {field}."
            )

    if (
        not isinstance(invoice.get("items"), list)
        or not invoice.get("items")
    ):
        extraction_reasons.append(
            "No source-backed invoice line items available."
        )

    if not _positive_money(
        invoice.get("total_amount_aed")
    ):
        extraction_reasons.append(
            "Invoice total must be a positive, valid amount."
        )

    # -------------------------------------------------
    # 2. Check extraction conflicts
    # -------------------------------------------------

    if interpretation.get(
        "item_comparison_status"
    ) in {"conflicting", "incomplete"}:
        extraction_reasons.append(
            "Native and Docling item sets disagree or are incomplete."
        )

    if interpretation.get("alternative_items") is not None:
        extraction_reasons.append(
            "Alternative item tables require administrator comparison."
        )

    if interpretation.get("field_conflicts"):
        extraction_reasons.append(
            "Conflicting source field values require review."
        )

    material_unresolved = [
        key
        for key in unresolved
        if (
            key == "invalid_unresolved_fields"
            or any(
                key == prefix
                or key.startswith(prefix + ".")
                for prefix in MATERIAL_UNRESOLVED_PREFIXES
            )
        )
    ]

    if material_unresolved:
        extraction_reasons.append(
            "Material unresolved fields: "
            + ", ".join(sorted(set(material_unresolved)))
            + "."
        )

    if interpretation.get("manual_review_required") is True:
        extraction_reasons.append(
            "Extraction engine requires administrator review."
        )

    # -------------------------------------------------
    # 3. Financial reconciliation
    # -------------------------------------------------

    source_total_reconciled = (
        finance.get("source_total_reconciled") is True
    )

    if not source_total_reconciled:
        posting_reasons.append(
            "Source line totals have not been independently "
            "reconciled to the printed invoice total."
        )

    if finance.get("issues"):
        posting_reasons.append(
            "Financial reconciliation contains discrepancies."
        )

    if finance.get("requires_review") is True:
        posting_reasons.append(
            "Financial reconciliation still requires review."
        )

    # -------------------------------------------------
    # 4. VAT and tax review
    # -------------------------------------------------

    # Arithmetic agreement is not legal tax confirmation.
    tax_arithmetic_verified = (
        finance.get("tax_calculation_verified") is True
    )

    if not tax_arithmetic_verified:
        tax_reasons.append(
            "VAT arithmetic is unverified or contradicted."
        )

    if review.get("tax_treatment_confirmed") is not True:
        tax_reasons.append(
            "An authorized reviewer has not confirmed "
            "the applicable tax treatment."
        )

    tax_review_passed = not tax_reasons

    if extraction_reasons:
        posting_reasons.append(
            "Extraction has unresolved material issues."
        )

    if not tax_review_passed:
        posting_reasons.append(
            "Tax review has not passed."
        )

    # -------------------------------------------------
    # 5. Dates and currency
    # -------------------------------------------------

    issue_date = _calendar_date(
        invoice.get("issue_date")
    )

    due_date = _calendar_date(
        invoice.get("due_date")
    )

    if issue_date is None:
        posting_reasons.append(
            "Issue date is not a verified calendar date."
        )

    if due_date is None:
        posting_reasons.append(
            "A reviewed calendar due date is required "
            "by the current invoice system."
        )

    elif issue_date is not None and due_date < issue_date:
        posting_reasons.append(
            "Due date is earlier than issue date."
        )

    if str(
        invoice.get("currency") or ""
    ).strip().upper() != "AED":
        posting_reasons.append(
            "Only AED invoices are eligible "
            "for the current AED ledger."
        )

    # -------------------------------------------------
    # 6. Existing invoice validation
    # -------------------------------------------------

    if validation.get("is_valid") is not True:
        posting_reasons.append(
            "Existing invoice_validator.validate_invoice() "
            "has not passed."
        )

    validator_errors = validation.get("errors") or []
    validator_warnings = validation.get("warnings") or []

    if (
        not isinstance(validator_errors, list)
        or not isinstance(validator_warnings, list)
    ):
        posting_reasons.append(
            "Validator returned an invalid "
            "errors/warnings structure."
        )

        validator_errors = [
            "Invalid validation result"
        ]
        validator_warnings = []

    if validator_errors:
        posting_reasons.append(
            "Validator reported blocking errors."
        )

    # -------------------------------------------------
    # 7. Administrator approval record
    # -------------------------------------------------

    approved_record = (
        review.get("status") == "approved"
        and _present(review.get("reviewer_id"))
        and _present(review.get("approved_at"))
    )

    if not approved_record:
        posting_reasons.append(
            "A persisted, authorized administrator "
            "approval record is required."
        )

    else:
        try:
            datetime.fromisoformat(
                str(
                    review["approved_at"]
                ).replace("Z", "+00:00")
            )

        except (ValueError, TypeError):
            posting_reasons.append(
                "Administrator approval timestamp is invalid."
            )

    # -------------------------------------------------
    # 8. Validator warning acknowledgments
    # -------------------------------------------------

    acknowledged = (
        review.get("acknowledged_warnings") or []
    )

    if not isinstance(
        acknowledged,
        (list, tuple, set),
    ):
        acknowledged = []

    missing_acknowledgments = [
        str(warning)
        for warning in validator_warnings
        if str(warning) not in acknowledged
    ]

    if missing_acknowledgments:
        posting_reasons.append(
            "Validator warnings must be explicitly "
            "acknowledged by the reviewer."
        )

    # -------------------------------------------------
    # 9. Duplicate invoice check
    # -------------------------------------------------

    duplicate_status = str(
        duplicate_check.get("status") or "not_checked"
    ).lower()

    if duplicate_status in BLOCKING_DUPLICATE_STATUSES:
        posting_reasons.append(
            "Duplicate invoice conflict requires resolution."
        )

    elif duplicate_status not in CLEAR_DUPLICATE_STATUSES:
        posting_reasons.append(
            "A trusted database duplicate check "
            "must pass before posting."
        )

    # -------------------------------------------------
    # 10. Final posting eligibility
    # -------------------------------------------------

    posting_reasons = _unique(posting_reasons)

    ready_for_posting = not posting_reasons

    # -------------------------------------------------
    # 11. Collections eligibility
    # -------------------------------------------------

    if not ready_for_posting:
        collections_reasons.append(
            "Invoice is not eligible for posting."
        )

    if due_date is None:
        collections_reasons.append(
            "Collections scheduling requires "
            "a verified calendar due date."
        )

    if collections.get(
        "recipient_verified"
    ) is not True:
        collections_reasons.append(
            "A verified collections recipient is required."
        )

    if collections.get(
        "account_status"
    ) not in {"active", "open"}:
        collections_reasons.append(
            "Receivable must be active/open and "
            "undisputed for collections."
        )

    if collections.get("disputed") is not False:
        collections_reasons.append(
            "Dispute status must be verified as not disputed."
        )

    collections_reasons = _unique(
        collections_reasons
    )

    ready_for_collections = not collections_reasons

    # -------------------------------------------------
    # 12. Return policy evaluation
    # -------------------------------------------------

    return {
        "policy_version": "phase2-v1",

        "extraction_status": (
            "review_required"
            if extraction_reasons
            else "candidate_complete"
        ),

        "financial_status": (
            "discrepancy"
            if (
                finance.get("issues")
                or finance.get(
                    "source_total_reconciled"
                ) is False
            )
            else (
                "source_total_reconciled"
                if source_total_reconciled
                else "unverified"
            )
        ),

        "tax_status": (
            "review_passed"
            if tax_review_passed
            else "unresolved"
        ),

        "tax_arithmetic_verified": (
            tax_arithmetic_verified
        ),

        "tax_review_passed": tax_review_passed,

        "ready_for_review": True,

        "ready_for_posting": ready_for_posting,

        "ready_for_collections": ready_for_collections,

        "manual_review_required": bool(
            extraction_reasons
            or posting_reasons
        ),

        "reasons": {
            "extraction": _unique(
                extraction_reasons
            ),
            "tax": _unique(
                tax_reasons
            ),
            "posting": posting_reasons,
            "collections": collections_reasons,
        },

        "note": (
            "Eligibility assessment only. This policy "
            "does not approve records, post invoices, "
            "authorize users, or send collection notices."
        ),
    }
