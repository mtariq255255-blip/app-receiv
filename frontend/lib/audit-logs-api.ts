
/**
 * ReceivAI UAE — Audit Logs API Client
 *
 * Module 6: Administrator Audit Logs
 *
 * Features:
 * - Authenticated audit history
 * - Pagination
 * - Date range filtering
 * - Action and entity filtering
 * - Search
 * - Available filter options
 * - Secure CSV export
 *
 * All audit operations are read-only.
 */

import {
  apiGet,
  clearToken,
  getToken,
} from "@/lib/api";

// ============================================================
// 1. AUDIT LOG FILTERS
// ============================================================

export type AuditFilters = {
  startDate?: string;
  endDate?: string;
  action?: string;
  entityType?: string;
  search?: string;
  page?: number;
  pageSize?: number;
};

// ============================================================
// 2. AUDIT EVENT DETAILS
// ============================================================

export type AuditEventDetails = Record<
  string,
  string | number | boolean | null | string[]
>;

// ============================================================
// 3. AUDIT EVENT
// ============================================================

export type AuditEvent = {
  id: number;

  created_at: string | null;

  actor_name: string;
  actor_email: string | null;

  action: string;

  entity_type: string | null;
  entity_id: number | null;

  details: AuditEventDetails;
};

// ============================================================
// 4. AUDIT ACTION STATISTICS
// ============================================================

export type AuditActionCount = {
  action: string;
  count: number;
};

// ============================================================
// 5. AUDIT HISTORY RESPONSE
// ============================================================

export type AuditResponse = {
  total: number;

  page: number;
  page_size: number;

  has_next: boolean;

  items: AuditEvent[];

  top_actions: AuditActionCount[];

  timezone: string;

  read_only: boolean;

  disclaimer: string;
};

// ============================================================
// 6. AUDIT FILTER OPTIONS
// ============================================================

export type AuditFilterOptions = {
  actions: string[];
  entity_types: string[];
};

// ============================================================
// 7. BUILD QUERY PARAMETERS
// ============================================================

function paramsFor(
  filters: AuditFilters
): URLSearchParams {
  const params = new URLSearchParams();

  if (filters.startDate) {
    params.set(
      "start_date",
      filters.startDate
    );
  }

  if (filters.endDate) {
    params.set(
      "end_date",
      filters.endDate
    );
  }

  if (filters.action) {
    params.set(
      "action",
      filters.action
    );
  }

  if (filters.entityType) {
    params.set(
      "entity_type",
      filters.entityType
    );
  }

  if (filters.search?.trim()) {
    params.set(
      "search",
      filters.search.trim()
    );
  }

  if (filters.page !== undefined) {
    params.set(
      "page",
      String(filters.page)
    );
  }

  if (filters.pageSize !== undefined) {
    params.set(
      "page_size",
      String(filters.pageSize)
    );
  }

  return params;
}

// ============================================================
// 8. FETCH AUDIT LOG HISTORY
// ============================================================

/**
 * Retrieves paginated audit records from the backend.
 *
 * Endpoint:
 * GET /api/audit-logs
 *
 * Supports:
 * - Start date
 * - End date
 * - Action
 * - Entity type
 * - Search term
 * - Page
 * - Page size
 */

export function listAuditLogs(
  filters: AuditFilters = {}
): Promise<AuditResponse> {
  const query = paramsFor(filters).toString();

  const endpoint = query
    ? `/api/audit-logs?${query}`
    : "/api/audit-logs";

  return apiGet<AuditResponse>(
    endpoint
  );
}

// ============================================================
// 9. FETCH FILTER OPTIONS
// ============================================================

/**
 * Retrieves distinct audit actions and entity types.
 *
 * Endpoint:
 * GET /api/audit-logs/actions
 */

export function getAuditFilterOptions():
  Promise<AuditFilterOptions> {
  return apiGet<AuditFilterOptions>(
    "/api/audit-logs/actions"
  );
}

// ============================================================
// 10. EXPORT AUDIT LOGS AS CSV
// ============================================================

/**
 * Downloads audit history using the administrator JWT.
 *
 * Endpoint:
 * GET /api/audit-logs/export
 *
 * Returns true if the backend truncated the export
 * because it exceeded the maximum permitted rows.
 */

export async function exportAuditLogsCSV(
  filters: AuditFilters = {}
): Promise<boolean> {

  // ----------------------------------------------------------
  // BROWSER CHECK
  // ----------------------------------------------------------

  if (typeof window === "undefined") {
    throw new Error(
      "Audit export is only available in the browser."
    );
  }

  // ----------------------------------------------------------
  // ADMINISTRATOR AUTHENTICATION
  // ----------------------------------------------------------

  const token = getToken();

  if (!token) {
    throw new Error(
      "Please sign in to export audit history."
    );
  }

  // ----------------------------------------------------------
  // BACKEND BASE URL
  // ----------------------------------------------------------

  const base = (
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");

  // ----------------------------------------------------------
  // FILTER PARAMETERS
  // ----------------------------------------------------------

  const query = paramsFor(filters).toString();

  const endpoint = query
    ? `${base}/api/audit-logs/export?${query}`
    : `${base}/api/audit-logs/export`;

  // ----------------------------------------------------------
  // AUTHENTICATED API REQUEST
  // ----------------------------------------------------------

  const response = await fetch(endpoint, {
    method: "GET",

    headers: {
      Authorization: `Bearer ${token}`,
    },

    cache: "no-store",
  });

  // ----------------------------------------------------------
  // EXPIRED ADMIN SESSION
  // ----------------------------------------------------------

  if (response.status === 401) {
    clearToken();

    window.dispatchEvent(
      new Event("receivai:unauthorized")
    );

    throw new Error(
      "Your session expired. Please sign in again."
    );
  }

  // ----------------------------------------------------------
  // API ERROR
  // ----------------------------------------------------------

  if (!response.ok) {
    throw new Error(
      "Unable to export audit logs."
    );
  }

  // ----------------------------------------------------------
  // CHECK EXPORT LIMIT
  // ----------------------------------------------------------

  const truncated =
    response.headers.get(
      "X-Audit-Export-Truncated"
    ) === "true";

  // ----------------------------------------------------------
  // PREPARE CSV FILE
  // ----------------------------------------------------------

  const blob = await response.blob();

  const objectURL =
    URL.createObjectURL(blob);

  // ----------------------------------------------------------
  // DOWNLOAD FILE
  // ----------------------------------------------------------

  try {
    const element =
      document.createElement("a");

    element.href = objectURL;

    element.download =
      "receivai_audit_logs.csv";

    document.body.appendChild(
      element
    );

    element.click();

    element.remove();
  } finally {
    window.setTimeout(() => {
      URL.revokeObjectURL(objectURL);
    }, 1000);
  }

  return truncated;
}
