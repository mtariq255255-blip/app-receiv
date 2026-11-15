
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# =====================================================
# 1. ADMIN USERS
# =====================================================

class AdminUser(Base):

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    full_name: Mapped[str] = mapped_column(
        String(150)
    )

    email: Mapped[str] = mapped_column(
        String(180),
        unique=True,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(
        Text
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )


# =====================================================
# 2. INVOICES
# =====================================================

class Invoice(Base):

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('pdf', 'docx', 'xlsx', 'xls', 'csv', 'manual', 'demo')",
            name="invoices_source_type_check",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    invoice_number: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True
    )

    customer_name: Mapped[str] = mapped_column(
        String(180),
        index=True
    )

    customer_email: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True
    )

    amount_aed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2)
    )

    issue_date: Mapped[date] = mapped_column(
        Date
    )

    due_date: Mapped[date] = mapped_column(
        Date,
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(20),
        index=True
    )

    source_type: Mapped[str] = mapped_column(
        String(20)
    )

    source_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    extraction_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True
    )

    review_status: Mapped[str] = mapped_column(
        String(20)
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    supplier_name: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True
    )

    supplier_address: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    supplier_emirate: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True
    )

    supplier_trn: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True
    )

    customer_address: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    customer_emirate: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True
    )

    customer_trn: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True
    )

    place_of_supply: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True
    )

    supply_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True
    )

    currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
        default="AED",
        server_default="AED"
    )

    subtotal_aed: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
        default=Decimal("0.00"),
        server_default="0.00"
    )

    discount_aed: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
        default=Decimal("0.00"),
        server_default="0.00"
    )

    vat_amount_aed: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
        default=Decimal("0.00"),
        server_default="0.00"
    )

    total_amount_aed: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
        default=Decimal("0.00"),
        server_default="0.00"
    )

    amount_in_words: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    declaration_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.current_timestamp(),
    )

    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice"
    )

    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="invoice"
    )

    items: Mapped[list["InvoiceItem"]] = relationship(
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class InvoiceItem(Base):

    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        index=True
    )

    invoice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3),
        nullable=True,
        default=Decimal("1"),
        server_default="1"
    )

    unit: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True
    )

    unit_price_aed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False
    )

    discount_aed: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
        default=Decimal("0.00"),
        server_default="0.00"
    )

    taxable_value_aed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False
    )

    vat_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        default=Decimal("5.00"),
        server_default="5.00"
    )

    vat_amount_aed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False
    )

    line_total_aed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        server_default=func.current_timestamp()
    )

    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        back_populates="items"
    )


# =====================================================
# 3. PAYMENTS
# =====================================================

class Payment(Base):

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id")
    )

    amount_aed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2)
    )

    payment_date: Mapped[date] = mapped_column(
        Date
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    invoice: Mapped["Invoice"] = relationship(
        back_populates="payments"
    )


# =====================================================
# 4. INVOICE DOCUMENTS
# =====================================================

class InvoiceDocument(Base):

    __tablename__ = "invoice_documents"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id"),
        nullable=True
    )

    original_filename: Mapped[str] = mapped_column(
        String(255)
    )

    storage_path: Mapped[str] = mapped_column(
        Text
    )

    mime_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    processing_status: Mapped[str] = mapped_column(
        String(30)
    )

    extraction_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # NEW: Stores extracted invoice information before approval.
    # Uses PostgreSQL JSONB for structured AI and CSV extraction data.
    extracted_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )


# =====================================================
# 5. REMINDERS
# =====================================================

class Reminder(Base):

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id")
    )

    channel: Mapped[str] = mapped_column(
        String(30)
    )

    subject: Mapped[str] = mapped_column(
        String(255)
    )

    message: Mapped[str] = mapped_column(
        Text
    )

    approval_status: Mapped[str] = mapped_column(
        String(20),
        index=True
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    invoice: Mapped["Invoice"] = relationship(
        back_populates="reminders"
    )


# =====================================================
# 6. AUDIT LOGS
# =====================================================

class AuditLog(Base):

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"),
        nullable=True
    )

    action: Mapped[str] = mapped_column(
        String(150)
    )

    entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    entity_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True
    )

    details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

# =====================================================
# 7. INVOICE GENERATION - DRAFTS
# =====================================================

class InvoiceDraft(Base):
    """An editable invoice draft, separate from registered receivables.

    The form_data JSONB value contains the form header and display settings.
    Line items are stored in invoice_draft_items instead of duplicated here.
    """

    __tablename__ = "invoice_drafts"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )

    created_by_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    updated_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    draft_title: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default=text("'draft'"),
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    form_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    finalized_invoice_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )

    finalization_key: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    created_by: Mapped["AdminUser"] = relationship(
        "AdminUser",
        foreign_keys=[created_by_id],
    )

    updated_by: Mapped["AdminUser | None"] = relationship(
        "AdminUser",
        foreign_keys=[updated_by_id],
    )

    finalized_invoice: Mapped["Invoice | None"] = relationship(
        "Invoice",
        foreign_keys=[finalized_invoice_id],
    )

    items: Mapped[list["InvoiceDraftItem"]] = relationship(
        "InvoiceDraftItem",
        back_populates="draft",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=lambda: (InvoiceDraftItem.sort_order, InvoiceDraftItem.id),
    )

    generated_document: Mapped["GeneratedInvoiceDocument | None"] = relationship(
        "GeneratedInvoiceDocument",
        back_populates="draft",
        uselist=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'finalized', 'cancelled')",
            name="ck_invoice_drafts_status",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_invoice_drafts_version",
        ),
        CheckConstraint(
            "jsonb_typeof(form_data) = 'object'",
            name="ck_invoice_drafts_form_data",
        ),
        CheckConstraint(
            "(status = 'finalized' "
            "AND finalized_invoice_id IS NOT NULL "
            "AND finalization_key IS NOT NULL) OR "
            "(status IN ('draft', 'cancelled') "
            "AND finalized_invoice_id IS NULL)",
            name="ck_invoice_drafts_finalization",
        ),
        Index(
            "ix_invoice_drafts_created_by_updated",
            created_by_id,
            updated_at.desc(),
        ),
        Index(
            "ix_invoice_drafts_status_updated",
            status,
            updated_at.desc(),
        ),
    )


# =====================================================
# 8. INVOICE GENERATION - DRAFT LINE ITEMS
# =====================================================

class InvoiceDraftItem(Base):
    """Editable invoice line item; incomplete values are valid for drafts."""

    __tablename__ = "invoice_draft_items"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )

    draft_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("invoice_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )

    client_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3),
        nullable=True,
    )

    unit: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    unit_price_aed: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
    )

    discount_aed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00"),
    )

    vat_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    custom_values: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    custom_fields: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    draft: Mapped["InvoiceDraft"] = relationship(
        "InvoiceDraft",
        back_populates="items",
    )

    __table_args__ = (
        CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_invoice_draft_items_quantity",
        ),
        CheckConstraint(
            "unit_price_aed IS NULL OR unit_price_aed >= 0",
            name="ck_invoice_draft_items_unit_price",
        ),
        CheckConstraint(
            "discount_aed >= 0",
            name="ck_invoice_draft_items_discount",
        ),
        CheckConstraint(
            "vat_rate IS NULL OR (vat_rate >= 0 AND vat_rate <= 100)",
            name="ck_invoice_draft_items_vat_rate",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_invoice_draft_items_sort_order",
        ),
        CheckConstraint(
            "jsonb_typeof(custom_values) = 'object'",
            name="ck_invoice_draft_items_custom_values",
        ),
        CheckConstraint(
            "jsonb_typeof(custom_fields) = 'array'",
            name="ck_invoice_draft_items_custom_fields",
        ),
        Index(
            "ix_invoice_draft_items_draft_order",
            draft_id,
            sort_order,
            id,
        ),
    )


# =====================================================
# 9. INVOICE GENERATION - FINAL PDF METADATA
# =====================================================

class GeneratedInvoiceDocument(Base):
    """Private finalized PDF metadata and immutable invoice rendering snapshot."""

    __tablename__ = "generated_invoice_documents"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )

    invoice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    draft_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("invoice_drafts.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    created_by_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    pdf_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    pdf_storage_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    pdf_mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="application/pdf",
        server_default=text("'application/pdf'"),
    )

    pdf_size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    pdf_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    template_version: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="v1",
        server_default=text("'v1'"),
    )

    invoice_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    invoice: Mapped["Invoice"] = relationship("Invoice")

    draft: Mapped["InvoiceDraft"] = relationship(
        "InvoiceDraft",
        back_populates="generated_document",
    )

    created_by: Mapped["AdminUser"] = relationship("AdminUser")

    __table_args__ = (
        CheckConstraint(
            "length(btrim(pdf_filename)) > 0",
            name="ck_generated_invoice_documents_pdf_name",
        ),
        CheckConstraint(
            "length(btrim(pdf_storage_path)) > 0",
            name="ck_generated_invoice_documents_pdf_path",
        ),
        CheckConstraint(
            "pdf_mime_type = 'application/pdf'",
            name="ck_generated_invoice_documents_pdf_mime",
        ),
        CheckConstraint(
            "pdf_size_bytes > 0",
            name="ck_generated_invoice_documents_pdf_size",
        ),
        CheckConstraint(
            "pdf_sha256 ~ '^[a-fA-F0-9]{64}$'",
            name="ck_generated_invoice_documents_pdf_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(invoice_snapshot) = 'object'",
            name="ck_generated_invoice_documents_snapshot",
        ),
    )
