"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import InvoiceLineItemsEditor from "@/components/invoices/InvoiceLineItemsEditor";
import InvoiceCustomFieldsEditor from "@/components/invoices/InvoiceCustomFieldsEditor";
import InvoiceTextWordmark from "@/components/invoices/InvoiceTextWordmark";
import InvoiceTotalsPanel from "@/components/invoices/InvoiceTotalsPanel";
import InvoiceLivePreview from "@/components/invoices/InvoiceLivePreview";
import InvoiceDraftsList from "@/components/invoices/InvoiceDraftsList";
import { apiGet, apiPost, apiPut, clearToken, getToken } from "@/lib/api";
import {
  createEmptyInvoiceForm,
  toInvoicePreviewRequest,
  type InvoiceBankDetails,
  type InvoiceDraftCreate,
  type InvoiceDraftListResponse,
  type InvoiceDraftListStatus,
  type InvoiceDraftResponse,
  type InvoiceDraftUpdate,
  type InvoiceFinalizeRequest,
  type InvoiceGenerationInput,
  type InvoiceGenerationResponse,
  type InvoiceGenerationValidationResponse,
  type InvoiceHeaderInput,
  type InvoicePartyInput,
} from "@/lib/invoice-generation-types";

/**
 * ReceivAI UAE — Main manual invoice generator.
 *
 * Uses existing single-admin bearer token; never sends financial totals from
 * the browser as authority. Finalization always validates a SAVED draft.
 * The parent page should wrap this component in <AuthenticatedPage>.
 */
export interface InvoiceGenerationFormProps {
  initialDraftId?: number;
  onDraftSaved?: (draft: InvoiceDraftResponse) => void;
  onFinalized?: (result: InvoiceGenerationResponse) => void;
  onOpenFinalizedInvoice?: (invoiceId: number) => void;
}

type Working = "loading" | "saving" | "validating" | "finalizing" | "previewing" | null;
type View = "editor" | "drafts";
type PartySection = "seller" | "buyer";

const ENDPOINT = "/api/invoice-generation";
const PAGE_SIZE = 20;
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

const PANEL: CSSProperties = {
  background: "#fff",
  border: "1px solid #e0e8f0",
  borderRadius: 16,
  padding: 20,
  boxShadow: "0 5px 22px rgba(16,37,62,0.04)",
};

const SUBTITLE: CSSProperties = { color: "#708198", fontSize: 13, marginBottom: 0 };

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to complete the operation.";
}

/** Used for authenticated binary PDFs and DELETE; JSON calls use lib/api.ts. */
async function fetchProtected(
  path: string,
  method: "POST" | "GET" | "DELETE",
  body?: unknown,
): Promise<Response> {
  const token = getToken();
  if (!token) throw new Error("Please sign in to continue.");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new Error("Could not connect to the ReceivAI API.");
  }

  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new Event("receivai:unauthorized"));
    throw new Error("Your session has expired. Please sign in again.");
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    let detail = `Request failed (${response.status}).`;
    if (payload && typeof payload === "object" && "detail" in payload) {
      const raw = (payload as { detail: unknown }).detail;
      if (typeof raw === "string") detail = raw;
      else if (Array.isArray(raw)) {
        detail = raw
          .map((item: unknown) =>
            item && typeof item === "object" && "msg" in item
              ? String(item.msg)
              : "Invalid invoice information",
          )
          .join("; ");
      }
    }
    throw new Error(detail);
  }
  return response;
}

async function fetchPdf(path: string, payload?: unknown): Promise<Blob> {
  const response = await fetchProtected(path, "POST", payload);
  const blob = await response.blob();
  if (!blob.size || !response.headers.get("content-type")?.includes("application/pdf")) {
    throw new Error("The server did not return a valid PDF document.");
  }
  return blob;
}

function downloadPdf(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function Section({ title, note, children }: {
  title: string;
  note?: string;
  children: ReactNode;
  key?: string;
}) {
  return (
    <section style={PANEL}>
      <div className="mb-3">
        <h2 className="h6 fw-bold mb-1" style={{ color: "#142b45" }}>{title}</h2>
        {note && <p style={SUBTITLE}>{note}</p>}
      </div>
      {children}
    </section>
  );
}

function TextField({ label, value, onChange, disabled, placeholder, maxLength = 180,
  type = "text", multiline = false, required = false }: {
  label: string;
  value: string | null;
  onChange: (value: string) => void;
  disabled: boolean;
  placeholder?: string;
  maxLength?: number;
  type?: "text" | "email" | "tel";
  multiline?: boolean;
  required?: boolean;
}) {
  return (
    <label className="d-block w-100">
      <span className="form-label mb-1 small fw-semibold" style={{ color: "#52647b" }}>
        {label}{required && <span className="text-danger"> *</span>}
      </span>
      {multiline ? (
        <textarea className="form-control form-control-sm" rows={2} maxLength={maxLength}
          disabled={disabled} placeholder={placeholder} value={value ?? ""}
          onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input className="form-control form-control-sm" type={type} maxLength={maxLength}
          disabled={disabled} placeholder={placeholder} value={value ?? ""}
          onChange={(event) => onChange(event.target.value)} />
      )}
    </label>
  );
}

function DateField({ label, value, onChange, disabled, required = false }: {
  label: string;
  value: string | null;
  onChange: (value: string) => void;
  disabled: boolean;
  required?: boolean;
}) {
  return (
    <label className="d-block w-100">
      <span className="form-label mb-1 small fw-semibold" style={{ color: "#52647b" }}>
        {label}{required && <span className="text-danger"> *</span>}
      </span>
      <input type="date" className="form-control form-control-sm" disabled={disabled}
        value={value ?? ""} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export default function InvoiceGenerationForm({
  initialDraftId,
  onDraftSaved,
  onFinalized,
  onOpenFinalizedInvoice,
}: InvoiceGenerationFormProps) {
  const [form, setForm] = useState<InvoiceGenerationInput>(() => createEmptyInvoiceForm());
  const [draftTitle, setDraftTitle] = useState("");
  const [currentDraft, setCurrentDraft] = useState<InvoiceDraftResponse | null>(null);
  const [isDirty, setIsDirty] = useState(true);
  const [validation, setValidation] = useState<InvoiceGenerationValidationResponse | null>(null);
  const [validatedRevision, setValidatedRevision] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const revisionRef = useRef(0);
  const finalizeAttempt = useRef<{ draftId: number; version: number; key: string } | null>(null);
  const [working, setWorking] = useState<Working>(null);
  const [view, setView] = useState<View>("editor");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finalized, setFinalized] = useState<InvoiceGenerationResponse | null>(null);

  const [drafts, setDrafts] = useState<InvoiceDraftResponse[]>([]);
  const [draftTotal, setDraftTotal] = useState(0);
  const [draftStatus, setDraftStatus] = useState<InvoiceDraftListStatus>("draft");
  const [draftPage, setDraftPage] = useState(1);
  const [draftsLoading, setDraftsLoading] = useState(false);
  const [draftsError, setDraftsError] = useState<string | null>(null);
  const listRequestRef = useRef(0);

  const isLocked = working !== null || currentDraft?.status !== undefined && currentDraft.status !== "draft";
  const isStale = validatedRevision !== revision || validation === null;
  const canFinalize = !isLocked && form.invoice.document_type !== "proforma_invoice";

  function changed(update: (previous: InvoiceGenerationInput) => InvoiceGenerationInput) {
    revisionRef.current += 1;
    setRevision(revisionRef.current);
    setForm(update);
    setIsDirty(true);
    setValidatedRevision(null);
    setValidation(null);
    setMessage(null);
    setError(null);
    finalizeAttempt.current = null;
    setFinalized(null);
  }

  function updateParty(section: PartySection, field: keyof InvoicePartyInput, value: string) {
    changed((previous) => ({
      ...previous,
      [section]: { ...previous[section], [field]: value || null },
    }));
  }

  function updateHeader(field: keyof InvoiceHeaderInput, value: string) {
    changed((previous) => ({
      ...previous,
      invoice: { ...previous.invoice, [field]: value || null },
    }));
  }

  function updateBank(field: keyof InvoiceBankDetails, value: string) {
    changed((previous) => ({
      ...previous,
      bank_details: { ...previous.bank_details, [field]: value || null },
    }));
  }

  function loadIntoEditor(draft: InvoiceDraftResponse) {
    revisionRef.current += 1;
    setRevision(revisionRef.current);
    setForm(draft.data);
    setDraftTitle(draft.draft_title ?? "");
    setCurrentDraft(draft);
    setIsDirty(false);
    setValidation(null);
    setValidatedRevision(null);
    setFinalized(null);
    setMessage(`Opened draft #${draft.id}.`);
    setError(null);
    finalizeAttempt.current = null;
    setView("editor");
  }

  useEffect(() => {
    if (initialDraftId === undefined) return;
    let active = true;
    setWorking("loading");
    void apiGet<InvoiceDraftResponse>(`${ENDPOINT}/drafts/${initialDraftId}`)
      .then((draft) => { if (active) loadIntoEditor(draft); })
      .catch((err: unknown) => { if (active) setError(errorText(err)); })
      .finally(() => { if (active) setWorking(null); });
    return () => { active = false; };
    // Load only when initialDraftId changes; editor state remains controlled locally.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDraftId]);

  const loadDrafts = useCallback(async () => {
    const requestNumber = ++listRequestRef.current;
    setDraftsLoading(true);
    setDraftsError(null);
    try {
      const params = new URLSearchParams({
        status: draftStatus,
        limit: String(PAGE_SIZE),
        offset: String((draftPage - 1) * PAGE_SIZE),
      });
      const result = await apiGet<InvoiceDraftListResponse>(`${ENDPOINT}/drafts?${params}`);
      if (requestNumber === listRequestRef.current) {
        setDrafts(result.drafts);
        setDraftTotal(result.total);
      }
    } catch (err: unknown) {
      if (requestNumber === listRequestRef.current) setDraftsError(errorText(err));
    } finally {
      if (requestNumber === listRequestRef.current) setDraftsLoading(false);
    }
  }, [draftStatus, draftPage]);

  useEffect(() => {
    if (view === "drafts") void loadDrafts();
  }, [view, loadDrafts]);

  /** Saves exactly the supplied snapshot, without silently overwriting later edits. */
  async function persistSnapshot(snapshot: InvoiceGenerationInput, title: string,
    existing: InvoiceDraftResponse | null, snapshotRevision: number): Promise<InvoiceDraftResponse> {
    const payload: InvoiceDraftCreate = { ...snapshot, draft_title: title.trim() || null };
    const saved = existing
      ? await apiPut<InvoiceDraftResponse>(`${ENDPOINT}/drafts/${existing.id}`, {
          ...payload,
          expected_version: existing.version,
        } satisfies InvoiceDraftUpdate)
      : await apiPost<InvoiceDraftResponse>(`${ENDPOINT}/drafts`, payload);
    setCurrentDraft(saved);
    if (snapshotRevision === revisionRef.current) setIsDirty(false);
    onDraftSaved?.(saved);
    return saved;
  }

  async function handleSave() {
    if (isLocked) return;
    setWorking("saving");
    setError(null);
    setMessage(null);
    try {
      const saved = !currentDraft || isDirty
        ? await persistSnapshot(form, draftTitle, currentDraft, revisionRef.current)
        : currentDraft;
      setMessage(`Draft #${saved.id} saved successfully (version ${saved.version}).`);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setWorking(null);
    }
  }

  async function handleValidate() {
    if (isLocked) return;
    const snapshotRevision = revisionRef.current;
    setWorking("validating");
    setError(null);
    try {
      const result = await apiPost<InvoiceGenerationValidationResponse>(`${ENDPOINT}/validate`, form);
      if (snapshotRevision === revisionRef.current) {
        setValidation(result);
        setValidatedRevision(snapshotRevision);
        setMessage(result.is_valid ? "Invoice details are valid." : "Review the validation issues below.");
      }
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setWorking(null);
    }
  }

  async function handlePreviewPdf() {
    if (working !== null) return;
    setWorking("previewing");
    setError(null);
    try {
      const blob = await fetchPdf(`${ENDPOINT}/preview`, toInvoicePreviewRequest(form));
      downloadPdf(blob, "receivai-draft-preview.pdf");
      setMessage("Draft PDF preview downloaded. It is not a finalized invoice.");
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setWorking(null);
    }
  }

  async function downloadFinalPdf(invoiceId: number) {
    if (working !== null) return;
    setWorking("previewing");
    setError(null);
    try {
      const response = await fetchProtected(`${ENDPOINT}/invoices/${invoiceId}/pdf`, "GET");
      const blob = await response.blob();
      if (!blob.size || !response.headers.get("content-type")?.includes("application/pdf")) {
        throw new Error("The server did not return a valid invoice PDF.");
      }
      downloadPdf(blob, `receivai-invoice-${invoiceId}.pdf`);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setWorking(null);
    }
  }

  async function handleFinalize() {
    if (!canFinalize) return;
    if (!window.confirm("Finalize this invoice? A permanent invoice number will be assigned and editing will be locked.")) return;

    const snapshotRevision = revisionRef.current;
    setWorking("finalizing");
    setError(null);
    setMessage(null);
    try {
      let saved = currentDraft;
      if (!saved || isDirty) saved = await persistSnapshot(form, draftTitle, saved, snapshotRevision);
      if (revisionRef.current !== snapshotRevision) {
        throw new Error("Invoice changed during saving. Please review and finalize again.");
      }

      // Validate THE SAVED draft that the backend will finalize.
      const check = await apiPost<InvoiceGenerationValidationResponse>(
        `${ENDPOINT}/drafts/${saved.id}/validate`, {},
      );
      if (revisionRef.current !== snapshotRevision) {
        throw new Error("Invoice changed during validation. Please validate again.");
      }
      setValidation(check);
      setValidatedRevision(snapshotRevision);
      if (!check.is_valid) {
        setError(check.errors.join("; ") || "Complete the required fields before finalizing.");
        return;
      }

      // Keep the SAME key if the network fails and admin retries this version.
      if (!finalizeAttempt.current || finalizeAttempt.current.draftId !== saved.id ||
        finalizeAttempt.current.version !== saved.version) {
        finalizeAttempt.current = {
          draftId: saved.id,
          version: saved.version,
          key: crypto.randomUUID(),
        };
      }
      const request: InvoiceFinalizeRequest = {
        expected_version: saved.version,
        idempotency_key: finalizeAttempt.current.key,
      };
      const result = await apiPost<InvoiceGenerationResponse>(
        `${ENDPOINT}/drafts/${saved.id}/finalize`, request,
      );
      setFinalized(result);
      setCurrentDraft({
        ...saved,
        status: "finalized",
        finalized_invoice_id: result.invoice_id,
      });
      setIsDirty(false);
      setMessage(`Invoice ${result.invoice_number} finalized and added to the Invoice Register.`);
      onFinalized?.(result);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setWorking(null);
    }
  }

  function handleNewInvoice() {
    if (working !== null) return;
    if (isDirty && !window.confirm("Start a new invoice? Unsaved changes will be lost.")) return;
    revisionRef.current += 1;
    setRevision(revisionRef.current);
    setForm(createEmptyInvoiceForm());
    setDraftTitle("");
    setCurrentDraft(null);
    setValidation(null);
    setValidatedRevision(null);
    setFinalized(null);
    setIsDirty(true);
    setMessage(null);
    setError(null);
    finalizeAttempt.current = null;
    setView("editor");
  }

  async function handleResumeDraft(draft: InvoiceDraftResponse) {
    if (working !== null) return;
    if (isDirty && !window.confirm("Open this draft? Unsaved changes in the current editor will be lost.")) return;
    setWorking("loading");
    setError(null);
    try {
      const latest = await apiGet<InvoiceDraftResponse>(`${ENDPOINT}/drafts/${draft.id}`);
      if (latest.status !== "draft") throw new Error("This invoice is no longer editable.");
      loadIntoEditor(latest);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setWorking(null);
    }
  }

  async function handleCancelDraft(draft: InvoiceDraftResponse) {
    const response = await fetchProtected(`${ENDPOINT}/drafts/${draft.id}`, "DELETE");
    const cancelled = await response.json() as InvoiceDraftResponse;
    if (currentDraft?.id === cancelled.id) {
      setCurrentDraft(cancelled);
      setIsDirty(false);
    }
    await loadDrafts();
  }

  // ============================================================
  // UI
  // ============================================================

  return (
    <div className="container-fluid py-3 py-md-4" style={{ background: "#f5f8fc", color: "#142b45", minHeight: "100vh" }}>
      <div className="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-4">
        <div>
          <div className="small fw-bold mb-1" style={{ color: "#087f7b", letterSpacing: ".08em" }}>
            RECEIVAI UAE · FINANCE WORKSPACE
          </div>
          <h1 className="h3 fw-bold mb-1">Generate Invoice</h1>
          <p style={SUBTITLE}>Create AED invoices, save drafts, preview PDFs and finalize into the Invoice Register.</p>
        </div>
        <div className="d-flex flex-wrap gap-2 align-items-center">
          <button type="button" className="btn btn-outline-secondary btn-sm" onClick={handleNewInvoice}
            disabled={working !== null}>
            <i className="bi bi-plus-lg me-1" aria-hidden="true" /> New invoice
          </button>
          <button type="button" className={`btn btn-sm ${view === "drafts" ? "btn-primary" : "btn-outline-primary"}`}
            onClick={() => setView(view === "drafts" ? "editor" : "drafts")}>
            <i className="bi bi-folder2-open me-1" aria-hidden="true" />
            {view === "drafts" ? "Back to editor" : "Saved invoices"}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {message && <div className="alert alert-success" role="status">{message}</div>}

      {view === "drafts" ? (
        <InvoiceDraftsList
          drafts={drafts}
          total={draftTotal}
          statusFilter={draftStatus}
          onStatusChange={(status) => { setDraftStatus(status); setDraftPage(1); }}
          onResumeDraft={(draft) => { void handleResumeDraft(draft); }}
          onCancelDraft={handleCancelDraft}
          onViewFinalizedInvoice={(id) => {
            if (onOpenFinalizedInvoice) onOpenFinalizedInvoice(id);
            else void downloadFinalPdf(id);
          }}
          onViewDraft={(draft) => {
            setMessage(`Draft #${draft.id}: ${draft.status}. Open a finalized invoice to download its PDF.`);
          }}
          onRefresh={() => { void loadDrafts(); }}
          onCreateNew={handleNewInvoice}
          page={draftPage}
          pageSize={PAGE_SIZE}
          onPageChange={setDraftPage}
          loading={draftsLoading}
          error={draftsError}
        />
      ) : (
        <>
          <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3 p-3"
            style={{ ...PANEL, padding: "12px 16px" }}>
            <div className="d-flex flex-wrap align-items-center gap-2">
              <span className={`badge ${currentDraft?.status === "finalized" ? "bg-success" : "bg-secondary"}`}>
                {currentDraft?.status === "finalized" ? "Finalized" : currentDraft ? `Draft #${currentDraft.id}` : "Unsaved invoice"}
              </span>
              {currentDraft?.status === "draft" && <span className="small text-muted">Version {currentDraft.version}</span>}
              {isDirty && <span className="small text-warning-emphasis">Unsaved changes</span>}
              {working !== null && <span className="small text-muted">{working}...</span>}
            </div>
            <div className="d-flex flex-wrap gap-2">
              <button className="btn btn-outline-secondary btn-sm" type="button"
                disabled={isLocked} onClick={() => void handleValidate()}>
                <i className="bi bi-check2-circle me-1" aria-hidden="true" /> Validate
              </button>
              <button className="btn btn-outline-primary btn-sm" type="button"
                disabled={isLocked} onClick={() => void handleSave()}>
                <i className="bi bi-floppy me-1" aria-hidden="true" /> Save draft
              </button>
              <button className="btn btn-primary btn-sm" type="button"
                disabled={!canFinalize} onClick={() => void handleFinalize()}>
                <i className="bi bi-file-earmark-check me-1" aria-hidden="true" /> Finalize invoice
              </button>
              {currentDraft?.status === "finalized" && currentDraft.finalized_invoice_id && (
                <button className="btn btn-success btn-sm" type="button" disabled={working !== null}
                  onClick={() => void downloadFinalPdf(currentDraft.finalized_invoice_id!)}>
                  <i className="bi bi-download me-1" aria-hidden="true" /> Download PDF
                </button>
              )}
            </div>
          </div>

          {form.invoice.document_type === "proforma_invoice" && (
            <div className="alert alert-info py-2" role="note">
              A proforma invoice can be saved or previewed, but the backend does not allow it to be finalized into receivables.
            </div>
          )}
          {finalized && (
            <div className="alert alert-success" role="status">
              <strong>{finalized.invoice_number}</strong> finalized successfully — AED {finalized.amount_aed}.
              {" "}This invoice is now read-only and available in your Invoice Register.
            </div>
          )}

          <div className="row g-4 align-items-start">
            <div className="col-12 col-xl-7">
              <fieldset disabled={isLocked} className="border-0 m-0 p-0 d-grid gap-3">
                <Section title="Invoice setup" note="Choose the invoice type and save it under a recognizable draft name.">
                  <div className="row g-3">
                    <div className="col-12 col-sm-6">
                      <TextField label="Draft title" value={draftTitle} disabled={isLocked} maxLength={120}
                        placeholder="e.g. November web development" onChange={(value) => {
                          setDraftTitle(value);
                          setIsDirty(true);
                          setMessage(null);
                          setError(null);
                        }} />
                    </div>
                    <div className="col-12 col-sm-6">
                      <label className="d-block w-100">
                        <span className="form-label mb-1 small fw-semibold">Document type</span>
                        <select className="form-select form-select-sm" value={form.invoice.document_type}
                          onChange={(event) => updateHeader("document_type", event.target.value)}>
                          <option value="tax_invoice">Tax invoice</option>
                          <option value="invoice">Invoice</option>
                          <option value="proforma_invoice">Proforma invoice</option>
                        </select>
                      </label>
                    </div>
                    <div className="col-12 col-md-6">
                      <TextField label="Invoice number (optional)" value={form.invoice.invoice_number}
                        disabled={isLocked} maxLength={100} placeholder="Automatic on finalization"
                        onChange={(value) => updateHeader("invoice_number", value)} />
                    </div>
                    <div className="col-12 col-md-6">
                      <TextField label="Purchase order number" value={form.invoice.purchase_order_number}
                        disabled={isLocked} maxLength={100} onChange={(value) => updateHeader("purchase_order_number", value)} />
                    </div>
                    <div className="col-6 col-md-4">
                      <DateField label="Issue date" value={form.invoice.issue_date} disabled={isLocked} required
                        onChange={(value) => updateHeader("issue_date", value)} />
                    </div>
                    <div className="col-6 col-md-4">
                      <DateField label="Due date" value={form.invoice.due_date} disabled={isLocked} required
                        onChange={(value) => updateHeader("due_date", value)} />
                    </div>
                    <div className="col-12 col-md-4">
                      <DateField label="Supply date" value={form.invoice.supply_date} disabled={isLocked}
                        onChange={(value) => updateHeader("supply_date", value)} />
                    </div>
                    <div className="col-12 col-md-6">
                      <TextField label="Payment terms" value={form.invoice.payment_terms} disabled={isLocked}
                        maxLength={300} placeholder="e.g. Net 30" onChange={(value) => updateHeader("payment_terms", value)} />
                    </div>
                    <div className="col-12 col-md-6">
                      <TextField label="Reference number" value={form.invoice.reference_number} disabled={isLocked}
                        maxLength={100} onChange={(value) => updateHeader("reference_number", value)} />
                    </div>
                    <div className="col-12 col-md-6">
                      <TextField label="Place of supply" value={form.invoice.place_of_supply} disabled={isLocked}
                        maxLength={150} placeholder="Dubai, UAE" onChange={(value) => updateHeader("place_of_supply", value)} />
                    </div>
                    <div className="col-12 col-md-6">
                      <label className="d-block">
                        <span className="form-label mb-1 small fw-semibold">Currency</span>
                        <input className="form-control form-control-sm" value="AED — UAE Dirham" readOnly />
                      </label>
                    </div>
                  </div>
                </Section>

                {(["seller", "buyer"] as const).map((section) => {
                  const party = form[section];
                  return (
                    <Section key={section} title={section === "seller" ? "Seller / company details" : "Bill-to / customer details"}
                      note={section === "seller" ? "Seller TRN is required when finalizing a tax invoice." : "Customer email is optional for creating an invoice."}>
                      <div className="row g-3">
                        <div className="col-12 col-md-6">
                          <TextField label={section === "seller" ? "Registered company name" : "Customer name"}
                            required value={party.name} disabled={isLocked} maxLength={180}
                            onChange={(value) => updateParty(section, "name", value)} />
                        </div>
                        <div className="col-12 col-md-6">
                          <TextField label="Tax registration number (TRN)" value={party.trn} disabled={isLocked}
                            maxLength={30} placeholder="15 digits" onChange={(value) => updateParty(section, "trn", value)} />
                        </div>
                        <div className="col-12">
                          <TextField label="Address" value={party.address} disabled={isLocked} maxLength={2000} multiline
                            onChange={(value) => updateParty(section, "address", value)} />
                        </div>
                        <div className="col-6">
                          <TextField label="Emirate" value={party.emirate} disabled={isLocked} maxLength={80}
                            placeholder="Dubai" onChange={(value) => updateParty(section, "emirate", value)} />
                        </div>
                        <div className="col-6">
                          <TextField label="Country" value={party.country} disabled={isLocked} maxLength={80}
                            placeholder="United Arab Emirates" onChange={(value) => updateParty(section, "country", value)} />
                        </div>
                        <div className="col-12 col-md-6">
                          <TextField label="Email" type="email" value={party.email} disabled={isLocked} maxLength={180}
                            onChange={(value) => updateParty(section, "email", value)} />
                        </div>
                        <div className="col-12 col-md-6">
                          <TextField label="Phone" type="tel" value={party.phone} disabled={isLocked} maxLength={50}
                            onChange={(value) => updateParty(section, "phone", value)} />
                        </div>
                        <div className="col-12">
                          <TextField label="Contact person" value={party.contact_person} disabled={isLocked} maxLength={150}
                            onChange={(value) => updateParty(section, "contact_person", value)} />
                        </div>
                      </div>
                    </Section>
                  );
                })}

                <InvoiceTextWordmark companyName={form.seller.name} settings={form.wordmark}
                  onChange={(wordmark) => changed((previous) => ({ ...previous, wordmark }))} disabled={isLocked} />

                <InvoiceLineItemsEditor items={form.items} customColumns={form.custom_columns}
                  calculated={!isStale ? validation?.calculated : null}
                  onChange={(items) => changed((previous) => ({ ...previous, items }))} disabled={isLocked} />

                <InvoiceCustomFieldsEditor custom_fields={form.custom_fields} custom_columns={form.custom_columns}
                  items={form.items} disabled={isLocked}
                  onChange={(next) => changed((previous) => ({ ...previous, ...next }))} />

                <Section title="Bank details and payment instructions" note="Displayed on invoices when provided.">
                  <div className="row g-3">
                    <div className="col-12 col-md-6"><TextField label="Account name" value={form.bank_details.account_name}
                      disabled={isLocked} maxLength={180} onChange={(value) => updateBank("account_name", value)} /></div>
                    <div className="col-12 col-md-6"><TextField label="Bank name" value={form.bank_details.bank_name}
                      disabled={isLocked} maxLength={180} onChange={(value) => updateBank("bank_name", value)} /></div>
                    <div className="col-12 col-md-6"><TextField label="IBAN" value={form.bank_details.iban}
                      disabled={isLocked} maxLength={50} onChange={(value) => updateBank("iban", value)} /></div>
                    <div className="col-12 col-md-6"><TextField label="SWIFT / BIC" value={form.bank_details.swift_code}
                      disabled={isLocked} maxLength={20} onChange={(value) => updateBank("swift_code", value)} /></div>
                    <div className="col-12"><TextField label="Payment instructions" value={form.bank_details.payment_instructions}
                      disabled={isLocked} maxLength={1000} multiline
                      onChange={(value) => updateBank("payment_instructions", value)} /></div>
                  </div>
                </Section>

                <Section title="Notes and legal text" note="Optional information for the generated PDF.">
                  <div className="d-grid gap-3">
                    <TextField label="Notes" value={form.notes} disabled={isLocked} maxLength={2000} multiline
                      onChange={(value) => changed((previous) => ({ ...previous, notes: value || null }))} />
                    <TextField label="Declaration" value={form.declaration_text} disabled={isLocked} maxLength={2000} multiline
                      onChange={(value) => changed((previous) => ({ ...previous, declaration_text: value || null }))} />
                    <TextField label="Footer text" value={form.footer_text} disabled={isLocked} maxLength={500} multiline
                      onChange={(value) => changed((previous) => ({ ...previous, footer_text: value || null }))} />
                  </div>
                </Section>
              </fieldset>

              <div className="mt-3">
                <InvoiceTotalsPanel validation={validation} isLoading={working === "validating" || working === "finalizing"}
                  isStale={isStale} disabled={isLocked} onRecalculate={() => void handleValidate()} />
              </div>

              <div className="d-flex flex-wrap gap-2 justify-content-end mt-3">
                <button type="button" className="btn btn-outline-primary" onClick={() => void handlePreviewPdf()}
                  disabled={working !== null || currentDraft?.status === "finalized" || currentDraft?.status === "cancelled"}><i className="bi bi-file-earmark-pdf me-1" /> Preview PDF</button>
                <button type="button" className="btn btn-outline-secondary" onClick={() => void handleSave()}
                  disabled={isLocked}><i className="bi bi-floppy me-1" /> Save draft</button>
                <button type="button" className="btn btn-primary" onClick={() => void handleFinalize()}
                  disabled={!canFinalize}><i className="bi bi-check-circle me-1" /> Finalize invoice</button>
              </div>
            </div>

            <div className="col-12 col-xl-5">
              <div className="p-3 p-md-4" style={{ background: "#10253e", borderRadius: 18 }}>
                <InvoiceLivePreview form={form} validation={validation} isStale={isStale}
                  isValidating={working === "validating" || working === "finalizing"}
                  onPreviewPdf={currentDraft?.status === "finalized" || currentDraft?.status === "cancelled" ? undefined : () => void handlePreviewPdf()}
                  isPreviewingPdf={working !== null} compact />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
