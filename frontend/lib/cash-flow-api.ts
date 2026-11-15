/**
 * ReceivAI UAE — Cash Flow Forecast API client
 *
 * Read-only, authenticated requests to the FastAPI forecast module.
 * Reuses apiGet from lib/api.ts, including the existing Bearer token,
 * session-expiry handling, and no-store fetch behavior.
 *
 * The forecast estimates AED receivables cash *inflows* only.
 * It is not a bank-verified balance or a company-wide net cash forecast.
 *
 * IMPORTANT: Amounts and probabilities arrive as decimal STRINGS.
 * Do not use JavaScript floating-point arithmetic for accounting totals.
 */

import { apiGet } from "@/lib/api";

// ============================================================
// 1. Shared API types
// ============================================================

export const FORECAST_HORIZONS = [7, 30, 60, 90] as const;

export type ForecastHorizon = (typeof FORECAST_HORIZONS)[number];
export type ForecastScenario = "conservative" | "base" | "optimistic";
export type ForecastGranularity = "day" | "week" | "month";
export type ForecastBasis =
  | "customer_history"
  | "portfolio_history"
  | "documented_fallback";
export type ForecastStatus =
  | "included"
  | "excluded"
  | "reconciliation_required";
export type ForecastRiskLevel =
  | "low"
  | "medium"
  | "high"
  | "review_required";
export type ForecastInsightSeverity = "info" | "warning" | "critical";
export type ForecastAgingBucket =
  | "paid"
  | "not_due"
  | "overdue_1_30"
  | "overdue_31_60"
  | "overdue_61_90"
  | "overdue_90_plus"
  | "unknown_due_date";

/** Exact decimal representation supplied by Pydantic (e.g. "3255.00"). */
export type AEDAmount = string;
/** Exact 0–1 decimal probability supplied by Pydantic (e.g. "0.7500"). */
export type ForecastProbability = string;
/** ISO date: YYYY-MM-DD. */
export type ISODate = string;
/** ISO datetime including timezone offset, as returned by FastAPI. */
export type ISODateTime = string;

// ============================================================
// 2. Request options (camelCase in frontend, snake_case in API)
// ============================================================

export interface ForecastOptions {
  horizonDays?: ForecastHorizon; // defaults to 30 on the server
  asOfDate?: ISODate; // server uses UAE-local today when omitted
  scenario?: ForecastScenario; // defaults to "base"
}

export interface ForecastTimelineOptions extends ForecastOptions {
  groupBy?: ForecastGranularity; // defaults to "week"
}

export interface ForecastInvoicesOptions extends ForecastOptions {
  page?: number; // >= 1; defaults to 1
  pageSize?: number; // 1–200; defaults to 50
  includeExcluded?: boolean; // defaults to false
}

export interface ForecastAgentOptions extends ForecastTimelineOptions {
  maxActions?: number; // 1–50; defaults to 10
}

/** The scenarios endpoint calculates all three scenarios in one request. */
export type ForecastScenariosOptions = Pick<
  ForecastOptions,
  "horizonDays" | "asOfDate"
>;

// ============================================================
// 3. Pydantic response contracts
// ============================================================

export interface ForecastMetadata {
  as_of_date: ISODate;
  start_date: ISODate;
  end_date: ISODate;
  horizon_days: ForecastHorizon;
  scenario: ForecastScenario;
  generated_at: ISODateTime;
  currency: "AED";
  scope: "receivables_cash_in_only";
  payment_evidence: "recorded_not_bank_verified";
  methodology: "deterministic_rules";
  assumptions_used: boolean;
}

export interface ForecastAssumption {
  label: string;
  basis: ForecastBasis;
  collection_probability: ForecastProbability;
  expected_delay_days: number;
  historical_sample_count: number;
  explanation: string;
}

export interface ForecastAssumptionsResponse {
  metadata: ForecastMetadata;
  assumptions: ForecastAssumption[];
  warnings: string[];
}

export interface ForecastSummaryMetrics {
  total_outstanding_aed: AEDAmount;
  overdue_outstanding_aed: AEDAmount;
  due_within_horizon_aed: AEDAmount;
  expected_collections_aed: AEDAmount;
  at_risk_outstanding_aed: AEDAmount;
  recorded_collections_last_30_days_aed: AEDAmount;
  eligible_invoice_count: number;
  forecast_invoice_count: number;
  excluded_invoice_count: number;
  reconciliation_required_count: number;
}

export interface ForecastSummaryResponse {
  metadata: ForecastMetadata;
  metrics: ForecastSummaryMetrics;
  warnings: string[];
}

export interface ForecastTimelinePoint {
  period_start: ISODate;
  period_end: ISODate;
  projected_collections_aed: AEDAmount;
  cumulative_projected_aed: AEDAmount;
  due_invoice_balance_aed: AEDAmount;
  invoice_count: number;
}

export interface ForecastTimelineResponse {
  metadata: ForecastMetadata;
  group_by: ForecastGranularity;
  points: ForecastTimelinePoint[];
  projected_total_aed: AEDAmount;
  warnings: string[];
}

export interface ForecastInvoiceProjection {
  invoice_id: number;
  invoice_number: string;
  customer_name: string;
  due_date: ISODate | null;
  invoice_total_aed: AEDAmount;
  recorded_paid_aed: AEDAmount;
  outstanding_aed: AEDAmount;
  days_overdue: number;
  aging_bucket: ForecastAgingBucket;
  payment_count: number;
  forecast_status: ForecastStatus;
  expected_receipt_date: ISODate | null;
  within_horizon: boolean;
  collection_probability: ForecastProbability | null;
  expected_collection_aed: AEDAmount;
  basis: ForecastBasis | null;
  risk_level: ForecastRiskLevel;
  risk_reasons: string[];
  recommended_action: string | null;
  exclusion_reason: string | null;
}

export interface ForecastInvoiceListResponse {
  metadata: ForecastMetadata;
  invoices: ForecastInvoiceProjection[];
  total: number;
  page: number;
  page_size: number;
  warnings: string[];
}

export interface ForecastScenarioResult {
  scenario: ForecastScenario;
  expected_collections_aed: AEDAmount;
  difference_from_base_aed: AEDAmount; // signed: can be negative
  forecast_invoice_count: number;
  assumptions: ForecastAssumption[];
  explanation: string;
}

export interface ForecastScenariosResponse {
  metadata: ForecastMetadata;
  scenarios: ForecastScenarioResult[];
  warnings: string[];
}

export interface ForecastInsight {
  code: string;
  severity: ForecastInsightSeverity;
  title: string;
  description: string;
  related_invoice_ids: number[];
  affected_outstanding_aed: AEDAmount | null;
  recommended_action: string | null;
}

export interface ForecastInsightsResponse {
  metadata: ForecastMetadata;
  insights: ForecastInsight[];
  warnings: string[];
}

export interface ForecastDashboardResponse {
  summary: ForecastSummaryResponse;
  timeline: ForecastTimelineResponse;
  scenarios: ForecastScenariosResponse;
  insights: ForecastInsightsResponse;
}

// ============================================================
// 4. Query builder — no direct fetch or duplicate token storage
// ============================================================

const FORECAST_API = "/api/forecast";

type QueryValue = string | number | boolean | null | undefined;

function withQuery(path: string, values: Record<string, QueryValue>): string {
  const query = new URLSearchParams();

  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }

  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

function standardParams(options: ForecastOptions): Record<string, QueryValue> {
  return {
    horizon_days: options.horizonDays,
    as_of_date: options.asOfDate,
    scenario: options.scenario,
  };
}

function timelineParams(
  options: ForecastTimelineOptions,
): Record<string, QueryValue> {
  return {
    ...standardParams(options),
    group_by: options.groupBy,
  };
}

// ============================================================
// 5. Authenticated, read-only forecast endpoints
// ============================================================

/** GET /api/forecast/summary — KPI totals and eligible invoice counts. */
export function getForecastSummary(
  options: ForecastOptions = {},
): Promise<ForecastSummaryResponse> {
  return apiGet<ForecastSummaryResponse>(
    withQuery(`${FORECAST_API}/summary`, standardParams(options)),
  );
}

/** GET /api/forecast/timeline — chart points grouped by day/week/month. */
export function getForecastTimeline(
  options: ForecastTimelineOptions = {},
): Promise<ForecastTimelineResponse> {
  return apiGet<ForecastTimelineResponse>(
    withQuery(`${FORECAST_API}/timeline`, timelineParams(options)),
  );
}

/** GET /api/forecast/invoices — paginated per-invoice projections. */
export function getForecastInvoices(
  options: ForecastInvoicesOptions = {},
): Promise<ForecastInvoiceListResponse> {
  return apiGet<ForecastInvoiceListResponse>(
    withQuery(`${FORECAST_API}/invoices`, {
      ...standardParams(options),
      page: options.page,
      page_size: options.pageSize,
      include_excluded: options.includeExcluded,
    }),
  );
}

/** GET /api/forecast/scenarios — conservative, base and optimistic results. */
export function getForecastScenarios(
  options: ForecastScenariosOptions = {},
): Promise<ForecastScenariosResponse> {
  return apiGet<ForecastScenariosResponse>(
    withQuery(`${FORECAST_API}/scenarios`, {
      horizon_days: options.horizonDays,
      as_of_date: options.asOfDate,
    }),
  );
}

/** GET /api/forecast/assumptions — probabilities and their sources. */
export function getForecastAssumptions(
  options: ForecastOptions = {},
): Promise<ForecastAssumptionsResponse> {
  return apiGet<ForecastAssumptionsResponse>(
    withQuery(`${FORECAST_API}/assumptions`, standardParams(options)),
  );
}

/** GET /api/forecast/insights — calculation service's rule-based warnings. */
export function getForecastInsights(
  options: ForecastOptions = {},
): Promise<ForecastInsightsResponse> {
  return apiGet<ForecastInsightsResponse>(
    withQuery(`${FORECAST_API}/insights`, standardParams(options)),
  );
}

/**
 * GET /api/forecast/dashboard — preferred single request for the main UI.
 * Returns summary, timeline, all scenarios and basic insights together.
 */
export function getForecastDashboard(
  options: ForecastTimelineOptions = {},
): Promise<ForecastDashboardResponse> {
  return apiGet<ForecastDashboardResponse>(
    withQuery(`${FORECAST_API}/dashboard`, timelineParams(options)),
  );
}

/**
 * GET /api/forecast/agent-insights — prioritised review suggestions.
 * This endpoint does NOT send reminders or modify invoice/payment records.
 */
export function getForecastAgentInsights(
  options: ForecastAgentOptions = {},
): Promise<ForecastInsightsResponse> {
  return apiGet<ForecastInsightsResponse>(
    withQuery(`${FORECAST_API}/agent-insights`, {
      ...timelineParams(options),
      max_actions: options.maxActions,
    }),
  );
}
