
"""ReceivAI UAE invoice extraction, review and validation schemas.

Supports:
- Existing AED-specific accounting and approval fields
- Original-currency invoice values (AED, USD, etc.)
- Docling-primary reconstructed line items
- PyMuPDF supporting evidence
- Source provenance and unresolved extraction fields

Original-currency values must never be silently copied into AED
accounting fields. Extracted values are not approved values.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


# ---------------------------------------------------------
# Source evidence
# ---------------------------------------------------------

class InvoiceFieldEvidence(BaseModel):
    """Evidence linking an extracted value to its source.

    bbox retains the source coordinate system.
    bbox_top_left is explicitly normalized for PDF display.
    """

    model_config = ConfigDict(extra="ignore")

    source_text: str | None = Field(
        default=None,
        max_length=2000,
    )
    source_page: int | None = Field(default=None, ge=1)
    source_worksheet: str | None = Field(
        default=None,
        max_length=200,
    )
    source_table: int | None = Field(default=None, ge=1)
    source_row: int | None = Field(default=None, ge=0)
    source_rows: list[int] = Field(default_factory=list)

    bbox: tuple[float, float, float, float] | None = None
    bbox_top_left: tuple[float, float, float, float] | None = None
    bbox_origin: str | None = Field(
        default=None,
        max_length=30,
    )

    extraction_method: str | None = Field(
        default=None,
        max_length=80,
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


# ---------------------------------------------------------
# Existing AED invoice item — retained for compatibility
# ---------------------------------------------------------

class UAEInvoiceItemSchema(BaseModel):
    """AED accounting item used by the legacy UAE workflow."""

    model_config = ConfigDict(extra="ignore")

    description: str = Field(
        min_length=1,
        max_length=500,
    )

    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=14,
        decimal_places=3,
    )

    unit: str | None = Field(
        default=None,
        max_length=40,
    )

    unit_price_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    discount_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    taxable_value_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    vat_rate: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )

    vat_amount_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    line_total_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    source_table: int | None = Field(default=None, ge=1)
    source_row: int | None = Field(default=None, ge=1)

    field_evidence: dict[
        str,
        list[InvoiceFieldEvidence],
    ] = Field(default_factory=dict)

    unresolved_fields: list[str] = Field(default_factory=list)


# ---------------------------------------------------------
# NEW: Source-currency invoice item
# ---------------------------------------------------------

class SourceCurrencyInvoiceItemSchema(BaseModel):
    """One reconstructed item in the document's original currency.

    This represents source evidence, not an AED accounting entry.

    Examples:
        AED 2500.00
        USD 27900.00

    A missing quantity, rate, tax or unit remains None.
    Negative line amounts are permitted for credit notes and
    documented adjustments.
    """

    model_config = ConfigDict(extra="ignore")

    description: str = Field(
        min_length=1,
        max_length=2000,
    )

    currency: str | None = Field(
        default=None,
        max_length=20,
    )

    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=6,
    )

    unit: str | None = Field(
        default=None,
        max_length=80,
    )

    unit_price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=6,
    )

    line_amount: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    discount: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    taxable_value: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    tax_amount: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    tax_rate_text: str | None = Field(
        default=None,
        max_length=100,
    )

    # Auxiliary logistics information must not be confused
    # with the billable quantity.
    container: str | None = Field(
        default=None,
        max_length=100,
    )

    other_quantity_text: str | None = Field(
        default=None,
        max_length=100,
    )

    # Original Docling evidence.
    source_page: int | None = Field(default=None, ge=1)
    source_table: int | None = Field(default=None, ge=1)

    # These indices come from the raw Docling grid and
    # are zero-based, unlike legacy source_row.
    source_rows: list[int] = Field(default_factory=list)

    source_representation: str | None = Field(
        default=None,
        max_length=40,
    )

    source_bbox: tuple[
        float, float, float, float
    ] | None = None

    # Compact supporting evidence, not the entire raw PDF.
    evidence: dict[str, Any] = Field(default_factory=dict)

    unresolved_fields: list[str] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_item_currency(
        cls,
        value: str | None,
    ) -> str | None:
        return value.strip().upper() if value and value.strip() else None


# ---------------------------------------------------------
# NEW: Compact hybrid extraction metadata
# ---------------------------------------------------------

class HybridExtractionSchema(BaseModel):
    """Compact Docling/PyMuPDF processing result.

    Complete raw engine evidence should be stored separately
    when persistence is implemented.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"

    primary_engine: str = "docling"
    supporting_engine: str = "pymupdf"

    currency: str | None = None
    mixed_currency: bool = False

    items: list[SourceCurrencyInvoiceItemSchema] = Field(
        default_factory=list,
    )

    item_count: int = Field(default=0, ge=0)
    table_count: int = Field(default=0, ge=0)
    page_count: int | None = Field(default=None, ge=0)

    warnings: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    field_candidates: dict[str, Any] = Field(default_factory=dict)

    raw_evidence_in_response: bool = False
    requires_review: bool = False

    @field_validator("currency")
    @classmethod
    def normalize_hybrid_currency(
        cls,
        value: str | None,
    ) -> str | None:
        return value.strip().upper() if value and value.strip() else None


# ---------------------------------------------------------
# Main invoice extraction schema
# ---------------------------------------------------------

class UAEInvoiceExtractionSchema(BaseModel):
    """Reviewable extracted invoice, not an approved invoice.

    Existing AED fields remain available.

    New source_* fields preserve amounts in the original
    document currency without performing conversion.
    """

    model_config = ConfigDict(extra="ignore")

    # -----------------------------------------------------
    # Document identification
    # -----------------------------------------------------

    invoice_number: str | None = Field(
        default=None,
        max_length=100,
    )

    invoice_type: str | None = Field(
        default=None,
        max_length=100,
    )

    # Tax invoice, proforma invoice, commercial invoice,
    # credit note, etc. This is an extraction classification,
    # not an accounting authorization.
    document_type: str | None = Field(
        default=None,
        max_length=100,
    )

    # -----------------------------------------------------
    # Supplier information
    # -----------------------------------------------------

    supplier_name: str | None = Field(
        default=None,
        max_length=180,
    )

    supplier_address: str | None = None

    supplier_emirate: str | None = Field(
        default=None,
        max_length=80,
    )

    supplier_country: str | None = Field(
        default=None,
        max_length=100,
    )

    supplier_trn: str | None = Field(
        default=None,
        max_length=30,
    )

    # -----------------------------------------------------
    # Customer information
    # -----------------------------------------------------

    customer_name: str | None = Field(
        default=None,
        max_length=180,
    )

    customer_address: str | None = None

    customer_email: str | None = Field(
        default=None,
        max_length=180,
    )

    customer_emirate: str | None = Field(
        default=None,
        max_length=80,
    )

    customer_country: str | None = Field(
        default=None,
        max_length=100,
    )

    customer_trn: str | None = Field(
        default=None,
        max_length=30,
    )

    # -----------------------------------------------------
    # Dates and terms
    # -----------------------------------------------------

    issue_date: date | None = None
    supply_date: date | None = None
    due_date: date | None = None

    place_of_supply: str | None = Field(
        default=None,
        max_length=150,
    )

    payment_terms: str | None = Field(
        default=None,
        max_length=500,
    )

    # -----------------------------------------------------
    # Currency
    # -----------------------------------------------------

    # Currency of the original document.
    # No conversion is implied.
    currency: str | None = Field(
        default=None,
        max_length=20,
    )

    # -----------------------------------------------------
    # Existing AED-specific accounting rows
    # -----------------------------------------------------

    items: list[UAEInvoiceItemSchema] = Field(
        default_factory=list,
    )

    subtotal_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    subtotal_before_discount_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    discount_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    vat_amount_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    total_amount_aed: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    # -----------------------------------------------------
    # NEW: Original-currency financial values
    # -----------------------------------------------------

    source_items: list[SourceCurrencyInvoiceItemSchema] = Field(
        default_factory=list,
    )

    source_subtotal: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    source_subtotal_before_discount: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    source_discount: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    source_tax_amount: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    source_total_amount: Decimal | None = Field(
        default=None,
        max_digits=18,
        decimal_places=4,
    )

    # None means the check has not been independently completed.
    source_totals_reconciled: bool | None = None

    # -----------------------------------------------------
    # Document statements
    # -----------------------------------------------------

    amount_in_words: str | None = None
    declaration_text: str | None = None

    # -----------------------------------------------------
    # Confidence and review
    # -----------------------------------------------------

    extraction_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    extraction_notes: list[str] = Field(
        default_factory=list,
    )

    missing_fields: list[str] = Field(
        default_factory=list,
    )

    field_evidence: dict[
        str,
        list[InvoiceFieldEvidence],
    ] = Field(default_factory=dict)

    unresolved_fields: list[str] = Field(
        default_factory=list,
    )

    extraction_method: str | None = Field(
        default=None,
        max_length=80,
    )

    parser_version: str | None = Field(
        default=None,
        max_length=100,
    )

    # An optional compact hybrid result. The worker can
    # currently also return this at the document level.
    hybrid_extraction: HybridExtractionSchema | None = None

    document_classification: Literal[
        "single_invoice",
        "multiple_invoices",
        "invoice_line_items",
        "invoice_register",
        "unknown",
    ] = "unknown"

    source_filename: str | None = None
    source_worksheet: str | None = None

    source_table: int | None = Field(
        default=None,
        ge=1,
    )

    source_page: int | None = None
    source_row: int | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(
        cls,
        value: str | None,
    ) -> str | None:
        return value.strip().upper() if value and value.strip() else None


# ---------------------------------------------------------
# Existing review and API response schemas
# ---------------------------------------------------------

class UAEInvoiceReviewSchema(UAEInvoiceExtractionSchema):
    """Invoice data reviewed by an administrator."""

    review_notes: str | None = None


class UAEInvoiceResponseSchema(UAEInvoiceExtractionSchema):
    """Invoice response returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------
# Existing validation result schemas
# ---------------------------------------------------------

class TRNValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None
    is_present: bool
    is_valid_format: bool
    message: str


class FieldValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: str | None = None
    is_valid: bool
    message: str


class InvoiceItemCalculationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    description: str
    extracted: dict[str, str | None]
    calculated: dict[str, str | None]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class InvoiceTotalsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtotal_aed: Decimal | None
    discount_aed: Decimal | None
    vat_amount_aed: Decimal | None
    total_amount_aed: Decimal | None
    invoice_discount_allocation_method: str


class CompleteInvoiceValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    review_required: bool
    errors: list[str]
    warnings: list[str]
    checks: dict[str, Any]
    calculated_totals: InvoiceTotalsResult
