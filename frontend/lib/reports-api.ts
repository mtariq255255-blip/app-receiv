
/**
 * ReceivAI UAE — Financial Reports API Client
 *
 * Authenticated, read-only financial reporting.
 *
 * Backend endpoints:
 * GET /api/reports/dashboard
 * GET /api/reports/export
 *
 * Features:
 * - Financial reporting data
 * - Customer and date filters
 * - Receivables aging
 * - Invoice and payment reports
 * - Collection and document reports
 * - Cash flow forecasts
 * - Reconciliation information
 * - Authenticated CSV downloads
 */

import {
  apiGet,
  getToken,
  clearToken,
} from "@/lib/api";

// ============================================================
// 1. REPORT TYPES
// ============================================================

export type ReportKind =
  | "aging"
  | "invoices"
  | "payments"
  | "collections"
  | "forecast"
  | "documents"
  | "reconciliation";

export type ExportReportKind =
  | "aging"
  | "invoices"
  | "payments"
  | "reconciliation";

// ============================================================
// 2. REPORT FILTERS
// ============================================================

export interface ReportFilters {
  startDate?: string;
  endDate?: string;
  customer?: string;
}

// ============================================================
// 3. REPORT SUMMARY
// ============================================================

export interface ReportSummary {
  total_outstanding_aed: string;
  overdue_outstanding_aed: string;
  recorded_collections_period_aed: string;

  open_invoice_count: number;

  reconciliation_required_count: number;
  reconciliation_amount_aed: string;

  invoices_issued_in_period: number;
  invoiced_value_in_period_aed: string;

  recorded_payment_count: number;
}

// ============================================================
// 4. RECEIVABLES AGING
// ============================================================

export interface AgingBucket {
  key: string;
  label: string;
  count: number;
  amount_aed: string;
}

// ============================================================
// 5. INVOICE REPORT
// ============================================================

export interface ReportInvoice {
  invoice_id: number;
  invoice_number: string;
  customer_name: string;

  issue_date: string | null;
  due_date: string | null;

  total_aed: string;
  recorded_paid_aed: string;
  outstanding_aed: string;

  days_overdue: number;
  status: string;
}

// ============================================================
// 6. PAYMENT REPORT
// ============================================================

export interface ReportPayment {
  id: number;
  invoice_id: number;

  date: string;

  invoice_number: string;
  customer_name: string;

  amount_aed: string;
  reference: string;
}

// ============================================================
// 7. STATUS COUNTS
// ============================================================

export interface ReportStatusCount {
  status: string;
  count: number;
}

// ============================================================
// 8. LEDGER STATUS
// ============================================================

export interface ReportLedgerStatus {
  label: string;
  count: number;
}

// ============================================================
// 9. COLLECTION TIMELINE
// ============================================================

export interface ReportCollectionTimeline {
  period: string;
  amount_aed: string;
  count: number;
}

// ============================================================
// 10. CASH FLOW FORECAST
// ============================================================

export interface ReportForecast {
  horizon_days: number;
  expected_receipts_aed: string;
  forecast_invoice_count: number;
}

// ============================================================
// 11. COMPLETE DASHBOARD RESPONSE
// ============================================================

export interface ReportsDashboardResponse {
  currency: "AED";
  read_only: true;

  as_of_date: string;

  period_start: string;
  period_end: string;

  customer_filter: string;

  summary: ReportSummary;

  aging: AgingBucket[];

  ledger_status: ReportLedgerStatus[];

  recorded_collections_timeline:
    ReportCollectionTimeline[];

  invoices: ReportInvoice[];

  aging_invoices: ReportInvoice[];

  payments: ReportPayment[];

  reminders: ReportStatusCount[];

  documents: ReportStatusCount[];

  forecasts: ReportForecast[];

  warnings: string[];

  totals_cover_all_matching_records: boolean;
}

// ============================================================
// 12. BUILD REPORT QUERY PARAMETERS
// ============================================================

function parameters(
  filters: ReportFilters,
): URLSearchParams {
  const params = new URLSearchParams();

  if (filters.startDate) {
    params.set(
      "start_date",
      filters.startDate,
    );
  }

  if (filters.endDate) {
    params.set(
      "end_date",
      filters.endDate,
    );
  }

  if (filters.customer?.trim()) {
    params.set(
      "customer",
      filters.customer.trim(),
    );
  }

  return params;
}

// ============================================================
// 13. FETCH FINANCIAL REPORTS
// ============================================================

export function getFinancialReports(
  filters: ReportFilters = {},
): Promise<ReportsDashboardResponse> {
  const query = parameters(filters).toString();

  const endpoint = query
    ? `/api/reports/dashboard?${query}`
    : "/api/reports/dashboard";

  return apiGet<ReportsDashboardResponse>(
    endpoint,
  );
}

// ============================================================
// 14. AUTHENTICATED CSV EXPORT
// ============================================================

/**
 * Download CSV reports using the administrator JWT.
 *
 * The JWT is sent in the Authorization header,
 * never in the URL.
 *
 * CSV is generated by the backend.
 * This function does not calculate financial figures.
 */

export async function exportFinancialReportCSV(
  kind: ExportReportKind,
  filters: ReportFilters = {},
): Promise<void> {
  // Browser-only operation
  if (typeof window === "undefined") {
    return;
  }

  // --------------------------------------------------------
  // ADMINISTRATOR TOKEN
  // --------------------------------------------------------

  const token = getToken();

  if (!token) {
    throw new Error(
      "Sign in to export financial reports.",
    );
  }

  // --------------------------------------------------------
  // REPORT FILTERS
  // --------------------------------------------------------

  const query = parameters(filters);

  query.set("kind", kind);

  // --------------------------------------------------------
  // BACKEND URL
  // --------------------------------------------------------

  const base = (
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");

  const url =
    `${base}/api/reports/export?${query.toString()}`;

  // --------------------------------------------------------
  // DOWNLOAD REQUEST
  // --------------------------------------------------------

  const response = await fetch(url, {
    method: "GET",

    headers: {
      Authorization: `Bearer ${token}`,
    },

    cache: "no-store",
  });

  // --------------------------------------------------------
  // HANDLE EXPIRED ADMIN SESSION
  // --------------------------------------------------------

  if (response.status === 401) {
    clearToken();

    window.dispatchEvent(
      new Event("receivai:unauthorized"),
    );

    throw new Error(
      "Session expired. Please sign in again.",
    );
  }

  // --------------------------------------------------------
  // HANDLE API FAILURE
  // --------------------------------------------------------

  if (!response.ok) {
    throw new Error(
      "Unable to export report. Please retry.",
    );
  }

  // --------------------------------------------------------
  // PREPARE CSV DOWNLOAD
  // --------------------------------------------------------

  const blob = await response.blob();

  const objectUrl =
    URL.createObjectURL(blob);

  const element =
    document.createElement("a");

  element.href = objectUrl;

  const date =
    new Date().toISOString().slice(0, 10);

  element.download =
    `receivai_${kind}_${date}.csv`;

  document.body.appendChild(element);

  // Trigger download
  element.click();

  // Remove temporary element
  element.remove();

  // Release browser object URL
  window.setTimeout(() => {
    URL.revokeObjectURL(objectUrl);
  }, 1000);
}
