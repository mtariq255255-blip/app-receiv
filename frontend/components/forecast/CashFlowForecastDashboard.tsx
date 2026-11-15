"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from "react";

import {
  FORECAST_HORIZONS,
  getForecastAgentInsights,
  getForecastAssumptions,
  getForecastDashboard,
  getForecastInvoices,
  type AEDAmount,
  type ForecastAssumptionsResponse,
  type ForecastDashboardResponse,
  type ForecastGranularity,
  type ForecastHorizon,
  type ForecastInsightsResponse,
  type ForecastInvoiceListResponse,
  type ForecastInvoiceProjection,
  type ForecastTimelinePoint,
} from "@/lib/cash-flow-api";

/*
 * ReceivAI UAE — Cash Flow Forecast Dashboard
 *
 * Embeddable in the existing Dashboard's Cash Flow Forecast view.
 * No additional sidebar, route, third-party chart library, or CSS file needed.
 *
 * Invoice amounts, payment records and forecast estimates come from FastAPI.
 * Demo invoices are excluded in the backend forecasting service.
 * JS Number conversion is ONLY used for visualization bar heights and
 * probability labels, never for money arithmetic or amount formatting.
 */

// Single forecast based on existing invoice and payment records.
// The existing backend requires the "base" key. This is NOT an actual receipt
// or a promise that a customer will pay on the estimated date.
const LIVE_FORECAST_BASIS = "base" as const;

const granularityLabels: Record<ForecastGranularity, string> = {
  day: "Daily",
  week: "Weekly",
  month: "Monthly",
};

const riskLabels: Record<ForecastInvoiceProjection["risk_level"], string> = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
  review_required: "Review required",
};

const statusLabels: Record<ForecastInvoiceProjection["forecast_status"], string> = {
  included: "Included",
  excluded: "Excluded",
  reconciliation_required: "Reconciliation",
};

const sourceLabels = {
  customer_history: "Customer payment history",
  portfolio_history: "Portfolio payment history",
  documented_fallback: "Documented fallback",
} as const;

function formatAED(amount: AEDAmount | null | undefined): string {
  // Pydantic sends 2-decimal AED amounts as strings. Format them without
  // converting money to floating point.
  if (amount === null || amount === undefined) return "—";
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(amount.trim());
  if (!match) return "—";
  const whole = match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = (match[3] ?? "").padEnd(2, "0");
  return `${match[1] ? "−" : ""}AED ${whole}.${fraction}`;
}

function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const parsed = new Date(`${isoDate.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString("en-GB", {
    timeZone: "UTC",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function shortDate(isoDate: string): string {
  const parsed = new Date(`${isoDate.slice(0, 10)}T12:00:00Z`);
  return Number.isNaN(parsed.getTime())
    ? isoDate
    : parsed.toLocaleDateString("en-GB", {
        timeZone: "UTC",
        day: "2-digit",
        month: "short",
      });
}

function percent(value: string | null | undefined): string {
  if (value == null) return "—";
  const numericValue = Number(value);
  return Number.isFinite(numericValue)
    ? `${(numericValue * 100).toFixed(1)}%`
    : "—";
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "The forecast could not be loaded. Please try again.";
}

function distinctWarnings(...groups: (string[] | undefined)[]): string[] {
  return [...new Set(groups.flatMap((group) => group ?? []).filter(Boolean))];
}

function MetricCard({
  icon,
  label,
  value,
  note,
  accent = "blue",
}: {
  icon: string;
  label: string;
  value: string;
  note: string;
  accent?: "blue" | "teal" | "amber" | "slate";
}) {
  return (
    <div className={`cf-metric cf-metric-${accent}`}>
      <div className="cf-metric-top">
        <span>{label}</span>
        <span className="cf-metric-icon" aria-hidden="true">
          <i className={`bi ${icon}`} />
        </span>
      </div>
      <div className="cf-metric-value">{value}</div>
      <div className="cf-metric-note">{note}</div>
    </div>
  );
}

function CollectionChart({
  points,
  groupBy,
}: {
  points: ForecastTimelinePoint[];
  groupBy: ForecastGranularity;
}) {
  const [showData, setShowData] = useState(false);

  const maximum = Math.max(
    0,
    ...points.map((point) =>
      Math.max(
        Number(point.projected_collections_aed) || 0,
        Number(point.due_invoice_balance_aed) || 0,
      ),
    ),
  );
  const hasValue = maximum > 0;

  return (
    <div className="cf-panel">
      <div className="cf-panel-head">
        <div>
          <h3>Expected cash collection timeline</h3>
          <p>Projected receipts versus invoice balances contractually due</p>
        </div>
        <div className="cf-legend" aria-label="Chart legend">
          <span><i className="cf-legend-swatch cf-legend-teal" />Expected receipts</span>
          <span><i className="cf-legend-swatch cf-legend-blue" />Invoice dues</span>
        </div>
      </div>

      {points.length === 0 || !hasValue ? (
        <div className="cf-empty cf-chart-empty">
          <i className="bi bi-bar-chart-line" aria-hidden="true" />
          <strong>No projected collections for this period</strong>
          <span>Try another horizon or check eligible unpaid invoices.</span>
        </div>
      ) : (
        <>
          <div className="cf-chart-scroll" role="region" aria-label="Forecast bar chart" tabIndex={0}>
            <div
              className="cf-chart"
              style={{ minWidth: `${Math.max(530, points.length * (groupBy === "day" ? 49 : 85))}px` }}
            >
              <div className="cf-chart-guide cf-chart-guide-one" />
              <div className="cf-chart-guide cf-chart-guide-two" />
              <div className="cf-chart-guide cf-chart-guide-three" />
              {points.map((point, index) => {
                const projected = Math.max(0, Number(point.projected_collections_aed) || 0);
                const due = Math.max(0, Number(point.due_invoice_balance_aed) || 0);
                const expectedHeight = (projected / maximum) * 100;
                const dueHeight = (due / maximum) * 100;
                return (
                  <div className="cf-chart-period" key={`${point.period_start}-${index}`}>
                    <div className="cf-chart-bars" title={`${shortDate(point.period_start)} – ${shortDate(point.period_end)}\nExpected: ${formatAED(point.projected_collections_aed)}\nDue: ${formatAED(point.due_invoice_balance_aed)}`}>
                      <div
                        className="cf-chart-bar cf-chart-bar-expected"
                        style={{ height: `${expectedHeight}%` }}
                      />
                      <div
                        className="cf-chart-bar cf-chart-bar-due"
                        style={{ height: `${dueHeight}%` }}
                      />
                    </div>
                    <div className="cf-chart-label">{shortDate(point.period_start)}</div>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="cf-chart-foot">
            <span>Scroll horizontally to view all periods.</span>
            <button type="button" className="cf-text-button" onClick={() => setShowData((value) => !value)} aria-expanded={showData}>
              {showData ? "Hide chart data" : "View chart data"}
              <i className={`bi bi-chevron-${showData ? "up" : "down"}`} aria-hidden="true" />
            </button>
          </div>
          {showData && (
            <div className="table-responsive cf-data-table-wrap">
              <table className="table table-sm cf-table">
                <thead><tr><th>Period</th><th className="text-end">Expected receipts</th><th className="text-end">Due balance</th><th className="text-end">Cumulative</th></tr></thead>
                <tbody>
                  {points.map((point) => (
                    <tr key={`${point.period_start}-${point.period_end}`}>
                      <td>{formatDate(point.period_start)} – {formatDate(point.period_end)}</td>
                      <td className="text-end">{formatAED(point.projected_collections_aed)}</td>
                      <td className="text-end">{formatAED(point.due_invoice_balance_aed)}</td>
                      <td className="text-end">{formatAED(point.cumulative_projected_aed)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function InsightsPanel({
  insights,
  agentInsights,
  agentLoading,
  agentError,
  showAgent,
  onToggleAgent,
}: {
  insights: ForecastDashboardResponse["insights"]["insights"];
  agentInsights: ForecastInsightsResponse | null;
  agentLoading: boolean;
  agentError: string;
  showAgent: boolean;
  onToggleAgent: () => void;
}) {
  // Hide scenario sensitivity because this dashboard only presents one
  // forecast. Other risk and collection insights remain available.
  const allInsights = (agentInsights?.insights ?? insights).filter(
    (item) => item.code !== "SCENARIO_SENSITIVITY",
  );
  return (
    <div className="cf-panel cf-insights-panel">
      <div className="cf-panel-head">
        <div><h3>Collection risks and recommendations</h3><p>Rule-based, read-only financial guidance</p></div>
        <button type="button" className="cf-button cf-button-secondary" onClick={onToggleAgent} aria-expanded={showAgent}>
          <i className="bi bi-stars" aria-hidden="true" />
          {showAgent ? "Hide agent analysis" : "Analyze forecast"}
        </button>
      </div>
      {showAgent && agentLoading && <div className="cf-inline-status" role="status">Analyzing invoice priorities…</div>}
      {showAgent && agentError && <div className="cf-inline-warning" role="alert">{agentError} Basic forecast insights remain available.</div>}
      {allInsights.length === 0 ? (
        <div className="cf-empty cf-insight-empty"><i className="bi bi-shield-check" aria-hidden="true" /><strong>No material risks flagged</strong><span>The forecast may still depend on fallback assumptions.</span></div>
      ) : (
        <div className="cf-insight-list">
          {allInsights.map((insight, index) => (
            <article key={`${insight.code}-${index}`} className="cf-insight">
              <span className={`cf-severity cf-severity-${insight.severity}`}>
                <i className={`bi ${insight.severity === "critical" ? "bi-exclamation-octagon" : insight.severity === "warning" ? "bi-exclamation-triangle" : "bi-info-circle"}`} aria-hidden="true" />
              </span>
              <div className="cf-insight-content">
                <h4>{insight.title}</h4>
                <p>{insight.description}</p>
                {insight.affected_outstanding_aed != null && <div className="cf-insight-amount">Balance affected: {formatAED(insight.affected_outstanding_aed)}</div>}
                {insight.recommended_action && <div className="cf-insight-action"><strong>Suggested action:</strong> {insight.recommended_action}</div>}
                {insight.related_invoice_ids.length > 0 && (
                  <div className="cf-linked-invoices">
                    {insight.related_invoice_ids.slice(0, 8).map((id) => <Link href={`/invoices/${id}`} key={id}>Invoice #{id}</Link>)}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

type CashFlowForecastDashboardProps = {
  /** Optional: use existing Dashboard setView for same-page navigation. */
  onOpenInvoiceRegister?: () => void;
};

export default function CashFlowForecastDashboard({
  onOpenInvoiceRegister,
}: CashFlowForecastDashboardProps = {}) {
  const [horizonDays, setHorizonDays] = useState<ForecastHorizon>(30);
  const [groupBy, setGroupBy] = useState<ForecastGranularity>("week");
  const [refreshKey, setRefreshKey] = useState(0);

  const [dashboard, setDashboard] = useState<ForecastDashboardResponse | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [dashboardError, setDashboardError] = useState("");

  const [page, setPage] = useState(1);
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [invoiceData, setInvoiceData] = useState<ForecastInvoiceListResponse | null>(null);
  const [invoiceLoading, setInvoiceLoading] = useState(true);
  const [invoiceError, setInvoiceError] = useState("");
  const [searchText, setSearchText] = useState("");

  const [showAssumptions, setShowAssumptions] = useState(false);
  const [assumptions, setAssumptions] = useState<ForecastAssumptionsResponse | null>(null);
  const [assumptionsLoading, setAssumptionsLoading] = useState(false);
  const [assumptionsError, setAssumptionsError] = useState("");

  const [showAgent, setShowAgent] = useState(false);
  const [agentInsights, setAgentInsights] = useState<ForecastInsightsResponse | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError, setAgentError] = useState("");

  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  const changeHorizon = (value: ForecastHorizon) => {
    setHorizonDays(value);
    setPage(1);
  };

  useEffect(() => {
    let active = true;
    setDashboardLoading(true);
    setDashboardError("");
    setDashboard(null);
    getForecastDashboard({ horizonDays, scenario: LIVE_FORECAST_BASIS, groupBy })
      .then((result) => { if (active) setDashboard(result); })
      .catch((error: unknown) => { if (active) setDashboardError(errorMessage(error)); })
      .finally(() => { if (active) setDashboardLoading(false); });
    return () => { active = false; };
  }, [horizonDays, groupBy, refreshKey]);

  useEffect(() => {
    let active = true;
    setInvoiceLoading(true);
    setInvoiceError("");
    setInvoiceData(null);
    getForecastInvoices({ horizonDays, scenario: LIVE_FORECAST_BASIS, page, pageSize: 10, includeExcluded })
      .then((result) => { if (active) setInvoiceData(result); })
      .catch((error: unknown) => { if (active) setInvoiceError(errorMessage(error)); })
      .finally(() => { if (active) setInvoiceLoading(false); });
    return () => { active = false; };
  }, [horizonDays, page, includeExcluded, refreshKey]);

  useEffect(() => {
    if (!showAssumptions) return;
    let active = true;
    setAssumptionsLoading(true);
    setAssumptionsError("");
    setAssumptions(null);
    getForecastAssumptions({ horizonDays, scenario: LIVE_FORECAST_BASIS })
      .then((result) => { if (active) setAssumptions(result); })
      .catch((error: unknown) => { if (active) setAssumptionsError(errorMessage(error)); })
      .finally(() => { if (active) setAssumptionsLoading(false); });
    return () => { active = false; };
  }, [horizonDays, showAssumptions, refreshKey]);

  useEffect(() => {
    if (!showAgent) return;
    let active = true;
    setAgentLoading(true);
    setAgentError("");
    setAgentInsights(null);
    getForecastAgentInsights({ horizonDays, scenario: LIVE_FORECAST_BASIS, groupBy, maxActions: 10 })
      .then((result) => { if (active) setAgentInsights(result); })
      .catch((error: unknown) => { if (active) setAgentError(errorMessage(error)); })
      .finally(() => { if (active) setAgentLoading(false); });
    return () => { active = false; };
  }, [horizonDays, groupBy, showAgent, refreshKey]);

  const filteredInvoices = useMemo(() => {
    const needle = searchText.trim().toLowerCase();
    if (!needle) return invoiceData?.invoices ?? [];
    return (invoiceData?.invoices ?? []).filter((row) =>
      `${row.invoice_number} ${row.customer_name} ${row.invoice_id}`.toLowerCase().includes(needle),
    );
  }, [invoiceData, searchText]);

  const warnings = dashboard
    ? distinctWarnings(
        dashboard.summary.warnings,
        dashboard.timeline.warnings,
        dashboard.insights.warnings,
      )
    : [];

  const metadata = dashboard?.summary.metadata;
  const metrics = dashboard?.summary.metrics;
  const pageCount = Math.max(1, Math.ceil((invoiceData?.total ?? 0) / 10));

  return (
    <section className="cf-root" aria-label="ReceivAI UAE cash flow forecast">
      <div className="cf-heading">
        <div>
          <div className="cf-eyebrow"><span className="cf-eyebrow-dot" /> RECEIVAI INTELLIGENCE</div>
          <h2>Cash Flow Forecast</h2>
          <p>Understand when outstanding customer invoices may turn into cash.</p>
        </div>
        <button type="button" className="cf-button cf-button-secondary cf-refresh" onClick={refresh} disabled={dashboardLoading}>
          <i className={`bi bi-arrow-clockwise ${dashboardLoading ? "cf-spinning" : ""}`} aria-hidden="true" />
          {dashboardLoading ? "Loading…" : "Refresh forecast"}
        </button>
      </div>

      <div className="cf-toolbar">
        <div className="cf-filter-block">
          <span className="cf-filter-label">Forecast period</span>
          <div className="cf-button-group" aria-label="Forecast horizon">
            {FORECAST_HORIZONS.map((days) => (
              <button key={days} type="button" aria-pressed={horizonDays === days} className={`cf-filter-button ${horizonDays === days ? "active" : ""}`} onClick={() => changeHorizon(days)}>{days} days</button>
            ))}
          </div>
        </div>
        <label className="cf-filter-block cf-select-block">
          <span className="cf-filter-label">Chart grouping</span>
          <select className="form-select form-select-sm" value={groupBy} onChange={(event: ChangeEvent<HTMLSelectElement>) => setGroupBy(event.target.value as ForecastGranularity)}>
            {(["day", "week", "month"] as ForecastGranularity[]).map((option) => <option key={option} value={option}>{granularityLabels[option]}</option>)}
          </select>
        </label>
      </div>

      <div className="cf-disclaimer"><i className="bi bi-info-circle" aria-hidden="true" /><span><strong>Database-backed figures:</strong> invoice balances, contractual due dates and recorded payments. <strong>Forecast estimates:</strong> future receipt dates and likely collections. Demo-tagged invoices are excluded by the current forecast service. This is receivables cash-in only; it does not include expenses, opening bank balances or bank verification.</span></div>

      {dashboardError && (
        <div className="cf-error" role="alert"><i className="bi bi-exclamation-triangle" aria-hidden="true"/><div><strong>Unable to load forecast</strong><p>{dashboardError}</p><button type="button" className="cf-button cf-button-secondary" onClick={refresh}>Try again</button></div></div>
      )}

      {dashboardLoading && (
        <div className="cf-loading" role="status"><span className="spinner-border spinner-border-sm" aria-hidden="true" />Calculating forecast using your invoice and payment records…</div>
      )}

      {dashboard && metrics && metadata && (
        <>
          <div className="cf-period-caption">
            <i className="bi bi-calendar3" aria-hidden="true" />
            Forecast dates: <strong>{formatDate(metadata.start_date)} – {formatDate(metadata.end_date)}</strong>
            <span>·</span><span>AED</span>
            <span className="cf-live-source"><i className="bi bi-database-check" aria-hidden="true" /> Live database · demo-tagged invoices excluded</span>
          </div>

          <div className="cf-metric-grid">
            <MetricCard icon="bi-calendar2-check" label={`Contractually due · next ${horizonDays} days`} value={formatAED(metrics.due_within_horizon_aed)} note="Exact outstanding on eligible invoices due in the period" accent="blue" />
            <MetricCard icon="bi-graph-up-arrow" label={`Estimated receipts · next ${horizonDays} days`} value={formatAED(metrics.expected_collections_aed)} note="Forecast estimate — not guaranteed cash" accent="teal" />
            <MetricCard icon="bi-wallet2" label="Total outstanding receivables" value={formatAED(metrics.total_outstanding_aed)} note="Recorded unpaid balances, including reconciliation exposure" accent="amber" />
            <MetricCard icon="bi-check2-circle" label="Recorded collections · past 30 days" value={formatAED(metrics.recorded_collections_last_30_days_aed)} note="Recorded payment ledger; not bank-confirmed" accent="slate" />
          </div>

          <div className="cf-stats-strip">
            <div><span>Overdue outstanding</span><strong>{formatAED(metrics.overdue_outstanding_aed)}</strong></div>
            <div><span>At-risk outstanding</span><strong>{formatAED(metrics.at_risk_outstanding_aed)}</strong></div>
            <div><span>Eligible invoices</span><strong>{metrics.eligible_invoice_count.toLocaleString("en-GB")}</strong></div>
            <div><span>Reconciliation review</span><strong>{metrics.reconciliation_required_count.toLocaleString("en-GB")}</strong></div>
          </div>

          {metrics.eligible_invoice_count === 0 && (
            <div className="cf-inline-warning" role="status">
              No eligible invoices were found for forecasting. Only reviewed AED invoices
              with unpaid balances and valid due dates contribute; demo-tagged invoices are excluded.
            </div>
          )}

          {warnings.length > 0 && (
            <div className="cf-warnings" role="status"><strong><i className="bi bi-exclamation-circle" aria-hidden="true" /> Data and forecast notices</strong><ul>{warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul></div>
          )}

          <CollectionChart points={dashboard.timeline.points} groupBy={groupBy} />

          <InsightsPanel insights={dashboard.insights.insights} agentInsights={agentInsights} agentLoading={agentLoading} agentError={agentError} showAgent={showAgent} onToggleAgent={() => setShowAgent((value) => !value)} />

          <div className="cf-panel">
            <div className="cf-panel-head cf-invoices-head">
              <div><h3>Invoice collection projections</h3><p>Only outstanding amounts can contribute to expected cash inflow.</p></div>
              {onOpenInvoiceRegister ? (
                <button type="button" onClick={onOpenInvoiceRegister} className="cf-button cf-button-secondary"><i className="bi bi-receipt" aria-hidden="true" /> Invoice register</button>
              ) : (
                <Link href="/?view=Invoice%20Management" className="cf-button cf-button-secondary"><i className="bi bi-receipt" aria-hidden="true" /> Invoice register</Link>
              )}
            </div>
            <div className="cf-invoice-controls">
              <label className="cf-search"><i className="bi bi-search" aria-hidden="true" /><input value={searchText} onChange={(event: ChangeEvent<HTMLInputElement>) => setSearchText(event.target.value)} placeholder="Search this page by invoice or customer" aria-label="Search invoices on current page" /></label>
              <label className="cf-checkbox"><input type="checkbox" checked={includeExcluded} onChange={(event: ChangeEvent<HTMLInputElement>) => { setIncludeExcluded(event.target.checked); setPage(1); }} /> Show excluded / reconciliation cases</label>
            </div>
            {invoiceLoading && <div className="cf-inline-status" role="status">Loading invoice projections…</div>}
            {invoiceError && <div className="cf-inline-warning" role="alert">{invoiceError} <button type="button" className="cf-text-button" onClick={refresh}>Retry</button></div>}
            {!invoiceLoading && !invoiceError && (
              <>
                <div className="table-responsive">
                  <table className="table cf-table cf-invoices-table">
                    <thead><tr><th>Invoice / Customer</th><th>Due date</th><th className="text-end">Outstanding</th><th>Expected receipt</th><th className="text-end">Forecast cash</th><th>Risk</th><th>Status</th></tr></thead>
                    <tbody>
                      {filteredInvoices.map((row) => (
                        <tr key={row.invoice_id}>
                          <td><Link className="cf-invoice-link" href={`/invoices/${row.invoice_id}`}>{row.invoice_number}</Link><div className="cf-table-secondary">{row.customer_name}</div></td>
                          <td>{formatDate(row.due_date)}{row.days_overdue > 0 && <div className="cf-table-overdue">{row.days_overdue}d overdue</div>}</td>
                          <td className="text-end cf-nowrap">{formatAED(row.outstanding_aed)}</td>
                          <td>{formatDate(row.expected_receipt_date)}{row.basis && <div className="cf-table-secondary">{sourceLabels[row.basis]}</div>}</td>
                          <td className="text-end cf-nowrap"><strong>{formatAED(row.expected_collection_aed)}</strong>{row.collection_probability !== null && <div className="cf-table-secondary">Assumed {percent(row.collection_probability)}</div>}</td>
                          <td><span className={`cf-pill cf-risk-${row.risk_level}`}>{riskLabels[row.risk_level]}</span></td>
                          <td><span className={`cf-pill cf-status-${row.forecast_status}`}>{statusLabels[row.forecast_status]}</span>{row.exclusion_reason && <div className="cf-table-secondary cf-reason">{row.exclusion_reason}</div>}{row.risk_reasons.length > 0 && <div className="cf-table-secondary cf-reason">{row.risk_reasons.join("; ")}</div>}</td>
                        </tr>
                      ))}
                      {filteredInvoices.length === 0 && <tr><td colSpan={7}><div className="cf-empty"><i className="bi bi-search" aria-hidden="true" /><strong>No invoices found</strong><span>{searchText ? "Try another search for this page." : "No invoice projections match these filters."}</span></div></td></tr>}
                    </tbody>
                  </table>
                </div>
                <div className="cf-pagination"><span>{invoiceData?.total ?? 0} invoice(s) · Page {page} of {pageCount}</span><div><button type="button" className="cf-button cf-button-secondary" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button><button type="button" className="cf-button cf-button-secondary" disabled={page >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))}>Next</button></div></div>
              </>
            )}
          </div>

          <div className="cf-panel cf-assumptions-panel">
            <div className="cf-panel-head"><div><h3>Forecast assumptions and methodology</h3><p>View the reasoning behind collection probabilities and expected delays.</p></div><button type="button" className="cf-button cf-button-secondary" aria-expanded={showAssumptions} onClick={() => setShowAssumptions((value) => !value)}>{showAssumptions ? "Hide assumptions" : "Show assumptions"}<i className={`bi bi-chevron-${showAssumptions ? "up" : "down"}`} aria-hidden="true" /></button></div>
            {showAssumptions && (
              <div className="cf-assumptions-content">
                {assumptionsLoading && <div className="cf-inline-status" role="status">Loading assumptions…</div>}
                {assumptionsError && <div className="cf-inline-warning" role="alert">{assumptionsError}</div>}
                {assumptions && (
                  assumptions.assumptions.length > 0 ? (
                    <div className="cf-assumption-list">{assumptions.assumptions.map((item, index) => <div className="cf-assumption" key={`${item.label}-${index}`}><div><strong>{item.label}</strong><span className="cf-pill cf-pill-neutral">{sourceLabels[item.basis]}</span></div><p>{item.explanation}</p><div className="cf-assumption-stats"><span>Assumed collection likelihood: <strong>{percent(item.collection_probability)}</strong></span><span>Estimated delay: <strong>{item.expected_delay_days} days</strong></span><span>Historical samples: <strong>{item.historical_sample_count}</strong></span></div></div>)}</div>
                  ) : <div className="cf-inline-status">No detailed assumptions returned.</div>
                )}
              </div>
            )}
          </div>

          <div className="cf-footer-note"><i className="bi bi-shield-check" aria-hidden="true" /> Read-only analysis · Forecast generated {new Date(metadata.generated_at).toLocaleString("en-GB", { timeZone: "Asia/Dubai", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })} (UAE) · Not a promise of payment.</div>
        </>
      )}

      <style>{`
        .cf-root{--cf-ink:#13233b;--cf-muted:#64748b;--cf-border:#e2eaf2;--cf-teal:#0e948d;--cf-blue:#2463d4;--cf-bg:#f5f8fc;color:var(--cf-ink);width:100%;padding:4px 0 24px;font-family:inherit}
        .cf-root *{box-sizing:border-box}
        .cf-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap;margin:0 0 20px}
        .cf-live-source{display:inline-flex;align-items:center;gap:5px;color:#178054;background:#e5f7ed;border:1px solid #c9eadb;border-radius:6px;padding:4px 9px;font-weight:700}
        .cf-eyebrow{font-size:10px;font-weight:800;letter-spacing:1.6px;color:#327b93;display:flex;align-items:center;gap:8px;margin-bottom:7px}
        .cf-eyebrow-dot{width:7px;height:7px;border-radius:50%;background:var(--cf-teal);box-shadow:0 0 0 3px #d9f4f0}
        .cf-heading h2{font-weight:800;letter-spacing:-.7px;font-size:clamp(25px,3vw,32px);margin:0 0 6px}
        .cf-heading p{color:var(--cf-muted);margin:0;font-size:13px}
        .cf-button{display:inline-flex;justify-content:center;align-items:center;gap:8px;border-radius:9px;font-size:12px;font-weight:700;line-height:1.2;padding:10px 13px;text-decoration:none;cursor:pointer;transition:.16s ease;white-space:nowrap}
        .cf-button-secondary{color:#344960;border:1px solid var(--cf-border);background:white}
        .cf-button-secondary:hover:not(:disabled){background:#eff5fd;border-color:#bbd0e8;color:#1c55a5}
        .cf-button:disabled{opacity:.5;cursor:not-allowed}
        .cf-toolbar{display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px;background:#fff;padding:17px 18px;border:1px solid var(--cf-border);border-radius:14px;margin-bottom:14px;box-shadow:0 3px 13px rgba(20,38,66,.025)}
        .cf-filter-block{display:flex;flex-direction:column;gap:7px;min-width:0}
        .cf-filter-label{font-size:11px;font-weight:750;color:#586b80}
        .cf-button-group{display:flex;gap:3px;border-radius:9px;padding:4px;background:#f0f4f9;flex-wrap:wrap}
        .cf-filter-button{border:0;background:transparent;color:#607087;font-size:12px;font-weight:650;padding:8px 12px;border-radius:7px;cursor:pointer;white-space:nowrap}
        .cf-filter-button.active{background:#fff;color:#1e5ac1;box-shadow:0 1px 5px rgba(15,38,70,.1)}
        .cf-filter-button:hover:not(.active){color:#244265;background:#e6edf7}
        .cf-select-block select{min-width:115px;border-color:var(--cf-border);color:#344960;font-size:12px;padding:9px 30px 9px 11px;background-color:#fff}
        .cf-disclaimer{display:flex;align-items:flex-start;gap:10px;border:1px solid #dceaf8;background:#f0f7ff;border-radius:10px;color:#42627e;padding:11px 13px;margin-bottom:18px;font-size:12px;line-height:1.55}
        .cf-disclaimer i{font-size:15px;color:#2463d4;margin-top:1px}
        .cf-disclaimer strong{color:#294765}
        .cf-period-caption{display:flex;flex-wrap:wrap;align-items:center;gap:8px;color:#6a7b90;font-size:12px;margin:0 0 13px}
        .cf-period-caption i{color:#4080c4}.cf-period-caption strong{color:#233d58}
        .cf-metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin-bottom:13px}
        .cf-metric{background:white;border:1px solid var(--cf-border);border-radius:14px;padding:17px 18px;box-shadow:0 4px 18px rgba(12,37,70,.035);min-width:0}
        .cf-metric-top{display:flex;align-items:center;justify-content:space-between;gap:9px;color:#6c7b8d;font-size:11px;font-weight:650;min-height:32px}
        .cf-metric-icon{display:flex;align-items:center;justify-content:center;width:33px;height:33px;min-width:33px;border-radius:10px;background:#eaf1fc;color:#2463d4;font-size:17px}
        .cf-metric-teal .cf-metric-icon{background:#dcf6f1;color:#088c83}.cf-metric-amber .cf-metric-icon{background:#fff3dd;color:#be801d}.cf-metric-slate .cf-metric-icon{background:#edf1f6;color:#506982}
        .cf-metric-value{font-size:clamp(18px,2vw,24px);font-weight:820;letter-spacing:-.6px;line-height:1.3;overflow-wrap:anywhere;margin:10px 0 7px;font-variant-numeric:tabular-nums;color:#1a2d44}
        .cf-metric-note{font-size:10px;color:#8a99a9;line-height:1.5}
        .cf-stats-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;background:white;border:1px solid var(--cf-border);border-radius:12px;margin-bottom:19px;overflow:hidden}
        .cf-stats-strip>div{padding:14px 18px;display:flex;flex-direction:column;gap:4px;border-right:1px solid var(--cf-border)}
        .cf-stats-strip>div:last-child{border-right:0}.cf-stats-strip span{color:#7d8c9c;font-size:11px}.cf-stats-strip strong{font-size:15px;font-weight:800;color:#263f58;overflow-wrap:anywhere}
        .cf-panel{background:#fff;border:1px solid var(--cf-border);box-shadow:0 3px 18px rgba(22,45,80,.035);border-radius:15px;padding:22px;margin-bottom:18px;min-width:0}
        .cf-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:19px}
        .cf-panel-head h3{font-size:16px;font-weight:800;letter-spacing:-.2px;margin:0 0 5px}.cf-panel-head p{font-size:12px;color:#8897a7;margin:0;line-height:1.55}
        .cf-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:#6d7c8c}.cf-legend span{display:inline-flex;gap:7px;align-items:center}.cf-legend-swatch{display:inline-block;width:10px;height:10px;border-radius:3px}.cf-legend-teal{background:#0c958e}.cf-legend-blue{background:#bdd1ee}
        .cf-chart-scroll{overflow-x:auto;overflow-y:hidden;padding:0 0 2px;scrollbar-width:thin}
        .cf-chart{height:240px;position:relative;display:flex;align-items:stretch;gap:9px;border-bottom:1px solid #e2eaf2;padding:14px 4px 0;margin-bottom:6px}
        .cf-chart-guide{position:absolute;left:0;right:0;border-top:1px dashed #e6edf4;pointer-events:none}.cf-chart-guide-one{top:25%}.cf-chart-guide-two{top:50%}.cf-chart-guide-three{top:75%}
        .cf-chart-period{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:9px;min-width:35px;position:relative;z-index:1}
        .cf-chart-bars{width:100%;max-width:60px;min-height:1px;flex:1;display:flex;align-items:flex-end;justify-content:center;gap:4px}
        .cf-chart-bar{width:38%;max-width:24px;min-height:0;border-radius:5px 5px 0 0;transition:height .2s ease}.cf-chart-bar-expected{background:linear-gradient(180deg,#15b9ae,#0c9089)}.cf-chart-bar-due{background:#bdd1ee}
        .cf-chart-label{height:28px;font-size:10px;color:#8595a7;white-space:nowrap;display:flex;align-items:flex-start;justify-content:center}
        .cf-chart-foot{display:flex;justify-content:space-between;gap:10px;align-items:center;color:#92a0af;font-size:10px;margin-top:9px}
        .cf-text-button{border:0;background:transparent;color:#2864ba;font-size:11px;font-weight:750;cursor:pointer;padding:2px;display:inline-flex;gap:5px;align-items:center}.cf-text-button:hover{text-decoration:underline}
        .cf-data-table-wrap{margin-top:15px;border-top:1px solid var(--cf-border);padding-top:12px}
        .cf-insight-list{display:flex;flex-direction:column;gap:0}.cf-insight{display:flex;gap:13px;padding:15px 2px;border-bottom:1px solid #edf1f5}.cf-insight:first-child{padding-top:0}.cf-insight:last-child{border-bottom:none;padding-bottom:0}
        .cf-severity{height:33px;width:33px;flex:none;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px}.cf-severity-info{background:#eaf3ff;color:#3268bc}.cf-severity-warning{background:#fff2da;color:#bd7e1f}.cf-severity-critical{background:#ffe9e9;color:#c94242}
        .cf-insight-content{flex:1;min-width:0}.cf-insight-content h4{font-weight:780;font-size:13px;margin:2px 0 6px}.cf-insight-content p{color:#65788d;font-size:12px;line-height:1.65;margin:0 0 7px}.cf-insight-amount{font-size:11px;font-weight:730;color:#52677e;margin:5px 0}.cf-insight-action{font-size:11px;line-height:1.6;color:#496579;background:#f5f8fc;border-radius:7px;padding:8px 10px;margin-top:7px}
        .cf-linked-invoices{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.cf-linked-invoices a{font-size:11px;text-decoration:none;color:#2463d4;background:#eff5ff;border-radius:6px;padding:4px 7px}.cf-linked-invoices a:hover{text-decoration:underline}
        .cf-invoice-controls{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:15px}.cf-search{display:flex;align-items:center;gap:9px;border:1px solid var(--cf-border);border-radius:9px;padding:0 12px;min-width:min(100%,300px);height:39px;color:#8594a6}.cf-search input{border:0;outline:0;width:100%;min-width:130px;color:#263b53;background:transparent;font-size:12px}.cf-search:focus-within{border-color:#84aadf;box-shadow:0 0 0 3px #e8f1ff}.cf-checkbox{font-size:11px;color:#61758b;display:flex;align-items:center;gap:8px;cursor:pointer}.cf-checkbox input{accent-color:#2463d4}
        .cf-table{font-size:11px;margin-bottom:0;vertical-align:middle}.cf-table thead th{color:#718296;background:#f7f9fc;letter-spacing:.15px;text-transform:none;font-size:10px;font-weight:750;padding:12px 12px;white-space:nowrap;border-bottom:1px solid #e9eef5}
        .cf-table tbody td{color:#374a61;border-bottom:1px solid #edf1f5;padding:13px 12px;vertical-align:top;line-height:1.5}.cf-table tbody tr:last-child td{border-bottom:0}.cf-invoice-link{font-weight:780;color:#2463d4;text-decoration:none}.cf-invoice-link:hover{text-decoration:underline}
        .cf-table-secondary{color:#91a0b0;font-size:10px;margin-top:4px;line-height:1.5}.cf-table-overdue{color:#b77922;font-size:10px;font-weight:700;margin-top:4px}.cf-nowrap{white-space:nowrap}.cf-reason{max-width:200px;white-space:normal}
        .cf-pill{display:inline-flex;align-items:center;white-space:nowrap;padding:4px 7px;border-radius:7px;font-size:10px;font-weight:760}.cf-risk-low,.cf-status-included{background:#e9f8f1;color:#178054}.cf-risk-medium{background:#fff4df;color:#a66e19}.cf-risk-high,.cf-risk-review_required,.cf-status-reconciliation_required{background:#fff0e8;color:#af5630}.cf-status-excluded{background:#eef1f5;color:#64748b}.cf-pill-neutral{background:#ecf3fd;color:#4771ae}
        .cf-pagination{border-top:1px solid #edf1f5;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding-top:15px;font-size:11px;color:#7a8ca0}.cf-pagination>div{display:flex;gap:7px}.cf-pagination .cf-button{padding:7px 11px;font-size:11px}
        .cf-assumptions-content{border-top:1px solid #edf1f5;padding-top:14px}.cf-assumption-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.cf-assumption{border:1px solid #e4edf5;border-radius:10px;padding:14px;background:#fbfcfe}.cf-assumption>div:first-child{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.cf-assumption strong{font-size:12px}.cf-assumption p{font-size:11px;line-height:1.6;color:#677b91;margin:8px 0}.cf-assumption-stats{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:10px;color:#71849b}.cf-assumption-stats strong{font-size:10px;color:#284c6d}
        .cf-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:30px;text-align:center;gap:7px;color:#8d9cb0}.cf-empty i{font-size:27px;color:#aabed2}.cf-empty strong{font-size:12px;color:#516980}.cf-empty span{font-size:11px}.cf-chart-empty{min-height:220px}.cf-insight-empty{min-height:150px}
        .cf-loading{display:flex;justify-content:center;align-items:center;gap:12px;border:1px solid #e3eaf2;background:white;border-radius:13px;padding:50px 16px;color:#59728c;font-size:13px}.cf-inline-status{font-size:12px;color:#698097;background:#f4f8fc;padding:12px;border-radius:8px}.cf-inline-warning{background:#fff9ee;border:1px solid #f9e6bc;color:#95621d;padding:12px;border-radius:9px;font-size:12px;margin-bottom:12px;line-height:1.5}.cf-error{display:flex;gap:12px;border:1px solid #f0c6c6;background:#fff4f4;padding:19px;border-radius:11px;color:#a54141;margin-bottom:17px}.cf-error>i{font-size:20px}.cf-error strong{font-size:14px}.cf-error p{font-size:12px;margin:6px 0 11px}
        .cf-warnings{background:#fffaf0;border:1px solid #f5e6bb;border-radius:10px;padding:13px 16px;margin-bottom:17px;color:#806329;font-size:11px;line-height:1.6}.cf-warnings strong{display:flex;gap:8px;align-items:center}.cf-warnings ul{margin:7px 0 0;padding-left:18px}.cf-warnings li{margin-top:4px}
        .cf-footer-note{display:flex;align-items:center;gap:8px;color:#90a0af;font-size:10px;line-height:1.5;flex-wrap:wrap;margin-top:10px}.cf-footer-note i{font-size:15px;color:#5aaf9e}
        .cf-spinning{display:inline-block;animation:cf-rotate 1.2s linear infinite}@keyframes cf-rotate{to{transform:rotate(360deg)}}
        @media(max-width:1250px){.cf-metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cf-stats-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.cf-stats-strip>div:nth-child(2){border-right:0}.cf-stats-strip>div:nth-child(-n+2){border-bottom:1px solid var(--cf-border)}}
        @media(max-width:750px){.cf-heading{align-items:flex-start}.cf-metric-grid{gap:9px}.cf-metric{padding:14px}.cf-metric-value{font-size:18px}.cf-panel{padding:16px}.cf-assumption-list{grid-template-columns:1fr}.cf-toolbar{gap:13px}.cf-filter-block{width:100%}.cf-select-block select{width:100%}.cf-filter-button{flex:1}.cf-chart-foot{align-items:flex-start}.cf-legend{width:100%}}
        @media(max-width:480px){.cf-metric-grid{grid-template-columns:1fr}.cf-stats-strip{grid-template-columns:1fr}.cf-stats-strip>div{border-right:0;border-bottom:1px solid var(--cf-border)!important}.cf-stats-strip>div:last-child{border-bottom:0!important}.cf-filter-button{font-size:11px;padding:8px}.cf-toolbar{padding:13px}.cf-panel-head{gap:12px}}
      `}</style>
    </section>
  );
}
