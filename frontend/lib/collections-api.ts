import { apiGet, apiPost, getToken } from "@/lib/api";

export type AgingBucket = { key: string; label: string; amount: string; invoice_count: number };
export type CollectionSummary = {
  as_of_date: string; currency: string; total_invoices: number;
  total_invoiced: string; total_recorded_payments: string;
  total_outstanding: string; total_overpayments: string; total_overdue: string;
  total_due_soon: string; collection_rate_percent: string;
  paid_invoice_count: number; partially_paid_invoice_count: number;
  unpaid_invoice_count: number; overdue_invoice_count: number;
  due_soon_invoice_count: number; aging_buckets: AgingBucket[];
};
export type ScoreBreakdown = { overdue: number; upcoming: number; amount: number; payment_history: number; reminder_history: number };
export type Receivable = {
  invoice_id: number; invoice_number: string; customer_name: string;
  customer_email: string | null; currency: string; invoice_date: string;
  due_date: string; invoice_total: string; paid_amount: string;
  outstanding_amount: string; overpayment_amount: string; payment_count: number;
  payment_status: string; days_overdue: number | null; aging_bucket: string;
  aging_label: string; is_overdue: boolean; due_soon: boolean;
  review_status: string; warnings: string[];
};
export type PriorityInvoice = Receivable & {
  priority_score: number; priority_level: string; priority_label: string;
  priority_reasons: string[]; recommended_action: string;
  reminder_count: number; collection_eligible: boolean;
  priority_warnings: string[]; scoring_date: string;
  score_breakdown?: ScoreBreakdown | null;
};
export type CollectionQueue = { total: number; as_of_date: string; currency: string; invoices: PriorityInvoice[] };
export type PrioritySummary = {
  as_of_date: string; currency: string; total_actionable_invoices: number;
  high_priority_count: number; medium_priority_count: number;
  low_priority_count: number; manual_review_count: number;
  categories: {priority: string; label: string; invoice_count: number; outstanding_amount: string}[];
};
export type PaymentInput = {
  invoice_id: number; amount_aed: string; payment_date: string;
  payment_reference: string; notes: string | null;
};
export type Payment = {
  id: number; invoice_id: number; amount_aed: string;
  payment_date: string; payment_reference: string | null;
  notes: string | null; created_at: string;
};
export type PaymentResult = { success: boolean; message: string; payment: Payment; receivable: Receivable };
export type ReminderDraft = {
  invoice_id: number; channel: "email"; tone: "friendly" | "professional" | "firm";
  stage: string; subject: string; message: string;
  generation_method: "openai" | "local_template";
  ai_used: boolean; approval_status: "draft";
  requires_admin_approval: boolean; sent: false; created_at: string; warnings: string[];
};
export type SavedReminder = {
  id: number; invoice_id: number; channel: string; subject: string;
  message: string; approval_status: string; approved_at?: string | null;
  created_at: string; sent?: boolean;
};

export const getCollectionSummary = () => apiGet<CollectionSummary>("/api/collections/summary");
export const getCollectionQueue = () => apiGet<CollectionQueue>("/api/collections/queue");
export const getPrioritySummary = () => apiGet<PrioritySummary>("/api/collections/priorities");
export const getCollectionReceivable = (id: number) => apiGet<Receivable>(`/api/collections/invoices/${id}`);
export const getCollectionPayments = (id: number) => apiGet<Payment[]>(`/api/collections/invoices/${id}/payments`);
export const recordCollectionPayment = (input: PaymentInput) => apiPost<PaymentResult>("/api/collections/payments", input);
export const generateCollectionDraft = (invoice_id: number, tone: ReminderDraft["tone"]) =>
  apiPost<ReminderDraft>("/api/collections/reminders/generate", { invoice_id, tone, channel: "email" });
export const listCollectionReminders = () => apiGet<SavedReminder[]>("/api/reminders");
export const saveCollectionReminder = (draft: Pick<SavedReminder, "invoice_id" | "subject" | "message">) =>
  apiPost<SavedReminder>("/api/reminders/drafts", { ...draft, channel: "email" });
export const approveCollectionReminder = (id: number) => apiPost<SavedReminder>(`/api/reminders/${id}/approve`, {});
export const rejectCollectionReminder = (id: number, reason: string) =>
  apiPost<SavedReminder>(`/api/reminders/${id}/reject`, { reason });

// Existing lib/api.ts exports GET/POST/PUT but no PATCH helper.
// Keep this limited PATCH request here so existing API code is unchanged.
export async function editCollectionReminder(id: number, subject: string, message: string): Promise<SavedReminder> {
  const token = getToken();
  if (!token) throw new Error("Please sign in again.");
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
  let response: Response;
  try {
    response = await fetch(`${base}/api/reminders/${id}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ subject, message }), cache: "no-store",
    });
  } catch {
    throw new Error("Unable to connect to the ReceivAI API.");
  }
  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      if (typeof window !== "undefined") window.dispatchEvent(new Event("receivai:unauthorized"));
      throw new Error("Your session has expired. Please sign in again.");
    }
    const result = body as {detail?: string | {message?: string}};
    throw new Error(typeof result.detail === "string" ? result.detail : result.detail?.message || `Request failed (${response.status}).`);
  }
  return body as SavedReminder;
}
