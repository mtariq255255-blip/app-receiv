
"""ReceivAI UAE - request/response contracts for administrator-generated invoices.

A separate manual-generation path; it does not touch uploaded-document evidence.
Drafts can be incomplete. Finalization must pass FinalizableInvoiceInput plus
server-side Decimal calculations, duplicate checks and a database transaction.
Financial values returned by clients are NEVER trusted as authoritative.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


DocumentType = Literal[
    "tax_invoice",
    "invoice",
    "proforma_invoice",
]

DraftStatus = Literal[
    "draft",
    "finalized",
    "cancelled",
]

WordmarkStyle = Literal[
    "modern",
    "classic",
    "minimal",
]

MAX_ITEMS = 300
MAX_CUSTOM_COLUMNS = 10
MAX_CUSTOM_FIELDS = 20

_EMAIL_RE = re.compile(
    r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
)

_TRN_RE = re.compile(
    r"^[0-9]{15}$"
)

_COLUMN_KEY_RE = re.compile(
    r"^[a-z][a-z0-9_]{0,39}$"
)

_RESERVED_COLUMNS = {
    "description",
    "quantity",
    "unit",
    "unit_price",
    "unit_price_aed",
    "discount",
    "discount_aed",
    "taxable_value",
    "taxable_value_aed",
    "vat_rate",
    "vat_amount",
    "vat_amount_aed",
    "line_total",
    "line_total_aed",
    "currency",
    "amount",
    "total",
    "price",
    "rate",
    "item_number",
}


# =====================================================
# 1. SHARED SCHEMA CONFIGURATION
# =====================================================

class GenerationSchema(BaseModel):
    """Base schema for invoice generation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
    )


# =====================================================
# 2. SELLER AND BUYER INFORMATION
# =====================================================

class InvoicePartyInput(GenerationSchema):
    """Seller or buyer details. Draft fields may be empty."""

    name: str | None = Field(
        default=None,
        max_length=180,
    )

    address: str | None = Field(
        default=None,
        max_length=2000,
    )

    emirate: str | None = Field(
        default=None,
        max_length=80,
    )

    country: str | None = Field(
        default=None,
        max_length=80,
    )

    trn: str | None = Field(
        default=None,
        max_length=30,
    )

    email: str | None = Field(
        default=None,
        max_length=180,
    )

    phone: str | None = Field(
        default=None,
        max_length=50,
    )

    contact_person: str | None = Field(
        default=None,
        max_length=150,
    )


# =====================================================
# 3. INVOICE HEADER INFORMATION
# =====================================================

class InvoiceHeaderInput(GenerationSchema):
    """Invoice metadata for the AED generation workflow."""

    document_type: DocumentType = "tax_invoice"

    invoice_number: str | None = Field(
        default=None,
        max_length=100,
    )

    issue_date: date | None = None

    supply_date: date | None = None

    due_date: date | None = None

    payment_terms: str | None = Field(
        default=None,
        max_length=300,
    )

    place_of_supply: str | None = Field(
        default=None,
        max_length=150,
    )

    purchase_order_number: str | None = Field(
        default=None,
        max_length=100,
    )

    reference_number: str | None = Field(
        default=None,
        max_length=100,
    )

    currency: Literal["AED"] = "AED"


# =====================================================
# 4. TEXT-BASED COMPANY LOGO
# =====================================================

class InvoiceWordmarkSettings(GenerationSchema):
    """Company logo rendered from text, not an image."""

    style: WordmarkStyle = "modern"

    accent_color: str = Field(
        default="#2463D4",
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )

    font_size_pt: int = Field(
        default=24,
        ge=14,
        le=40,
    )

    uppercase: bool = True

    subtitle: str | None = Field(
        default=None,
        max_length=120,
    )

    show_accent_line: bool = True


# =====================================================
# 5. CUSTOM FIELDS AND COLUMNS
# =====================================================

class InvoiceCustomField(GenerationSchema):
    """Additional non-financial invoice information."""

    label: str = Field(
        min_length=1,
        max_length=80,
    )

    value: str = Field(
        default="",
        max_length=500,
    )

    show_on_pdf: bool = True

    sort_order: int = Field(
        default=0,
        ge=0,
        le=1000,
    )


class InvoiceCustomColumn(GenerationSchema):
    """User-defined column for the invoice items table."""

    key: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    label: str = Field(
        min_length=1,
        max_length=60,
    )

    show_on_pdf: bool = True

    sort_order: int = Field(
        default=0,
        ge=0,
        le=1000,
    )

    @field_validator("key")
    @classmethod
    def reject_reserved_column_names(
        cls,
        value: str,
    ) -> str:

        if (
            not _COLUMN_KEY_RE.fullmatch(value)
            or value in _RESERVED_COLUMNS
        ):
            raise ValueError(
                "Custom column key is invalid or reserved."
            )

        return value


# =====================================================
# 6. DYNAMIC INVOICE LINE ITEMS
# =====================================================

class InvoiceLineItemInput(GenerationSchema):
    """Editable AED invoice line item.

    Uses tax-exclusive unit pricing.

    Totals are calculated by the backend rather than
    accepted from user-supplied values.

    Drafts may have missing quantity, price, or VAT.
    """

    client_id: str | None = Field(
        default=None,
        max_length=80,
    )

    description: str | None = Field(
        default=None,
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

    discount_aed: Decimal = Field(
        default=Decimal("0.00"),
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

    sort_order: int = Field(
        default=0,
        ge=0,
        le=100000,
    )

    custom_values: dict[str, str] = Field(
        default_factory=dict,
        max_length=MAX_CUSTOM_COLUMNS,
    )

    custom_fields: list[InvoiceCustomField] = Field(
        default_factory=list,
        max_length=MAX_CUSTOM_FIELDS,
    )

    @field_validator(
        "quantity",
        "unit_price_aed",
        "discount_aed",
        "vat_rate",
        mode="before",
    )
    @classmethod
    def prevent_float_money(
        cls,
        value: object,
    ) -> object:

        if isinstance(value, (bool, float)):
            raise ValueError(
                "Use a decimal string for exact invoice "
                "numbers, not a float."
            )

        return value

    @field_validator("custom_values")
    @classmethod
    def validate_custom_values(
        cls,
        values: dict[str, str],
    ) -> dict[str, str]:

        for key, value in values.items():

            if (
                not _COLUMN_KEY_RE.fullmatch(key)
                or key in _RESERVED_COLUMNS
            ):
                raise ValueError(
                    f"Invalid custom column key: {key!r}."
                )

            if (
                not isinstance(value, str)
                or len(value) > 500
            ):
                raise ValueError(
                    "Each custom column value must be "
                    "text up to 500 characters."
                )

        return values


# =====================================================
# 7. BANK AND PAYMENT INFORMATION
# =====================================================

class InvoiceBankDetails(GenerationSchema):
    """Optional bank information for the PDF invoice."""

    account_name: str | None = Field(
        default=None,
        max_length=180,
    )

    bank_name: str | None = Field(
        default=None,
        max_length=180,
    )

    iban: str | None = Field(
        default=None,
        max_length=50,
    )

    swift_code: str | None = Field(
        default=None,
        max_length=20,
    )

    payment_instructions: str | None = Field(
        default=None,
        max_length=1000,
    )


# =====================================================
# 8. COMPLETE INVOICE FORM DATA
# =====================================================

class InvoiceGenerationInput(GenerationSchema):
    """Editable invoice data for drafts and previews."""

    seller: InvoicePartyInput = Field(
        default_factory=InvoicePartyInput,
    )

    buyer: InvoicePartyInput = Field(
        default_factory=InvoicePartyInput,
    )

    invoice: InvoiceHeaderInput = Field(
        default_factory=InvoiceHeaderInput,
    )

    items: list[InvoiceLineItemInput] = Field(
        default_factory=list,
        max_length=MAX_ITEMS,
    )

    wordmark: InvoiceWordmarkSettings = Field(
        default_factory=InvoiceWordmarkSettings,
    )

    custom_columns: list[InvoiceCustomColumn] = Field(
        default_factory=list,
        max_length=MAX_CUSTOM_COLUMNS,
    )

    custom_fields: list[InvoiceCustomField] = Field(
        default_factory=list,
        max_length=MAX_CUSTOM_FIELDS,
    )

    bank_details: InvoiceBankDetails = Field(
        default_factory=InvoiceBankDetails,
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )

    declaration_text: str | None = Field(
        default=None,
        max_length=2000,
    )

    footer_text: str | None = Field(
        default=None,
        max_length=500,
    )

    @model_validator(mode="after")
    def verify_custom_column_references(
        self,
    ) -> "InvoiceGenerationInput":

        keys = [
            column.key
            for column in self.custom_columns
        ]

        if len(set(keys)) != len(keys):
            raise ValueError(
                "Custom column keys must be unique."
            )

        known = set(keys)

        for row_number, item in enumerate(
            self.items,
            start=1,
        ):
            unknown = set(item.custom_values) - known

            if unknown:
                raise ValueError(
                    f"Line {row_number} refers to "
                    "undefined custom columns: "
                    + ", ".join(sorted(unknown))
                )

        return self


# =====================================================
# 9. FINALIZATION VALIDATION
# =====================================================

class FinalizableInvoiceInput(InvoiceGenerationInput):
    """Completeness validation before finalization.

    The service must still run deterministic financial
    calculations, invoice-number checks, and database
    transaction controls.
    """

    @model_validator(mode="after")
    def require_ready_invoice(
        self,
    ) -> "FinalizableInvoiceInput":

        if self.invoice.document_type == "proforma_invoice":
            raise ValueError(
                "Proforma invoices cannot enter the "
                "receivables ledger as finalized invoices."
            )

        if not self.seller.name or not self.seller.name.strip():
            raise ValueError(
                "Seller company name is required."
            )

        if not self.buyer.name or not self.buyer.name.strip():
            raise ValueError(
                "Customer name is required."
            )

        if (
            self.invoice.document_type == "tax_invoice"
            and not self.seller.trn
        ):
            raise ValueError(
                "Seller TRN is required for a Tax Invoice."
            )

        if (
            self.seller.trn
            and not _TRN_RE.fullmatch(
                self.seller.trn.replace(" ", "").replace("-", "")
            )
        ):
            raise ValueError(
                "Seller TRN must contain 15 digits "
                "when provided."
            )

        if (
            self.buyer.trn
            and not _TRN_RE.fullmatch(
                self.buyer.trn.replace(" ", "").replace("-", "")
            )
        ):
            raise ValueError(
                "Buyer TRN must contain 15 digits "
                "when provided."
            )

        for party in (self.seller, self.buyer):
            if (
                party.email
                and not _EMAIL_RE.fullmatch(party.email)
            ):
                raise ValueError(
                    "A supplied company email address is invalid."
                )

        if (
            self.invoice.issue_date is None
            or self.invoice.due_date is None
        ):
            raise ValueError(
                "Issue date and due date are required "
                "before finalization."
            )

        if self.invoice.due_date < self.invoice.issue_date:
            raise ValueError(
                "Due date cannot precede the issue date."
            )

        if not self.items:
            raise ValueError(
                "At least one invoice line item is required."
            )

        for index, item in enumerate(
            self.items,
            start=1,
        ):
            if (
                not item.description
                or not item.description.strip()
            ):
                raise ValueError(
                    f"Line {index}: description is required."
                )

            if (
                item.quantity is None
                or item.unit_price_aed is None
            ):
                raise ValueError(
                    f"Line {index}: quantity and unit "
                    "price are required."
                )

            if item.vat_rate is None:
                raise ValueError(
                    f"Line {index}: select the applicable "
                    "VAT rate explicitly."
                )

            if (
                item.discount_aed
                > item.quantity * item.unit_price_aed
            ):
                raise ValueError(
                    f"Line {index}: discount cannot "
                    "exceed gross line value."
                )

        return self


# =====================================================
# 10. DRAFT REQUESTS
# =====================================================

class InvoiceDraftCreate(InvoiceGenerationInput):
    """Create an invoice draft with incomplete data."""

    draft_title: str | None = Field(
        default=None,
        max_length=120,
    )


class InvoiceDraftUpdate(InvoiceDraftCreate):
    """Replace a draft snapshot with version checking."""

    expected_version: int = Field(
        ge=1,
    )


# =====================================================
# 11. PREVIEW AND FINALIZATION REQUESTS
# =====================================================

class InvoicePreviewRequest(InvoiceGenerationInput):
    """Preview an invoice before finalization."""

    watermark: Literal["DRAFT"] = "DRAFT"


class InvoiceFinalizeRequest(GenerationSchema):
    """Finalize a stored draft.

    The backend loads draft data and calculates totals.
    Totals are not accepted from the finalize request.
    """

    expected_version: int = Field(
        ge=1,
    )

    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
    )


# =====================================================
# 12. FINANCIAL CALCULATION RESPONSES
# =====================================================

class InvoiceLineCalculation(GenerationSchema):
    """Backend-calculated financial values for one item."""

    description: str

    gross_value_aed: Decimal | None = None

    discount_aed: Decimal | None = None

    taxable_value_aed: Decimal | None = None

    vat_amount_aed: Decimal | None = None

    line_total_aed: Decimal | None = None


class InvoiceFinancialSummary(GenerationSchema):
    """Backend-calculated invoice totals."""

    currency: Literal["AED"] = "AED"

    subtotal_aed: Decimal | None = None

    discount_aed: Decimal | None = None

    vat_amount_aed: Decimal | None = None

    total_amount_aed: Decimal | None = None

    line_items: list[InvoiceLineCalculation] = Field(
        default_factory=list,
    )


class InvoiceGenerationValidationResponse(GenerationSchema):
    """Result of server-side invoice validation."""

    is_valid: bool

    errors: list[str] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    calculated: InvoiceFinancialSummary | None = None


# =====================================================
# 13. DRAFT API RESPONSES
# =====================================================

class InvoiceDraftResponse(GenerationSchema):
    """Stored invoice draft returned by the API."""

    id: int = Field(gt=0)

    version: int = Field(ge=1)

    status: DraftStatus

    data: InvoiceGenerationInput

    draft_title: str | None = None

    finalized_invoice_id: int | None = None

    created_at: datetime

    updated_at: datetime


class InvoiceDraftListResponse(GenerationSchema):
    """List of saved invoice drafts."""

    drafts: list[InvoiceDraftResponse] = Field(
        default_factory=list,
    )

    total: int = Field(
        ge=0,
    )


# =====================================================
# 14. FINALIZED INVOICE RESPONSE
# =====================================================

class InvoiceGenerationResponse(GenerationSchema):
    """Response after successful invoice finalization."""

    invoice_id: int = Field(
        gt=0,
    )

    draft_id: int = Field(
        gt=0,
    )

    invoice_number: str = Field(
        min_length=1,
        max_length=100,
    )

    amount_aed: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
    )

    status: Literal[
        "unpaid",
        "overdue",
    ]

    source_type: Literal["manual"] = "manual"

    review_status: Literal["reviewed"] = "reviewed"

    pdf_available: bool

    message: str = (
        "Invoice finalized and added to the Invoice Register."
    )
