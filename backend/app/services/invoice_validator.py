"""ReceivAI UAE — deterministic invoice validation (privacy-first).

All calculations are local Decimal operations. The validator does NOT infer a
VAT rate, supplier identity, due date, or payment evidence. It distinguishes
source arithmetic from tax-verified totals and never approves incomplete rows.

Backwards-compatible public functions and response keys for existing routes.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

CENT = Decimal("0.01")
QUANTITY_PRECISION = Decimal("0.001")
RATE_PRECISION = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y",
    "%d/%m/%Y %H:%M", "%d %b %Y", "%d %B %Y",
    "%d %b, %Y", "%d %B, %Y", "%Y/%m/%d",
    "%d.%m.%Y", "%Y.%m.%d", "%B %d %Y", "%b %d %Y",
    "%B %d, %Y", "%b %d, %Y",
)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    raw = str(value).strip()
    raw = re.sub(r"^(AED\s*|د\.إ\s*)", "", raw, flags=re.I)
    raw = re.sub(r"(\s*AED|\s*د\.إ)$", "", raw, flags=re.I)
    raw = raw.replace(",", "").strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1].strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", raw):
        return None
    try:
        num = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return num if num.is_finite() else None


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    try:
        return str(value.quantize(CENT, rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def _cent(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_invoice_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    # Remove only ordinal suffixes on day numbers, not arbitrary prose.
    raw = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", raw, flags=re.I)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_invoice_amount(value: Any) -> Decimal | None:
    parsed = _decimal(value)
    return _cent(parsed) if parsed is not None else None


def validate_trn(trn: str | None) -> dict[str, Any]:
    if trn is None or not str(trn).strip():
        return {"value": None, "is_present": False, "is_valid_format": False,
                "message": "Supplier or buyer TRN was not provided."}
    normalized = re.sub(r"[\s-]", "", str(trn).strip())
    valid = len(normalized) == 15 and normalized.isascii() and normalized.isdigit()
    return {"value": normalized, "is_present": True,
            "is_valid_format": valid,
            "message": ("TRN format is valid; official FTA registration was not checked."
                        if valid else "TRN must contain exactly 15 digits.")}


def calculate_invoice_item(item: dict[str, Any]) -> dict[str, Any]:
    """Calculate provable amount(s) even if tax is unknown.

    ``taxable_value_aed`` here means the *potential pre-tax base* assuming
    unit prices are tax exclusive; it must not be treated as a tax determination.
    """
    errors: list[str] = []
    warnings: list[str] = []
    description = str(item.get("description") or "").strip()
    qty = _decimal(item.get("quantity"))
    price = _decimal(item.get("unit_price_aed"))
    raw_discount = item.get("discount_aed")
    discount = _decimal(raw_discount) if raw_discount not in (None, "") else ZERO
    rate = _decimal(item.get("vat_rate"))
    if not description:
        errors.append("Line item description is required.")
    if qty is None or qty <= ZERO:
        errors.append("Line item quantity is missing or invalid.")
    if price is None or price < ZERO:
        errors.append("Line item unit price is missing or invalid.")
    if discount is None or discount < ZERO:
        errors.append("Line item discount is missing or invalid.")
    if rate is None:
        errors.append("Line item VAT rate is missing or invalid; confirm tax treatment.")
    elif rate < ZERO or rate > Decimal("100"):
        errors.append("Line item VAT rate must be between 0 and 100.")
    elif rate not in (Decimal("0"), Decimal("5")):
        warnings.append("VAT rate differs from common UAE 0% or 5%; confirm applicability.")

    for key in ("taxable_value_aed", "vat_amount_aed", "line_total_aed"):
        raw = item.get(key)
        val = _decimal(raw)
        if raw not in (None, "") and val is None:
            errors.append(f"Extracted {key.replace('_', ' ')} is not a valid number.")
        elif val is not None and val < ZERO:
            errors.append(f"Extracted {key.replace('_', ' ')} cannot be negative.")

    extracted = {key: _money(_decimal(item.get(key))) for key in
                 ("discount_aed", "taxable_value_aed", "vat_amount_aed", "line_total_aed")}
    extracted.update({
        "quantity": str(qty.quantize(QUANTITY_PRECISION, rounding=ROUND_HALF_UP)) if qty is not None else None,
        "unit_price_aed": _money(price),
        "vat_rate": str(rate.quantize(RATE_PRECISION)) if rate is not None else None,
    })
    calculated: dict[str, str | None] = {
        "gross_value_aed": None, "discount_aed": _money(discount),
        "taxable_value_aed": None, "vat_amount_aed": None,
        "line_total_aed": None,
    }
    if qty is not None and qty > ZERO and price is not None and price >= ZERO and discount is not None and discount >= ZERO:
        gross = _cent(qty * price)
        calculated["gross_value_aed"] = _money(gross)
        if discount > gross:
            errors.append("Line item discount cannot exceed its gross value.")
        else:
            base = _cent(gross - discount)
            calculated["taxable_value_aed"] = _money(base)
            if rate is None:
                warnings.append("Pre-tax arithmetic is available, but VAT remains unverified.")
            elif ZERO <= rate <= Decimal("100"):
                tax = _cent(base * rate / Decimal("100"))
                line_total = _cent(base + tax)
                calculated["vat_amount_aed"] = _money(tax)
                calculated["line_total_aed"] = _money(line_total)
                for key in ("taxable_value_aed", "vat_amount_aed", "line_total_aed"):
                    observed = _decimal(item.get(key))
                    expected = _decimal(calculated[key])
                    if observed is not None and expected is not None and _cent(observed) != expected:
                        errors.append(f"Calculated {key.replace('_', ' ')} differs from the extracted value.")

    return {
        "is_valid": not errors,
        "description": description,
        "extracted": extracted,
        "calculated": calculated,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def calculate_invoice_totals(items: list[dict[str, Any]], invoice_discount_aed: Any = None) -> dict[str, Any]:
    rows = [calculate_invoice_item(item) for item in items]
    known_base = [_decimal(row["calculated"]["taxable_value_aed"]) for row in rows]
    known_tax = [_decimal(row["calculated"]["vat_amount_aed"]) for row in rows]
    known_totals = [_decimal(row["calculated"]["line_total_aed"]) for row in rows]
    base_complete = bool(rows) and all(x is not None for x in known_base)
    tax_complete = bool(rows) and all(x is not None for x in known_tax)
    total_complete = bool(rows) and all(x is not None for x in known_totals)
    base = _cent(sum((x or ZERO for x in known_base), ZERO)) if base_complete else None
    vat = _cent(sum((x or ZERO for x in known_tax), ZERO)) if tax_complete else None
    total = _cent(sum((x or ZERO for x in known_totals), ZERO)) if total_complete else None
    line_discounts = _cent(sum((_decimal(r["calculated"]["discount_aed"]) or ZERO for r in rows), ZERO))
    invoice_discount = _decimal(invoice_discount_aed) if invoice_discount_aed not in (None, "") else ZERO
    warnings = []
    if invoice_discount is None or invoice_discount < ZERO:
        warnings.append("Invoice-level discount is invalid.")
        invoice_discount = ZERO
        allocation = "invalid_invoice_discount"
    elif invoice_discount and invoice_discount == line_discounts:
        allocation = "included_in_line_discounts"
    elif invoice_discount:
        # A distinct invoice-level discount may change the VAT base.
        # Without an explicit allocation rule, do NOT claim an accurate
        # tax-inclusive computed total by simply subtracting it after VAT.
        allocation = "unresolved_separate_invoice_discount"
        warnings.append("Invoice-level discount treatment is unresolved; confirm its VAT allocation and total.")
        vat = None
        total = None
        tax_complete = False
    else:
        allocation = "line_discounts_only"
    discount_sum = line_discounts + (invoice_discount if invoice_discount and allocation != "included_in_line_discounts" else ZERO)

    # Independent source-line comparison: not tax verification.
    stated_lines = [_decimal(item.get("line_total_aed")) for item in items]
    source_total = _money(_cent(sum(stated_lines, ZERO))) if items and all(x is not None for x in stated_lines) else None
    return {
        "subtotal_aed": _money(base),
        "discount_aed": _money(discount_sum),
        "vat_amount_aed": _money(vat),
        "total_amount_aed": _money(total),
        "invoice_discount_allocation_method": allocation,
        "line_items": rows,
        "warnings": warnings,
        "source_line_total_aed": source_total,
        "tax_calculation_complete": tax_complete,
    }


def validate_invoice(data: dict[str, Any]) -> dict[str, Any]:
    """Validate for administrator review. Never approve an unresolved invoice."""
    errors: list[str] = []
    warnings: list[str] = []
    items = data.get("items") or []
    if not isinstance(items, list):
        errors.append("Line item data is invalid.")
        items = []

    for key, message in (
        ("invoice_number", "Invoice number is required."),
        ("supplier_name", "Supplier name is required."),
        ("customer_name", "Customer name is required."),
    ):
        if not str(data.get(key) or "").strip():
            errors.append(message)
    if data.get("customer_email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(data["customer_email"]).strip()):
        errors.append("Customer email format is invalid.")

    dates: dict[str, Any] = {}
    parsed_dates: dict[str, date | None] = {}
    for key, label in (("issue_date", "Issue date"), ("supply_date", "Supply date"), ("due_date", "Due date")):
        raw = data.get(key)
        parsed = parse_invoice_date(raw)
        parsed_dates[key] = parsed
        dates[key] = {"value": str(raw) if raw not in (None, "") else None,
                      "is_valid": (parsed is not None) if raw not in (None, "") else None}
        if raw not in (None, "") and parsed is None:
            errors.append(f"{label} is not a valid supported calendar date.")
        elif key == "issue_date" and parsed is None:
            errors.append("Issue date is required.")
        elif key == "due_date" and parsed is None:
            errors.append("Due date is required for the current invoice database; resolve payment terms before approval.")
        elif parsed is None:
            warnings.append(f"{label} was not provided.")
    issue_date, supply_date, due_date = (parsed_dates[k] for k in ("issue_date", "supply_date", "due_date"))
    if issue_date and due_date and due_date < issue_date:
        errors.append("Due date cannot be earlier than invoice issue date.")
    if supply_date and issue_date and supply_date < issue_date:
        warnings.append("Supply date is earlier than issue date; confirm it.")
    if supply_date and due_date and supply_date > due_date:
        warnings.append("Supply date is later than due date; confirm it.")

    supplier_trn = validate_trn(data.get("supplier_trn"))
    customer_trn = validate_trn(data.get("customer_trn"))
    for label, result in (("Supplier", supplier_trn), ("Buyer", customer_trn)):
        if result["is_present"] and not result["is_valid_format"]:
            warnings.append(f"{label} TRN must contain 15 digits.")
        elif not result["is_present"]:
            warnings.append(f"{label} TRN was not provided.")
    currency = str(data.get("currency") or "").strip().upper()
    currency_check = {"value": currency or None, "is_present": bool(currency),
                      "is_supported_for_aed_ledger": currency == "AED"}
    if not currency:
        errors.append("Currency is missing. Confirm the invoice currency.")
        warnings.append("Currency is missing. Confirm the invoice currency.")
    elif currency != "AED":
        errors.append("Only AED invoices can be approved into the AED invoice register; foreign-currency conversion is not performed.")
    if not items:
        warnings.append("No line items were provided; the clearly stated invoice total will be used.")

    raw_invoice_discount = data.get("discount_aed")
    invoice_discount = _decimal(raw_invoice_discount) if raw_invoice_discount not in (None, "") else ZERO
    if invoice_discount is None or invoice_discount < ZERO:
        errors.append("Invoice-level discount must be a non-negative number.")
    totals = calculate_invoice_totals(items, raw_invoice_discount)
    expected_subtotal = _decimal(data.get("subtotal_aed"))
    expected_vat = _decimal(data.get("vat_amount_aed"))
    review_amount = _decimal(data.get("amount_aed"))
    expected_total = _decimal(data.get("total_amount_aed")) if data.get("total_amount_aed") is not None else review_amount
    for field in ("subtotal_aed", "vat_amount_aed", "total_amount_aed", "amount_aed"):
        raw = data.get(field)
        value = _decimal(raw)
        if raw not in (None, "") and value is None:
            errors.append(f"{field.replace('_', ' ').capitalize()} is not a valid amount.")
        elif value is not None and value < ZERO:
            errors.append(f"{field.replace('_', ' ').capitalize()} cannot be negative.")
    if expected_total is None or expected_total <= ZERO:
        errors.append("A positive invoice total is required.")
    if review_amount is not None and expected_total is not None and _cent(review_amount) != _cent(expected_total):
        errors.append("Reviewed invoice amount differs from extracted grand total.")

    if not items:
        # Stated fields are not independently calculated. Preserve unknown
        # values as null rather than replacing them with misleading zeroes.
        totals.update({"subtotal_aed": _money(expected_subtotal),
                       "discount_aed": _money(invoice_discount),
                       "vat_amount_aed": _money(expected_vat),
                       "total_amount_aed": _money(expected_total),
                       "invoice_discount_allocation_method": "stated_invoice_totals_no_line_items"})
        if all(x is not None for x in (expected_subtotal, expected_vat, expected_total)):
            stated = _cent(expected_subtotal + expected_vat - (invoice_discount or ZERO))
            if stated != _cent(expected_total):
                errors.append("Stated subtotal, discount, VAT and invoice total do not reconcile.")
        else:
            warnings.append("Invoice totals cannot be independently recalculated without line items.")

    line_errors = [message for row in totals["line_items"] for message in row["errors"]]
    line_warnings = [message for row in totals["line_items"] for message in row["warnings"]]
    errors.extend(line_errors)
    warnings.extend(line_warnings)
    warnings.extend(totals["warnings"])

    comparisons = {}
    for field, expected in (("subtotal_aed", expected_subtotal), ("vat_amount_aed", expected_vat),
                            ("total_amount_aed", expected_total)):
        calculated = _decimal(totals[field])
        matches = None if expected is None or not items or calculated is None else _cent(expected) == calculated
        comparisons[field] = {"extracted": _money(expected), "calculated": totals[field], "matches": matches}
        if matches is False:
            errors.append(f"Calculated {field.replace('_', ' ')} differs from the extracted value.")

    calculated_total = _decimal(totals["total_amount_aed"])
    review_matches = None if not items or review_amount is None or calculated_total is None else _cent(review_amount) == calculated_total
    comparisons["amount_aed"] = {"extracted": _money(review_amount),
                                 "calculated": totals["total_amount_aed"] if items else None,
                                 "matches": review_matches}
    if review_matches is False:
        errors.append("Calculated grand total differs from the reviewed invoice amount.")

    source_lines = _decimal(totals.get("source_line_total_aed"))
    source_matches = None if source_lines is None or expected_total is None else source_lines == _cent(expected_total)
    comparisons["source_line_total_aed"] = {
        "extracted": _money(expected_total),
        "calculated": totals.get("source_line_total_aed"),
        "matches": source_matches,
    }
    if source_matches is False:
        # Where a distinct invoice-level discount is stated, its treatment
        # must be resolved before independent totals can be confirmed.
        if totals["invoice_discount_allocation_method"] == "unresolved_separate_invoice_discount":
            warnings.append("Stated line totals and invoice grand total differ; confirm invoice-level discount allocation.")
        else:
            errors.append("Sum of stated line totals differs from the invoice grand total.")
    if items and not totals["tax_calculation_complete"]:
        warnings.append("Stated line arithmetic can be checked, but VAT and final calculated total remain unresolved.")
    if totals["invoice_discount_allocation_method"] == "unresolved_separate_invoice_discount":
        errors.append("Invoice-level discount VAT treatment is unresolved; confirm allocation before approval.")

    duplicate = data.get("duplicate") or {"status": "not_checked", "message": "Duplicate invoice status has not been checked."}
    if not isinstance(duplicate, dict):
        duplicate = {"status": "ambiguous", "message": "Duplicate-check result is invalid; review required."}
    conflict = duplicate.get("status") in {"same_invoice", "conflicting_number", "duplicate_upload", "duplicate"}
    if conflict:
        errors.append(duplicate.get("message") or "Existing invoice conflict was found.")
    elif duplicate.get("status") == "ambiguous":
        warnings.append(duplicate.get("message") or "Invoice number needs duplicate review.")

    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    return {
        "is_valid": not errors,
        "review_required": bool(errors or warnings or conflict or duplicate.get("status") == "ambiguous"),
        "errors": errors, "warnings": warnings,
        "checks": {
            "dates": dates, "supplier_trn": supplier_trn, "customer_trn": customer_trn,
            "currency": currency_check,
            "line_items": {"count": len(items), "results": totals["line_items"], "is_valid": not line_errors},
            "vat": {"calculated_vat_aed": totals["vat_amount_aed"],
                    "extracted_vat_aed": _money(expected_vat),
                    "matches": comparisons["vat_amount_aed"]["matches"]},
            "totals": comparisons, "duplicate": duplicate,
        },
        "calculated_totals": {key: totals[key] for key in
                              ("subtotal_aed", "discount_aed", "vat_amount_aed",
                               "total_amount_aed", "invoice_discount_allocation_method")},
    }


def validate_extracted_fields(fields: dict) -> dict:
    errors: list[str] = []
    missing = [key for key in ("invoice_number", "customer_name", "amount_aed", "issue_date")
               if fields.get(key) in (None, "")]
    invoice_number = fields.get("invoice_number")
    customer = fields.get("customer_name")
    if invoice_number and len(str(invoice_number).strip()) > 100:
        errors.append("Invoice number exceeds 100 characters.")
    if customer and len(str(customer).strip()) > 200:
        errors.append("Customer name exceeds 200 characters.")
    amount = parse_invoice_amount(fields.get("amount_aed"))
    if fields.get("amount_aed") not in (None, "") and amount is None:
        errors.append("Invoice amount is not a valid number.")
    elif amount is not None and amount <= ZERO:
        errors.append("Invoice amount must be greater than zero.")
    issue_date = parse_invoice_date(fields.get("issue_date"))
    due_date = parse_invoice_date(fields.get("due_date"))
    if fields.get("issue_date") and issue_date is None:
        errors.append("Issue date format is invalid.")
    if fields.get("due_date") and due_date is None:
        errors.append("Due date format is invalid.")
    if issue_date and due_date and due_date < issue_date:
        errors.append("Due date cannot be earlier than issue date.")
    if fields.get("customer_email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(fields["customer_email"]).strip()):
        errors.append("Customer email format is invalid.")
    return {"valid": not errors and not missing, "errors": errors, "missing_fields": missing,
            "normalised": {"amount_aed": _money(amount),
                           "issue_date": issue_date.isoformat() if issue_date else None,
                           "due_date": due_date.isoformat() if due_date else None}}
