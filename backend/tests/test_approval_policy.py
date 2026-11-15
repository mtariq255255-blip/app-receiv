
"""Standalone financial approval policy tests for ReceivAI UAE.

Run using backend/.venv.
No Docling installation is required.
"""

from copy import deepcopy

from app.services.document_intelligence.approval_policy import (
    evaluate_approval_policy,
)


def nova():
    """Return a synthetic Nova invoice interpretation."""

    return {
        "invoice": {
            "invoice_number": "INV-2026-001",
            "supplier_name": "Nova Test Services LLC",
            "customer_name": "Example Pearl Ventures LLC",
            "issue_date": "2026-11-12",
            "due_date": "2026-12-12",
            "currency": "AED",
            "total_amount_aed": "3675.00",
            "items": [
                {
                    "description": "Services",
                    "line_total_aed": "3675.00",
                }
            ],
        },
        "unresolved_fields": [],
        "field_conflicts": {},
        "financial_reconciliation": {
            "source_total_reconciled": True,
            "tax_calculation_verified": True,
            "issues": [],
            "warnings": [],
            "requires_review": False,
        },
        "manual_review_required": False,
    }


def approved():
    """Return a simulated trusted administrator approval."""

    return {
        "status": "approved",
        "reviewer_id": "admin1",
        "approved_at": "2026-11-12T15:00:00+04:00",
        "tax_treatment_confirmed": True,
        "acknowledged_warnings": [],
    }


def valid():
    """Return a simulated successful invoice validation."""

    return {
        "is_valid": True,
        "review_required": False,
        "errors": [],
        "warnings": [],
    }


def evaluate(data=None, **kwargs):
    return evaluate_approval_policy(
        nova() if data is None else data,
        **kwargs,
    )


def test_clean_extraction_does_not_auto_approve():
    result = evaluate()

    assert result["ready_for_review"] is True
    assert result["ready_for_posting"] is False
    assert result["ready_for_collections"] is False


def test_explicit_trusted_signoffs_can_make_eligible():
    result = evaluate(
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
        collections={
            "recipient_verified": True,
            "account_status": "open",
            "disputed": False,
        },
    )

    assert result["ready_for_posting"] is True
    assert result["ready_for_collections"] is True


def test_unknown_vat_blocks_tax_and_posting():
    data = nova()

    data["unresolved_fields"] = [
        "items.vat_rate",
    ]

    data["financial_reconciliation"][
        "tax_calculation_verified"
    ] = None

    result = evaluate(
        data,
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["tax_review_passed"] is False
    assert result["ready_for_posting"] is False


def test_due_on_receipt_is_not_a_calendar_date():
    data = nova()

    data["invoice"]["due_date"] = None
    data["invoice"]["payment_terms"] = "Upon receipt"

    result = evaluate(
        data,
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is False
    assert result["ready_for_collections"] is False


def test_conflict_cannot_be_approved():
    data = nova()

    data["field_conflicts"] = {
        "supplier_name": [
            "Alpha LLC",
            "Beta LLC",
        ]
    }

    result = evaluate(
        data,
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is False


def test_mismatched_total_is_blocking():
    data = nova()

    data["financial_reconciliation"][
        "source_total_reconciled"
    ] = False

    result = evaluate(
        data,
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is False
    assert result["financial_status"] == "discrepancy"


def test_duplicate_check_must_be_trusted_and_clear():
    result = evaluate(
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "not_checked",
        },
    )

    assert result["ready_for_posting"] is False

    result = evaluate(
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "duplicate",
        },
    )

    assert result["ready_for_posting"] is False


def test_unacknowledged_validator_warnings_block_posting():
    validation = valid()

    validation["warnings"] = [
        "Supplier TRN was not provided.",
    ]

    result = evaluate(
        validation=validation,
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is False

    review = approved()

    review["acknowledged_warnings"] = (
        validation["warnings"]
    )

    result = evaluate(
        validation=validation,
        review=review,
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is True


def test_invalid_amount_and_non_aed_are_blocked():
    data = nova()

    data["invoice"]["total_amount_aed"] = "NaN"

    result = evaluate(
        data,
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is False

    data = nova()

    data["invoice"]["currency"] = "USD"

    result = evaluate(
        data,
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is False


def test_collections_requires_recipient_and_undisputed_account():
    result = evaluate(
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
        collections={
            "recipient_verified": False,
            "account_status": "open",
            "disputed": False,
        },
    )

    assert result["ready_for_posting"] is True
    assert result["ready_for_collections"] is False


def test_item_conflict_blocks_posting():
    data = nova()

    data["item_comparison_status"] = "conflicting"

    result = evaluate(
        data,
        validation=valid(),
        review=approved(),
        duplicate_check={
            "status": "clear",
        },
    )

    assert result["ready_for_posting"] is False
