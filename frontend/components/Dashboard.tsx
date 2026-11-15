"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { apiGet, apiPost, getDocuments } from "@/lib/api";
import DocumentUpload from "@/components/documents/DocumentUpload";
import WorkspaceSidebar from "@/components/WorkspaceSidebar";
import CashFlowForecastDashboard from "@/components/forecast/CashFlowForecastDashboard";
import FinanceAssistant from "@/components/assistant/FinanceAssistant";
import ReportsDashboard from "@/components/reports/ReportsDashboard";
import UaeGreeting from "@/components/UaeGreeting";
import { getForecastSummary, type ForecastSummaryResponse } from "@/lib/cash-flow-api";
import AuditLogsDashboard from "@/components/audit/AuditLogsDashboard";


type Summary = {
  invoice_count: number;
  paid_count: number;
  unpaid_count: number;
  overdue_count: number;
  outstanding_aed: string;
  currency?: string;
  data_label?: string;
};

type Invoice = {
  id: number;
  invoice_number: string;
  customer_name: string;
  customer_email?: string | null;
  amount_aed: string;
  issue_date: string;
  due_date: string;
  status: string;
};

type Reminder = {
  id: number;
  invoice_id: number;
  subject: string;
  message: string;
  approval_status: string;
  channel: string;
};

type PendingDoc = {
  id: number;
  original_filename: string;
  processing_status: string;
  extraction_notes?: string | null;
  extracted_data?: Record<string, unknown> | null;
  uploaded_at?: string;
};

type PendingDocumentsResponse = {
  count: number;
  documents: PendingDoc[];
};

type ReviewItem = {
  description: string;
  quantity: string;
  unit: string;
  unit_price_aed: string;
  discount_aed: string;
  taxable_value_aed: string;
  vat_rate: string;
  vat_amount_aed: string;
  line_total_aed: string;
};

type DashboardProps = {
  adminEmail?: string;
  onLogout: () => void;
};

const money = (v: number | string | null | undefined) =>
  `AED ${Number(v ?? 0).toLocaleString("en-AE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const dateLabel = (v?: string) =>
  v
    ? new Date(`${v.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    : "—";

const objectValue = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};

const reviewLabel = (value: unknown) =>
  value === null || value === undefined || value === ""
    ? "Not found"
    : String(value);

export default function Dashboard({
  adminEmail,
  onLogout,
}: DashboardProps) {
  const router = useRouter();
  // Start consistently for server rendering; read URL after hydration.
  const [view, setView] = useState("Overview");

  useEffect(() => {
    const syncView = () => {
      const requestedView = new URLSearchParams(window.location.search).get("view");
      if (requestedView === "Payment Collections") {
        router.replace("/collections");
        return;
      }
    
      const availableViews = [
        "Overview",
        "Invoice Management",
        "Cash Flow Forecast",
        "AI Finance Assistant",
        "Reports",
        "Audit Logs",
      ];
      setView(requestedView && availableViews.includes(requestedView) ? requestedView : "Overview");
    };

    syncView();
    window.addEventListener("popstate", syncView);
    return () => window.removeEventListener("popstate", syncView);
  }, [router]);

  const [summary, setSummary] = useState<Summary | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [pending, setPending] = useState<PendingDoc[]>([]);
  const [documentReviewCount, setDocumentReviewCount] = useState(0);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [reviewDoc, setReviewDoc] = useState<PendingDoc | null>(null);
  const [reviewInvoiceIndex, setReviewInvoiceIndex] = useState(0);

  const [reviewForm, setReviewForm] = useState<{
    invoice_number: string;
    supplier_name: string;
    supplier_address: string;
    supplier_emirate: string;
    supplier_trn: string;
    customer_name: string;
    customer_email: string;
    customer_address: string;
    customer_emirate: string;
    customer_trn: string;
    currency: string;
    place_of_supply: string;
    amount_aed: string;
    subtotal_aed: string;
    discount_aed: string;
    vat_amount_aed: string;
    issue_date: string;
    supply_date: string;
    due_date: string;
    notes: string;
    items: ReviewItem[];
  }>({
    invoice_number: "",
    supplier_name: "",
    supplier_address: "",
    supplier_emirate: "",
    supplier_trn: "",
    customer_name: "",
    customer_email: "",
    customer_address: "",
    customer_emirate: "",
    customer_trn: "",
    currency: "",
    place_of_supply: "",
    amount_aed: "",
    subtotal_aed: "",
    discount_aed: "",
    vat_amount_aed: "",
    issue_date: "",
    supply_date: "",
    due_date: "",
    notes: "",
    items: [],
  });

  const [savingReview, setSavingReview] = useState(false);
  const [reprocessingId, setReprocessingId] = useState<number | null>(null);
  const [validationResult, setValidationResult] =
    useState<Record<string, unknown> | null>(null);
  const [validatingReview, setValidatingReview] = useState(false);
  const [rejectingReview, setRejectingReview] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const [s, i, r, p, documentCount] = await Promise.all([
        apiGet<Summary>("/api/dashboard/summary"),
        apiGet<Invoice[]>("/api/invoices"),
        apiGet<Reminder[]>("/api/reminders"),
        apiGet<PendingDocumentsResponse>("/api/documents/pending"),
        getDocuments({ status: "pending_review", page: 1, pageSize: 1 }),
      ]);

      setSummary(s);
      setInvoices(i);
      setReminders(r);
      setPending(p.documents);
      setDocumentReviewCount(documentCount.total);
    } catch (e: unknown) {
      setError(
        e instanceof Error
          ? e.message
          : "Unable to load finance records."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  // A paid/unpaid status toggle does not record a receipt in the payment ledger.
  // Route the administrator to Payment Collections for a confirmation, payment
  // history review, amount, date, method and unique reference. Invoice status
  // must follow the ledger rather than being changed silently from this table.
  const openPaymentRecording = useCallback((invoice: Invoice) => {
    router.push(`/collections?invoice=${invoice.id}`);
  }, [router]);

  useEffect(() => {
    const timeout = setTimeout(() => {
      void loadData();
    }, 0);

    return () => clearTimeout(timeout);
  }, [loadData]);

  function openReview(doc: PendingDoc, requestedIndex?: number) {
    const d = doc.extracted_data || {};
    const extraction = objectValue(d.structured_extraction);
    const extractedInvoices = Array.isArray(extraction.invoices)
      ? extraction.invoices
      : [];
    const approvedIndices = Array.isArray(d.approved_invoice_indices)
      ? d.approved_invoice_indices
      : [];
    const invoiceIndex =
      requestedIndex ??
      extractedInvoices.findIndex(
        (_, index) => !approvedIndices.includes(index),
      );
    const selectedInvoiceIndex = invoiceIndex < 0 ? 0 : invoiceIndex;
    const structured = selectedInvoiceIndex === 0 &&
      Object.keys(objectValue(d.structured_invoice)).length
      ? objectValue(d.structured_invoice)
      : objectValue(extractedInvoices[selectedInvoiceIndex]);
    const invoiceReviews = objectValue(d.invoice_reviews);
    const reviewFields = objectValue(invoiceReviews[String(selectedInvoiceIndex)]);
    const fields = {
      ...structured,
      ...(selectedInvoiceIndex === 0 ? objectValue(d.fields) : {}),
      ...reviewFields,
    };
    const itemSource = Array.isArray(structured.items)
      ? structured.items
      : [];

    setReviewDoc(doc);
    setReviewInvoiceIndex(selectedInvoiceIndex);
    const validations = objectValue(d.invoice_validations);
    const savedValidation = objectValue(
      validations[String(selectedInvoiceIndex)],
    );
    setValidationResult(
      Object.keys(objectValue(savedValidation.result)).length
        ? objectValue(savedValidation.result)
        : selectedInvoiceIndex === 0 &&
          Object.keys(objectValue(d.validation)).length
        ? objectValue(d.validation)
        : null
    );
    setReviewForm({
      invoice_number: String(fields.invoice_number ?? ""),
      supplier_name: String(fields.supplier_name ?? ""),
      supplier_address: String(fields.supplier_address ?? ""),
      supplier_emirate: String(fields.supplier_emirate ?? ""),
      supplier_trn: String(fields.supplier_trn ?? ""),
      customer_name: String(fields.customer_name ?? ""),
      customer_email: String(fields.customer_email ?? ""),
      customer_address: String(fields.customer_address ?? ""),
      customer_emirate: String(fields.customer_emirate ?? ""),
      customer_trn: String(fields.customer_trn ?? ""),
      currency: String(fields.currency ?? ""),
      place_of_supply: String(fields.place_of_supply ?? ""),
      amount_aed: String(fields.amount_aed ?? fields.total_amount_aed ?? ""),
      subtotal_aed: String(fields.subtotal_aed ?? ""),
      discount_aed: String(fields.discount_aed ?? ""),
      vat_amount_aed: String(fields.vat_amount_aed ?? ""),
      issue_date: String(fields.issue_date ?? ""),
      supply_date: String(fields.supply_date ?? ""),
      due_date: String(fields.due_date ?? ""),
      notes: String(fields.notes ?? d.notes ?? ""),
      items: itemSource.map((item) => {
        const row = objectValue(item);
        return {
          description: String(row.description ?? ""),
          quantity: String(row.quantity ?? ""),
          unit: String(row.unit ?? ""),
          unit_price_aed: String(row.unit_price_aed ?? ""),
          discount_aed: String(row.discount_aed ?? ""),
          taxable_value_aed: String(row.taxable_value_aed ?? ""),
          vat_rate: String(row.vat_rate ?? ""),
          vat_amount_aed: String(row.vat_amount_aed ?? ""),
          line_total_aed: String(row.line_total_aed ?? ""),
        };
      }),
    });
  }

  function reviewPayload() {
    const optional = (value: string) => value.trim() || null;
    return {
      invoice_number: reviewForm.invoice_number,
      supplier_name: optional(reviewForm.supplier_name),
      supplier_address: optional(reviewForm.supplier_address),
      supplier_emirate: optional(reviewForm.supplier_emirate),
      supplier_trn: optional(reviewForm.supplier_trn),
      customer_name: reviewForm.customer_name,
      customer_email: optional(reviewForm.customer_email),
      customer_address: optional(reviewForm.customer_address),
      customer_emirate: optional(reviewForm.customer_emirate),
      customer_trn: optional(reviewForm.customer_trn),
      currency: optional(reviewForm.currency),
      place_of_supply: optional(reviewForm.place_of_supply),
      amount_aed: optional(reviewForm.amount_aed),
      subtotal_aed: optional(reviewForm.subtotal_aed),
      discount_aed: optional(reviewForm.discount_aed),
      vat_amount_aed: optional(reviewForm.vat_amount_aed),
      total_amount_aed: optional(reviewForm.amount_aed),
      issue_date: optional(reviewForm.issue_date),
      supply_date: optional(reviewForm.supply_date),
      due_date: optional(reviewForm.due_date),
      notes: optional(reviewForm.notes),
      invoice_index: reviewInvoiceIndex,
      items: reviewForm.items.map((item) => ({
        description: optional(item.description),
        quantity: optional(item.quantity),
        unit: optional(item.unit),
        unit_price_aed: optional(item.unit_price_aed),
        discount_aed: optional(item.discount_aed),
        taxable_value_aed: optional(item.taxable_value_aed),
        vat_rate: optional(item.vat_rate),
        vat_amount_aed: optional(item.vat_amount_aed),
        line_total_aed: optional(item.line_total_aed),
      })),
    };
  }

  function updateReviewForm(changes: Partial<typeof reviewForm>) {
    setReviewForm((current) => ({ ...current, ...changes }));
    setValidationResult(null);
  }

  async function validateReview() {
    if (!reviewDoc) return;
    setValidatingReview(true);
    setError("");
    try {
      const result = await apiPost<Record<string, unknown>>(
        `/api/documents/${reviewDoc.id}/validate`,
        reviewPayload(),
      );
      setValidationResult(result);
      setReviewDoc((current) =>
        current
          ? {
              ...current,
              extracted_data: {
                ...(current.extracted_data || {}),
                validation: result,
              },
            }
          : current,
      );
      await loadData();
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not validate this invoice."
      );
    } finally {
      setValidatingReview(false);
    }
  }

  async function approveReview(e: FormEvent) {
    e.preventDefault();

    if (!reviewDoc) return;

    setSavingReview(true);
    setError("");

    try {
      await apiPost(`/api/documents/${reviewDoc.id}/approve`, {
        ...reviewPayload(),
      });

      setNotice("Invoice reviewed and saved to the invoice register.");
      setReviewDoc(null);

      await loadData();
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not save reviewed invoice."
      );
    } finally {
      setSavingReview(false);
    }
  }

  async function rejectReview() {
    if (!reviewDoc) return;
    const reason = window.prompt("Enter a reason for rejecting this document:");
    if (!reason?.trim()) return;
    setRejectingReview(true);
    setError("");
    try {
      await apiPost(`/api/documents/${reviewDoc.id}/reject`, {
        reason: reason.trim(),
      });
      setNotice("Document rejected and retained for audit.");
      setReviewDoc(null);
      setValidationResult(null);
      await loadData();
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Could not reject this document."
      );
    } finally {
      setRejectingReview(false);
    }
  }

  async function reprocessDocument(doc: PendingDoc) {
    setReprocessingId(doc.id);
    setError("");
    try {
      const action = doc.processing_status === "uploaded" ? "process" : "retry";
      await apiPost(`/api/documents/${doc.id}/${action}`, {});
      setNotice("Document reprocessed. Review the refreshed extraction before approval.");
      await loadData();
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Document reprocessing failed."
      );
    } finally {
      setReprocessingId(null);
    }
  }


  return (
    <div className="app-shell">
      <style>{`
        .app-shell aside a,
        .app-shell aside a:hover,
        .app-shell aside a:focus,
        .app-shell .sidebar a,
        .app-shell .sidebar a:hover,
        .app-shell .sidebar a:focus,
        .app-shell nav a,
        .app-shell nav a:hover,
        .app-shell nav a:focus {
          text-decoration: none !important;
        }
      `}</style>
      <WorkspaceSidebar
        activeView={view}
        pendingCount={documentReviewCount}
        onSelect={(selectedView) => {
          if (selectedView === "Payment Collections") {
            router.push("/collections");
            return;
          }
          setNotice("");
          setView(selectedView);
          // Preserve the selected workspace view on reload and direct links.
          const url = new URL(window.location.href);
          url.searchParams.set("view", selectedView);
          window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
        }}
      />

      <div className="main-area">
        <header className="topbar">
          <div>
            <div className="welcome-title">
              <UaeGreeting />
            </div>
            <div className="welcome-sub">
              Here is your receivables and collections overview for today.
            </div>
          </div>

          <div className="top-actions">
            <div className="searchbox">
              <i className="bi bi-search" />
              <input
                className="form-control"
                placeholder="Search invoices, customers…"
                onChange={(e) => {
                  (window as Window & { __receivaiSearch?: string }).__receivaiSearch =
                    e.target.value;
                }}
              />
            </div>

            <button
              className="icon-button"
              title="Notifications"
              onClick={() => setNotice("You are all caught up.")}
            >
              <i className="bi bi-bell" />
              <span className="notification-dot" />
            </button>

            <div className="avatar">AD</div>

            <div className="admin-label">
              {adminEmail || "Administrator"}
            </div>

            <button
              className="icon-button"
              type="button"
              title="Sign out"
              aria-label="Sign out"
              onClick={onLogout}
            >
              <i className="bi bi-box-arrow-right" />
            </button>
          </div>
        </header>

        <main className="content">
          {/* Each of these modules renders its own page heading. */}
          {view !== "Cash Flow Forecast" &&
            view !== "AI Finance Assistant" &&
            view !== "Reports" &&
            view !== "Audit Logs" && (
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  Receivables workspace / {view}
                </div>

                <h1 className="page-title">{view}</h1>

                <div className="page-subtitle">
                  From unpaid invoices to intelligent cash-flow decisions.
                </div>
              </div>

              <span className="demo-pill">
                {!summary
                  ? "Loading database records…"
                  : /synthetic|demo/i.test(summary.data_label ?? "")
                    ? "Database records · includes test/demo data"
                    : summary.data_label || "Database records"}
              </span>
            </div>
          )}

          {error && (
            <div className="alert alert-danger py-2 small">
              {error}
              <button
                className="btn btn-sm btn-link"
                onClick={loadData}
              >
                Retry
              </button>
            </div>
          )}

          {notice && (
            <div className="alert alert-info py-2 small">
              {notice}
              <button
                className="btn btn-sm btn-link"
                onClick={() => setNotice("")}
              >
                Dismiss
              </button>
            </div>
          )}

          {loading && (
            <div className="small muted mb-2">
              Refreshing finance records…
            </div>
          )}

          {view === "Overview" && (
            <Overview
              summary={summary}
              invoices={invoices}
              setView={setView}
              reminders={reminders}
              onStatusChange={openPaymentRecording}
            />
          )}

          {view === "Invoice Management" && (
            <>
              {/* Manual invoice creation entry point */}
              <div className="panel mb-3">
                <div className="d-flex flex-wrap align-items-center justify-content-between gap-3">
                  <div>
                    <h2 className="panel-title mb-1">Create a new invoice</h2>
                    <div className="panel-subtitle">
                      Enter invoice details, calculate AED totals, save drafts and generate a PDF.
                    </div>
                  </div>
                  <Link className="btn btn-brand" href="/invoices/new">
                    <i className="bi bi-file-earmark-plus me-2" aria-hidden="true" />
                    Generate Invoice
                  </Link>
                </div>
              </div>

              <div className="row g-3 mb-3">
                <div className="col-12">
                  <DocumentUpload
                    onUploaded={async () => {
                      await loadData();
                      setView("Invoice Management");
                    }}
                  />
                </div>
              </div>

              <div className="panel mb-3">
                <div className="d-flex justify-content-between align-items-center mb-3">
                  <div>
                    <h2 className="panel-title">
                      Pending invoice reviews
                    </h2>
                    <div className="panel-subtitle">
                      Check extracted details and correct them before saving to the invoice register.
                    </div>
                  </div>

                  <span className="badge rounded-pill text-bg-info">
                    {pending.length} pending
                  </span>
                </div>

                {pending.length ? (
                  pending.map((doc) => (
                    <div className="review-card" key={doc.id}>
                      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2">
                        <div>
                          <div className="fw-bold">
                            {doc.original_filename}
                          </div>

                          <div className="small muted">
                            Document #{doc.id} · {doc.processing_status}
                          </div>

                          {doc.extraction_notes && (
                            <div className="small text-warning mt-1">
                              {doc.extraction_notes}
                            </div>
                          )}
                        </div>

                        <button
                          className="btn btn-outline-primary btn-sm"
                          disabled={doc.processing_status !== "pending_review"}
                          onClick={() => router.push(`/documents/${doc.id}`)}
                        >
                          Review extracted details
                        </button>
                        <button
                          className="btn btn-outline-secondary btn-sm"
                          disabled={
                            reprocessingId === doc.id ||
                            !["uploaded", "processing_failed"].includes(
                              doc.processing_status,
                            )
                          }
                          onClick={() => void reprocessDocument(doc)}
                        >
                          {reprocessingId === doc.id
                            ? "Processing…"
                            : doc.processing_status === "uploaded"
                            ? "Start processing"
                            : "Retry processing"}
                        </button>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="empty-state">
                    <i className="bi bi-file-earmark-check fs-4 d-block mb-2" />
                    No pending documents. Upload a supported file to begin extraction.
                  </div>
                )}
              </div>

              <div className="panel">
                <div className="d-flex justify-content-between mb-3">
                  <h2 className="panel-title">Invoice register</h2>

                  <button
                    className="btn btn-light btn-sm"
                    onClick={loadData}
                  >
                    <i className="bi bi-arrow-clockwise me-1" />
                    Refresh
                  </button>
                </div>

                <InvoiceTable
                  invoices={invoices}
                  onStatusChange={openPaymentRecording}
                />
              </div>

              {reviewDoc && (
                <div
                  className="modal d-block"
                  tabIndex={-1}
                  style={{
                    background: "#101d3177",
                    overflowY: "auto",
                  }}
                >
                  <div className="modal-dialog modal-lg modal-dialog-centered">
                    <div className="modal-content border-0 rounded-4">
                      <form onSubmit={approveReview}>
                        <div className="modal-header">
                          <div>
                            <h5 className="modal-title fw-bold">
                              Review extracted invoice
                            </h5>
                            <div className="small muted">
                              {reviewDoc.original_filename}
                            </div>
                          </div>

                          <button
                            type="button"
                            className="btn-close"
                            onClick={() => setReviewDoc(null)}
                          />
                        </div>

                        <div className="modal-body">
                          {Array.isArray(
                            objectValue(
                              objectValue(reviewDoc.extracted_data)
                                .structured_extraction,
                            ).invoices,
                          ) &&
                            (objectValue(
                              objectValue(reviewDoc.extracted_data)
                                .structured_extraction,
                            ).invoices as unknown[]).length > 1 && (
                              <div className="mb-3">
                                <label className="form-label fw-semibold">
                                  Invoice in spreadsheet
                                </label>
                                <select
                                  className="form-select"
                                  value={reviewInvoiceIndex}
                                  onChange={(event) =>
                                    openReview(
                                      reviewDoc,
                                      Number(event.target.value),
                                    )
                                  }
                                >
                                  {(
                                    objectValue(
                                      objectValue(reviewDoc.extracted_data)
                                        .structured_extraction,
                                    ).invoices as unknown[]
                                  ).map((invoice, index) => {
                                    const source = objectValue(invoice);
                                    const approvedIndices =
                                      reviewDoc.extracted_data
                                        ?.approved_invoice_indices;
                                    const approved =
                                      Array.isArray(approvedIndices) &&
                                      approvedIndices.includes(index);
                                    return (
                                      <option
                                        key={index}
                                        value={index}
                                        disabled={approved}
                                      >
                                        {`Invoice ${index + 1}: ${
                                          String(source.invoice_number || "unnumbered")
                                        }${approved ? " (approved)" : ""}`}
                                      </option>
                                    );
                                  })}
                                </select>
                              </div>
                            )}
                          <InvoiceExtractionPreview
                            data={reviewDoc.extracted_data || {}}
                          />
                          <div className="row g-3">
                            {(
                              [
                                ["invoice_number", "Invoice number"],
                                ["supplier_name", "Supplier name"],
                                ["supplier_address", "Supplier address"],
                                ["supplier_emirate", "Supplier emirate"],
                                ["supplier_trn", "Supplier TRN"],
                                ["customer_name", "Customer name"],
                                ["customer_email", "Customer email"],
                                ["customer_address", "Buyer address"],
                                ["customer_emirate", "Buyer emirate"],
                                ["customer_trn", "Buyer TRN"],
                                ["currency", "Currency"],
                                ["place_of_supply", "Place of supply"],
                                ["amount_aed", "Invoice total (AED)"],
                                ["subtotal_aed", "Subtotal (AED)"],
                                ["discount_aed", "Discount (AED)"],
                                ["vat_amount_aed", "VAT (AED)"],
                                ["issue_date", "Issue date"],
                                ["supply_date", "Supply date"],
                                ["due_date", "Due date"],
                              ] as const
                            ).map(([key, label]) => (
                              <div className="col-md-6" key={key}>
                                <label className="form-label">
                                  {label}
                                </label>

                                <input
                                  className="form-control"
                                  type={
                                    key.includes("date")
                                      ? "date"
                                      : key === "customer_email"
                                      ? "email"
                                      : key.endsWith("_aed")
                                      ? "number"
                                      : "text"
                                  }
                                  step={key.endsWith("_aed") ? "0.01" : undefined}
                                  value={reviewForm[key]}
                                  onChange={(e) =>
                                    updateReviewForm({ [key]: e.target.value })
                                  }
                                  required={[
                                    "invoice_number",
                                    "supplier_name",
                                    "customer_name",
                                    "currency",
                                    "amount_aed",
                                    "issue_date",
                                    "due_date",
                                  ].includes(key)}
                                />
                              </div>
                            ))}

                            <div className="col-12">
                              <div className="d-flex justify-content-between align-items-center mb-2">
                                <label className="form-label fw-semibold mb-0">
                                  Editable line items
                                </label>
                                <button
                                  type="button"
                                  className="btn btn-outline-secondary btn-sm"
                                  onClick={() =>
                                    updateReviewForm({
                                      items: [
                                        ...reviewForm.items,
                                        {
                                          description: "",
                                          quantity: "1",
                                          unit: "",
                                          unit_price_aed: "",
                                          discount_aed: "0",
                                          taxable_value_aed: "",
                                          vat_rate: "",
                                          vat_amount_aed: "",
                                          line_total_aed: "",
                                        },
                                      ],
                                    })
                                  }
                                >
                                  Add line item
                                </button>
                              </div>
                              {reviewForm.items.length ? (
                                <div className="table-responsive">
                                  <table className="table table-sm table-bordered align-middle">
                                    <thead>
                                      <tr>
                                        <th>Description</th>
                                        <th>Quantity</th>
                                        <th>Unit</th>
                                        <th>Unit price</th>
                                        <th>Discount</th>
                                        <th>Taxable</th>
                                        <th>VAT rate</th>
                                        <th>VAT amount</th>
                                        <th>Extracted total</th>
                                        <th>Calculated total</th>
                                        <th>Validation status</th>
                                        <th />
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {reviewForm.items.map((item, index) => {
                                        const lineChecks = objectValue(
                                          objectValue(
                                            objectValue(validationResult?.checks).line_items,
                                          ),
                                        );
                                        const lineResults = Array.isArray(lineChecks.results)
                                          ? lineChecks.results
                                          : [];
                                        const lineResult = objectValue(lineResults[index]);
                                        const calculated = objectValue(lineResult.calculated);
                                        const lineErrors = Array.isArray(lineResult.errors)
                                          ? lineResult.errors
                                          : [];
                                        const lineWarnings = Array.isArray(lineResult.warnings)
                                          ? lineResult.warnings
                                          : [];
                                        return (
                                          <tr key={index}>
                                            {([
                                              ["description", "text"],
                                              ["quantity", "number"],
                                              ["unit", "text"],
                                              ["unit_price_aed", "number"],
                                              ["discount_aed", "number"],
                                              ["taxable_value_aed", "number"],
                                              ["vat_rate", "number"],
                                              ["vat_amount_aed", "number"],
                                              ["line_total_aed", "number"],
                                            ] as const).map(([field, type]) => (
                                              <td key={field}>
                                                <input
                                                  className="form-control form-control-sm"
                                                  type={type}
                                                  step={
                                                    field === "quantity"
                                                      ? "0.001"
                                                      : type === "number"
                                                      ? "0.01"
                                                      : undefined
                                                  }
                                                  value={item[field]}
                                                  onChange={(event) => {
                                                    const items = [...reviewForm.items];
                                                    items[index] = {
                                                      ...items[index],
                                                      [field]: event.target.value,
                                                    };
                                                    updateReviewForm({ items });
                                                  }}
                                                />
                                              </td>
                                            ))}
                                            <td className="small">
                                              {reviewLabel(calculated.line_total_aed)}
                                              <div className={
                                                lineErrors.length
                                                  ? "text-danger"
                                                  : validationResult
                                                  ? "text-success"
                                                  : "muted"
                                              }>
                                                {lineErrors.length
                                                  ? "Invalid"
                                                    : lineWarnings.length
                                                    ? "Review"
                                                    : lineResult.is_valid === true
                                                    ? "Valid"
                                                    : "Not checked"}
                                              </div>
                                            </td>
                                            <td>
                                              <button
                                                type="button"
                                                className="btn btn-sm btn-outline-danger"
                                                aria-label={`Remove line item ${index + 1}`}
                                                onClick={() =>
                                                  updateReviewForm({
                                                    items: reviewForm.items.filter(
                                                      (_, rowIndex) => rowIndex !== index,
                                                    ),
                                                  })
                                                }
                                              >
                                                Remove
                                              </button>
                                            </td>
                                          </tr>
                                        );
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                              ) : (
                                <div className="small muted">
                                  No line items. The stated invoice total will be validated.
                                </div>
                              )}
                            </div>

                            <div className="col-12">
                              <label className="form-label">
                                Notes
                              </label>

                              <textarea
                                className="form-control"
                                rows={2}
                                value={reviewForm.notes}
                                onChange={(e) =>
                                  updateReviewForm({ notes: e.target.value })
                                }
                              />
                            </div>
                          </div>

                          <InvoiceValidationSummary result={validationResult} />

                          <div className="section-note mt-3">
                            Please verify the amount, invoice number and dates against the original document. The invoice is only added to your register after you approve this review.
                          </div>
                        </div>

                        <div className="modal-footer">
                          <button
                            type="button"
                            className="btn btn-light"
                            onClick={() => setReviewDoc(null)}
                          >
                            Cancel
                          </button>

                          <button
                            type="button"
                            className="btn btn-outline-danger me-auto"
                            disabled={rejectingReview}
                            onClick={() => void rejectReview()}
                          >
                            {rejectingReview ? "Rejecting…" : "Reject document"}
                          </button>

                          <button
                            type="button"
                            className="btn btn-outline-primary"
                            disabled={validatingReview || savingReview}
                            onClick={() => void validateReview()}
                          >
                            {validatingReview ? "Validating…" : "Validate / recalculate"}
                          </button>

                          <button
                            className="btn btn-brand"
                            disabled={
                              savingReview ||
                              validationResult?.is_valid !== true ||
                              [
                                "same_invoice",
                                "conflicting_number",
                                "duplicate_upload",
                                "duplicate",
                                "ambiguous",
                              ].includes(String(objectValue(
                                objectValue(validationResult?.checks).duplicate,
                              ).status ?? ""))
                            }
                          >
                            {savingReview
                              ? "Saving…"
                              : "Approve and save invoice"}
                          </button>
                        </div>
                      </form>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          
          {/* MODULE 3 — CASH FLOW FORECAST */}

          {view === "Cash Flow Forecast" && (
            <CashFlowForecastDashboard
              onOpenInvoiceRegister={() =>
                setView("Invoice Management")
              }
            />
          )}

          {/* MODULE 4 — AI FINANCIAL ASSISTANT */}

          {view === "AI Finance Assistant" && (
            <FinanceAssistant />
          )}

          {/* MODULE 5 — FINANCIAL REPORTS */}

          {view === "Reports" && (
            <ReportsDashboard />
          )}

          {/* MODULE 6 — ADMINISTRATOR AUDIT LOGS */}

          {view === "Audit Logs" && (
            <AuditLogsDashboard />
          )}

        </main>
      </div>
    </div>
  );
}

function Overview({
  summary,
  invoices,
  setView,
  reminders,
  onStatusChange,
}: {
  summary: Summary | null;
  invoices: Invoice[];
  setView: (v: string) => void;
  reminders: Reminder[];
  onStatusChange: (invoice: Invoice) => void;
}) {
  const router = useRouter();

  // Status counts are supplied by /api/dashboard/summary. They describe
  // register statuses, NOT bank-verified or fully reconciled payments.
  const paid = summary?.paid_count || 0;
  const unpaid = summary?.unpaid_count || 0;
  const late = summary?.overdue_count || 0;
  const total = summary?.invoice_count || 0;
  const unpaidNotOverdue = Math.max(0, unpaid - late);

  const paidPct = total ? (paid / total) * 100 : 0;
  const overduePct = total ? (late / total) * 100 : 0;
  const notDuePct = total ? (unpaidNotOverdue / total) * 100 : 0;

  // The receivables forecast is backed by the payment ledger. This is the
  // same authoritative outstanding amount used in the Cash Flow Forecast
  // and Payment Collections, unlike the register's status-only total.
  const [ledgerForecast, setLedgerForecast] = useState<ForecastSummaryResponse | null>(null);
  const [ledgerLoading, setLedgerLoading] = useState(true);
  const [ledgerError, setLedgerError] = useState("");
  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLedgerLoading(true);
    setLedgerError("");
    setLedgerForecast(null);

    getForecastSummary({ horizonDays: 30, scenario: "base" })
      .then((result) => {
        if (active) setLedgerForecast(result);
      })
      .catch((reason: unknown) => {
        if (active) {
          setLedgerError(
            reason instanceof Error
              ? reason.message
              : "Unable to load reconciled invoice balances.",
          );
        }
      })
      .finally(() => {
        if (active) setLedgerLoading(false);
      });

    return () => { active = false; };
  }, [invoices, ledgerRefreshKey]);

  const ledgerMetrics = ledgerForecast?.metrics;
  const ledgerOpenCount = ledgerMetrics
    ? ledgerMetrics.eligible_invoice_count + ledgerMetrics.reconciliation_required_count
    : null;
  const retryLedger = () => setLedgerRefreshKey((value) => value + 1);
  const ledgerAmount = (amount: string | undefined): string =>
    ledgerLoading ? "Calculating…" : amount === undefined ? "Unavailable" : money(amount);

  return (
    <>
      <div className="row g-3 mb-3">
        <Metric
          label="Total invoices"
          value={total}
          icon="bi-receipt"
          tone="blue"
          foot="Invoices in your register"
        />

        <Metric
          label="Outstanding receivables"
          value={ledgerAmount(ledgerMetrics?.total_outstanding_aed)}
          icon="bi-cash-stack"
          tone="teal"
          foot="Payment-ledger balance, including reconciliation cases"
        />

        <Metric
          label="Overdue receivables"
          value={ledgerAmount(ledgerMetrics?.overdue_outstanding_aed)}
          icon="bi-clock-history"
          tone="red"
          foot="Unsettled balances already past due"
        />

        <Metric
          label="Reconciliation review"
          value={ledgerLoading ? "Calculating…" : ledgerMetrics?.reconciliation_required_count ?? "—"}
          icon="bi-exclamation-circle"
          tone="blue"
          foot="Payment/status records requiring review"
        />
      </div>

      {ledgerError && (
        <div className="alert alert-warning small d-flex flex-wrap align-items-center gap-2" role="alert">
          <span>Receivables ledger figures are unavailable: {ledgerError}</span>
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={retryLedger}>
            Retry ledger
          </button>
        </div>
      )}

      {(ledgerMetrics?.reconciliation_required_count ?? 0) > 0 && (
        <div className="alert alert-warning small" role="status">
          <strong>{ledgerMetrics?.reconciliation_required_count} invoice(s) require payment/status reconciliation.</strong>
          {" "}These balances remain in outstanding receivables, but are excluded from estimated future collections until reviewed.
          Review them in Payment Collections before marking any invoice as fully paid.
        </div>
      )}

      <div className="row g-3 mb-3">
        <div className="col-xl-5">
          <div className="panel h-100">
            <div className="d-flex justify-content-between">
              <div>
                <h2 className="panel-title">
                  Receivables overview
                </h2>

                <div className="panel-subtitle">
                  Register status breakdown (not proof of payment)
                </div>
              </div>

              <span className="small muted">Current</span>
            </div>

            <div className="donut-row">
              <div
                className="donut"
                style={{
                  background: `conic-gradient(
                    #64748b 0 ${paidPct}%,
                    #f35b61 ${paidPct}% ${Math.min(
                      100,
                      paidPct + overduePct
                    )}%,
                    #3985ed ${Math.min(
                      100,
                      paidPct + overduePct
                    )}% 100%
                  )`,
                }}
              >
                <div className="donut-hole">
                  <strong>{total}</strong>
                  <span>Invoices</span>
                </div>
              </div>

              <div className="legend">
                <Legend
                  color="#64748b"
                  label={`Marked paid (${paid})`}
                  value={`${paidPct.toFixed(1)}%`}
                />

                <Legend
                  color="#f35b61"
                  label={`Overdue status (${late})`}
                  value={`${overduePct.toFixed(1)}%`}
                />

                <Legend
                  color="#3985ed"
                  label={`Unpaid, not yet due (${unpaidNotOverdue})`}
                  value={`${notDuePct.toFixed(1)}%`}
                />
              </div>
              <div className="small muted mt-3">
                Register status is not payment reconciliation: invoices marked paid
                may still have outstanding payment-ledger balances.
              </div>
            </div>
          </div>
        </div>

        <div className="col-xl-7">
          <div className="panel h-100">
            <div className="d-flex justify-content-between align-items-start">
              <div>
                <h2 className="panel-title">
                  Receivables snapshot
                </h2>

                <div className="panel-subtitle">
                  Outstanding balances and invoice activity
                </div>
              </div>

              <span className="badge text-bg-light">
                Register and payment ledger
              </span>
            </div>

            <div className="row g-3 mt-2">
              <div className="col-6">
                <div
                  className="p-3 rounded-3"
                  style={{ background: "#eaf4ff" }}
                >
                  <div className="small muted">Outstanding invoice records</div>
                  <div className="fs-3 fw-bold">
                    {ledgerLoading ? "…" : ledgerOpenCount ?? "—"}
                  </div>
                  <div className="small muted">
                    Eligible outstanding + reconciliation cases
                  </div>
                </div>
              </div>

              <div className="col-6">
                <div
                  className="p-3 rounded-3"
                  style={{ background: "#e9f8f2" }}
                >
                  <div className="small muted">Collection drafts</div>
                  <div className="fs-3 fw-bold">
                    {reminders.length}
                  </div>
                  <div className="small muted">
                    Awaiting review / action
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-3">
              <div className="d-flex justify-content-between small mb-2">
                <span className="muted">Marked paid (status only)</span>
                <strong>{paidPct.toFixed(1)}%</strong>
              </div>

              <div className="progress" style={{ height: 9 }}>
                <div
                  className="progress-bar"
                  style={{
                    width: `${paidPct}%`,
                    background: "#0c9d70",
                  }}
                />
              </div>
            </div>

            <div className="small muted mt-3">
              Payment-ledger reconciliation takes precedence over the register's paid status.
              Historical monthly trend snapshots are not yet available.
            </div>
          </div>
        </div>
      </div>

      <div className="row g-3">
        <div className="col-xl-8">
          <div className="panel">
            <div className="d-flex justify-content-between align-items-center mb-3">
              <div>
                <h2 className="panel-title">Recent invoices</h2>
                <div className="panel-subtitle">
                  Latest records from your invoice register
                </div>
              </div>

              <button
                className="btn btn-link btn-sm text-decoration-none"
                onClick={() => setView("Invoice Management")}
              >
                View all invoices <i className="bi bi-arrow-right" />
              </button>
            </div>

            <InvoiceTable
              invoices={invoices.slice(0, 5)}
              onStatusChange={onStatusChange}
            />
          </div>
        </div>

        <div className="col-xl-4">
          <div className="assistant-card mb-3">
            <div className="assistant-head">
              <div className="assistant-icon">
                <i className="bi bi-robot" />
              </div>

              <div>
                <div className="assistant-title">
                  AI Finance Assistant
                </div>

                <div className="assistant-copy">
                  Ask about invoices, collections and customer payments.
                </div>
              </div>
            </div>

            <div className="assistant-input">
              <input
                placeholder="Ask a finance question…"
                onFocus={() => setView("AI Finance Assistant")}
              />

              <button
                onClick={() => setView("AI Finance Assistant")}
              >
                <i className="bi bi-send-fill" />
              </button>
            </div>
          </div>

          <div className="panel mb-3">
            <div className="fw-bold mb-2">
              <i className="bi bi-lightning-charge-fill text-warning me-2" />
              Quick actions
            </div>

            <button
              className="quick-action primary"
              onClick={() => setView("Invoice Management")}
            >
              <i className="bi bi-cloud-arrow-up me-2" />
              Upload invoices (PDF / CSV)
            </button>

            <button
              className="quick-action"
              onClick={() => setView("Invoice Management")}
            >
              <i className="bi bi-journal-plus me-2" />
              Review extracted invoices
            </button>

            <button
              className="quick-action"
              onClick={() => router.push("/collections")}
            >
              <i className="bi bi-envelope me-2" />
              View collection reminders
            </button>
          </div>

          <OverviewForecastCard
            onOpenForecast={() => setView("Cash Flow Forecast")}
            forecast={ledgerForecast}
            forecastLoading={ledgerLoading}
            forecastError={ledgerError}
            onRetry={retryLedger}
          />
        </div>
      </div>
    </>
  );
}

/**
 * Small live forecast summary on the Overview screen.
 * Detailed analysis lives inside CashFlowForecastDashboard.
 * No hardcoded amounts or accounting calculations are used here.
 */
function OverviewForecastCard({
  onOpenForecast,
  forecast,
  forecastLoading,
  forecastError,
  onRetry,
}: {
  onOpenForecast: () => void;
  forecast: ForecastSummaryResponse | null;
  forecastLoading: boolean;
  forecastError: string;
  onRetry: () => void;
}) {
  return (
    <div className="forecast-card">
      <div className="fw-bold small">
        <i className="bi bi-calendar3 me-2" aria-hidden="true" />
        30-day estimated cash collections
      </div>

      <div className="forecast-amount" aria-live="polite">
        {forecastLoading
          ? "Calculating…"
          : forecast
            ? money(forecast.metrics.expected_collections_aed)
            : "Unavailable"}
      </div>

      <div className="small muted">
        {forecast
          ? `${forecast.metrics.forecast_invoice_count} invoice(s) included in this estimate`
          : "Estimated future customer receipts from eligible invoices."}
      </div>
      <div className="small muted mt-1">
        Estimates use assumptions, not guaranteed receipts. Recorded payments
        are not bank-verified cash. Check payment/status reconciliation notices.
      </div>

      {forecastError && (
        <div className="small text-danger mt-2" role="alert">
          {forecastError}
          <button
            type="button"
            className="btn btn-sm btn-link p-0 ms-2"
            onClick={onRetry}
          >
            Retry
          </button>
        </div>
      )}

      <button
        type="button"
        className="btn btn-sm btn-link p-0 mt-2 text-decoration-none"
        onClick={onOpenForecast}
      >
        View forecast details <i className="bi bi-arrow-right" aria-hidden="true" />
      </button>
    </div>
  );
}

function InvoiceValidationSummary({
  result,
}: {
  result: Record<string, unknown> | null;
}) {
  if (!result) {
    return (
      <div className="alert alert-info py-2 small mt-3 mb-0">
        Validate the edited invoice to calculate totals and check dates, TRNs,
        currency, VAT and duplicate status.
      </div>
    );
  }

  const checks = objectValue(result.checks);
  const dates = objectValue(checks.dates);
  const supplierTrn = objectValue(checks.supplier_trn);
  const customerTrn = objectValue(checks.customer_trn);
  const duplicate = objectValue(checks.duplicate);
  const duplicateMatches = Array.isArray(duplicate.matches)
    ? duplicate.matches.map(objectValue)
    : [];
  const ignoredDemoMatches = Array.isArray(duplicate.ignored_demo_matches)
    ? duplicate.ignored_demo_matches.map(objectValue)
    : [];
  const totals = objectValue(checks.totals);
  const calculated = objectValue(result.calculated_totals);
  const errors = Array.isArray(result.errors) ? result.errors : [];
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const status =
    result.is_valid !== true
      ? "Invalid"
      : result.review_required === true
      ? "Review required"
      : "Valid";
  const statusClass =
    status === "Invalid"
      ? "text-bg-danger"
      : status === "Review required"
      ? "text-bg-warning"
      : "text-bg-success";
  const extractedTotal = objectValue(totals.total_amount_aed).extracted;
  const calculatedTotal =
    calculated.total_amount_aed ?? objectValue(totals.total_amount_aed).calculated;
  const amountDifference =
    extractedTotal !== null &&
    extractedTotal !== undefined &&
    calculatedTotal !== null &&
    calculatedTotal !== undefined
      ? Number(calculatedTotal) - Number(extractedTotal)
      : null;

  return (
    <div className="border rounded-3 p-3 mt-3">
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
        <strong>Invoice validation</strong>
        <span className={`badge ${statusClass}`}>{status}</span>
      </div>

      <div className="row g-2 small mb-3">
        <div className="col-md-6">
          <strong>Supplier TRN:</strong> {reviewLabel(supplierTrn.value)} ·{" "}
          {String(supplierTrn.message ?? "Not checked")}
        </div>
        <div className="col-md-6">
          <strong>Buyer TRN:</strong> {reviewLabel(customerTrn.value)} ·{" "}
          {String(customerTrn.message ?? "Not checked")}
        </div>
        {(["issue_date", "supply_date", "due_date"] as const).map((field) => {
          const dateCheck = objectValue(dates[field]);
          return (
            <div className="col-md-4" key={field}>
              <strong>{field.replace("_", " ")}:</strong>{" "}
              {reviewLabel(dateCheck.value)} ·{" "}
              {dateCheck.is_valid === true
                ? "Valid"
                : dateCheck.is_valid === false
                ? "Invalid"
                : "Not provided"}
            </div>
          );
        })}
      </div>

      {duplicateMatches.length > 0 && (
        <div className="small mb-3">
          <strong>Duplicate details</strong>
          <ul className="mb-0 mt-1">
            {duplicateMatches.map((match, index) => (
              <li key={`${String(match.invoice_id ?? match.document_id)}-${index}`}>
                {match.invoice_id !== undefined
                  ? `Invoice #${String(match.invoice_id)}`
                  : `Document #${String(match.document_id)}`}
                {match.invoice_number ? ` · ${String(match.invoice_number)}` : ""}
                {match.supplier_name ? ` · ${String(match.supplier_name)}` : ""}
                {match.supplier_trn ? ` · TRN ${String(match.supplier_trn)}` : ""}
                {match.filename ? ` · ${String(match.filename)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {ignoredDemoMatches.length > 0 && (
        <div className="small text-secondary mb-3">
          Ignored demo records:{" "}
          {ignoredDemoMatches.map((match) =>
            `#${String(match.invoice_id)} (${String(match.invoice_number)})`
          ).join(", ")}
        </div>
      )}

      <div className="table-responsive mb-3">
        <table className="table table-sm table-bordered mb-0">
          <thead>
            <tr>
              <th>Subtotal</th>
              <th>Discount</th>
              <th>VAT</th>
              <th>Extracted grand total</th>
              <th>Calculated grand total</th>
              <th>Difference</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{money(String(calculated.subtotal_aed ?? 0))}</td>
              <td>{money(String(calculated.discount_aed ?? 0))}</td>
              <td>{money(String(calculated.vat_amount_aed ?? 0))}</td>
              <td>{reviewLabel(extractedTotal)}</td>
              <td>{reviewLabel(calculatedTotal)}</td>
              <td>
                {amountDifference === null
                  ? "—"
                  : money(amountDifference.toFixed(2))}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {errors.length > 0 && (
        <div className="alert alert-danger py-2 small">
          <strong>Errors</strong>
          <ul className="mb-0 mt-1">
            {errors.map((error, index) => <li key={index}>{String(error)}</li>)}
          </ul>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="alert alert-warning py-2 small mb-0">
          <strong>Warnings</strong>
          <ul className="mb-0 mt-1">
            {warnings.map((warning, index) => (
              <li key={index}>{String(warning)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function InvoiceExtractionPreview({
  data,
}: {
  data: Record<string, unknown>;
}) {
  const structured = objectValue(data.structured_invoice);
  const extraction = objectValue(data.structured_extraction);
  const invoices = Array.isArray(extraction.invoices)
    ? extraction.invoices
    : [];
  const invoice = Object.keys(structured).length
    ? structured
    : objectValue(invoices[0]);
  const items = Array.isArray(invoice.items)
    ? invoice.items.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null && !Array.isArray(item),
      )
    : [];
  const warnings = Array.isArray(data.warnings)
    ? data.warnings
    : Array.isArray(invoice.extraction_notes)
      ? invoice.extraction_notes
      : [];
  const missing = Array.isArray(invoice.missing_fields)
    ? invoice.missing_fields
    : [];
  const source = objectValue(data.raw_extraction);
  const method = reviewLabel(source.extraction_method ?? data.extraction_method);
  const detailGroups: { title: string; fields: [string, unknown][] }[] = [
    {
      title: "Supplier details",
      fields: [
        ["Name", invoice.supplier_name],
        ["Address", invoice.supplier_address],
        ["Emirate", invoice.supplier_emirate],
        ["TRN", invoice.supplier_trn],
      ],
    },
    {
      title: "Buyer details",
      fields: [
        ["Name", invoice.customer_name],
        ["Address", invoice.customer_address],
        ["Emirate", invoice.customer_emirate],
        ["TRN", invoice.customer_trn],
      ],
    },
    {
      title: "Invoice details",
      fields: [
        ["Invoice number", invoice.invoice_number],
        ["Issue date", invoice.issue_date],
        ["Supply date", invoice.supply_date],
        ["Due date", invoice.due_date],
        ["Place of supply", invoice.place_of_supply],
        ["Currency", invoice.currency],
      ],
    },
  ];

  return (
    <section className="mb-4">
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <h6 className="fw-bold mb-0">Extracted invoice preview</h6>
        <span className="badge text-bg-light">
          Method: {method} · Confidence:{" "}
          {typeof invoice.extraction_confidence === "number"
            ? `${Math.round(invoice.extraction_confidence * 100)}%`
            : "Not available"}
        </span>
      </div>
      {detailGroups.map((group) => (
        <div className="mb-3" key={group.title}>
          <div className="small fw-semibold mb-1">{group.title}</div>
          <div className="row g-2 small">
            {group.fields.map(([label, value]) => (
              <div className="col-md-6" key={label}>
                <strong>{label}:</strong> {reviewLabel(value)}
              </div>
            ))}
          </div>
        </div>
      ))}

      <div className="small fw-semibold mb-1">Line items</div>
      {items.length > 0 ? (
        <div className="table-responsive mb-3">
          <table className="table table-sm table-bordered align-middle">
            <thead>
              <tr>
                <th>Description</th>
                <th>Quantity</th>
                <th>Unit</th>
                <th>Unit price</th>
                <th>Discount</th>
                <th>Taxable value</th>
                <th>VAT rate</th>
                <th>VAT amount</th>
                <th>Line total</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={index}>
                  <td>{reviewLabel(item.description)}</td>
                  <td>{reviewLabel(item.quantity)}</td>
                  <td>{reviewLabel(item.unit)}</td>
                  <td>{reviewLabel(item.unit_price_aed)}</td>
                  <td>{reviewLabel(item.discount_aed)}</td>
                  <td>{reviewLabel(item.taxable_value_aed)}</td>
                  <td>{reviewLabel(item.vat_rate)}</td>
                  <td>{reviewLabel(item.vat_amount_aed)}</td>
                  <td>{reviewLabel(item.line_total_aed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="small muted mb-3">No line items were identified.</div>
      )}

      <div className="row g-2 small mb-3">
        {([
          ["Subtotal", invoice.subtotal_aed],
          ["Discount", invoice.discount_aed],
          ["VAT", invoice.vat_amount_aed],
          ["Grand total", invoice.total_amount_aed],
        ] as const).map(([label, value]) => (
          <div className="col-6 col-lg-3" key={label}>
            <strong>{label}:</strong> {reviewLabel(value)}
          </div>
        ))}
      </div>

      {missing.length > 0 && (
        <div className="alert alert-warning py-2 small">
          <strong>Missing fields:</strong>{" "}
          {missing.map(String).join(", ")}
        </div>
      )}
      {warnings.length > 0 && (
        <div className="alert alert-warning py-2 small">
          <strong>Extraction warnings:</strong>
          <ul className="mb-0 mt-1">
            {warnings.slice(0, 8).map((warning, index) => (
              <li key={index}>{String(warning)}</li>
            ))}
          </ul>
        </div>
      )}
      <details className="small">
        <summary>Inspect structured extraction data</summary>
        <pre className="bg-light rounded p-2 mt-2 overflow-auto">
          {JSON.stringify(invoice, null, 2)}
        </pre>
      </details>
    </section>
  );
}

function Metric({
  label,
  value,
  icon,
  tone,
  foot,
}: {
  label: string;
  value: string | number;
  icon: string;
  tone: string;
  foot: string;
}) {
  const bg: Record<string, string> = {
    blue: "#e6f3ff",
    teal: "#e1f7f3",
    red: "#ffeaec",
    green: "#e2f8ec",
  };

  const fg: Record<string, string> = {
    blue: "#1875b9",
    teal: "#07958d",
    red: "#e24e5a",
    green: "#159b68",
  };

  return (
    <div className="col-6 col-xl-3">
      <div className="metric-card h-100">
        <div className="metric-top">
          <div className="metric-label">{label}</div>

          <div
            className="metric-icon"
            style={{
              background: bg[tone],
              color: fg[tone],
            }}
          >
            <i className={`bi ${icon}`} />
          </div>
        </div>

        <div
          className="metric-value"
          style={{
            fontSize:
              typeof value === "string" && value.length > 14
                ? "18px"
                : undefined,
          }}
        >
          {value}
        </div>

        <div className="metric-foot">{foot}</div>
      </div>
    </div>
  );
}

function Legend({
  color,
  label,
  value,
}: {
  color: string;
  label: string;
  value: string;
}) {
  return (
    <div className="legend-item">
      <div className="legend-name">
        <span
          className="legend-dot"
          style={{ background: color }}
        />
        {label}
      </div>

      <span className="legend-value">{value}</span>
    </div>
  );
}

function InvoiceTable({
  invoices,
  onStatusChange,
}: {
  invoices: Invoice[];
  onStatusChange: (invoice: Invoice) => void;
}) {
  if (!invoices.length) {
    return (
      <div className="empty-state">
        No invoice records found. Upload a PDF or CSV to get started.
      </div>
    );
  }

  return (
    <div className="table-responsive">
      <table className="table align-middle mb-0">
        <thead>
          <tr>
            <th>Invoice number</th>
            <th>Customer</th>
            <th>Amount (AED)</th>
            <th>Due date</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>

        <tbody>
          {invoices.map((i) => (
            <tr key={i.id}>
              <td>
                <span className="invoice-link">
                  {i.invoice_number}
                </span>
              </td>

              <td>{i.customer_name}</td>

              <td className="fw-semibold">
                {Number(i.amount_aed).toLocaleString("en-AE", {
                  minimumFractionDigits: 2,
                })}
              </td>

              <td>{dateLabel(i.due_date)}</td>

              <td>
                <span
                  className={`status status-${
                    i.status?.toLowerCase() === "paid"
                      ? "paid"
                      : i.status?.toLowerCase() === "overdue"
                      ? "overdue"
                      : "unpaid"
                  }`}
                >
                  {i.status}
                </span>
              </td>

              <td className="text-nowrap">
                <Link
                  className="btn btn-sm btn-outline-secondary me-2"
                  href={`/invoices/${i.id}`}
                  aria-label={`View or edit ${i.invoice_number}`}
                >
                  <i className="bi bi-pencil-square me-1" />Edit
                </Link>
                <button
                  className={`btn btn-sm ${i.status === "paid" ? "btn-outline-warning" : "btn-outline-success"}`}
                  type="button"
                  onClick={() => onStatusChange(i)}
                  title="Open Payment Collections to confirm a receipt or review payment reconciliation"
                >
                  <i className="bi bi-wallet2 me-1" aria-hidden="true" />
                  {i.status === "paid" ? "Review payment" : "Record payment"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
