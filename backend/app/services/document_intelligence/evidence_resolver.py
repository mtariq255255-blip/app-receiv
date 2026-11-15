
"""ReceivAI UAE - Phase 2 evidence resolver.

Conservatively resolves source-backed invoice field candidates.

Rules:
- Equivalent representations are normalized.
- Conflicting values remain unresolved.
- Missing values are never invented.
- Source evidence is preserved for review.
- Confidence cannot override a genuine conflict.
- Extracted evidence is not automatically verified or approved.

Public contract:
    resolve_fields(candidates) -> dict[str, Any]

Compatible with the existing document_intelligence orchestrator.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")

MONEY_FIELDS = frozenset({
    "subtotal_aed",
    "vat_amount_aed",
    "total_amount_aed",
})

DATE_FIELDS = frozenset({
    "issue_date",
    "due_date",
})

IDENTITY_FIELDS = frozenset({
    "supplier_name",
    "customer_name",
})

TRN_FIELDS = frozenset({
    "supplier_trn",
    "customer_trn",
})

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d %b, %Y",
    "%d %B, %Y",
    "%Y/%m/%d",
)


def _clean(value: Any) -> str:
    """Normalize whitespace without destroying source meaning."""

    if value is None:
        return ""

    return " ".join(str(value).strip().split())


def _normalize_money(value: Any) -> str | None:
    """Normalize a monetary value using exact Decimal arithmetic.

    Examples:
        AED 3,675.00 -> 3675.00
        3675         -> 3675.00
        3,675.0      -> 3675.00

    This function does not perform currency conversion.
    """

    if value is None or isinstance(value, bool):
        return None

    raw = _clean(value)

    if not raw:
        return None

    # Only remove the expected AED currency indicator.
    raw = re.sub(
        r"(?i)\bAED\b|د\.إ",
        "",
        raw,
    ).strip()

    raw = raw.replace(",", "").strip()

    # Do not silently parse arbitrary text as money.
    if not re.fullmatch(
        r"[+-]?\d+(?:\.\d+)?",
        raw,
    ):
        return None

    try:
        amount = Decimal(raw)

        if not amount.is_finite():
            return None

        # Amounts for these invoice fields must not be negative.
        if amount < 0:
            return None

        return str(
            amount.quantize(
                CENT,
                rounding=ROUND_HALF_UP,
            )
        )

    except (InvalidOperation, ValueError):
        return None


def _normalize_date(value: Any) -> str | None:
    """Normalize supported invoice dates to YYYY-MM-DD."""

    raw = _clean(value)

    if not raw:
        return None

    raw = re.sub(
        r"\b(\d{1,2})(?:st|nd|rd|th)\b",
        r"\1",
        raw,
        flags=re.I,
    )

    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(
                raw,
                date_format,
            )

            return parsed.date().isoformat()

        except ValueError:
            continue

    # Payment terms are not calendar dates.
    return None


def _normalize_identity(value: Any) -> str | None:
    """Compare party names conservatively.

    Case and repeated spaces are ignored.

    Different legal suffixes or substantially different names
    are NOT assumed equivalent.
    """

    raw = _clean(value)

    if not raw:
        return None

    return raw.casefold()


def _normalize_trn(value: Any) -> str | None:
    """Normalize UAE TRN formatting without validating registration."""

    raw = re.sub(
        r"[\s-]",
        "",
        _clean(value),
    )

    if not re.fullmatch(r"\d{15}", raw):
        return None

    return raw


def _normalize_value(
    field: str,
    value: Any,
) -> str | None:
    """Return the canonical representation used for comparisons."""

    if field in MONEY_FIELDS:
        return _normalize_money(value)

    if field in DATE_FIELDS:
        return _normalize_date(value)

    if field in TRN_FIELDS:
        return _normalize_trn(value)

    if field == "currency":
        raw = _clean(value).upper()

        if raw in {"AED", "UAE DIRHAM", "UAE DIRHAMS"}:
            return "AED"

        return raw if re.fullmatch(r"[A-Z]{3}", raw) else None

    if field in IDENTITY_FIELDS:
        return _normalize_identity(value)

    if field == "invoice_number":
        raw = _clean(value)
        return raw.casefold() if raw else None

    raw = _clean(value)

    return raw.casefold() if raw else None


def _output_value(
    field: str,
    candidate: dict[str, Any],
    normalized: str,
) -> str:
    """Choose a consistent output without inventing information."""

    if field in MONEY_FIELDS:
        return normalized

    if field in DATE_FIELDS:
        return normalized

    if field in TRN_FIELDS:
        return normalized

    if field == "currency":
        return normalized

    # Preserve original casing for names, terms and identifiers.
    return _clean(candidate["value"])


def _source_type(candidate: dict[str, Any]) -> str:
    """Classify evidence origin for audit and review."""

    method = str(
        candidate.get("method") or ""
    ).lower()

    if method.startswith("native"):
        return "native_parser"

    if method.startswith("docling"):
        return "docling"

    if method.startswith("manual"):
        return "manual"

    return "other"


def _safe_confidence(value: Any) -> float | None:
    """Validate confidence metadata; never use it to hide conflicts."""

    if isinstance(value, bool) or value is None:
        return None

    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None

    if not 0 <= result <= 1:
        return None

    return result


def _prepare_evidence(
    field: str,
    candidate: dict[str, Any],
    normalized: str | None,
) -> dict[str, Any]:
    """Preserve source evidence in a JSON-compatible structure."""

    return {
        "field": field,
        "value": candidate.get("value"),
        "normalized_value": normalized,
        "source_text": candidate.get("source_text"),
        "source_page": candidate.get("source_page"),
        "bbox": candidate.get("bbox"),
        "method": candidate.get("method"),
        "source_type": _source_type(candidate),
        "confidence": _safe_confidence(
            candidate.get("confidence")
        ),
        "valid": normalized is not None,
    }


def resolve_fields(
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Resolve invoice field candidates conservatively.

    Returns existing orchestrator keys:
        fields
        field_evidence
        unresolved_fields

    Adds:
        field_status
        field_conflicts
        resolution_notes

    Status values:
        extracted_unverified
        corroborated
        conflicting
        invalid

    A field with no candidate is not assigned here.
    Missing/not-stated classification requires document-level
    context from the orchestrator or review policy.
    """

    fields: dict[str, Any] = {}

    field_evidence: dict[
        str, list[dict[str, Any]]
    ] = {}

    field_status: dict[str, str] = {}

    field_conflicts: dict[
        str, list[str]
    ] = {}

    unresolved_fields: list[str] = []

    resolution_notes: list[str] = []

    if not isinstance(candidates, dict):
        raise TypeError(
            "candidates must be a dictionary"
        )

    for field, raw_candidates in candidates.items():

        if not isinstance(raw_candidates, list):
            continue

        usable: list[
            tuple[dict[str, Any], str]
        ] = []

        all_evidence: list[
            dict[str, Any]
        ] = []

        for candidate in raw_candidates:

            if not isinstance(candidate, dict):
                continue

            raw_value = candidate.get("value")

            if raw_value is None:
                continue

            if not _clean(raw_value):
                continue

            normalized = _normalize_value(
                field,
                raw_value,
            )

            all_evidence.append(
                _prepare_evidence(
                    field,
                    candidate,
                    normalized,
                )
            )

            if normalized is not None:
                usable.append(
                    (candidate, normalized)
                )

        if not all_evidence:
            continue

        # Preserve a bounded amount of display evidence.
        # Resolution itself uses all supplied candidates.
        field_evidence[field] = all_evidence[:15]

        if not usable:
            fields[field] = None
            field_status[field] = "invalid"

            unresolved_fields.append(field)

            resolution_notes.append(
                f"{field}: no valid source-backed "
                "candidate could be resolved."
            )

            continue

        # Group equivalent values by canonical representation.
        distinct: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        for candidate, normalized in usable:
            distinct.setdefault(
                normalized,
                [],
            ).append(candidate)

        # A real contradiction must not be resolved using
        # confidence or by choosing the first candidate.
        if len(distinct) > 1:

            fields[field] = None

            field_status[field] = "conflicting"

            unresolved_fields.append(field)

            field_conflicts[field] = list(
                distinct.keys()
            )

            resolution_notes.append(
                f"{field}: conflicting source values "
                "require review."
            )

            continue

        normalized_value = next(iter(distinct))

        supporting_candidates = distinct[
            normalized_value
        ]

        selected_candidate = supporting_candidates[0]

        fields[field] = _output_value(
            field,
            selected_candidate,
            normalized_value,
        )

        # Multiple observations are corroboration, not
        # automatic financial or legal verification.
        sources = {
            _source_type(candidate)
            for candidate in supporting_candidates
        }

        if len(sources) > 1:
            field_status[field] = "corroborated"
        else:
            field_status[field] = "extracted_unverified"

        # If invalid candidates were also found, keep the
        # resolved value but flag them for review.
        invalid_count = sum(
            1
            for evidence in all_evidence
            if not evidence["valid"]
        )

        if invalid_count:
            resolution_notes.append(
                f"{field}: {invalid_count} invalid "
                "candidate(s) were ignored; "
                "review the source evidence."
            )

    return {
        # Backward-compatible keys.
        "fields": fields,
        "field_evidence": field_evidence,
        "unresolved_fields": sorted(
            set(unresolved_fields)
        ),

        # Additional finance-review metadata.
        "field_status": field_status,
        "field_conflicts": field_conflicts,
        "resolution_notes": list(
            dict.fromkeys(resolution_notes)
        ),
    }
