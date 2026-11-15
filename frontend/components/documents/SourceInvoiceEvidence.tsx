
"use client";

import { useState } from "react";
import type {
  SourceInvoiceItem,
  UAEInvoice,
  DoclingEnrichment,
} from "@/lib/api";

// ============================================================
// TYPES
// ============================================================

type SourceInvoiceEvidenceProps = {
  invoice: UAEInvoice;
  doclingEnrichment?: DoclingEnrichment | null;
  manualReviewRequired?: boolean;
  className?: string;
};

// ============================================================
// FORMATTING HELPERS
// ============================================================

function displayText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  return String(value);
}

function formatNumber(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return String(value);
  }

  return number.toLocaleString("en-AE", {
    maximumFractionDigits: 4,
  });
}

function formatMoney(
  value: unknown,
  currency: string | null | undefined
): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const number = Number(value);

  const formatted = Number.isFinite(number)
    ? number.toLocaleString("en-AE", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    : String(value);

  return currency ? `${currency} ${formatted}` : formatted;
}

function normalizeCurrency(
  value: string | null | undefined
): string | null {
  if (!value) return null;

  const currency = value.trim().toUpperCase();

  return currency || null;
}

function getReconciliationLabel(
  value: boolean | null | undefined
): string {
  if (value === true) return "Reconciled";
  if (value === false) return "Mismatch or not reconciled";

  return "Not established";
}

function getReconciliationClass(
  value: boolean | null | undefined
): string {
  if (value === true) {
    return "bg-success-subtle text-success-emphasis border-success-subtle";
  }

  if (value === false) {
    return "bg-danger-subtle text-danger-emphasis border-danger-subtle";
  }

  return "bg-warning-subtle text-warning-emphasis border-warning-subtle";
}

function formatDocumentType(
  value: string | null | undefined
): string {
  if (!value) return "Not established";

  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

// ============================================================
// SOURCE ITEM TABLE
// ============================================================

function SourceItemsTable({
  items,
  currency,
}: {
  items: SourceInvoiceItem[];
  currency: string | null;
}) {
  if (items.length === 0) {
    return (
      <div className="text-muted small py-3">
        No reconstructed source line items are available.
        The original document may still contain information
        that requires manual verification.
      </div>
    );
  }

  return (
    <div className="table-responsive">
      <table className="table table-sm table-hover align-middle mb-0">
        <thead className="table-light">
          <tr>
            <th style={{ minWidth: 240 }}>Description</th>
            <th className="text-end">Quantity</th>
            <th>Unit</th>
            <th className="text-end">Unit price</th>
            <th className="text-end">Line amount</th>
          </tr>
        </thead>

        <tbody>
          {items.map((item, index) => {
            const itemCurrency =
              normalizeCurrency(item.currency) || currency;

            return (
              <tr key={`${index}-${item.description ?? "item"}`}>
                <td>
                  <div className="fw-medium">
                    {displayText(item.description)}
                  </div>

                  {item.other_quantity_text && (
                    <div className="small text-muted mt-1">
                      {item.other_quantity_text}
                    </div>
                  )}

                  {item.container && (
                    <div className="small text-muted">
                      Container: {item.container}
                    </div>
                  )}
                </td>

                <td className="text-end text-nowrap">
                  {formatNumber(item.quantity)}
                </td>

                <td>{displayText(item.unit)}</td>

                <td className="text-end text-nowrap">
                  {formatMoney(item.unit_price, itemCurrency)}
                </td>

                <td className="text-end text-nowrap fw-semibold">
                  {formatMoney(item.line_amount, itemCurrency)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ============================================================
// FINANCIAL SUMMARY ROW
// ============================================================

function SummaryRow({
  label,
  value,
  currency,
  emphasized = false,
}: {
  label: string;
  value: unknown;
  currency: string | null;
  emphasized?: boolean;
}) {
  return (
    <div
      className={`d-flex justify-content-between align-items-center gap-3 py-2 ${
        emphasized ? "fw-bold fs-6" : "small"
      }`}
    >
      <span>{label}</span>

      <span className="text-end text-nowrap">
        {formatMoney(value, currency)}
      </span>
    </div>
  );
}

// ============================================================
// MAIN COMPONENT
// ============================================================

export default function SourceInvoiceEvidence({
  invoice,
  doclingEnrichment,
  manualReviewRequired = false,
  className = "",
}: SourceInvoiceEvidenceProps) {
  const [showDetails, setShowDetails] = useState(false);

  const sourceItems = Array.isArray(invoice.source_items)
    ? invoice.source_items
    : [];

  const currency = normalizeCurrency(invoice.currency);

  const isAED = currency === "AED";

  const hasSourceFinancials =
    invoice.source_subtotal != null ||
    invoice.source_subtotal_before_discount != null ||
    invoice.source_discount != null ||
    invoice.source_tax_amount != null ||
    invoice.source_total_amount != null;

  const hasSourceEvidence =
    sourceItems.length > 0 || hasSourceFinancials;

  const hasLegacyAEDValues =
    isAED &&
    (Boolean(invoice.items?.length) ||
      invoice.total_amount_aed != null);

  const shouldDisplay =
    hasSourceEvidence ||
    hasLegacyAEDValues ||
    Boolean(doclingEnrichment);

  if (!shouldDisplay) {
    return null;
  }

  const total =
    invoice.source_total_amount ??
    (isAED ? invoice.total_amount_aed : null);

  const subtotal =
    invoice.source_subtotal ??
    (isAED ? invoice.subtotal_aed : null);

  const discount =
    invoice.source_discount ??
    (isAED ? invoice.discount_aed : null);

  const tax =
    invoice.source_tax_amount ??
    (isAED ? invoice.vat_amount_aed : null);

  const unresolvedFields = Array.isArray(invoice.unresolved_fields)
    ? invoice.unresolved_fields
    : doclingEnrichment?.unresolved_fields ?? [];

  const isProforma =
    invoice.document_type?.toLowerCase() === "proforma_invoice";

  const requiresReview =
    manualReviewRequired ||
    invoice.manual_review_required === true ||
    doclingEnrichment?.requires_review === true ||
    isProforma ||
    (currency !== null && currency !== "AED");

  const usingLegacyAED =
    !hasSourceEvidence && hasLegacyAEDValues;

  return (
    <section
      className={`card border-0 shadow-sm mt-3 ${className}`}
      aria-label="Original invoice evidence"
    >
      <div className="card-body p-3 p-lg-4">
        {/* Header */}

        <div className="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
          <div>
            <h3 className="h5 fw-semibold mb-1">
              Original Invoice Evidence
            </h3>

            <p className="text-muted small mb-0">
              Extracted values from the source document.
              No currency conversion or automatic approval
              has been performed.
            </p>
          </div>

          <div className="d-flex flex-wrap gap-2">
            <span className="badge text-bg-light border">
              {currency || "Currency unknown"}
            </span>

            <span
              className={`badge border ${getReconciliationClass(
                invoice.source_totals_reconciled
              )}`}
            >
              {getReconciliationLabel(
                invoice.source_totals_reconciled
              )}
            </span>

            {requiresReview && (
              <span className="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle">
                Manual review
              </span>
            )}
          </div>
        </div>

        {/* Document information */}

        <div className="row g-3 mb-4">
          <div className="col-12 col-md-4">
            <div className="small text-muted mb-1">
              Document type
            </div>

            <div className="fw-medium">
              {formatDocumentType(
                invoice.document_type || invoice.invoice_type
              )}
            </div>
          </div>

          <div className="col-12 col-md-4">
            <div className="small text-muted mb-1">
              Invoice number
            </div>

            <div className="fw-medium">
              {displayText(invoice.invoice_number)}
            </div>
          </div>

          <div className="col-12 col-md-4">
            <div className="small text-muted mb-1">
              Source line items
            </div>

            <div className="fw-medium">
              {sourceItems.length}
            </div>
          </div>
        </div>

        {/* Important notices */}

        {!currency && (
          <div className="alert alert-warning small py-2">
            The document currency is not established.
            Verify the source before using any financial values.
          </div>
        )}

        {currency && currency !== "AED" && (
          <div className="alert alert-info small py-2">
            This document is denominated in {currency}.
            These values are source evidence only and must
            not be treated as AED accounting amounts.
          </div>
        )}

        {isProforma && (
          <div className="alert alert-warning small py-2">
            This document is classified as a proforma invoice.
            It is not eligible for the existing AED invoice
            approval and collections workflow.
          </div>
        )}

        {usingLegacyAED && (
          <div className="alert alert-secondary small py-2">
            Showing available AED accounting totals.
            Separate reconstructed source-currency evidence
            was not recorded for this document.
          </div>
        )}

        {/* Source item table */}

        <div className="mb-4">
          <h4 className="h6 fw-semibold mb-3">
            Extracted Source Line Items
          </h4>

          <SourceItemsTable
            items={sourceItems}
            currency={currency}
          />
        </div>

        {/* Source financial summary */}

        <div className="row g-3">
          <div className="col-12 col-lg-6">
            <div className="border rounded-3 p-3 h-100">
              <h4 className="h6 fw-semibold mb-3">
                Source Financial Summary
              </h4>

              {invoice.source_subtotal_before_discount != null && (
                <SummaryRow
                  label="Subtotal before discount"
                  value={invoice.source_subtotal_before_discount}
                  currency={currency}
                />
              )}

              {subtotal != null && (
                <SummaryRow
                  label="Subtotal"
                  value={subtotal}
                  currency={currency}
                />
              )}

              {discount != null && (
                <SummaryRow
                  label="Discount"
                  value={discount}
                  currency={currency}
                />
              )}

              {tax != null && (
                <SummaryRow
                  label="Tax amount"
                  value={tax}
                  currency={currency}
                />
              )}

              <hr className="my-2" />

              <SummaryRow
                label="Original document total"
                value={total}
                currency={currency}
                emphasized
              />

              <p className="small text-muted mt-3 mb-0">
                Totals are displayed in the currency stated
                on the source document.
              </p>
            </div>
          </div>

          <div className="col-12 col-lg-6">
            <div className="border rounded-3 p-3 h-100">
              <h4 className="h6 fw-semibold mb-3">
                Extraction & Reconciliation
              </h4>

              <div className="d-flex justify-content-between gap-2 small mb-2">
                <span className="text-muted">Reconciliation</span>
                <span className="fw-medium text-end">
                  {getReconciliationLabel(
                    invoice.source_totals_reconciled
                  )}
                </span>
              </div>

              <div className="d-flex justify-content-between gap-2 small mb-2">
                <span className="text-muted">Extraction engine</span>
                <span className="fw-medium text-end">
                  {doclingEnrichment?.used === true
                    ? "Docling + PyMuPDF"
                    : displayText(invoice.extraction_method)}
                </span>
              </div>

              <div className="d-flex justify-content-between gap-2 small mb-2">
                <span className="text-muted">Docling status</span>
                <span className="fw-medium text-end">
                  {doclingEnrichment
                    ? displayText(doclingEnrichment.status)
                    : "Not recorded"}
                </span>
              </div>

              <div className="d-flex justify-content-between gap-2 small mb-2">
                <span className="text-muted">Reconstructed rows</span>
                <span className="fw-medium">
                  {doclingEnrichment?.reconstructed_item_count ??
                    sourceItems.length}
                </span>
              </div>

              {doclingEnrichment?.processing_seconds != null && (
                <div className="d-flex justify-content-between gap-2 small mb-2">
                  <span className="text-muted">Processing time</span>
                  <span className="fw-medium">
                    {formatNumber(
                      doclingEnrichment.processing_seconds
                    )}{" "}
                    seconds
                  </span>
                </div>
              )}

              <div className="d-flex justify-content-between gap-2 small">
                <span className="text-muted">Review status</span>
                <span className="fw-medium">
                  {requiresReview
                    ? "Manual review required"
                    : "Review status not flagged"}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Optional unresolved-field details */}

        {unresolvedFields.length > 0 && (
          <div className="mt-3">
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => setShowDetails((previous) => !previous)}
              aria-expanded={showDetails}
            >
              {showDetails ? "Hide" : "Show"} unresolved fields
              {" "}
              ({unresolvedFields.length})
            </button>

            {showDetails && (
              <div className="border rounded-3 p-3 mt-2">
                <p className="small text-muted mb-2">
                  The following fields require verification
                  or additional evidence:
                </p>

                <ul className="small mb-0">
                  {unresolvedFields.map((field) => (
                    <li key={field}>
                      {field.replaceAll("_", " ")}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Final safety notice */}

        <p className="small text-muted mt-4 mb-0">
          Source evidence is read-only. Administrator validation
          and approval are controlled separately by the
          ReceivAI backend.
        </p>
      </div>
    </section>
  );
}
