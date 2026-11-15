
"use client";

import { useId } from "react";
import type { CSSProperties } from "react";

import type {
  DecimalString,
  InvoiceFinancialSummary,
  InvoiceGenerationValidationResponse,
  InvoiceLineCalculation,
} from "@/lib/invoice-generation-types";

/**
 * ReceivAI UAE — server-calculated invoice totals and validation panel.
 *
 * Controlled presentation component: no fetch, no financial arithmetic,
 * no JavaScript floating-point conversions, and no database side effects.
 *
 * The parent calls POST /api/invoice-generation/validate and passes the
 * response through `validation`. Set `isStale=true` whenever form values
 * change, so old financial totals are never displayed as current.
 */

export interface InvoiceTotalsPanelProps {
  validation?: InvoiceGenerationValidationResponse | null;
  isLoading?: boolean;
  isStale?: boolean;
  disabled?: boolean;
  showLineBreakdown?: boolean;
  onRecalculate?: () => void;
}

const cardStyle: CSSProperties = {
  background: "#fff",
  border: "1px solid #e1eaf2",
  borderRadius: 18,
  boxShadow: "0 5px 20px rgba(24, 54, 84, 0.045)",
};

const mutedStyle: CSSProperties = {
  color: "#73859b",
  fontSize: 12,
};

const labelStyle: CSSProperties = {
  color: "#506581",
  fontSize: 13,
};

const numericStyle: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
};

/**
 * Format an exact decimal response without rounding or using Number().
 * The API supplies monetary values as decimal strings (typically 2 dp).
 * We preserve additional decimal places instead of silently changing them.
 */
export function formatInvoiceAED(
  value: DecimalString | null | undefined,
): string {
  if (value == null) return "—";

  const raw = value.trim();
  if (!/^-?\d+(?:\.\d+)?$/.test(raw)) return "—";

  const negative = raw.startsWith("-");
  const unsigned = negative ? raw.slice(1) : raw;
  const [integer, decimal = ""] = unsigned.split(".");

  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = decimal.padEnd(2, "0");

  return `${negative ? "-" : ""}${grouped}.${fraction}`;
}

function AmountRow({
  label,
  amount,
  hint,
}: {
  label: string;
  amount: DecimalString | null | undefined;
  hint?: string;
}) {
  return (
    <div className="d-flex align-items-start justify-content-between gap-3 py-2">
      <div>
        <span style={labelStyle}>{label}</span>
        {hint && (
          <div style={mutedStyle}>{hint}</div>
        )}
      </div>
      <span
        className="fw-semibold"
        style={{ ...numericStyle, color: "#203551" }}
      >
        {formatInvoiceAED(amount)}
      </span>
    </div>
  );
}

function LineBreakdown({
  rows,
}: {
  rows: InvoiceLineCalculation[];
}) {
  return (
    <details className="mt-3 pt-3 border-top">
      <summary
        className="fw-semibold"
        style={{ color: "#087f7b", fontSize: 13, cursor: "pointer" }}
      >
        View calculated line items ({rows.length})
      </summary>

      <div className="d-grid gap-2 mt-3">
        {rows.map((row, index) => (
          <div
            className="rounded-3 p-3"
            key={index}
            style={{
              background: "#f8fafc",
              border: "1px solid #e6edf4",
            }}
          >
            <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
              <span
                className="fw-semibold"
                style={{
                  color: "#203551",
                  fontSize: 12,
                  overflowWrap: "anywhere",
                }}
              >
                {index + 1}. {row.description || "Untitled item"}
              </span>
              <span
                className="fw-bold"
                style={{
                  ...numericStyle,
                  color: "#142b45",
                  fontSize: 12,
                }}
              >
                {formatInvoiceAED(row.line_total_aed)}
              </span>
            </div>

            <div className="d-flex flex-wrap gap-3" style={mutedStyle}>
              <span>Gross: {formatInvoiceAED(row.gross_value_aed)}</span>
              <span>Discount: {formatInvoiceAED(row.discount_aed)}</span>
              <span>Taxable: {formatInvoiceAED(row.taxable_value_aed)}</span>
              <span>VAT: {formatInvoiceAED(row.vat_amount_aed)}</span>
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

export default function InvoiceTotalsPanel({
  validation = null,
  isLoading = false,
  isStale = false,
  disabled = false,
  showLineBreakdown = true,
  onRecalculate,
}: InvoiceTotalsPanelProps) {
  const idPrefix = useId().replace(/:/g, "");

  // Hide cached totals and messages as soon as form inputs become stale.
  // Display numbers only from a completed validation for the current form.
  const isCurrent = !isLoading && !isStale && validation !== null;

  const calculated: InvoiceFinancialSummary | null = isCurrent
    ? validation?.calculated ?? null
    : null;

  const errors = isCurrent ? validation?.errors ?? [] : [];
  const warnings = isCurrent ? validation?.warnings ?? [] : [];

  const completeTotal =
    calculated?.total_amount_aed !== null &&
    calculated?.total_amount_aed !== undefined;

  const ready =
    isCurrent &&
    validation?.is_valid === true &&
    completeTotal;

  const statusLabel = isLoading
    ? "Calculating"
    : isStale
      ? "Needs refresh"
      : !isCurrent
        ? "Not validated"
        : ready
          ? "Validated"
          : "Needs attention";

  const statusColor = ready
    ? "#087f7b"
    : isCurrent && errors.length > 0
      ? "#b54745"
      : "#64748b";

  const statusIcon = isLoading
    ? "bi-arrow-repeat"
    : ready
      ? "bi-check-circle-fill"
      : isCurrent && errors.length > 0
        ? "bi-exclamation-circle-fill"
        : "bi-clock-history";

  return (
    <section
      className="p-3 p-md-4"
      style={cardStyle}
      aria-labelledby={`${idPrefix}-title`}
    >
      {/* PANEL HEADER */}
      <div className="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
        <div>
          <h2
            id={`${idPrefix}-title`}
            className="h5 fw-bold mb-1"
            style={{ color: "#142b45" }}
          >
            Invoice totals
          </h2>
          <p className="mb-0" style={mutedStyle}>
            Exact amounts calculated and validated by FastAPI.
          </p>
        </div>

        {onRecalculate && (
          <button
            type="button"
            className="btn btn-outline-primary btn-sm"
            disabled={disabled || isLoading}
            onClick={onRecalculate}
          >
            <i
              className="bi bi-arrow-clockwise me-1"
              aria-hidden="true"
            />
            {isLoading ? "Calculating..." : "Validate totals"}
          </button>
        )}
      </div>

      {/* CALCULATION STATUS */}
      <div
        className="d-flex align-items-center gap-2 mb-3"
        role="status"
        aria-live="polite"
        style={{
          color: statusColor,
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        {isLoading ? (
          <span
            className="spinner-border spinner-border-sm"
            role="presentation"
            aria-hidden="true"
          />
        ) : (
          <i
            className={`bi ${statusIcon}`}
            aria-hidden="true"
          />
        )}
        <span>{statusLabel}</span>
      </div>

      {/* SERVER-CALCULATED AMOUNTS */}
      <div
        className="rounded-3 p-3"
        style={{
          background: "#fbfdff",
          border: "1px solid #e5edf4",
        }}
      >
        <div className="d-flex justify-content-between align-items-center mb-2">
          <span
            style={{
              ...labelStyle,
              fontWeight: 700,
            }}
          >
            AMOUNTS
          </span>
          <span className="badge rounded-pill bg-light text-secondary border">
            AED
          </span>
        </div>

        <AmountRow
          label="Taxable subtotal"
          hint="After line-item discounts"
          amount={calculated?.subtotal_aed}
        />

        <AmountRow
          label="Line-item discounts"
          hint="Included in taxable subtotal"
          amount={calculated?.discount_aed}
        />

        <AmountRow
          label="VAT amount"
          hint="From each item's selected VAT rate"
          amount={calculated?.vat_amount_aed}
        />

        <div
          className="d-flex align-items-center justify-content-between gap-3 mt-2 pt-3"
          style={{
            borderTop: "1px solid #dce5ef",
          }}
        >
          <div>
            <div
              className="fw-bold"
              style={{
                color: "#142b45",
                fontSize: 15,
              }}
            >
              Total payable
            </div>
            <div style={mutedStyle}>
              Taxable subtotal + VAT
            </div>
          </div>
          <strong
            className="text-end"
            style={{
              ...numericStyle,
              color: "#087f7b",
              fontSize: 22,
            }}
          >
            {formatInvoiceAED(calculated?.total_amount_aed)}
          </strong>
        </div>
      </div>

      <p className="mb-0 mt-2" style={mutedStyle}>
        Discounts are already reflected in the taxable subtotal;
        do not subtract them twice.
      </p>

      {/* EMPTY, STALE OR LOADING STATE */}
      {!isCurrent && (
        <div
          className="mt-3 rounded-3 p-3"
          style={{
            background: "#f3f7fb",
            color: "#506581",
            fontSize: 13,
          }}
        >
          {isLoading
            ? "Checking invoice lines, discounts and VAT with the backend..."
            : isStale
              ? "Invoice details have changed. Validate again to refresh the displayed totals."
              : "Enter invoice details, then select Validate totals to see the calculated amounts."}
        </div>
      )}

      {/* VALIDATION ERRORS */}
      {errors.length > 0 && (
        <div
          className="alert alert-danger mt-3 mb-0"
          role="alert"
        >
          <div className="fw-semibold mb-2">
            <i
              className="bi bi-exclamation-triangle me-2"
              aria-hidden="true"
            />
            Resolve before finalizing ({errors.length})
          </div>
          <ul
            className="mb-0 ps-3"
            style={{ fontSize: 13 }}
          >
            {errors.map((message, index) => (
              <li key={`${index}-${message}`}>
                {message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* VALIDATION WARNINGS */}
      {warnings.length > 0 && (
        <div
          className="alert alert-warning mt-3 mb-0"
          role="note"
        >
          <div className="fw-semibold mb-2">
            <i
              className="bi bi-info-circle me-2"
              aria-hidden="true"
            />
            Review before finalizing ({warnings.length})
          </div>
          <ul
            className="mb-0 ps-3"
            style={{ fontSize: 13 }}
          >
            {warnings.map((message, index) => (
              <li key={`${index}-${message}`}>
                {message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* VALIDATED CONFIRMATION */}
      {ready && errors.length === 0 && (
        <div
          className="d-flex align-items-start gap-2 mt-3"
          style={{
            color: "#087f7b",
            fontSize: 13,
          }}
        >
          <i
            className="bi bi-shield-check"
            aria-hidden="true"
          />
          <span>
            The backend accepted the current invoice details.
            Finalization will revalidate the saved draft and
            calculate the totals again.
          </span>
        </div>
      )}

      {/* OPTIONAL ROW-BY-ROW DETAIL */}
      {showLineBreakdown &&
        calculated &&
        calculated.line_items.length > 0 && (
          <LineBreakdown
            rows={calculated.line_items}
          />
        )}
    </section>
  );
}
