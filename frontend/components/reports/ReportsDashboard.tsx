
"use client";

/**
 * ReceivAI UAE — Financial Reports Dashboard
 * Read-only reporting using authenticated backend data.
 */

import Link from "next/link";

import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { formatFinanceAED } from "@/lib/finance-assistant-api";

import {
  exportFinancialReportCSV,
  getFinancialReports,
  type ReportFilters,
  type ReportInvoice,
  type ReportsDashboardResponse,
  type ReportKind,
  type ReportPayment,
} from "@/lib/reports-api";

// ============================================================
// REPORT CATEGORIES
// ============================================================

const SECTIONS: {
  id: ReportKind;
  title: string;
  icon: string;
  sub: string;
}[] = [
  {
    id: "aging",
    title: "Receivables Aging",
    icon: "bi-clock-history",
    sub: "Overdue balance buckets",
  },
  {
    id: "invoices",
    title: "Invoice Reports",
    icon: "bi-receipt",
    sub: "Invoices issued in period",
  },
  {
    id: "payments",
    title: "Payment Reports",
    icon: "bi-credit-card",
    sub: "Recorded ledger payments",
  },
  {
    id: "collections",
    title: "Collections",
    icon: "bi-wallet2",
    sub: "Reminder approval activity",
  },
  {
    id: "forecast",
    title: "Cash Flow",
    icon: "bi-graph-up-arrow",
    sub: "Estimated receipts",
  },
  {
    id: "documents",
    title: "Documents",
    icon: "bi-file-earmark-check",
    sub: "Upload and processing status",
  },
  {
    id: "reconciliation",
    title: "Reconciliation",
    icon: "bi-shield-exclamation",
    sub: "Status/ledger mismatches",
  },
];

// ============================================================
// UAE DATE AND CURRENCY HELPERS
// ============================================================

function uaeDate(): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Dubai",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).formatToParts(new Date());

  const part = (kind: string) =>
    parts.find((item) => item.type === kind)?.value || "";

  return `${part("year")}-${part("month")}-${part("day")}`;
}

function pastDays(days: number): ReportFilters {
  const endDate = uaeDate();

  const startDate = new Date(
    `${endDate}T12:00:00Z`
  );

  startDate.setUTCDate(
    startDate.getUTCDate() - days + 1
  );

  return {
    startDate: startDate.toISOString().slice(0, 10),
    endDate,
  };
}

function AED(value: string): string {
  return formatFinanceAED(value);
}

function dateText(value: string | null): string {
  if (!value) return "—";

  const [year, month, day] = value.split("-");

  if (!year || !month || !day) {
    return value;
  }

  const d = new Date(
    `${value}T12:00:00+04:00`
  );

  if (Number.isNaN(d.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Dubai",
  }).format(d);
}

// ============================================================
// BAR CHART COMPONENT
// ============================================================

function BarSeries({
  rows,
  money,
}: {
  rows: {
    label: string;
    amount: string;
    detail?: string;
  }[];
  money?: boolean;
}) {
  const max = Math.max(
    0,
    ...rows.map(
      (row) => Number(row.amount) || 0
    )
  );

  if (rows.length === 0) {
    return (
      <p className="rr-empty">
        No records are available for this chart.
      </p>
    );
  }

  return (
    <div className="rr-bars">
      {rows.map((row) => {
        const value = Number(row.amount) || 0;

        const width =
          max > 0 ? (value / max) * 100 : 0;

        return (
          <div
            className="rr-bar-item"
            key={row.label}
          >
            <div className="rr-bar-heading">
              <span>{row.label}</span>

              <strong>
                {money
                  ? AED(row.amount)
                  : row.amount}

                {row.detail
                  ? ` · ${row.detail}`
                  : ""}
              </strong>
            </div>

            <div
              className="rr-bar-track"
              role="meter"
              aria-valuenow={value}
              aria-valuemin={0}
              aria-valuemax={Math.max(max, 1)}
              aria-label={row.label}
            >
              <span
                style={{
                  width: `${width}%`,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ============================================================
// INVOICE REPORT TABLE
// ============================================================

function InvoiceTable({
  rows,
  showAging = false,
}: {
  rows: ReportInvoice[];
  showAging?: boolean;
}) {
  return (
    <div
      className="rr-table-scroll"
      role="region"
      aria-label="Invoice report"
      tabIndex={0}
    >
      <table className="rr-table">
        <thead>
          <tr>
            <th>Invoice</th>
            <th>Customer</th>
            <th>Issued</th>
            <th>Due</th>
            <th>Original total</th>
            <th>Recorded paid</th>
            <th>Outstanding</th>

            {showAging && (
              <th>Days overdue</th>
            )}

            <th>Ledger status</th>
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={row.invoice_id}>
              <td>
                <Link
                  href={`/invoices/${row.invoice_id}`}
                >
                  {row.invoice_number}
                </Link>
              </td>

              <td>{row.customer_name}</td>

              <td>
                {dateText(row.issue_date)}
              </td>

              <td>
                {dateText(row.due_date)}
              </td>

              <td className="rr-number">
                {AED(row.total_aed)}
              </td>

              <td className="rr-number">
                {AED(row.recorded_paid_aed)}
              </td>

              <td className="rr-number rr-weight">
                {AED(row.outstanding_aed)}
              </td>

              {showAging && (
                <td>
                  {row.days_overdue || "—"}
                </td>
              )}

              <td>
                <span
                  className={`rr-status ${
                    row.status ===
                    "Reconciliation required"
                      ? "rr-alert-status"
                      : ""
                  }`}
                >
                  {row.status}
                </span>
              </td>
            </tr>
          ))}

          {!rows.length && (
            <tr>
              <td
                colSpan={showAging ? 9 : 8}
                className="rr-empty"
              >
                No matching invoices for this report.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ============================================================
// PAYMENTS REPORT TABLE
// ============================================================

function PaymentsTable({
  rows,
}: {
  rows: ReportPayment[];
}) {
  return (
    <div
      className="rr-table-scroll"
      role="region"
      aria-label="Recorded payments"
      tabIndex={0}
    >
      <table className="rr-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Invoice</th>
            <th>Customer</th>
            <th>Recorded amount</th>
            <th>Payment reference</th>
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                {dateText(row.date)}
              </td>

              <td>
                <Link
                  href={`/invoices/${row.invoice_id}`}
                >
                  {row.invoice_number}
                </Link>
              </td>

              <td>
                {row.customer_name}
              </td>

              <td className="rr-number rr-weight">
                {AED(row.amount_aed)}
              </td>

              <td>
                {row.reference || "Not supplied"}
              </td>
            </tr>
          ))}

          {!rows.length && (
            <tr>
              <td
                className="rr-empty"
                colSpan={5}
              >
                No payments recorded within this date range.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ============================================================
// CSV EXPORT TYPES
// ============================================================

type CsvReportKind =
  | "aging"
  | "invoices"
  | "payments"
  | "reconciliation";

const CSV_KINDS: readonly ReportKind[] = [
  "aging",
  "invoices",
  "payments",
  "reconciliation",
];

// ============================================================
// MAIN REPORTS DASHBOARD
// ============================================================

export default function ReportsDashboard() {
  const [section, setSection] =
    useState<ReportKind>("aging");

  const [period, setPeriod] =
    useState("30");

  const [customerInput, setCustomerInput] =
    useState("");

  const [startInput, setStartInput] =
    useState("");

  const [endInput, setEndInput] =
    useState("");

  const [filters, setFilters] =
    useState<ReportFilters>({});

  const [report, setReport] =
    useState<ReportsDashboardResponse | null>(
      null
    );

  const [busy, setBusy] =
    useState(true);

  const [exporting, setExporting] =
    useState(false);

  const [error, setError] =
    useState("");

  const [refreshId, setRefreshId] =
    useState(0);

  // ==========================================================
  // REFRESH REPORT DATA
  // ==========================================================

  const reload = useCallback(() => {
    setError("");
    setReport(null);
    setBusy(true);

    setRefreshId(
      (value) => value + 1
    );
  }, []);

  // ==========================================================
  // FETCH FINANCIAL REPORTS
  // ==========================================================

  useEffect(() => {
    let active = true;

    getFinancialReports(filters)
      .then((value) => {
        if (active) {
          setReport(value);
          setError("");
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setReport(null);

          setError(
            cause instanceof Error
              ? cause.message
              : "Reports unavailable."
          );
        }
      })
      .finally(() => {
        if (active) {
          setBusy(false);
        }
      });

    return () => {
      active = false;
    };
  }, [filters, refreshId]);

  // ==========================================================
  // RECONCILIATION RECORDS
  // ==========================================================

  const reconciliationRows = useMemo(
    () =>
      report?.aging_invoices.filter(
        (item) =>
          item.status ===
          "Reconciliation required"
      ) ?? [],
    [report]
  );

  // ==========================================================
  // APPLY REPORT FILTERS
  // ==========================================================

  function applyFilters(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    if (
      period === "custom" &&
      (!startInput || !endInput)
    ) {
      setError(
        "Select both start and end dates for a custom range."
      );

      return;
    }

    const chosen =
      period === "custom"
        ? {
            startDate: startInput,
            endDate: endInput,
          }
        : pastDays(Number(period));

    if (
      !chosen.startDate ||
      !chosen.endDate
    ) {
      setError(
        "Select a valid start date and end date."
      );

      return;
    }

    if (
      chosen.startDate > chosen.endDate
    ) {
      setError(
        "Start date must be on or before end date."
      );

      return;
    }

    if (chosen.endDate > uaeDate()) {
      setError(
        "End date cannot be in the future (UAE time)."
      );

      return;
    }

    const elapsedDays =
      (
        Date.parse(
          `${chosen.endDate}T00:00:00Z`
        ) -
        Date.parse(
          `${chosen.startDate}T00:00:00Z`
        )
      ) / 86_400_000;

    if (
      !Number.isFinite(elapsedDays) ||
      elapsedDays > 730
    ) {
      setError(
        "Choose a valid reporting period of 731 days or less."
      );

      return;
    }

    setError("");
    setReport(null);
    setBusy(true);

    setFilters({
      ...chosen,
      customer: customerInput.trim(),
    });
  }

  // ==========================================================
  // EXPORT FINANCIAL REPORT CSV
  // ==========================================================

  async function exportCSV() {
    if (
      !CSV_KINDS.includes(section) ||
      busy ||
      !report
    ) {
      return;
    }

    setExporting(true);

    try {
      await exportFinancialReportCSV(
        section as CsvReportKind,
        filters
      );

      setError("");
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Export failed."
      );
    } finally {
      setExporting(false);
    }
  }

  const chosenSection =
    SECTIONS.find(
      (item) => item.id === section
    )!;

  const summary = report?.summary;

  // ==========================================================
  // PAGE RENDER
  // ==========================================================

  return (
    <section
      className="rr"
      aria-label="Financial Reports"
    >
      <style>{STYLES}</style>

      {/* PAGE HEADER */}

      <div className="rr-hero">
        <div>
          <span className="rr-eyebrow">
            RECEIVAI UAE / MANAGEMENT
          </span>

          <h1>
            <i
              className="bi bi-file-earmark-bar-graph"
              aria-hidden="true"
            />{" "}
            Financial Reports
          </h1>

          <p>
            Live reporting for receivables, invoices,
            payment records, collections and forecasts.
          </p>
        </div>

        <button
          type="button"
          className="rr-button"
          onClick={reload}
          disabled={busy}
        >
          <i
            className="bi bi-arrow-clockwise"
            aria-hidden="true"
          />{" "}
          Refresh
        </button>
      </div>

      {/* REPORT FILTERS */}

      <form
        className="rr-filters"
        onSubmit={applyFilters}
      >
        <label>
          Activity period

          <select
            value={period}
            onChange={(
              event: ChangeEvent<HTMLSelectElement>
            ) => setPeriod(event.target.value)}
          >
            <option value="7">
              Last 7 days
            </option>

            <option value="30">
              Last 30 days
            </option>

            <option value="90">
              Last 90 days
            </option>

            <option value="365">
              Last 365 days
            </option>

            <option value="custom">
              Custom range
            </option>
          </select>
        </label>

        {period === "custom" && (
          <>
            <label>
              From

              <input
                type="date"
                value={startInput}
                onChange={(
                  event: ChangeEvent<HTMLInputElement>
                ) => setStartInput(event.target.value)}
                required
              />
            </label>

            <label>
              To

              <input
                type="date"
                value={endInput}
                onChange={(
                  event: ChangeEvent<HTMLInputElement>
                ) => setEndInput(event.target.value)}
                required
              />
            </label>
          </>
        )}

        <label className="rr-search">
          Customer name

          <input
            value={customerInput}
            maxLength={100}
            placeholder="All customers"
            onChange={(
              event: ChangeEvent<HTMLInputElement>
            ) => setCustomerInput(event.target.value)}
          />
        </label>

        <button
          className="rr-primary"
          type="submit"
          disabled={busy}
        >
          <i
            className="bi bi-funnel"
            aria-hidden="true"
          />{" "}
          Apply filters
        </button>
      </form>

      {/* REPORTING EXPLANATION */}

      <div className="rr-note">
        <i
          className="bi bi-info-circle"
          aria-hidden="true"
        />{" "}
        Activity filters apply to issued invoices,
        recorded payments, reminders and documents.
        Outstanding balances and aging always reflect
        the current ledger snapshot.
      </div>

      {/* ERROR MESSAGE */}

      {error && (
        <div
          role="alert"
          className="rr-error"
        >
          {error}

          <button
            type="button"
            onClick={reload}
          >
            Retry
          </button>
        </div>
      )}

      {/* LOADING STATE */}

      {busy && (
        <div
          role="status"
          className="rr-loading"
        >
          Loading financial reports from the database…
        </div>
      )}

      {/* FINANCIAL DATA */}

      {report && !busy && (
        <>
          {/* REPORT DATE RANGE */}

          <div className="rr-meta">
            Data as of{" "}
            <strong>
              {dateText(report.as_of_date)}
            </strong>
            {" · "}
            Activity from{" "}
            <strong>
              {dateText(report.period_start)}
            </strong>{" "}
            to{" "}
            <strong>
              {dateText(report.period_end)}
            </strong>

            {report.customer_filter && (
              <>
                {" · "}Customer contains{" "}
                <strong>
                  {report.customer_filter}
                </strong>
              </>
            )}
          </div>

          {/* FINANCIAL KPI CARDS */}

          <div className="rr-kpis">
            <div className="rr-kpi">
              <span>
                Outstanding receivables
              </span>

              <strong>
                {AED(summary!.total_outstanding_aed)}
              </strong>

              <small>
                Current approved AED ledger
              </small>
            </div>

            <div className="rr-kpi">
              <span>
                Overdue receivables
              </span>

              <strong>
                {AED(summary!.overdue_outstanding_aed)}
              </strong>

              <small>
                Outstanding past the due date
              </small>
            </div>

            <div className="rr-kpi">
              <span>
                Recorded payments · selected period
              </span>

              <strong>
                {AED(
                  summary!
                    .recorded_collections_period_aed
                )}
              </strong>

              <small>
                Not bank-verified
              </small>
            </div>

            <div className="rr-kpi">
              <span>
                Open invoices
              </span>

              <strong>
                {summary!.open_invoice_count}
              </strong>

              <small>
                {
                  summary!
                    .reconciliation_required_count
                }{" "}
                reconciliation exception(s)
              </small>
            </div>
          </div>

          {/* REPORT NAVIGATION */}

          <div
            className="rr-section-tabs"
            role="tablist"
            aria-label="Report categories"
          >
            {SECTIONS.map((item) => (
              <button
                type="button"
                key={item.id}
                role="tab"
                aria-selected={
                  section === item.id
                }
                className={
                  section === item.id
                    ? "active"
                    : ""
                }
                onClick={() =>
                  setSection(item.id)
                }
              >
                <i
                  className={`bi ${item.icon}`}
                  aria-hidden="true"
                />{" "}
                {item.title}
              </button>
            ))}
          </div>

          {/* CURRENT REPORT PANEL */}

          <div className="rr-panel">
            <div className="rr-panel-heading">
              <div>
                <h2>
                  {chosenSection.title}
                </h2>

                <p>
                  {chosenSection.sub}
                </p>
              </div>

              {CSV_KINDS.includes(section) && (
                <button
                  className="rr-button"
                  type="button"
                  onClick={() =>
                    void exportCSV()
                  }
                  disabled={
                    exporting ||
                    busy ||
                    !report
                  }
                >
                  <i
                    className="bi bi-download"
                    aria-hidden="true"
                  />{" "}
                  {exporting
                    ? "Exporting…"
                    : "Export loaded CSV"}
                </button>
              )}
            </div>

            {/* RECEIVABLES AGING */}

            {section === "aging" && (
              <>
                <h3>
                  Current receivables aging
                </h3>

                <BarSeries
                  money
                  rows={report.aging.map(
                    (item) => ({
                      label: item.label,
                      amount: item.amount_aed,
                      detail:
                        `${item.count} invoice(s)`,
                    })
                  )}
                />

                <h3>
                  Open invoice balances
                </h3>

                <InvoiceTable
                  rows={report.aging_invoices}
                  showAging
                />
              </>
            )}

            {/* INVOICE REPORTS */}

            {section === "invoices" && (
              <>
                <div className="rr-mini-kpis">
                  <span>
                    Issued in period:{" "}
                    <strong>
                      {
                        summary!
                          .invoices_issued_in_period
                      }
                    </strong>
                  </span>

                  <span>
                    Issued value:{" "}
                    <strong>
                      {AED(
                        summary!
                          .invoiced_value_in_period_aed
                      )}
                    </strong>
                  </span>
                </div>

                <h3>
                  Current ledger status distribution
                </h3>

                <BarSeries
                  rows={report.ledger_status.map(
                    (row) => ({
                      label: row.label,
                      amount: String(row.count),
                    })
                  )}
                />

                <h3>
                  Invoices issued during selected period
                </h3>

                <InvoiceTable
                  rows={report.invoices}
                />
              </>
            )}

            {/* PAYMENT REPORTS */}

            {section === "payments" && (
              <>
                <div className="rr-mini-kpis">
                  <span>
                    Ledger entries in period:{" "}
                    <strong>
                      {
                        summary!
                          .recorded_payment_count
                      }
                    </strong>
                  </span>

                  <span>
                    Recorded total:{" "}
                    <strong>
                      {AED(
                        summary!
                          .recorded_collections_period_aed
                      )}
                    </strong>
                  </span>
                </div>

                <h3>
                  Recorded payments by{" "}
                  {report.recorded_collections_timeline
                    .length > 0 &&
                  report.recorded_collections_timeline[0]
                    .period.length === 7
                    ? "month"
                    : "day"}
                </h3>

                <BarSeries
                  money
                  rows={
                    report.recorded_collections_timeline.map(
                      (item) => ({
                        label: item.period,
                        amount: item.amount_aed,
                        detail:
                          `${item.count} payment(s)`,
                      })
                    )
                  }
                />

                <h3>
                  Payment entries
                </h3>

                <PaymentsTable
                  rows={report.payments}
                />
              </>
            )}

            {/* COLLECTION REPORTS */}

            {section === "collections" && (
              <>
                <p className="rr-muted">
                  Reminder workflow status for the
                  selected period. Approval does not
                  prove that a reminder was actually sent.
                </p>

                <BarSeries
                  rows={report.reminders.map(
                    (item) => ({
                      label:
                        item.status.replaceAll(
                          "_",
                          " "
                        ),
                      amount: String(item.count),
                    })
                  )}
                />

                <div className="rr-link-row">
                  <Link href="/collections">
                    Open Payment Collections{" "}
                    <i className="bi bi-arrow-up-right" />
                  </Link>
                </div>
              </>
            )}

            {/* CASH FLOW REPORTS */}

            {section === "forecast" && (
              <>
                <p className="rr-muted">
                  Portfolio-wide estimated customer
                  cash receipts, using the existing
                  base forecast assumptions.
                  Not a company-wide net cash-flow
                  statement.
                </p>

                {report.customer_filter ? (
                  <p className="rr-empty">
                    Clear the customer filter to display
                    portfolio-level forecasts.
                  </p>
                ) : (
                  <BarSeries
                    money
                    rows={report.forecasts.map(
                      (row) => ({
                        label:
                          `Next ${row.horizon_days} days`,
                        amount:
                          row.expected_receipts_aed,
                        detail:
                          `${row.forecast_invoice_count} invoice(s)`,
                      })
                    )}
                  />
                )}

                <div className="rr-link-row">
                  <Link
                    href="/?view=Cash%20Flow%20Forecast"
                  >
                    Open detailed Cash Flow Forecast{" "}
                    <i className="bi bi-arrow-up-right" />
                  </Link>
                </div>
              </>
            )}

            {/* DOCUMENT REPORTS */}

            {section === "documents" && (
              <>
                <p className="rr-muted">
                  Document processing events uploaded
                  during the selected date range.
                  Document totals are operational counts
                  and are not customer-filtered.
                </p>

                <BarSeries
                  rows={report.documents.map(
                    (item) => ({
                      label:
                        item.status.replaceAll(
                          "_",
                          " "
                        ),
                      amount: String(item.count),
                    })
                  )}
                />

                <div className="rr-link-row">
                  <Link href="/documents">
                    Open Document Intelligence{" "}
                    <i className="bi bi-arrow-up-right" />
                  </Link>
                </div>
              </>
            )}

            {/* RECONCILIATION REPORT */}

            {section === "reconciliation" && (
              <>
                <div className="rr-mini-kpis">
                  <span>
                    Invoices needing review:{" "}
                    <strong>
                      {
                        summary!
                          .reconciliation_required_count
                      }
                    </strong>
                  </span>

                  <span>
                    Balance affected:{" "}
                    <strong>
                      {AED(
                        summary!
                          .reconciliation_amount_aed
                      )}
                    </strong>
                  </span>
                </div>

                <p className="rr-muted">
                  Invoices marked paid but not covered
                  by sufficient recorded payment-ledger
                  entries. Do not create duplicate
                  payments to remove these warnings.
                </p>

                <InvoiceTable
                  rows={reconciliationRows}
                  showAging
                />

                <div className="rr-link-row">
                  <Link href="/collections">
                    Review in Payment Collections{" "}
                    <i className="bi bi-arrow-up-right" />
                  </Link>
                </div>
              </>
            )}
          </div>

          {/* REPORT DISCLOSURES */}

          <div className="rr-disclaimer">
            <i
              className="bi bi-shield-check"
              aria-hidden="true"
            />

            <div>
              <strong>
                Read-only financial reporting
              </strong>

              {report.warnings.map(
                (warning, index) => (
                  <p key={index}>
                    {warning}
                  </p>
                )
              )}

              <p>
                CSV exports contain only the currently
                loaded rows (maximum 300); headline
                totals include all matching records.
              </p>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// ============================================================
// COMPONENT STYLES
// ============================================================

const STYLES = `
.rr {
  color: #0F1B2D;
  width: 100%;
  font-family: inherit;
}

.rr * {
  box-sizing: border-box;
}

.rr-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin: 0 0 22px;
}

.rr-eyebrow {
  font-size: 11px;
  color: #2463D4;
  font-weight: 800;
  letter-spacing: 1.4px;
}

.rr h1 {
  font-size: clamp(25px, 2.3vw, 33px);
  font-weight: 800;
  letter-spacing: -.7px;
  margin: 10px 0 5px;
}

.rr h1 i {
  color: #2463D4;
  margin-right: 9px;
}

.rr-hero p {
  font-size: 13px;
  color: #66758A;
  margin: 0;
}

.rr-filters {
  display: flex;
  align-items: end;
  gap: 11px;
  flex-wrap: wrap;
  background: #fff;
  border: 1px solid #DCE3EC;
  padding: 15px;
  border-radius: 14px;
}

.rr-filters label {
  display: grid;
  gap: 5px;
  font-size: 11px;
  color: #66758A;
  font-weight: 700;
}

.rr-filters input,
.rr-filters select {
  padding: 10px 12px;
  border: 1px solid #DCE3EC;
  border-radius: 9px;
  font: inherit;
  min-height: 41px;
  background: #fff;
  color: #0F1B2D;
  font-size: 12px;
}

.rr-search {
  flex: 1;
  min-width: 160px;
}

.rr-button,
.rr-primary {
  border: 1px solid #DCE3EC;
  padding: 10px 13px;
  min-height: 41px;
  border-radius: 9px;
  background: #fff;
  color: #425166;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}

.rr-primary {
  background: #2463D4;
  color: #fff;
  border-color: #2463D4;
}

.rr-button:hover,
.rr-primary:hover {
  filter: brightness(.97);
}

.rr button:disabled {
  opacity: .55;
  cursor: not-allowed;
}

.rr-note,
.rr-meta {
  font-size: 11px;
  color: #66758A;
  margin: 10px 0 14px;
  line-height: 1.6;
}

.rr-note i {
  color: #2463D4;
  margin-right: 6px;
}

.rr-error,
.rr-loading {
  padding: 12px;
  background: #fff3f3;
  border: 1px solid #f1c5c5;
  color: #922c2c;
  border-radius: 10px;
  margin: 12px 0;
  font-size: 12px;
}

.rr-loading {
  background: #EEF3F8;
  color: #425166;
  border-color: #DCE3EC;
}

.rr-error button {
  margin-left: 9px;
  border: 0;
  color: #2463D4;
  background: transparent;
}

.rr-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 19px;
}

.rr-kpi {
  background: #fff;
  border: 1px solid #DCE3EC;
  border-radius: 13px;
  padding: 17px;
  display: grid;
  gap: 9px;
  min-width: 0;
}

.rr-kpi span {
  font-size: 11px;
  font-weight: 650;
  color: #66758A;
}

.rr-kpi strong {
  font-size: clamp(17px, 1.7vw, 25px);
  letter-spacing: -.45px;
  overflow-wrap: anywhere;
}

.rr-kpi small {
  font-size: 10px;
  color: #66758A;
}

.rr-section-tabs {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  border-bottom: 1px solid #DCE3EC;
  padding: 4px 0 0;
}

.rr-section-tabs button {
  white-space: nowrap;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  padding: 12px;
  border: 0;
  background: none;
  color: #66758A;
  cursor: pointer;
  border-bottom: 3px solid transparent;
}

.rr-section-tabs button.active {
  color: #2463D4;
  border-bottom-color: #2463D4;
}

.rr-section-tabs button i {
  margin-right: 6px;
}

.rr-panel {
  background: #fff;
  border: 1px solid #DCE3EC;
  border-top: 0;
  border-radius: 0 0 14px 14px;
  padding: 21px;
  min-height: 250px;
}

.rr-panel-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 21px;
}

.rr-panel-heading h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
}

.rr-panel-heading p {
  margin: 5px 0 0;
  font-size: 11px;
  color: #66758A;
}

.rr-panel h3 {
  font-size: 13px;
  font-weight: 800;
  margin: 21px 0 13px;
}

.rr-bars {
  display: grid;
  gap: 13px;
}

.rr-bar-heading {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 11px;
  color: #425166;
  margin-bottom: 6px;
}

.rr-bar-heading strong {
  font-size: 11px;
  color: #0F1B2D;
}

.rr-bar-track {
  background: #E7EDF5;
  border-radius: 99px;
  height: 11px;
  overflow: hidden;
}

.rr-bar-track span {
  display: block;
  height: 100%;
  background: linear-gradient(
    90deg,
    #2463D4,
    #7048C8
  );
  border-radius: 99px;
  min-width: 0;
}

.rr-table-scroll {
  overflow-x: auto;
  margin: 10px 0;
}

.rr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  min-width: 820px;
}

.rr-table th {
  text-align: left;
  font-weight: 750;
  color: #66758A;
  background: #F7F9FC;
  padding: 12px 10px;
  border-bottom: 1px solid #DCE3EC;
  white-space: nowrap;
}

.rr-table td {
  padding: 12px 10px;
  border-bottom: 1px solid #EDF1F6;
  vertical-align: top;
}

.rr-table a,
.rr-link-row a {
  color: #2463D4;
  text-decoration: none;
  font-weight: 750;
}

.rr-table a:hover,
.rr-link-row a:hover {
  text-decoration: underline;
}

.rr-number {
  white-space: nowrap;
}

.rr-weight {
  font-weight: 750;
}

.rr-status {
  padding: 5px 8px;
  background: #EEF3F8;
  border-radius: 7px;
  display: inline-block;
  white-space: nowrap;
}

.rr-alert-status {
  color: #95580c;
  background: #fff4dc;
}

.rr-mini-kpis {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 13px;
}

.rr-mini-kpis span {
  font-size: 12px;
  color: #425166;
  background: #F7F9FC;
  border: 1px solid #DCE3EC;
  padding: 10px;
  border-radius: 9px;
}

.rr-empty {
  font-size: 12px;
  text-align: center;
  padding: 20px;
  color: #66758A;
}

.rr-muted {
  font-size: 12px;
  color: #66758A;
  line-height: 1.6;
}

.rr-link-row {
  margin-top: 20px;
  font-size: 12px;
}

.rr-disclaimer {
  display: flex;
  gap: 10px;
  border: 1px solid #DDE7F6;
  background: #EEF3F8;
  border-radius: 12px;
  padding: 15px;
  margin-top: 15px;
}

.rr-disclaimer i {
  color: #2463D4;
}

.rr-disclaimer strong {
  font-size: 11px;
}

.rr-disclaimer p {
  font-size: 10px;
  color: #66758A;
  line-height: 1.6;
  margin: 5px 0 0;
}

@media (max-width: 1150px) {
  .rr-kpis {
    grid-template-columns: repeat(
      2,
      minmax(0, 1fr)
    );
  }
}

@media (max-width: 680px) {
  .rr-kpis {
    grid-template-columns: 1fr;
  }

  .rr-panel {
    padding: 12px;
  }

  .rr-filters {
    align-items: stretch;
  }

  .rr-filters label {
    width: 100%;
  }

  .rr-hero {
    align-items: flex-start;
  }

  .rr-hero h1 {
    font-size: 25px;
  }

  .rr-panel-heading {
    align-items: flex-start;
  }
}
`;
