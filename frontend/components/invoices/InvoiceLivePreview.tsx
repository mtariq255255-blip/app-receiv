
"use client";

import type { CSSProperties, ReactNode } from "react";

import InvoiceTextWordmark from "@/components/invoices/InvoiceTextWordmark";
import { formatInvoiceAED } from "@/components/invoices/InvoiceTotalsPanel";

import type {
  InvoiceCustomField,
  InvoiceGenerationInput,
  InvoiceGenerationValidationResponse,
  InvoicePartyInput,
} from "@/lib/invoice-generation-types";

/**
 * ReceivAI UAE — Read-only invoice HTML preview.
 *
 * - Seller, buyer and item text come from the current form.
 * - Financial calculations come exclusively from FastAPI.
 * - No client-side VAT or total calculations are performed.
 * - Parent must set isStale=true whenever the form changes.
 * - The actual PDF is generated separately by the backend.
 */

export interface InvoiceLivePreviewProps {
  form: InvoiceGenerationInput;

  validation?: InvoiceGenerationValidationResponse | null;

  isStale?: boolean;
  isValidating?: boolean;

  onPreviewPdf?: () => void;
  isPreviewingPdf?: boolean;

  compact?: boolean;
}

// ============================================================
// 1. DESIGN COLORS
// ============================================================

const COLORS = {
  navy: "#163252",
  ink: "#203551",
  muted: "#64748b",
  border: "#dce5ef",
  pale: "#f3f7fb",
  teal: "#087f7b",
};

// ============================================================
// 2. COMMON STYLES
// ============================================================

const labelStyle: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.09em",
  color: COLORS.muted,
  textTransform: "uppercase",
};

const cellStyle: CSSProperties = {
  fontSize: 11,
  color: COLORS.ink,
  borderBottom: `1px solid ${COLORS.border}`,
  padding: "11px 8px",
  verticalAlign: "top",
};

const numericCellStyle: CSSProperties = {
  ...cellStyle,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
};

// ============================================================
// 3. TEXT AND DATE HELPERS
// ============================================================

function present(
  value: string | null | undefined,
  fallback = "—",
): string {
  return value?.trim() || fallback;
}

/**
 * Format YYYY-MM-DD without interpreting the date
 * as a UTC timestamp.
 */
function displayDate(
  value: string | null | undefined,
): string {
  if (!value) return "—";

  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);

  if (!match) return value;

  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];

  const month = Number(match[2]);
  const day = Number(match[3]);

  if (
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > 31
  ) {
    return value;
  }

  return (
    `${String(day).padStart(2, "0")} ` +
    `${months[month - 1]} ${match[1]}`
  );
}

// ============================================================
// 4. INVOICE-LEVEL CUSTOM FIELDS
// ============================================================

function VisibleCustomFields({
  fields,
}: {
  fields: InvoiceCustomField[];
}) {
  const visible = [...fields]
    .filter((field) => field.show_on_pdf)
    .sort(
      (a, b) => a.sort_order - b.sort_order,
    );

  if (visible.length === 0) return null;

  return (
    <div className="d-grid gap-1 mt-2">
      {visible.map((field, index) => (
        <div
          key={`${field.sort_order}-${index}`}
          style={{
            fontSize: 11,
            overflowWrap: "anywhere",
          }}
        >
          <span style={{ color: COLORS.muted }}>
            {field.label}:
          </span>{" "}

          <strong
            style={{
              color: COLORS.ink,
              fontWeight: 600,
            }}
          >
            {present(field.value)}
          </strong>
        </div>
      ))}
    </div>
  );
}

// ============================================================
// 5. COMPANY AND CUSTOMER DETAILS
// ============================================================

function ContactDetails({
  party,
}: {
  party: InvoicePartyInput;
}) {
  const address = [
    party.address,
    party.emirate,
    party.country,
  ]
    .map((value) => value?.trim())
    .filter(Boolean);

  const properties: Array<
    [string, string | null]
  > = [
    ["TRN", party.trn],
    ["Email", party.email],
    ["Phone", party.phone],
    ["Contact", party.contact_person],
  ];

  return (
    <div
      style={{
        fontSize: 11,
        lineHeight: 1.65,
        color: COLORS.muted,
      }}
    >
      {address.length > 0 ? (
        <div
          style={{
            whiteSpace: "pre-line",
            overflowWrap: "anywhere",
          }}
        >
          {address.join("\n")}
        </div>
      ) : (
        <div>Address not entered</div>
      )}

      {properties
        .filter(([, value]) =>
          Boolean(value?.trim()),
        )
        .map(([label, value]) => (
          <div
            key={label}
            style={{
              overflowWrap: "anywhere",
            }}
          >
            <strong
              style={{
                color: COLORS.ink,
              }}
            >
              {label}:
            </strong>{" "}
            {value}
          </div>
        ))}
    </div>
  );
}

// ============================================================
// 6. INVOICE METADATA ROW
// ============================================================

function Detail({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div
      className="d-flex justify-content-between gap-3"
      style={{
        fontSize: 11,
        lineHeight: 1.75,
      }}
    >
      <span
        style={{
          color: COLORS.muted,
          flexShrink: 0,
        }}
      >
        {label}
      </span>

      <strong
        style={{
          color: COLORS.ink,
          fontWeight: 600,
          textAlign: "right",
          overflowWrap: "anywhere",
        }}
      >
        {value}
      </strong>
    </div>
  );
}

// ============================================================
// 7. NOTES / DECLARATION
// ============================================================

function MemoSection({
  title,
  content,
}: {
  title: string;
  content: string | null;
}) {
  if (!content?.trim()) return null;

  return (
    <section
      style={{
        marginTop: 20,
      }}
    >
      <div style={labelStyle}>
        {title}
      </div>

      <p
        style={{
          fontSize: 11,
          color: COLORS.ink,
          margin: "8px 0 0",
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
          lineHeight: 1.65,
        }}
      >
        {content}
      </p>
    </section>
  );
}

// ============================================================
// 8. MAIN INVOICE PREVIEW
// ============================================================

export default function InvoiceLivePreview({
  form,
  validation = null,
  isStale = false,
  isValidating = false,
  onPreviewPdf,
  isPreviewingPdf = false,
  compact = false,
}: InvoiceLivePreviewProps) {
  const invoice = form.invoice;
  const bank = form.bank_details;

  // ----------------------------------------------------------
  // AUTHORITATIVE FINANCIAL RESULTS
  // ----------------------------------------------------------

  // Show calculated figures only when validation
  // belongs to the current form and the row count matches.

  const calculated =
    !isStale &&
    !isValidating &&
    validation?.calculated?.line_items.length ===
      form.items.length
      ? validation.calculated
      : null;

  const validationCurrent =
    !isStale &&
    !isValidating &&
    validation !== null;

  const statusText = isValidating
    ? "Validating"
    : isStale
      ? "Changes not validated"
      : !validationCurrent
        ? "Draft preview"
        : validation.is_valid
          ? "Validated draft"
          : "Review required";

  // ----------------------------------------------------------
  // DOCUMENT TYPE
  // ----------------------------------------------------------

  const title = {
    tax_invoice: "TAX INVOICE",
    invoice: "INVOICE",
    proforma_invoice: "PROFORMA INVOICE",
  }[invoice.document_type];

  // ----------------------------------------------------------
  // OPTIONAL INFORMATION
  // ----------------------------------------------------------

  const hasBankDetails = Boolean(
    bank.account_name ||
      bank.bank_name ||
      bank.iban ||
      bank.swift_code ||
      bank.payment_instructions,
  );

  const visibleColumns = [
    ...form.custom_columns,
  ]
    .filter(
      (column) => column.show_on_pdf,
    )
    .sort(
      (a, b) => a.sort_order - b.sort_order,
    );

  // ----------------------------------------------------------
  // INVOICE PAPER STYLING
  // ----------------------------------------------------------

  const paperStyle: CSSProperties = {
    backgroundColor: "#ffffff",
    color: COLORS.ink,

    width: "100%",
    maxWidth: 820,

    margin: "0 auto",

    padding: compact
      ? "20px 18px"
      : "28px clamp(18px, 4%, 38px)",

    border: `1px solid ${COLORS.border}`,
    borderRadius: 12,

    boxShadow:
      "0 12px 35px rgba(17, 37, 64, 0.07)",

    fontFamily:
      'Arial, "Helvetica Neue", sans-serif',

    overflowWrap: "anywhere",
  };

  // ==========================================================
  // 9. RENDER
  // ==========================================================

  return (
    <section
      aria-label="Live invoice preview"
    >
      {/* ======================================================
          PREVIEW TOOLBAR
      ====================================================== */}

      <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
        <div>
          <h2
            className="h5 fw-bold mb-1"
            style={{
              color: "#e9f2f8",
            }}
          >
            Invoice preview
          </h2>

          <p
            className="mb-0"
            style={{
              color: "#9aa9bd",
              fontSize: 12,
            }}
          >
            Live document view · exact exported
            layout is available via PDF preview
          </p>
        </div>

        <div className="d-flex flex-wrap align-items-center gap-2">
          <span
            className="rounded-pill px-3 py-2"
            role="status"
            aria-live="polite"
            style={{
              background: "#eaf7f5",
              border: "1px solid #c4e8e3",
              color: COLORS.teal,
              fontSize: 11,
              fontWeight: 700,
            }}
          >
            {statusText}
          </span>

          {onPreviewPdf && (
            <button
              type="button"
              className="btn btn-outline-info btn-sm"
              disabled={isPreviewingPdf}
              onClick={onPreviewPdf}
            >
              <i
                className="bi bi-file-earmark-pdf me-1"
                aria-hidden="true"
              />

              {isPreviewingPdf
                ? "Preparing PDF..."
                : "Preview PDF"}
            </button>
          )}
        </div>
      </div>

      {/* ======================================================
          INVOICE DOCUMENT
      ====================================================== */}

      <article
        style={paperStyle}
        aria-label={`${title} document`}
      >
        {/* ====================================================
            HEADER — COMPANY WORDMARK AND INVOICE DETAILS
        ==================================================== */}

        <header
          className="d-flex flex-wrap justify-content-between gap-4"
          style={{
            borderBottom:
              `1px solid ${COLORS.border}`,
            paddingBottom: 20,
          }}
        >
          {/* SELLER DETAILS */}

          <div
            style={{
              flex: "1 1 260px",
              minWidth: 0,
            }}
          >
            <InvoiceTextWordmark
              companyName={form.seller.name}
              settings={form.wordmark}
              showControls={false}
              compact
            />

            <div className="mt-3">
              <ContactDetails
                party={form.seller}
              />
            </div>
          </div>

          {/* INVOICE METADATA */}

          <div
            style={{
              flex: "0 1 235px",
              minWidth: 0,
            }}
          >
            <h3
              style={{
                fontSize: compact ? 18 : 22,
                fontWeight: 800,
                color: COLORS.navy,
                marginBottom: 13,
                textAlign: "right",
                letterSpacing: "0.02em",
              }}
            >
              {title}
            </h3>

            <Detail
              label="Invoice No."
              value={present(
                invoice.invoice_number,
                "Assigned on finalization",
              )}
            />

            <Detail
              label="Issue date"
              value={displayDate(
                invoice.issue_date,
              )}
            />

            <Detail
              label="Due date"
              value={displayDate(
                invoice.due_date,
              )}
            />

            {invoice.supply_date && (
              <Detail
                label="Supply date"
                value={displayDate(
                  invoice.supply_date,
                )}
              />
            )}

            {invoice.purchase_order_number && (
              <Detail
                label="PO number"
                value={
                  invoice.purchase_order_number
                }
              />
            )}

            {invoice.reference_number && (
              <Detail
                label="Reference"
                value={invoice.reference_number}
              />
            )}

            {invoice.payment_terms && (
              <Detail
                label="Payment terms"
                value={invoice.payment_terms}
              />
            )}
          </div>
        </header>

        {/* ====================================================
            BILL TO — CUSTOMER AND ADDITIONAL FIELDS
        ==================================================== */}

        <div
          className="d-flex flex-wrap gap-3 mt-4"
          style={{
            background: COLORS.pale,
            border:
              `1px solid ${COLORS.border}`,
            borderRadius: 9,
            padding: 14,
          }}
        >
          <section
            style={{
              flex: "1 1 230px",
              minWidth: 0,
            }}
          >
            <div style={labelStyle}>
              Bill to
            </div>

            <div
              style={{
                fontWeight: 700,
                color: COLORS.navy,
                margin: "7px 0",
                fontSize: 14,
              }}
            >
              {present(
                form.buyer.name,
                "Customer name not entered",
              )}
            </div>

            <ContactDetails
              party={form.buyer}
            />

            {invoice.place_of_supply && (
              <div
                style={{
                  fontSize: 11,
                  color: COLORS.muted,
                  marginTop: 6,
                }}
              >
                <strong
                  style={{
                    color: COLORS.ink,
                  }}
                >
                  Place of supply:
                </strong>{" "}
                {invoice.place_of_supply}
              </div>
            )}
          </section>

          <section
            style={{
              flex: "1 1 195px",
              minWidth: 0,
            }}
          >
            <div style={labelStyle}>
              Invoice information
            </div>

            <div
              style={{
                marginTop: 7,
              }}
            >
              <Detail
                label="Currency"
                value="AED"
              />
            </div>

            <VisibleCustomFields
              fields={form.custom_fields}
            />
          </section>
        </div>

        {/* ====================================================
            DYNAMIC LINE ITEMS
        ==================================================== */}

        <section
          style={{
            marginTop: 25,
          }}
        >
          <div
            style={{
              ...labelStyle,
              color: COLORS.navy,
              marginBottom: 9,
            }}
          >
            Invoice items
          </div>

          {/* Horizontal scrolling on smaller screens */}

          <div
            style={{
              overflowX: "auto",
              borderRadius: 8,
              border:
                `1px solid ${COLORS.border}`,
            }}
          >
            <table
              className="w-100"
              style={{
                borderCollapse: "collapse",
                minWidth: 730,
                margin: 0,
              }}
            >
              <thead
                style={{
                  background: COLORS.navy,
                  color: "#ffffff",
                }}
              >
                <tr>
                  {[
                    "#",
                    "Description",
                    "Qty",
                    "Unit",
                    "Rate (AED)",
                    "Taxable (AED)",
                    "VAT %",
                    "VAT (AED)",
                    "Total (AED)",
                  ].map((label) => (
                    <th
                      key={label}
                      scope="col"
                      style={{
                        padding: "10px 8px",
                        textAlign:
                          label === "Description" ||
                          label === "Unit"
                            ? "left"
                            : "right",
                        fontSize: 10,
                        fontWeight: 700,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody>
                {/* EMPTY ITEMS */}

                {form.items.length === 0 && (
                  <tr>
                    <td
                      colSpan={9}
                      style={{
                        ...cellStyle,
                        textAlign: "center",
                        padding: 22,
                      }}
                    >
                      No invoice items entered.
                    </td>
                  </tr>
                )}

                {/* EACH INVOICE LINE */}

                {form.items.map(
                  (item, index) => {
                    const backendLine =
                      calculated?.line_items[index];

                    const itemDetails = [
                      ...visibleColumns
                        .filter((column) =>
                          item.custom_values[
                            column.key
                          ]?.trim(),
                        )
                        .map((column) => ({
                          label: column.label,
                          value:
                            item.custom_values[
                              column.key
                            ],
                        })),

                      ...[...item.custom_fields]
                        .filter(
                          (field) =>
                            field.show_on_pdf &&
                            field.label.trim(),
                        )
                        .sort(
                          (a, b) =>
                            a.sort_order -
                            b.sort_order,
                        )
                        .map((field) => ({
                          label: field.label,
                          value: field.value,
                        })),
                    ];

                    return (
                      <tr
                        key={
                          item.client_id ||
                          `item-${index}`
                        }
                        style={{
                          background:
                            index % 2 === 0
                              ? "#ffffff"
                              : "#fafcfe",
                        }}
                      >
                        {/* ROW NUMBER */}

                        <td
                          style={
                            numericCellStyle
                          }
                        >
                          {index + 1}
                        </td>

                        {/* DESCRIPTION AND CUSTOM DATA */}

                        <td
                          style={{
                            ...cellStyle,
                            minWidth: 180,
                          }}
                        >
                          <div
                            style={{
                              fontWeight: 600,
                              whiteSpace:
                                "pre-wrap",
                            }}
                          >
                            {present(
                              item.description,
                              "Item description",
                            )}
                          </div>

                          {item.discount_aed &&
                            item.discount_aed !==
                              "0.00" &&
                            item.discount_aed !==
                              "0" && (
                              <div
                                style={{
                                  fontSize: 10,
                                  color:
                                    COLORS.muted,
                                  marginTop: 5,
                                }}
                              >
                                Discount: AED{" "}
                                {formatInvoiceAED(
                                  item.discount_aed,
                                )}
                              </div>
                            )}

                          {itemDetails.length > 0 && (
                            <div
                              style={{
                                fontSize: 10,
                                color:
                                  COLORS.muted,
                                marginTop: 5,
                                lineHeight: 1.55,
                              }}
                            >
                              {itemDetails.map(
                                (
                                  detail,
                                  detailIndex,
                                ) => (
                                  <div
                                    key={
                                      `${detail.label}-` +
                                      detailIndex
                                    }
                                  >
                                    <strong>
                                      {detail.label}:
                                    </strong>{" "}
                                    {present(
                                      detail.value,
                                    )}
                                  </div>
                                ),
                              )}
                            </div>
                          )}
                        </td>

                        {/* QUANTITY */}

                        <td
                          style={numericCellStyle}
                        >
                          {present(item.quantity)}
                        </td>

                        {/* UNIT */}

                        <td style={cellStyle}>
                          {present(item.unit)}
                        </td>

                        {/* INPUT UNIT PRICE */}

                        <td
                          style={numericCellStyle}
                        >
                          {formatInvoiceAED(
                            item.unit_price_aed,
                          )}
                        </td>

                        {/* SERVER TAXABLE VALUE */}

                        <td
                          style={numericCellStyle}
                        >
                          {formatInvoiceAED(
                            backendLine
                              ?.taxable_value_aed,
                          )}
                        </td>

                        {/* VAT RATE */}

                        <td
                          style={numericCellStyle}
                        >
                          {item.vat_rate != null &&
                          item.vat_rate !== ""
                            ? `${item.vat_rate}%`
                            : "—"}
                        </td>

                        {/* SERVER VAT AMOUNT */}

                        <td
                          style={numericCellStyle}
                        >
                          {formatInvoiceAED(
                            backendLine
                              ?.vat_amount_aed,
                          )}
                        </td>

                        {/* SERVER LINE TOTAL */}

                        <td
                          style={{
                            ...numericCellStyle,
                            fontWeight: 700,
                          }}
                        >
                          {formatInvoiceAED(
                            backendLine
                              ?.line_total_aed,
                          )}
                        </td>
                      </tr>
                    );
                  },
                )}
              </tbody>
            </table>
          </div>

          {!calculated && (
            <p
              style={{
                fontSize: 11,
                color: COLORS.muted,
                margin: "8px 0 0",
              }}
            >
              {isValidating
                ? "Calculating values with the backend..."
                : "Calculated amounts will appear after the current form is validated."}
            </p>
          )}
        </section>

        {/* ====================================================
            INVOICE TOTALS
        ==================================================== */}

        <div
          className="d-flex flex-wrap justify-content-between gap-4"
          style={{
            marginTop: 22,
          }}
        >
          {/* AMOUNT IN WORDS */}

          <div
            style={{
              flex: "1 1 190px",
              minWidth: 0,
            }}
          >
            <div style={labelStyle}>
              Amount in words
            </div>

            <p
              style={{
                marginTop: 8,
                color: COLORS.muted,
                fontSize: 11,
                lineHeight: 1.6,
              }}
            >
              The exact amount in words is
              included in the generated PDF.
            </p>

            {validationCurrent &&
              validation &&
              !validation.is_valid && (
                <p
                  style={{
                    color: "#b45309",
                    fontSize: 11,
                  }}
                >
                  This draft still has{" "}
                  {validation.errors.length}{" "}
                  validation{" "}
                  {validation.errors.length === 1
                    ? "issue"
                    : "issues"}
                  .
                </p>
              )}
          </div>

          {/* FINANCIAL TOTALS */}

          <div
            style={{
              flex: "1 1 245px",
              maxWidth: 330,
              minWidth: 0,
              marginLeft: "auto",
            }}
          >
            <div className="d-grid gap-1">
              <Detail
                label="Taxable subtotal"
                value={
                  `AED ${formatInvoiceAED(
                    calculated?.subtotal_aed,
                  )}`
                }
              />

              <Detail
                label="Line discounts (included above)"
                value={
                  `AED ${formatInvoiceAED(
                    calculated?.discount_aed,
                  )}`
                }
              />

              <Detail
                label="VAT total"
                value={
                  `AED ${formatInvoiceAED(
                    calculated?.vat_amount_aed,
                  )}`
                }
              />
            </div>

            {/* GRAND TOTAL */}

            <div
              className="d-flex align-items-center justify-content-between gap-2 mt-2"
              style={{
                padding: "12px 9px",
                background: COLORS.pale,
                borderTop:
                  `2px solid ${COLORS.teal}`,
                borderRadius: 5,
              }}
            >
              <strong
                style={{
                  fontSize: 12,
                  color: COLORS.navy,
                }}
              >
                TOTAL DUE
              </strong>

              <strong
                style={{
                  fontSize: 17,
                  color: COLORS.navy,
                  fontVariantNumeric:
                    "tabular-nums",
                }}
              >
                AED{" "}
                {formatInvoiceAED(
                  calculated
                    ?.total_amount_aed,
                )}
              </strong>
            </div>
          </div>
        </div>

        {/* ====================================================
            BANK DETAILS
        ==================================================== */}

        {hasBankDetails && (
          <section
            style={{
              marginTop: 24,
              borderTop:
                `1px solid ${COLORS.border}`,
              paddingTop: 18,
            }}
          >
            <div style={labelStyle}>
              Payment details
            </div>

            <div className="d-flex flex-wrap gap-3 mt-2">
              <div
                style={{
                  flex: "1 1 200px",
                  minWidth: 0,
                }}
              >
                {bank.account_name && (
                  <Detail
                    label="Account name"
                    value={
                      bank.account_name
                    }
                  />
                )}

                {bank.bank_name && (
                  <Detail
                    label="Bank"
                    value={bank.bank_name}
                  />
                )}
              </div>

              <div
                style={{
                  flex: "1 1 200px",
                  minWidth: 0,
                }}
              >
                {bank.iban && (
                  <Detail
                    label="IBAN"
                    value={bank.iban}
                  />
                )}

                {bank.swift_code && (
                  <Detail
                    label="SWIFT"
                    value={
                      bank.swift_code
                    }
                  />
                )}
              </div>
            </div>

            {bank.payment_instructions && (
              <p
                style={{
                  whiteSpace: "pre-wrap",
                  color: COLORS.ink,
                  fontSize: 11,
                  marginTop: 9,
                }}
              >
                {bank.payment_instructions}
              </p>
            )}
          </section>
        )}

        {/* ====================================================
            NOTES AND DECLARATIONS
        ==================================================== */}

        <MemoSection
          title="Notes"
          content={form.notes}
        />

        <MemoSection
          title="Declaration"
          content={form.declaration_text}
        />

        <MemoSection
          title="Additional information"
          content={form.footer_text}
        />

        {/* ====================================================
            INVOICE FOOTER
        ==================================================== */}

        <footer
          style={{
            marginTop: 24,
            paddingTop: 14,
            borderTop:
              `1px solid ${COLORS.border}`,
          }}
        >
          <div
            style={{
              fontSize: 10,
              color: COLORS.muted,
            }}
          >
            Authorised signatory (if applicable):
            ____________________
          </div>

          <div
            style={{
              fontSize: 10,
              color: COLORS.muted,
              marginTop: 12,
              textAlign: "center",
            }}
          >
            Draft screen preview · not a
            finalized tax document
          </div>
        </footer>
      </article>
    </section>
  );
}
