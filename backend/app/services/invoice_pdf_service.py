
"""ReceivAI UAE: text-only wordmark, tax-invoice PDF renderer.

Public API (used by invoice_generation_service):
    render_invoice_pdf_bytes(snapshot: dict) -> bytes

Snapshot format: {invoice_number, form_data, calculated, ...}.

This module renders locally with ReportLab. It never calls an AI API,
stores files, modifies the database, or renders a raster logo.

The optional DRAFT watermark enables previewing partially filled invoices.

For finalized invoices, all fields and Decimal totals are revalidated
and checked against the server calculation snapshot before rendering.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from reportlab.platypus.doctemplate import LayoutError

from app.schemas.invoice_generation import (
    FinalizableInvoiceInput,
    InvoiceGenerationInput,
    InvoiceFinancialSummary,
)

from app.services.invoice_validator import (
    calculate_invoice_totals,
)


# =====================================================
# 1. PDF CONFIGURATION
# =====================================================

PAGE_WIDTH, PAGE_HEIGHT = A4

MARGIN_X = 32

CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X

MONEY = Decimal("0.01")

NAVY = colors.HexColor("#163252")

INK = colors.HexColor("#1C2B3A")

MUTED = colors.HexColor("#64748B")

BORDER = colors.HexColor("#DCE5EF")

PALE = colors.HexColor("#F3F7FB")


class InvoicePDFError(ValueError):
    """Invoice snapshot is invalid or cannot be rendered safely."""


# =====================================================
# 2. PDF FONTS
# =====================================================

def _fonts() -> tuple[str, str]:
    """Use local Unicode fonts when installed; never depend on image assets."""

    registered = set(
        pdfmetrics.getRegisteredFontNames()
    )

    if {
        "ReceivAIBody",
        "ReceivAIBold",
    } <= registered:
        return "ReceivAIBody", "ReceivAIBold"

    pairs = [
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        ),
        (
            Path(
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans.ttf"
            ),
            Path(
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans-Bold.ttf"
            ),
        ),
        (
            Path(
                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Regular.ttf"
            ),
            Path(
                "/usr/share/fonts/truetype/liberation2/"
                "LiberationSans-Bold.ttf"
            ),
        ),
    ]

    for regular, bold in pairs:

        if regular.is_file() and bold.is_file():

            pdfmetrics.registerFont(
                TTFont(
                    "ReceivAIBody",
                    str(regular),
                )
            )

            pdfmetrics.registerFont(
                TTFont(
                    "ReceivAIBold",
                    str(bold),
                )
            )

            return "ReceivAIBody", "ReceivAIBold"

    # Built-in fonts support English and basic Latin text.
    return "Helvetica", "Helvetica-Bold"


# =====================================================
# 3. TEXT AND NUMBER HELPERS
# =====================================================

def _text(value: Any) -> str:
    """Escape user text so it cannot become ReportLab markup."""

    return escape(
        str(value) if value is not None else "",
        quote=True,
    ).replace(
        "\n",
        "<br/>",
    )


def _present(
    value: Any,
    *,
    default: str = "-",
) -> str:

    if value not in (None, ""):
        return _text(value)

    return _text(default)


def _decimal(value: Any) -> Decimal | None:

    if value is None or value == "":
        return None

    try:
        number = Decimal(str(value))

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:

        raise InvoicePDFError(
            "A calculated financial value is invalid."
        ) from exc

    if not number.is_finite():
        raise InvoicePDFError(
            "A calculated financial value is not finite."
        )

    return number


def _money(value: Any) -> str:

    parsed = _decimal(value)

    if parsed is None:
        return "-"

    return f"{parsed.quantize(MONEY):,.2f}"


def _quantity(value: Any) -> str:

    parsed = _decimal(value)

    if parsed is None:
        return "-"

    return format(
        parsed.normalize(),
        "f",
    )


def _date(value: Any) -> str:

    if value:
        return value.strftime("%d %b %Y")

    return "-"


def _hex_color(value: str) -> colors.Color:

    try:
        return colors.HexColor(value)

    except (
        ValueError,
        TypeError,
    ) as exc:

        raise InvoicePDFError(
            "Invalid company wordmark accent color."
        ) from exc


# =====================================================
# 4. AMOUNT IN WORDS
# =====================================================

def _amount_words(value: Decimal) -> str:
    """Express a nonnegative AED amount in English Dirhams and Fils."""

    if (
        value < 0
        or value > Decimal("999999999999.99")
    ):
        raise InvoicePDFError(
            "Amount outside supported text range."
        )

    ones = (
        "Zero",
        "One",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
        "Eleven",
        "Twelve",
        "Thirteen",
        "Fourteen",
        "Fifteen",
        "Sixteen",
        "Seventeen",
        "Eighteen",
        "Nineteen",
    )

    tens = (
        "",
        "",
        "Twenty",
        "Thirty",
        "Forty",
        "Fifty",
        "Sixty",
        "Seventy",
        "Eighty",
        "Ninety",
    )

    def under_thousand(n: int) -> str:

        parts: list[str] = []

        if n >= 100:

            parts.append(
                ones[n // 100] + " Hundred"
            )

            n %= 100

        if n >= 20:

            parts.append(
                tens[n // 10]
                + (
                    "-" + ones[n % 10]
                    if n % 10
                    else ""
                )
            )

        elif n > 0:
            parts.append(ones[n])

        return " ".join(parts)

    def int_words(n: int) -> str:

        if n == 0:
            return "Zero"

        groups = (
            (1_000_000_000, "Billion"),
            (1_000_000, "Million"),
            (1_000, "Thousand"),
            (1, ""),
        )

        chunks: list[str] = []

        for divisor, label in groups:

            part, n = divmod(
                n,
                divisor,
            )

            if part:

                chunks.append(
                    " ".join(
                        filter(
                            None,
                            (
                                under_thousand(part),
                                label,
                            ),
                        )
                    )
                )

        return " ".join(chunks)

    fils_total = int(
        (
            value.quantize(MONEY) * 100
        ).to_integral_value()
    )

    dirhams, fils = divmod(
        fils_total,
        100,
    )

    result = (
        int_words(dirhams)
        + (
            " Dirham"
            if dirhams == 1
            else " Dirhams"
        )
    )

    if fils:

        result += (
            " and "
            + int_words(fils)
            + (
                " Fil"
                if fils == 1
                else " Fils"
            )
        )

    return result + " Only"


# =====================================================
# 5. PDF TEXT STYLES
# =====================================================

def _styles(
    normal: str,
    bold: str,
) -> dict[str, ParagraphStyle]:

    def s(
        name: str,
        *,
        size: float = 8.7,
        leading: float = 13,
        color=INK,
        font: str | None = None,
        align=TA_LEFT,
        space_after: float = 0,
    ) -> ParagraphStyle:

        return ParagraphStyle(
            name,
            fontName=font or normal,
            fontSize=size,
            leading=leading,
            textColor=color,
            alignment=align,
            spaceAfter=space_after,
            allowWidows=0,
            allowOrphans=0,
            splitLongWords=True,
        )

    return {
        "body": s(
            "rai_body",
        ),

        "small": s(
            "rai_small",
            size=7.4,
            leading=10.3,
            color=MUTED,
        ),

        "small_bold": s(
            "rai_small_bold",
            size=7.7,
            leading=11,
            font=bold,
        ),

        "heading": s(
            "rai_heading",
            size=8.2,
            leading=12,
            font=bold,
            color=NAVY,
        ),

        "title": s(
            "rai_title",
            size=18,
            leading=22,
            font=bold,
            color=NAVY,
            align=TA_RIGHT,
        ),

        "value": s(
            "rai_value",
            size=9,
            leading=13,
            font=bold,
        ),

        "num": s(
            "rai_num",
            size=7.15,
            leading=10,
            align=TA_RIGHT,
        ),

        "num_bold": s(
            "rai_num_bold",
            size=7.1,
            leading=10,
            font=bold,
            align=TA_RIGHT,
        ),

        "num_center": s(
            "rai_num_center",
            size=7.1,
            leading=10,
            align=TA_CENTER,
        ),

        "tablehead": s(
            "rai_tablehead",
            size=7,
            leading=9,
            font=bold,
            color=colors.white,
            align=TA_CENTER,
        ),

        "desc": s(
            "rai_desc",
            size=7.7,
            leading=11,
        ),

        "meta": s(
            "rai_meta",
            size=7.0,
            leading=10,
            color=MUTED,
        ),

        "grand": s(
            "rai_grand",
            size=11,
            leading=15,
            font=bold,
            color=NAVY,
            align=TA_RIGHT,
        ),
    }


def _paragraph(
    value: Any,
    style: ParagraphStyle,
) -> Paragraph:

    return Paragraph(
        _text(value),
        style,
    )


def _line_text(
    label: str,
    value: Any,
) -> str | None:

    if value in (None, ""):
        return None

    return (
        f"<b>{_text(label)}:</b> "
        f"{_text(value)}"
    )


# =====================================================
# 6. SELLER AND BUYER INFORMATION
# =====================================================

def _contact_paragraph(
    party: Any,
    styles: dict[str, ParagraphStyle],
    *,
    place_of_supply: str | None = None,
) -> Paragraph:

    parts: list[str] = []

    for key in (
        "address",
        "emirate",
        "country",
    ):

        value = getattr(
            party,
            key,
        )

        if value:
            parts.append(
                _text(value)
            )

    for key, label in (
        ("trn", "TRN"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("contact_person", "Contact"),
    ):

        line = _line_text(
            label,
            getattr(party, key),
        )

        if line:
            parts.append(line)

    extra = _line_text(
        "Place of supply",
        place_of_supply,
    )

    if extra:
        parts.append(extra)

    return Paragraph(
        "<br/>".join(parts)
        if parts
        else "-",
        styles["small"],
    )


# =====================================================
# 7. VERIFY PDF SNAPSHOT
# =====================================================

def _verify_snapshot(
    snapshot: dict[str, Any],
):
    """Validate invoice data and independently check calculated totals."""

    if not isinstance(snapshot, dict):
        raise InvoicePDFError(
            "Snapshot must be a dictionary."
        )

    watermark = snapshot.get(
        "watermark"
    )

    if watermark not in (
        None,
        "DRAFT",
    ):
        raise InvoicePDFError(
            "Unsupported invoice watermark."
        )

    is_draft = (
        watermark == "DRAFT"
    )

    try:

        raw = snapshot["form_data"]

        if not isinstance(raw, dict):
            raise InvoicePDFError(
                "Snapshot form_data must be an object."
            )

        form = InvoiceGenerationInput.model_validate(
            raw
        )

        if not is_draft:

            FinalizableInvoiceInput.model_validate(
                raw
            )

    except (
        KeyError,
        TypeError,
        ValidationError,
    ) as exc:

        raise InvoicePDFError(
            "Invoice snapshot has invalid form data."
        ) from exc

    number = str(
        snapshot.get("invoice_number") or ""
    ).strip()

    if not is_draft and not number:
        raise InvoicePDFError(
            "Final invoice number is missing."
        )

    calculated = calculate_invoice_totals(
        [
            item.model_dump(
                mode="python"
            )
            for item in form.items
        ]
    )

    # Finalized invoices must match trusted
    # Decimal calculations exactly.
    if not is_draft:

        try:

            financial = InvoiceFinancialSummary.model_validate(
                snapshot["calculated"]
            )

        except (
            KeyError,
            ValidationError,
            TypeError,
        ) as exc:

            raise InvoicePDFError(
                "Final invoice financial snapshot "
                "is missing or invalid."
            ) from exc

        for field in (
            "subtotal_aed",
            "discount_aed",
            "vat_amount_aed",
            "total_amount_aed",
        ):

            expected = _decimal(
                calculated[field]
            )

            supplied = getattr(
                financial,
                field,
            )

            if (
                expected is None
                or supplied != expected
            ):
                raise InvoicePDFError(
                    f"Financial snapshot mismatch: {field}."
                )

        if len(financial.line_items) != len(
            calculated["line_items"]
        ):
            raise InvoicePDFError(
                "Invoice row count differs "
                "from calculation snapshot."
            )

        for index, (
            expected_row,
            supplied_row,
        ) in enumerate(
            zip(
                calculated["line_items"],
                financial.line_items,
            ),
            start=1,
        ):

            if expected_row["errors"]:
                raise InvoicePDFError(
                    f"Invalid invoice line {index}."
                )

            for field in (
                "gross_value_aed",
                "discount_aed",
                "taxable_value_aed",
                "vat_amount_aed",
                "line_total_aed",
            ):

                expected = _decimal(
                    expected_row["calculated"][field]
                )

                supplied = getattr(
                    supplied_row,
                    field,
                )

                if (
                    expected is None
                    or supplied != expected
                ):
                    raise InvoicePDFError(
                        f"Invoice line {index} mismatch: {field}."
                    )

        total = _decimal(
            calculated["total_amount_aed"]
        )

        if (
            total is None
            or total <= 0
        ):
            raise InvoicePDFError(
                "Final invoice amount must be greater than zero."
            )

    return (
        form,
        number,
        calculated,
        is_draft,
    )


# =====================================================
# 8. MAIN PDF RENDERING FUNCTION
# =====================================================

def render_invoice_pdf_bytes(
    snapshot: dict[str, Any],
) -> bytes:
    """Render a professional A4 invoice as PDF bytes.

    Company logo and all invoice content are rendered as text.

    The function supports:
        - Final invoices
        - Draft PDF previews
        - Custom company wordmark
        - Multiple invoice items
        - Custom line-item fields
        - Automatic page breaks
        - Repeated table headers
        - VAT breakdown
        - Amount in words

    No database or storage changes occur in this function.
    """

    (
        form,
        invoice_number,
        calc,
        is_draft,
    ) = _verify_snapshot(snapshot)

    normal, bold = _fonts()

    st = _styles(
        normal,
        bold,
    )

    accent = _hex_color(
        form.wordmark.accent_color
    )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,

        pagesize=A4,

        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,

        topMargin=34,
        bottomMargin=45,

        title=(
            f"Invoice {invoice_number or 'Draft'}"
        ),

        author=(
            form.seller.name
            or "ReceivAI UAE"
        ),

        subject="Generated invoice",

        pageCompression=1,
    )

    # -------------------------------------------------
    # Page footer and draft watermark
    # -------------------------------------------------

    def on_page(
        canv,
        pdf_doc,
    ):

        canv.saveState()

        canv.setStrokeColor(
            BORDER
        )

        canv.setLineWidth(
            0.6
        )

        canv.line(
            MARGIN_X,
            35,
            PAGE_WIDTH - MARGIN_X,
            35,
        )

        canv.setFillColor(
            MUTED
        )

        canv.setFont(
            normal,
            7,
        )

        canv.drawString(
            MARGIN_X,
            23,
            "Computer-generated invoice | ReceivAI UAE",
        )

        canv.drawRightString(
            PAGE_WIDTH - MARGIN_X,
            23,
            f"Page {pdf_doc.page}",
        )

        if is_draft:

            canv.setFont(
                bold,
                70,
            )

            canv.setFillColor(
                colors.Color(
                    0.70,
                    0.75,
                    0.80,
                    alpha=0.16,
                )
            )

            canv.translate(
                PAGE_WIDTH / 2,
                PAGE_HEIGHT / 2,
            )

            canv.rotate(40)

            canv.drawCentredString(
                0,
                0,
                "DRAFT",
            )

        canv.restoreState()

    story = []

    seller = form.seller
    buyer = form.buyer
    header = form.invoice
    wordmark = form.wordmark

    # -------------------------------------------------
    # 9. TEXT-BASED COMPANY LOGO
    # -------------------------------------------------

    name = (
        (
            seller.name
            or "COMPANY NAME"
        ).upper()
        if wordmark.uppercase
        else (
            seller.name
            or "Company Name"
        )
    )

    brand_font = (
        "Times-Bold"
        if (
            wordmark.style == "classic"
            and name.isascii()
        )
        else bold
    )

    brand_size = (
        wordmark.font_size_pt
    )

    if len(name) > 36:
        brand_size = min(
            brand_size,
            18,
        )

    if len(name) > 64:
        brand_size = min(
            brand_size,
            14,
        )

    brand_style = ParagraphStyle(
        "rai_wordmark",

        parent=st["heading"],

        fontName=brand_font,

        fontSize=brand_size,

        leading=brand_size * 1.2,

        textColor=accent,

        splitLongWords=True,
    )

    left_stack: list[Any] = [
        Paragraph(
            _text(name),
            brand_style,
        )
    ]

    if wordmark.show_accent_line:

        left_stack.append(
            Spacer(1, 5)
        )

        left_stack.append(
            HRFlowable(
                width=64,
                thickness=2.5,
                color=accent,
                hAlign="LEFT",
            )
        )

    if wordmark.subtitle:

        left_stack.append(
            Spacer(1, 5)
        )

        left_stack.append(
            _paragraph(
                wordmark.subtitle,
                st["small_bold"],
            )
        )

    left_stack.append(
        Spacer(1, 9)
    )

    left_stack.append(
        _contact_paragraph(
            seller,
            st,
        )
    )

    # -------------------------------------------------
    # 10. INVOICE TITLE AND METADATA
    # -------------------------------------------------

    title = {
        "tax_invoice": "TAX INVOICE",
        "invoice": "INVOICE",
        "proforma_invoice": "PROFORMA INVOICE",
    }[header.document_type]

    meta = [
        Paragraph(
            title,
            st["title"],
        ),

        Spacer(1, 8),

        Paragraph(
            "<b>No.</b> "
            + _present(
                invoice_number,
                default="Unassigned",
            ),
            st["body"],
        ),

        Paragraph(
            "<b>Issue date:</b> "
            + _text(
                _date(
                    header.issue_date
                )
            ),
            st["body"],
        ),

        Paragraph(
            "<b>Due date:</b> "
            + _text(
                _date(
                    header.due_date
                )
            ),
            st["body"],
        ),
    ]

    if header.supply_date:

        meta.append(
            Paragraph(
                "<b>Supply date:</b> "
                + _text(
                    _date(header.supply_date)
                ),
                st["body"],
            )
        )

    if header.purchase_order_number:

        meta.append(
            Paragraph(
                "<b>PO No.:</b> "
                + _text(
                    header.purchase_order_number
                ),
                st["small"],
            )
        )

    if header.reference_number:

        meta.append(
            Paragraph(
                "<b>Reference:</b> "
                + _text(
                    header.reference_number
                ),
                st["small"],
            )
        )

    if header.payment_terms:

        meta.append(
            Paragraph(
                "<b>Payment terms:</b> "
                + _text(
                    header.payment_terms
                ),
                st["small"],
            )
        )

    top = Table(
        [
            [
                left_stack,
                meta,
            ]
        ],
        colWidths=[
            CONTENT_WIDTH * 0.55,
            CONTENT_WIDTH * 0.45,
        ],
    )

    top.setStyle(
        TableStyle(
            [
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    0,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (0, 0),
                    15,
                ),
                (
                    "RIGHTPADDING",
                    (1, 0),
                    (1, 0),
                    0,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]
        )
    )

    story += [
        top,

        HRFlowable(
            width="100%",
            thickness=1,
            color=BORDER,
        ),

        Spacer(1, 12),
    ]

    # -------------------------------------------------
    # 11. CUSTOMER DETAILS
    # -------------------------------------------------

    buyer_box = [
        Paragraph(
            "BILL TO",
            st["heading"],
        ),

        Spacer(1, 4),

        _paragraph(
            buyer.name
            or "Customer name not entered",
            st["value"],
        ),

        Spacer(1, 4),

        _contact_paragraph(
            buyer,
            st,
            place_of_supply=(
                header.place_of_supply
            ),
        ),
    ]

    custom_header_lines = []

    for field in sorted(
        form.custom_fields,
        key=lambda f: f.sort_order,
    ):

        if field.show_on_pdf:

            custom_header_lines.append(
                Paragraph(
                    f"<b>{_text(field.label)}:</b> "
                    f"{_present(field.value)}",
                    st["small"],
                )
            )

    right_box = [
        Paragraph(
            "INVOICE INFORMATION",
            st["heading"],
        ),

        Spacer(1, 5),

        Paragraph(
            "<b>Currency:</b> AED",
            st["small"],
        ),
    ] + custom_header_lines

    cards = Table(
        [
            [
                buyer_box,
                right_box,
            ]
        ],
        colWidths=[
            CONTENT_WIDTH * 0.56,
            CONTENT_WIDTH * 0.44,
        ],
    )

    cards.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    BORDER,
                ),
                (
                    "LINEBEFORE",
                    (1, 0),
                    (1, -1),
                    0.6,
                    BORDER,
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    PALE,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    11,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    11,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
            ]
        )
    )

    story += [
        cards,

        Spacer(1, 18),

        Paragraph(
            "INVOICE ITEMS",
            st["heading"],
        ),

        Spacer(1, 7),
    ]

    # -------------------------------------------------
    # 12. DYNAMIC INVOICE ITEMS
    # -------------------------------------------------

    widths = [
        28,
        152,
        38,
        30,
        54,
        64,
        38,
        60,
        67,
    ]

    # Account for small floating-point A4 differences.
    widths[-1] += (
        CONTENT_WIDTH - sum(widths)
    )

    labels = [
        "#",
        "DESCRIPTION",
        "QTY",
        "UNIT",
        "RATE<br/>AED",
        "TAXABLE<br/>AED",
        "VAT<br/>%",
        "VAT<br/>AED",
        "TOTAL<br/>AED",
    ]

    table_data: list[list[Any]] = [
        [
            Paragraph(
                label,
                st["tablehead"],
            )
            for label in labels
        ]
    ]

    vat_groups: dict[
        Decimal,
        dict[str, Decimal],
    ] = defaultdict(
        lambda: {
            "taxable": Decimal("0.00"),
            "vat": Decimal("0.00"),
        }
    )

    visible_columns = {
        column.key: column.label

        for column in sorted(
            form.custom_columns,
            key=lambda col: col.sort_order,
        )

        if column.show_on_pdf
    }

    for index, (
        item,
        row,
    ) in enumerate(
        zip(
            form.items,
            calc["line_items"],
        ),
        1,
    ):

        amounts = row["calculated"]

        desc = _text(
            item.description or "-"
        )

        if item.discount_aed:

            desc += (
                "<br/>"
                "<font color='#64748B'>"
                "Discount: AED "
                + _money(
                    item.discount_aed
                )
                + "</font>"
            )

        table_data.append(
            [
                Paragraph(
                    str(index),
                    st["num_center"],
                ),

                Paragraph(
                    desc,
                    st["desc"],
                ),

                Paragraph(
                    _quantity(
                        item.quantity
                    ),
                    st["num"],
                ),

                _paragraph(
                    item.unit or "-",
                    st["small"],
                ),

                Paragraph(
                    _money(
                        item.unit_price_aed
                    ),
                    st["num"],
                ),

                Paragraph(
                    _money(
                        amounts[
                            "taxable_value_aed"
                        ]
                    ),
                    st["num"],
                ),

                Paragraph(
                    (
                        _quantity(
                            item.vat_rate
                        )
                        + "%"
                    )
                    if item.vat_rate is not None
                    else "-",
                    st["num"],
                ),

                Paragraph(
                    _money(
                        amounts[
                            "vat_amount_aed"
                        ]
                    ),
                    st["num"],
                ),

                Paragraph(
                    _money(
                        amounts[
                            "line_total_aed"
                        ]
                    ),
                    st["num_bold"],
                ),
            ]
        )

        if (
            amounts["taxable_value_aed"] is not None
            and amounts["vat_amount_aed"] is not None
        ):

            rate = (
                item.vat_rate
                or Decimal("0")
            )

            vat_groups[rate]["taxable"] += Decimal(
                amounts["taxable_value_aed"]
            )

            vat_groups[rate]["vat"] += Decimal(
                amounts["vat_amount_aed"]
            )

        # ---------------------------------------------
        # Custom line-item fields
        # ---------------------------------------------

        extra_lines = []

        for key, label in visible_columns.items():

            if key in item.custom_values:

                extra_lines.append(
                    f"<b>{_text(label)}:</b> "
                    f"{_text(item.custom_values[key])}"
                )

        for field in sorted(
            item.custom_fields,
            key=lambda f: f.sort_order,
        ):

            if field.show_on_pdf:

                extra_lines.append(
                    f"<b>{_text(field.label)}:</b> "
                    f"{_text(field.value)}"
                )

        # Custom fields are displayed within the
        # corresponding item's table area.
        #
        # This avoids creating very narrow columns
        # when customers add many custom fields.

        if extra_lines:

            for start in range(
                0,
                len(extra_lines),
                2,
            ):

                table_data.append(
                    [
                        Paragraph(
                            (
                                "<font color='#64748B'>"
                                f"Item {index} details: "
                                + " &nbsp; | &nbsp; ".join(
                                    extra_lines[
                                        start:start + 2
                                    ]
                                )
                                + "</font>"
                            ),
                            st["meta"],
                        )
                    ]
                    + [""] * 8
                )

    # -------------------------------------------------
    # 13. REPEATING MULTI-PAGE TABLE
    # -------------------------------------------------

    items_table = LongTable(
        table_data,

        colWidths=widths,

        repeatRows=1,

        hAlign="LEFT",

        splitByRow=1,

        splitInRow=1,
    )

    formatting = [
        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            NAVY,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "TOP",
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.35,
            BORDER,
        ),

        (
            "ROWBACKGROUNDS",
            (0, 1),
            (-1, -1),
            [
                colors.white,
                colors.HexColor("#FAFCFE"),
            ],
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, 0),
            9,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, 0),
            9,
        ),

        (
            "TOPPADDING",
            (0, 1),
            (-1, -1),
            6,
        ),

        (
            "BOTTOMPADDING",
            (0, 1),
            (-1, -1),
            6,
        ),
    ]

    for row_num, row in enumerate(
        table_data[1:],
        1,
    ):

        if (
            len(row) == 9
            and all(
                cell == ""
                for cell in row[1:]
            )
        ):

            formatting.append(
                (
                    "SPAN",
                    (0, row_num),
                    (-1, row_num),
                )
            )

    items_table.setStyle(
        TableStyle(
            formatting
        )
    )

    story += [
        items_table,
        Spacer(1, 14),
    ]

    # -------------------------------------------------
    # 14. FINANCIAL SUMMARY
    # -------------------------------------------------

    # The existing validator reports subtotal as the
    # taxable amount after discounts.
    #
    # Show gross amount and discount separately
    # to avoid misrepresenting taxable totals.

    gross = sum(
        (
            Decimal(
                line["calculated"][
                    "gross_value_aed"
                ] or "0"
            )
            for line in calc["line_items"]
        ),
        Decimal("0"),
    )

    subtotal = _decimal(
        calc["subtotal_aed"]
    )

    total = _decimal(
        calc["total_amount_aed"]
    )

    discounts = _decimal(
        calc["discount_aed"]
    )

    vat_total = _decimal(
        calc["vat_amount_aed"]
    )

    totals_data = [
        [
            Paragraph(
                "Gross amount",
                st["small"],
            ),

            Paragraph(
                "AED " + _money(gross),
                st["num"],
            ),
        ],

        [
            Paragraph(
                "Discounts",
                st["small"],
            ),

            Paragraph(
                "AED " + _money(discounts),
                st["num"],
            ),
        ],

        [
            Paragraph(
                "Taxable subtotal",
                st["small"],
            ),

            Paragraph(
                "AED " + _money(subtotal),
                st["num"],
            ),
        ],

        [
            Paragraph(
                "VAT total",
                st["small"],
            ),

            Paragraph(
                "AED " + _money(vat_total),
                st["num"],
            ),
        ],

        [
            Paragraph(
                "TOTAL DUE",
                st["heading"],
            ),

            Paragraph(
                "AED " + _money(total),
                st["grand"],
            ),
        ],
    ]

    total_box = Table(
        totals_data,

        colWidths=[
            117,
            132,
        ],
    )

    total_box.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, -1),
                    (-1, -1),
                    PALE,
                ),

                (
                    "LINEABOVE",
                    (0, -1),
                    (-1, -1),
                    1,
                    accent,
                ),

                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),

                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),

                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
            ]
        )
    )

    amount_words = [
        Paragraph(
            "AMOUNT IN WORDS",
            st["heading"],
        ),

        Spacer(1, 5),
    ]

    if total is not None:

        amount_words.append(
            Paragraph(
                _text(
                    _amount_words(total)
                ),
                st["body"],
            )
        )

    else:

        amount_words.append(
            Paragraph(
                "Not yet calculated",
                st["small"],
            )
        )

    summary = Table(
        [
            [
                amount_words,
                total_box,
            ]
        ],

        colWidths=[
            CONTENT_WIDTH - 249,
            249,
        ],
    )

    summary.setStyle(
        TableStyle(
            [
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),

                (
                    "LEFTPADDING",
                    (0, 0),
                    (0, 0),
                    0,
                ),

                (
                    "RIGHTPADDING",
                    (0, 0),
                    (0, 0),
                    16,
                ),

                (
                    "LEFTPADDING",
                    (1, 0),
                    (1, 0),
                    0,
                ),

                (
                    "RIGHTPADDING",
                    (1, 0),
                    (1, 0),
                    0,
                ),
            ]
        )
    )

    story.append(
        KeepTogether(
            [
                summary,
                Spacer(1, 13),
            ]
        )
    )

    # -------------------------------------------------
    # 15. VAT BREAKDOWN
    # -------------------------------------------------

    if vat_groups:

        story += [
            Paragraph(
                "VAT BREAKDOWN",
                st["heading"],
            ),

            Spacer(1, 5),
        ]

        vat_table = [
            [
                "VAT RATE",
                "TAXABLE VALUE (AED)",
                "VAT AMOUNT (AED)",
            ]
        ]

        for rate, amounts in sorted(
            vat_groups.items()
        ):

            vat_table.append(
                [
                    _quantity(rate) + "%",

                    _money(
                        amounts["taxable"]
                    ),

                    _money(
                        amounts["vat"]
                    ),
                ]
            )

        breakdown = Table(
            vat_table,

            colWidths=[
                100,
                170,
                CONTENT_WIDTH - 270,
            ],
        )

        breakdown.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        PALE,
                    ),

                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.4,
                        BORDER,
                    ),

                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, 0),
                        bold,
                    ),

                    (
                        "FONTNAME",
                        (0, 1),
                        (-1, -1),
                        normal,
                    ),

                    (
                        "FONTSIZE",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),

                    (
                        "ALIGN",
                        (1, 1),
                        (-1, -1),
                        "RIGHT",
                    ),

                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),

                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                ]
            )
        )

        story += [
            breakdown,
            Spacer(1, 15),
        ]

    # -------------------------------------------------
    # 16. BANK AND PAYMENT DETAILS
    # -------------------------------------------------

    bank = form.bank_details

    bank_lines = []

    for key, label in (
        ("account_name", "Account name"),
        ("bank_name", "Bank"),
        ("iban", "IBAN"),
        ("swift_code", "SWIFT"),
        (
            "payment_instructions",
            "Payment instructions",
        ),
    ):

        line = _line_text(
            label,
            getattr(
                bank,
                key,
            ),
        )

        if line:

            bank_lines.append(
                Paragraph(
                    line,
                    st["body"],
                )
            )

    if bank_lines:

        story += [
            Paragraph(
                "PAYMENT DETAILS",
                st["heading"],
            ),

            Spacer(1, 5),
        ] + bank_lines + [
            Spacer(1, 13)
        ]

    # -------------------------------------------------
    # 17. NOTES, DECLARATION, FOOTER
    # -------------------------------------------------

    for label, value in (
        ("NOTES", form.notes),

        (
            "DECLARATION",
            form.declaration_text,
        ),

        (
            "ADDITIONAL INFORMATION",
            form.footer_text,
        ),
    ):

        if value:

            story.extend(
                [
                    Paragraph(
                        label,
                        st["heading"],
                    ),

                    Spacer(1, 4),

                    _paragraph(
                        value,
                        st["body"],
                    ),

                    Spacer(1, 11),
                ]
            )

    story += [
        Spacer(1, 10),

        HRFlowable(
            width="100%",
            thickness=0.7,
            color=BORDER,
        ),

        Spacer(1, 9),

        Paragraph(
            "Authorised signatory (if applicable): "
            "____________________",
            st["small"],
        ),
    ]

    # -------------------------------------------------
    # 18. BUILD PDF
    # -------------------------------------------------

    try:

        doc.build(
            story,

            onFirstPage=on_page,

            onLaterPages=on_page,
        )

    except (
        ValueError,
        TypeError,
        LayoutError,
    ) as exc:

        raise InvoicePDFError(
            "Invoice PDF layout could not be rendered."
        ) from exc

    result = buffer.getvalue()

    if (
        not result.startswith(b"%PDF-")
        or b"%%EOF" not in result[-1024:]
    ):
        raise InvoicePDFError(
            "PDF renderer returned incomplete output."
        )

    return result
