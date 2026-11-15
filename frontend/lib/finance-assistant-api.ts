
/**
 * ReceivAI UAE — Finance Assistant API client (Module 4)
 *
 * Typed, authenticated requests to the existing FastAPI assistant routes.
 * Reuses lib/api.ts, which supplies the administrator bearer token,
 * session-expiry handling and `cache: "no-store"` for every request.
 *
 * The assistant is READ-ONLY. Financial amounts come from backend finance
 * services; forecast values are estimates, not guaranteed or bank-verified.
 * This module neither calculates accounting totals nor stores chat history.
 */

import { apiGet, apiPost } from "@/lib/api";

// ============================================================
// 1. SHARED TYPES
// ============================================================

export const FINANCE_ASSISTANT_HORIZONS = [7, 30, 60, 90] as const;

export type FinanceAssistantHorizon =
  (typeof FINANCE_ASSISTANT_HORIZONS)[number];

export type FinanceISODate = string;
export type FinanceISODateTime = string;

// Exact decimal string, e.g. "29260.00"
export type FinanceAEDAmount = string;

export type FinanceAssistantIntent =
  | "general"
  | "invoice_lookup"
  | "receivables_summary"
  | "overdue_analysis"
  | "payment_history"
  | "reconciliation"
  | "collection_priorities"
  | "cash_flow_forecast"
  | "document_reviews"
  | "reminder_status"
  | "unsupported";

export type FinanceDataSource =
  | "dashboard_summary"
  | "invoice_register"
  | "payment_ledger"
  | "payment_collections"
  | "cash_flow_forecast"
  | "document_intelligence"
  | "collection_reminders";

export type FinanceDataNature =
  | "recorded"
  | "calculated"
  | "estimated";

export type FinanceResponseStatus =
  | "success"
  | "partial"
  | "no_data";

export type FinanceSeverity =
  | "info"
  | "warning"
  | "critical";

export type FinanceValueType =
  | "aed"
  | "count"
  | "percent"
  | "date"
  | "text";

// ============================================================
// 2. CHAT REQUEST
// ============================================================

export interface FinanceChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface FinanceAssistantChatOptions {
  question: string;
  sessionId?: string | null;
  history?: FinanceChatHistoryMessage[];
  horizonDays?: FinanceAssistantHorizon;
}

// Exact FastAPI request structure
export interface FinanceAssistantChatRequest {
  question: string;
  session_id?: string | null;
  history?: FinanceChatHistoryMessage[];
  horizon_days?: FinanceAssistantHorizon;
}

// ============================================================
// 3. FINANCIAL METRICS
// ============================================================

export interface FinanceMetric {
  key: string;
  label: string;
  value: string;
  value_type: FinanceValueType;
  nature: FinanceDataNature;
  description: string | null;
  source: FinanceDataSource;
}

// ============================================================
// 4. FINANCIAL TABLES
// ============================================================

export interface FinanceTableColumn {
  key: string;
  label: string;
  value_type: FinanceValueType;
}

export type FinanceTableCell =
  | string
  | number
  | boolean
  | null;

export interface FinanceDataTable {
  title: string;
  columns: FinanceTableColumn[];
  rows: Array<Record<string, FinanceTableCell>>;
  description: string | null;
  nature: FinanceDataNature;
  source: FinanceDataSource;
  total_rows: number | null;
}

// ============================================================
// 5. INVOICE REFERENCES
// ============================================================

export interface FinanceInvoiceReference {
  invoice_id: number;
  invoice_number: string;
  customer_name: string | null;
  due_date: FinanceISODate | null;
  invoice_status: string | null;
  outstanding_aed: FinanceAEDAmount | null;
  days_overdue: number | null;
}

// ============================================================
// 6. INSIGHTS AND RECOMMENDATIONS
// ============================================================

export interface FinanceInsight {
  severity: FinanceSeverity;
  title: string;
  explanation: string;
  recommended_action: string | null;
  related_invoice_ids: number[];
  nature: FinanceDataNature;
}

// ============================================================
// 7. NAVIGATION ACTIONS
// ============================================================

export interface FinanceNavigationAction {
  label: string;
  href: string;
  description: string | null;
  kind: "navigate";
}

// ============================================================
// 8. DATA SOURCE EVIDENCE
// ============================================================

export interface FinanceEvidence {
  source: FinanceDataSource;
  description: string;
  nature: FinanceDataNature;
  as_of: FinanceISODateTime | null;
  record_ids: number[];
}

// ============================================================
// 9. CHAT RESPONSE
// ============================================================

export interface FinanceAssistantChatResponse {
  session_id: string | null;
  question: string;
  answer: string;
  intent: FinanceAssistantIntent;
  status: FinanceResponseStatus;

  generated_at: FinanceISODateTime;
  data_as_of: FinanceISODateTime | null;

  currency: "AED";
  read_only: true;

  metrics: FinanceMetric[];
  tables: FinanceDataTable[];
  invoices: FinanceInvoiceReference[];
  insights: FinanceInsight[];
  actions: FinanceNavigationAction[];
  evidence: FinanceEvidence[];

  warnings: string[];
  follow_up_questions: string[];
}

// ============================================================
// 10. SUGGESTED QUESTIONS
// ============================================================

export interface FinanceSuggestedQuestion {
  id: string;
  question: string;
  category: FinanceAssistantIntent;
  description: string | null;
}

export interface FinanceAssistantSuggestionsResponse {
  suggestions: FinanceSuggestedQuestion[];
}

// ============================================================
// 11. CAPABILITIES
// ============================================================

export interface FinanceAssistantCapability {
  id: string;
  title: string;
  description: string;
  available: boolean;
  sources: FinanceDataSource[];
  read_only: true;
}

export interface FinanceAssistantCapabilitiesResponse {
  capabilities: FinanceAssistantCapability[];
  supported_horizons_days: FinanceAssistantHorizon[];
  currency: "AED";
  read_only: true;
}

// ============================================================
// 12. API ERROR MODEL
// ============================================================

export interface FinanceAssistantErrorResponse {
  error_code:
    | "invalid_question"
    | "unsupported_question"
    | "data_unavailable"
    | "service_error";

  message: string;
  request_id: string | null;
}

// ============================================================
// 13. SEND CHAT MESSAGE
// ============================================================

export function chatWithFinanceAssistant(
  options: FinanceAssistantChatOptions,
): Promise<FinanceAssistantChatResponse> {

  const question = options.question.trim();

  if (question.length < 3 || question.length > 2000) {
    throw new Error(
      "Enter a financial question between 3 and 2,000 characters."
    );
  }

  const horizonDays = options.horizonDays ?? 30;

  if (
    !(FINANCE_ASSISTANT_HORIZONS as readonly number[])
      .includes(horizonDays)
  ) {
    throw new Error(
      "Forecast period must be 7, 30, 60 or 90 days."
    );
  }

  const sessionId = options.sessionId ?? null;

  if (
    sessionId !== null &&
    !/^[A-Za-z0-9_-]{8,128}$/.test(sessionId)
  ) {
    throw new Error(
      "Invalid assistant session identifier."
    );
  }

  const history = (options.history ?? [])
    .slice(-10)
    .map(({ role, content }) => ({
      role,
      content: content.trim(),
    }))
    .filter(
      (message) =>
        (
          message.role === "user" ||
          message.role === "assistant"
        ) &&
        message.content.length > 0 &&
        message.content.length <= 3000
    );

  const body: FinanceAssistantChatRequest = {
    question,
    horizon_days: horizonDays,
    history,
    ...(sessionId ? { session_id: sessionId } : {}),
  };

  return apiPost<FinanceAssistantChatResponse>(
    "/api/assistant/chat",
    body
  );
}

// ============================================================
// 14. FETCH SUGGESTED QUESTIONS
// ============================================================

export function getFinanceAssistantSuggestions():
  Promise<FinanceAssistantSuggestionsResponse> {

  return apiGet<FinanceAssistantSuggestionsResponse>(
    "/api/assistant/suggestions"
  );
}

// ============================================================
// 15. FETCH CAPABILITIES
// ============================================================

export function getFinanceAssistantCapabilities():
  Promise<FinanceAssistantCapabilitiesResponse> {

  return apiGet<FinanceAssistantCapabilitiesResponse>(
    "/api/assistant/capabilities"
  );
}

// ============================================================
// 16. AED DISPLAY FORMATTER
// ============================================================

// Presentation only. No floating-point money calculations.
export function formatFinanceAED(
  amount: FinanceAEDAmount | null | undefined,
): string {

  if (amount == null) return "—";

  const match = /^(-?)(\d+)\.(\d{2})$/.exec(amount);

  if (!match) return "—";

  const whole = match[2].replace(
    /\B(?=(\d{3})+(?!\d))/g,
    ","
  );

  return `${match[1] ? "−" : ""}AED ${whole}.${match[3]}`;
}
