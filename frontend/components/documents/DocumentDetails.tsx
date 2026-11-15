
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import DocumentStatusBadge from "@/components/documents/DocumentStatusBadge";

import {
  getDocumentPreview,
  type DocumentDetails as DocumentDetailsRecord,
  type UAEInvoice,
  type StructuredExtraction,
} from "@/lib/api";

// ============================================================
// TYPES
// ============================================================

type Props = {
  document: DocumentDetailsRecord;
  invoiceIndex?: number;
};

type PreviewState = {
  documentId: number;
  url: string;
  error: string;
  loading: boolean;
};

type DetailRow = {
  label: string;
  value: unknown;
};

// ============================================================
// HELPERS
// ============================================================

function objectValue(
  value: unknown
): Record<string, unknown> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value)
  )
    ? (value as Record<string, unknown>)
    : {};
}

function detailValue(value: unknown): string {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "Not identified";
  }

  return String(value);
}

function readableDate(
  value: string | null | undefined
): string {
  if (!value) return "Not available";

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatMoney(
  value: unknown,
  currency: string | null
): string {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "Not identified";
  }

  const number = Number(value);

  const formatted = Number.isFinite(number)
    ? number.toLocaleString("en-AE", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    : String(value);

  return currency
    ? `${currency} ${formatted}`
    : formatted;
}

function normalizeCurrency(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const currency = value.trim().toUpperCase();

  return currency || null;
}

function formatDocumentType(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.trim()
  ) {
    return "Not established";
  }

  return value
    .trim()
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatReconciliation(
  reconciled: boolean | null | undefined
): string {
  if (reconciled === true) {
    return "Reconciled";
  }

  if (reconciled === false) {
    return "Not reconciled";
  }

  return "Not established";
}

function reconciliationClass(
  reconciled: boolean | null | undefined
): string {
  if (reconciled === true) {
    return "text-bg-success";
  }

  if (reconciled === false) {
    return "text-bg-danger";
  }

  return "text-bg-warning";
}

function formatFileSize(value: number | null): string {
  if (
    value === null ||
    value === undefined ||
    !Number.isFinite(value)
  ) {
    return "Not available";
  }

  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function getSourceInvoice(
  data: Record<string, unknown>,
  invoiceIndex: number
): UAEInvoice {
  const extraction = objectValue(
    data.structured_extraction
  );

  const invoices = Array.isArray(
    extraction.invoices
  )
    ? extraction.invoices
    : [];

  const structured = objectValue(
    data.structured_invoice
  );

  if (
    invoiceIndex === 0 &&
    Object.keys(structured).length > 0
  ) {
    return structured as UAEInvoice;
  }

  return objectValue(
    invoices[invoiceIndex]
  ) as UAEInvoice;
}

// ============================================================
// REUSABLE DETAIL GRID
// ============================================================

function DetailGrid({
  rows,
}: {
  rows: DetailRow[];
}) {
  return (
    <dl className="document-meta-grid mb-0">
      {rows.map((row) => (
        <div key={row.label}>
          <dt>{row.label}</dt>

          <dd className="text-break">
            {detailValue(row.value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ============================================================
// COMPONENT
// ============================================================

export default function DocumentDetails({
  document,
  invoiceIndex = 0,
}: Props) {
  // ==========================================================
  // EXTRACTED DATA
  // ==========================================================

  const data = objectValue(
    document.extracted_data
  );

  const structuredExtraction =
    objectValue(
      data.structured_extraction
    ) as StructuredExtraction;

  const invoice = getSourceInvoice(
    data,
    invoiceIndex
  );

  const rawExtraction = objectValue(
    data.raw_extraction
  );

  const metadata = objectValue(
    rawExtraction.metadata ??
    data.processing_metadata
  );

  const privacy = objectValue(
    data.privacy_processing
  );

  const approvals = objectValue(
    data.approvals
  );

  const rejection = objectValue(
    data.rejection
  );

  // ==========================================================
  // CURRENCY AND FINANCIAL VALUES
  // ==========================================================

  const currency = normalizeCurrency(
    invoice.currency
  );

  const isAED = currency === "AED";

  const documentType = (
    invoice.document_type ??
    invoice.invoice_type
  );

  const isProforma =
    String(documentType || "")
      .trim()
      .toLowerCase() === "proforma_invoice";

  const sourceItems = Array.isArray(
    invoice.source_items
  )
    ? invoice.source_items
    : [];

  const accountingItems = Array.isArray(
    invoice.items
  )
    ? invoice.items
    : [];

  const hasSourceEvidence =
    sourceItems.length > 0 ||
    invoice.source_total_amount != null;

  // Never use foreign-currency amounts from AED fields.
  // AED fallback supports previously processed documents.

  const sourceSubtotal =
    invoice.source_subtotal ??
    (
      isAED
        ? invoice.subtotal_aed
        : null
    );

  const sourceSubtotalBeforeDiscount =
    invoice.source_subtotal_before_discount ??
    (
      isAED
        ? invoice.subtotal_before_discount_aed
        : null
    );

  const sourceDiscount =
    invoice.source_discount ??
    (
      isAED
        ? invoice.discount_aed
        : null
    );

  const sourceTax =
    invoice.source_tax_amount ??
    (
      isAED
        ? invoice.vat_amount_aed
        : null
    );

  const sourceTotal =
    invoice.source_total_amount ??
    (
      isAED
        ? invoice.total_amount_aed
        : null
    );

  const sourceReconciled =
    invoice.source_totals_reconciled;

  // ==========================================================
  // DOCLING METADATA
  // ==========================================================

  const docling =
    structuredExtraction.docling_enrichment;

  const doclingUsed =
    docling?.used === true;

  const doclingStatus =
    docling?.status || "Not recorded";

  const reconstructedCount =
    docling?.reconstructed_item_count ??
    structuredExtraction.source_record_count ??
    sourceItems.length;

  const reviewRequired =
    structuredExtraction.manual_review_required === true ||
    invoice.manual_review_required === true ||
    docling?.requires_review === true ||
    isProforma ||
    (
      currency !== null &&
      currency !== "AED"
    );

  const unresolvedFields = Array.isArray(
    invoice.unresolved_fields
  )
    ? invoice.unresolved_fields
    : Array.isArray(docling?.unresolved_fields)
      ? docling.unresolved_fields
      : [];

  // ==========================================================
  // SOURCE LOCATION
  // ==========================================================

  const sourceLocation = [
    invoice.source_page
      ? `Page ${invoice.source_page}`
      : null,

    invoice.source_worksheet
      ? `Worksheet ${invoice.source_worksheet}`
      : null,

    invoice.source_row
      ? `Row ${invoice.source_row}`
      : null,
  ].filter(Boolean);

  const worksheetNames = Array.isArray(
    metadata.worksheet_names
  )
    ? metadata.worksheet_names.map(String).join(", ")
    : "";

  // ==========================================================
  // PRIVACY DETAILS
  // ==========================================================

  const privacyMode =
    String(
      privacy.mode ||
      structuredExtraction.processing_mode ||
      "Not recorded"
    );

  const aiCalled =
    privacy.ai_called === true;

  const privacyGate =
    aiCalled
      ? privacy.outbound_privacy_check_passed === true
        ? "Passed"
        : "Failed or not established"
      : privacy.outbound_privacy_check_passed === false
        ? "Failed"
        : "Not applicable";

  let privacyMessage =
    "Privacy processing details are unavailable for this document.";

  if (privacyMode === "LOCAL_ONLY") {
    privacyMessage =
      "Document extraction was performed locally without external AI processing.";
  } else if (privacyMode === "REDACTED_AI") {
    privacyMessage =
      "AI interpretation used sanitized information according to the recorded privacy workflow.";
  } else if (
    privacyMode === "MANUAL_REVIEW_REQUIRED"
  ) {
    privacyMessage =
      "Administrator review is required before this document can proceed through the accounting workflow.";
  }

  // ==========================================================
  // PREVIEW STATE
  // ==========================================================

  const isPdf = document.original_filename
    .toLowerCase()
    .endsWith(".pdf");

  const text =
    typeof rawExtraction.text === "string"
      ? rawExtraction.text.slice(0, 10000)
      : "";

  const [preview, setPreview] =
    useState<PreviewState>({
      documentId: document.id,
      url: "",
      error: "",
      loading: true,
    });

  useEffect(() => {
    let active = true;
    let objectUrl = "";

    getDocumentPreview(document.id)
      .then((blob) => {
        if (!active) return;

        objectUrl = URL.createObjectURL(blob);

        setPreview({
          documentId: document.id,
          url: objectUrl,
          error: "",
          loading: false,
        });
      })
      .catch((error: unknown) => {
        if (!active) return;

        setPreview({
          documentId: document.id,
          url: "",
          error:
            error instanceof Error
              ? error.message
              : "Unable to load source document.",
          loading: false,
        });
      });

    return () => {
      active = false;

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [document.id]);

  const currentPreview =
    preview.documentId === document.id;

  const previewUrl =
    currentPreview ? preview.url : "";

  const previewError =
    currentPreview ? preview.error : "";

  const previewLoading =
    !currentPreview || preview.loading;

  // ==========================================================
  // ORIGINAL INVOICE DETAILS
  // ==========================================================

  const originalRows: DetailRow[] = [
    {
      label: "Supplier",
      value: invoice.supplier_name,
    },
    {
      label: "Supplier TRN",
      value: invoice.supplier_trn,
    },
    {
      label: "Buyer",
      value: invoice.customer_name,
    },
    {
      label: "Buyer TRN",
      value: invoice.customer_trn,
    },
    {
      label: "Invoice number",
      value: invoice.invoice_number,
    },
    {
      label: "Document type",
      value: formatDocumentType(
        documentType
      ),
    },
    {
      label: "Currency",
      value: currency,
    },
    {
      label: "Invoice date",
      value: invoice.issue_date,
    },
    {
      label: "Due date",
      value: invoice.due_date,
    },
    {
      label: "Payment terms",
      value: invoice.payment_terms,
    },
    {
      label: "Original subtotal",
      value: formatMoney(
        sourceSubtotal,
        currency
      ),
    },
    {
      label: "Subtotal before discount",
      value: formatMoney(
        sourceSubtotalBeforeDiscount,
        currency
      ),
    },
    {
      label: "Original discount",
      value: formatMoney(
        sourceDiscount,
        currency
      ),
    },
    {
      label: "Original tax",
      value: formatMoney(
        sourceTax,
        currency
      ),
    },
    {
      label: "Original grand total",
      value: formatMoney(
        sourceTotal,
        currency
      ),
    },
  ];

  // ==========================================================
  // JSX
  // ==========================================================

  return (
    <aside className="document-card">

      {/* DOCUMENT HEADER */}

      <div className="d-flex justify-content-between align-items-start gap-2">
        <div>
          <div className="document-kicker">
            SOURCE DOCUMENT
          </div>

          <h2 className="document-section-title text-break">
            {document.original_filename}
          </h2>
        </div>

        <DocumentStatusBadge
          status={document.processing_status}
        />
      </div>

      {/* FILE METADATA */}

      <dl className="document-meta-grid mt-3 mb-0">
        <div>
          <dt>Document ID</dt>
          <dd>#{document.id}</dd>
        </div>

        <div>
          <dt>File type</dt>
          <dd className="text-uppercase">
            {document.file_type || "Unknown"}
          </dd>
        </div>

        <div>
          <dt>Uploaded</dt>
          <dd>{readableDate(document.uploaded_at)}</dd>
        </div>

        <div>
          <dt>File size</dt>
          <dd>
            {formatFileSize(
              document.file_size
            )}
          </dd>
        </div>

        <div>
          <dt>Extraction</dt>
          <dd>
            {detailValue(
              invoice.extraction_method ??
              rawExtraction.extraction_method ??
              data.processing_status
            )}
          </dd>
        </div>

        <div>
          <dt>Source location</dt>
          <dd>
            {sourceLocation.length
              ? sourceLocation.join(" · ")
              : "Not provided by extraction"}
          </dd>
        </div>
      </dl>

      {/* PRIVACY INFORMATION */}

      <div className="border-top mt-4 pt-3">
        <h3 className="document-subtitle">
          Privacy-first processing
        </h3>

        <p className="small text-secondary mb-2">
          {privacyMessage}
        </p>

        <dl className="document-meta-grid mb-0">
          <div>
            <dt>Processing method</dt>
            <dd>{privacyMode}</dd>
          </div>

          <div>
            <dt>External AI used</dt>
            <dd>
              {privacy.ai_called === undefined
                ? "Not recorded"
                : aiCalled
                  ? "Yes"
                  : "No"}
            </dd>
          </div>

          <div>
            <dt>Privacy gate</dt>
            <dd>
              {privacy.ai_called === undefined
                ? "Not recorded"
                : privacyGate}
            </dd>
          </div>

          <div>
            <dt>Admin review</dt>
            <dd>
              {reviewRequired
                ? "Required"
                : "Subject to validation"}
            </dd>
          </div>

          {typeof privacy.processing_reason === "string" && (
            <div>
              <dt>Processing reason</dt>
              <dd>{privacy.processing_reason}</dd>
            </div>
          )}
        </dl>
      </div>

      {/* ORIGINAL EXTRACTED VALUES */}

      {Object.keys(invoice).length > 0 && (
        <div className="border-top mt-4 pt-3">
          <h3 className="document-subtitle">
            Original extracted values
          </h3>

          <p className="small text-secondary mb-3">
            Values are shown in the document&apos;s
            original currency. No foreign-exchange conversion
            is applied.
          </p>

          <DetailGrid rows={originalRows} />

          <div className="d-flex flex-wrap gap-2 mt-3">
            <span className="badge text-bg-light border">
              {currency || "Currency unknown"}
            </span>

            <span
              className={`badge ${reconciliationClass(
                sourceReconciled
              )}`}
            >
              {formatReconciliation(
                sourceReconciled
              )}
            </span>

            {isProforma && (
              <span className="badge text-bg-warning">
                Proforma invoice
              </span>
            )}
          </div>

          {hasSourceEvidence && (
            <div className="small text-secondary mt-3">
              <strong>Original-currency source rows:</strong>{" "}
              {sourceItems.length}
            </div>
          )}

          {!hasSourceEvidence && isAED && (
            <div className="small text-secondary mt-3">
              This older AED document uses the legacy accounting
              representation with {accountingItems.length} line
              item(s). Separate reconstructed source-currency
              rows were not recorded.
            </div>
          )}

          {currency && currency !== "AED" && (
            <div className="alert alert-info py-2 small mt-3 mb-0">
              This document uses {currency}. Its financial
              amounts are source evidence only and must not
              be posted directly to the AED invoice ledger.
            </div>
          )}
        </div>
      )}

      {/* DOCLING AND RECONCILIATION */}

      {(docling || hasSourceEvidence) && (
        <div className="border-top mt-4 pt-3">
          <h3 className="document-subtitle">
            Extraction & reconciliation
          </h3>

          <dl className="document-meta-grid mb-0">
            <div>
              <dt>Docling worker</dt>
              <dd>
                {doclingUsed
                  ? "Used"
                  : docling
                    ? "Not used"
                    : "Not recorded"}
              </dd>
            </div>

            <div>
              <dt>Worker status</dt>
              <dd>{doclingStatus}</dd>
            </div>

            <div>
              <dt>Reconstructed rows</dt>
              <dd>{reconstructedCount}</dd>
            </div>

            <div>
              <dt>Financial reconciliation</dt>
              <dd>
                {formatReconciliation(
                  sourceReconciled
                )}
              </dd>
            </div>

            {docling?.processing_seconds != null && (
              <div>
                <dt>Processing time</dt>
                <dd>
                  {Number(
                    docling.processing_seconds
                  ).toFixed(2)}{" "}
                  seconds
                </dd>
              </div>
            )}

            {docling?.financial_status && (
              <div>
                <dt>Financial status</dt>
                <dd>
                  {String(
                    docling.financial_status
                  ).replaceAll("_", " ")}
                </dd>
              </div>
            )}
          </dl>

          {unresolvedFields.length > 0 && (
            <div className="alert alert-warning small py-2 mt-3 mb-0">
              <strong>Fields requiring review:</strong>{" "}
              {unresolvedFields
                .map((field) =>
                  field.replaceAll("_", " ")
                )
                .join(", ")}
            </div>
          )}
        </div>
      )}

      {/* EXTRACTION WARNINGS */}

      {document.extraction_notes && (
        <div className="alert alert-warning py-2 small mt-3 mb-0">
          {document.extraction_notes}
        </div>
      )}

      {/* REJECTION */}

      {document.processing_status === "rejected" && (
        <div className="alert alert-danger py-2 small mt-3 mb-0">
          <strong>Rejection reason:</strong>{" "}
          {detailValue(
            rejection.reason ??
            document.extraction_notes
          )}
        </div>
      )}

      {/* DOCUMENT PREVIEW */}

      <div className="border-top mt-4 pt-3">
        <h3 className="document-subtitle">
          Document preview
        </h3>

        {previewLoading && (
          <div
            className="small text-secondary"
            role="status"
          >
            Loading original document…
          </div>
        )}

        {previewError && (
          <div
            className="alert alert-warning py-2 small"
            role="alert"
          >
            {previewError}
          </div>
        )}

        {previewUrl && (
          <>
            <div className="d-flex justify-content-between align-items-center gap-2 mb-2">
              <p className="small text-secondary mb-0">
                {isPdf
                  ? "Original PDF preview. Use the viewer controls to zoom or navigate pages."
                  : "This file format is not supported by the browser's inline viewer."}
              </p>

              <a
                className="btn btn-sm btn-outline-primary flex-shrink-0"
                href={previewUrl}
                download={
                  document.original_filename
                }
              >
                <i className="bi bi-download me-1" />
                Download original
              </a>
            </div>

            {isPdf ? (
              <iframe
                className="document-source-preview"
                src={previewUrl}
                title={`Original source document: ${document.original_filename}`}
              />
            ) : text ? (
              <pre className="document-text-preview">
                {text}
              </pre>
            ) : (
              <div className="small text-secondary">
                No inline preview is available for this file type.
              </div>
            )}
          </>
        )}

        {!previewLoading && !previewUrl && text && (
          <>
            <p className="small text-secondary">
              Showing extracted text because the original
              file preview is unavailable.
            </p>

            <pre className="document-text-preview">
              {text}
            </pre>
          </>
        )}

        {!previewLoading && !previewUrl && !text && (
          <div className="small text-secondary">
            No document preview is available.
          </div>
        )}
      </div>

      {/* WORKSHEET NAMES */}

      {worksheetNames && (
        <div className="small mt-3">
          <strong>Worksheets:</strong>{" "}
          {worksheetNames}
        </div>
      )}

      {/* APPROVED INVOICE LINKS */}

      {document.invoice_id !== null && (
        <div className="border-top mt-4 pt-3">
          <h3 className="document-subtitle">
            Approved invoice records
          </h3>

          <Link
            className="btn btn-outline-success btn-sm"
            href={`/invoices/${document.invoice_id}`}
          >
            <i className="bi bi-box-arrow-up-right me-2" />
            View invoice #{document.invoice_id}
          </Link>
        </div>
      )}

      {Object.entries(approvals)
        .filter(([, value]) => {
          const approval = objectValue(value);

          return Number(
            approval.invoice_id
          ) !== document.invoice_id;
        })
        .map(([index, value]) => {
          const approval = objectValue(value);

          const invoiceId = Number(
            approval.invoice_id
          );

          if (
            !Number.isInteger(invoiceId) ||
            invoiceId <= 0
          ) {
            return null;
          }

          return (
            <Link
              className="btn btn-outline-success btn-sm mt-2 me-2"
              href={`/invoices/${invoiceId}`}
              key={index}
            >
              View approved invoice #{invoiceId}
            </Link>
          );
        })}
    </aside>
  );
}
