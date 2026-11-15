
"use client";

/**
 * ReceivAI UAE — AI Financial Assistant Results
 *
 * Displays structured financial data returned by the
 * authenticated Finance Assistant backend.
 *
 * This component is used inside FinanceAssistant.tsx.
 * All financial amounts are supplied by the backend.
 * No payment or invoice modifications are performed.
 */

import Link from "next/link";
import { useState } from "react";

import {
  formatFinanceAED,
  type FinanceAssistantChatResponse,
  type FinanceDataSource,
  type FinanceDataTable,
  type FinanceTableCell,
  type FinanceValueType,
} from "@/lib/finance-assistant-api";

// ============================================================
// PROPS
// ============================================================

export interface AssistantResultsProps {
  result: FinanceAssistantChatResponse;
  onQuestion?: (question: string) => void;
  disabled?: boolean;
}

// ============================================================
// SOURCE LABELS
// ============================================================

const SOURCE_LABELS: Record<FinanceDataSource, string> = {
  dashboard_summary: "Dashboard summary",
  invoice_register: "Invoice register",
  payment_ledger: "Payment ledger",
  payment_collections: "Payment Collections",
  cash_flow_forecast: "Cash Flow Forecast",
  document_intelligence: "Document Intelligence",
  collection_reminders: "Collection reminders",
};

// ============================================================
// SAFE INTERNAL NAVIGATION
// ============================================================

function safeInternalHref(href: string): string | null {
  if (
    !href.startsWith("/") ||
    href.startsWith("//") ||
    /[\\\u0000-\u001F\u007F]/.test(href)
  ) {
    return null;
  }

  try {
    const parsed = new URL(
      href,
      "https://receivai.invalid",
    );

    return parsed.origin === "https://receivai.invalid"
      ? href
      : null;
  } catch {
    return null;
  }
}

// ============================================================
// DATE FORMATTING
// ============================================================

function formatFinanceDate(
  value: string | null | undefined,
  withTime = false,
): string {
  if (!value) return "—";

  const dateOnly =
    /^\d{4}-\d{2}-\d{2}$/.test(value);

  const date = new Date(
    dateOnly
      ? `${value}T12:00:00+04:00`
      : value,
  );

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime && !dateOnly
      ? {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }
      : {}),
    timeZone: "Asia/Dubai",
  }).format(date);
}

// ============================================================
// VALUE FORMATTING
// ============================================================

function displayValue(
  value: FinanceTableCell | undefined,
  type: FinanceValueType,
): string {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "—";
  }

  if (type === "aed") {
    // Values are formatted, not recalculated.
    return typeof value === "string"
      ? formatFinanceAED(value)
      : "—";
  }

  if (type === "percent") {
    const text = String(value);

    return text.endsWith("%")
      ? text
      : `${text}%`;
  }

  if (type === "date") {
    return formatFinanceDate(String(value));
  }

  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }

  return String(value);
}

function natureLabel(
  nature: "recorded" | "calculated" | "estimated",
): string {
  if (nature === "estimated") {
    return "Forecast estimate";
  }

  if (nature === "calculated") {
    return "Calculated from records";
  }

  return "Recorded data";
}

// ============================================================
// FINANCIAL DATA TABLE
// ============================================================

function DataTable({
  table,
}: {
  table: FinanceDataTable;
}) {
  const [showAll, setShowAll] = useState(false);

  const visibleRows = showAll
    ? table.rows
    : table.rows.slice(0, 8);

  const hasMoreLoaded =
    table.rows.length > 8;

  const totalAvailable = Math.max(
    table.rows.length,
    table.total_rows ?? 0,
  );

  return (
    <section
      className="rfa-table-card"
      aria-label={table.title}
    >
      <div className="rfa-table-title">
        <strong>{table.title}</strong>

        <span>
          {natureLabel(table.nature)}
        </span>
      </div>

      {table.description && (
        <p className="rfa-table-desc">
          {table.description}
        </p>
      )}

      <div
        className="rfa-table-scroll"
        role="region"
        aria-label={`${table.title} table`}
        tabIndex={0}
      >
        <table>
          <caption className="visually-hidden">
            {table.title}
          </caption>

          <thead>
            <tr>
              {table.columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={index}>
                {table.columns.map((column) => {
                  const text = displayValue(
                    row[column.key],
                    column.value_type,
                  );

                  // Link invoice numbers when a valid ID exists.
                  const invoiceId = row.invoice_id;

                  const linkedInvoiceNumber =
                    column.key === "invoice_number" &&
                    typeof invoiceId === "number" &&
                    Number.isSafeInteger(invoiceId) &&
                    invoiceId > 0;

                  return (
                    <td
                      key={column.key}
                      className={
                        column.value_type === "aed"
                          ? "rfa-money"
                          : undefined
                      }
                    >
                      {linkedInvoiceNumber ? (
                        <Link
                          href={`/invoices/${invoiceId}`}
                        >
                          {text}
                        </Link>
                      ) : (
                        text
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}

            {visibleRows.length === 0 && (
              <tr>
                <td
                  colSpan={table.columns.length}
                  className="rfa-table-empty"
                >
                  No matching records returned.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="rfa-table-footer">
        <span>
          Showing {visibleRows.length} of{" "}
          {table.rows.length} loaded record(s)

          {totalAvailable > table.rows.length
            ? ` · ${totalAvailable} total`
            : ""}
        </span>

        {hasMoreLoaded && (
          <button
            type="button"
            className="rfa-text-button"
            aria-expanded={showAll}
            onClick={() =>
              setShowAll((value) => !value)
            }
          >
            {showAll
              ? "Show fewer"
              : `Show all ${table.rows.length} loaded`}
          </button>
        )}
      </div>
    </section>
  );
}

// ============================================================
// MAIN RESULTS COMPONENT
// ============================================================

export default function AssistantResults({
  result,
  onQuestion,
  disabled = false,
}: AssistantResultsProps) {
  const [showAllInvoices, setShowAllInvoices] =
    useState(false);

  const invoices = showAllInvoices
    ? result.invoices
    : result.invoices.slice(0, 8);

  const hasForecastData =
    result.intent === "cash_flow_forecast" ||
    result.metrics.some(
      (metric) => metric.nature === "estimated",
    ) ||
    result.tables.some(
      (table) => table.nature === "estimated",
    );

  const hasPaymentData =
    result.intent === "payment_history" ||
    result.intent === "reconciliation";

  return (
    <div className="rfa-answer-details">

      {/* INCOMPLETE RESPONSE WARNING */}

      {result.status === "partial" && (
        <div
          className="rfa-warnings"
          role="status"
        >
          <i
            className="bi bi-exclamation-triangle"
            aria-hidden="true"
          />

          <span>
            Some requested records were unavailable.
            The results below may be incomplete.
          </span>
        </div>
      )}

      {/* NO DATA */}

      {result.status === "no_data" && (
        <div
          className="rfa-insight rfa-insight-info"
          role="status"
        >
          <i
            className="bi bi-info-circle"
            aria-hidden="true"
          />

          <div>
            <strong>
              No matching financial records
            </strong>

            <p>
              The requested information was not
              available in the returned dataset.
            </p>
          </div>
        </div>
      )}

      {/* FINANCIAL METRICS */}

      {result.metrics.length > 0 && (
        <section
          aria-label="Financial metrics"
          className="rfa-metric-grid"
        >
          {result.metrics.map((metric, index) => (
            <div
              className="rfa-metric"
              key={`${metric.source}-${metric.key}-${index}`}
            >
              <span className="rfa-metric-label">
                {metric.label}
              </span>

              <strong>
                {displayValue(
                  metric.value,
                  metric.value_type,
                )}
              </strong>

              <span className="rfa-metric-meta">
                {natureLabel(metric.nature)}
                {" · "}
                {metric.description ||
                  SOURCE_LABELS[metric.source]}
              </span>
            </div>
          ))}
        </section>
      )}

      {/* STRUCTURED FINANCIAL TABLES */}

      {result.tables.map((table, index) => (
        <DataTable
          key={`${table.source}-${table.title}-${index}`}
          table={table}
        />
      ))}

      {/* RELATED INVOICES */}

      {result.invoices.length > 0 && (
        <section
          className="rfa-linked-invoices"
          aria-label="Related invoice records"
        >
          <strong>Related invoices</strong>

          <div className="rfa-chip-row">
            {invoices.map((invoice) => (
              <Link
                className="rfa-link-chip"
                href={`/invoices/${invoice.invoice_id}`}
                key={invoice.invoice_id}
                title={[
                  invoice.customer_name,
                  invoice.outstanding_aed !== null
                    ? `Outstanding ${formatFinanceAED(
                        invoice.outstanding_aed,
                      )}`
                    : null,
                  invoice.due_date
                    ? `Due ${formatFinanceDate(
                        invoice.due_date,
                      )}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              >
                <i
                  className="bi bi-receipt"
                  aria-hidden="true"
                />

                {invoice.invoice_number}

                <i
                  className="bi bi-arrow-up-right"
                  aria-hidden="true"
                />
              </Link>
            ))}
          </div>

          {result.invoices.length > 8 && (
            <button
              type="button"
              className="rfa-text-button"
              aria-expanded={showAllInvoices}
              onClick={() =>
                setShowAllInvoices(
                  (value) => !value,
                )
              }
            >
              {showAllInvoices
                ? "Show fewer invoices"
                : `Show ${
                    result.invoices.length - 8
                  } more related invoices`}
            </button>
          )}
        </section>
      )}

      {/* FINANCIAL INSIGHTS */}

      {result.insights.length > 0 && (
        <section
          className="rfa-insight-list"
          aria-label="Analysis and recommendations"
        >
          {result.insights.map(
            (insight, index) => (
              <div
                className={`rfa-insight rfa-insight-${insight.severity}`}
                key={`${insight.title}-${index}`}
              >
                <i
                  aria-hidden="true"
                  className={`bi ${
                    insight.severity === "critical"
                      ? "bi-exclamation-octagon"
                      : insight.severity === "warning"
                        ? "bi-exclamation-circle"
                        : "bi-lightbulb"
                  }`}
                />

                <div>
                  <strong>
                    {insight.title}
                  </strong>

                  <p>
                    {insight.explanation}
                  </p>

                  {insight.recommended_action && (
                    <small>
                      Suggested action:{" "}
                      {insight.recommended_action}
                    </small>
                  )}

                  {insight.nature === "estimated" && (
                    <small>
                      Recommendation based on
                      forecast assumptions.
                    </small>
                  )}
                </div>
              </div>
            ),
          )}
        </section>
      )}

      {/* BACKEND WARNINGS */}

      {result.warnings.length > 0 && (
        <div
          className="rfa-warnings"
          role="note"
        >
          <i
            className="bi bi-info-circle"
            aria-hidden="true"
          />

          <div>
            {result.warnings.map(
              (warning, index) => (
                <p key={index}>
                  {warning}
                </p>
              ),
            )}
          </div>
        </div>
      )}

      {/* FORECAST AND PAYMENT DISCLAIMERS */}

      {(hasForecastData || hasPaymentData) && (
        <div
          className="rfa-warnings"
          role="note"
        >
          <i
            className="bi bi-shield-exclamation"
            aria-hidden="true"
          />

          <div>
            {hasForecastData && (
              <p>
                Forecast cash amounts are estimates,
                not guaranteed receipts.
              </p>
            )}

            {hasPaymentData && (
              <p>
                Recorded payments are not independently
                bank-verified.
              </p>
            )}
          </div>
        </div>
      )}

      {/* RELATED MODULE LINKS */}

      {result.actions.length > 0 && (
        <nav
          className="rfa-chip-row rfa-action-row"
          aria-label="Related finance pages"
        >
          {result.actions.map(
            (action, index) => {
              const href = safeInternalHref(
                action.href,
              );

              return href ? (
                <Link
                  key={`${href}-${index}`}
                  href={href}
                  title={
                    action.description ||
                    undefined
                  }
                  className="rfa-action-link"
                >
                  {action.label}

                  <i
                    className="bi bi-arrow-up-right"
                    aria-hidden="true"
                  />
                </Link>
              ) : null;
            },
          )}
        </nav>
      )}

      {/* FOLLOW-UP QUESTIONS */}

      {result.follow_up_questions.length > 0 &&
        onQuestion && (
          <div className="rfa-followups">
            <span>
              Continue exploring
            </span>

            <div className="rfa-chip-row">
              {result.follow_up_questions.map(
                (question, index) => (
                  <button
                    type="button"
                    key={`${question}-${index}`}
                    className="rfa-prompt-chip"
                    disabled={disabled}
                    onClick={() =>
                      onQuestion(question)
                    }
                  >
                    {question}

                    <i
                      className="bi bi-arrow-up-right"
                      aria-hidden="true"
                    />
                  </button>
                ),
              )}
            </div>
          </div>
        )}

      {/* SOURCE EVIDENCE */}

      <div className="rfa-evidence-footer">
        <i
          className="bi bi-shield-check"
          aria-hidden="true"
        />

        <div>
          <strong>
            Read-only analysis · {result.currency}
          </strong>

          {result.data_as_of && (
            <span>
              {" · "}Data as of{" "}
              {formatFinanceDate(
                result.data_as_of,
                true,
              )}{" "}
              (UAE)
            </span>
          )}

          {result.evidence.length > 0 && (
            <div>
              {result.evidence.map(
                (evidence, index) => (
                  <div
                    key={`${evidence.source}-${index}`}
                  >
                    {SOURCE_LABELS[evidence.source]}
                    {" ("}
                    {natureLabel(evidence.nature)}
                    {"): "}
                    {evidence.description}

                    {evidence.as_of &&
                      ` · ${formatFinanceDate(
                        evidence.as_of,
                        true,
                      )} (UAE)`}
                  </div>
                ),
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
