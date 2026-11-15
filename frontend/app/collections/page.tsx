
"use client";

import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import AuthenticatedPage from "@/components/documents/AuthenticatedPage";
import WorkspaceSidebar from "@/components/WorkspaceSidebar";
import { clearToken, updateInvoiceStatus } from "@/lib/api";

import {
  approveCollectionReminder,
  editCollectionReminder,
  generateCollectionDraft,
  getCollectionPayments,
  getCollectionQueue,
  getCollectionSummary,
  getPrioritySummary,
  listCollectionReminders,
  recordCollectionPayment,
  rejectCollectionReminder,
  saveCollectionReminder,
  type CollectionQueue,
  type CollectionSummary,
  type Payment,
  type PriorityInvoice,
  type PrioritySummary,
  type ReminderDraft,
  type SavedReminder,
} from "@/lib/collections-api";

import "./collections.css";

type Tab = "queue" | "reminders";
type Tone = "friendly" | "professional" | "firm";

const number = (value: unknown) => Number(value ?? 0);

const aed = (value: unknown) =>
  `AED ${number(value).toLocaleString("en-AE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const day = (value: string | null | undefined) =>
  value
    ? new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString(
        "en-GB",
        {
          day: "2-digit",
          month: "short",
          year: "numeric",
        },
      )
    : "—";

const today = () => {
  const d = new Date();

  return `${d.getFullYear()}-${String(
    d.getMonth() + 1,
  ).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const statusLabel = (status: string) =>
  status.replace(/_/g, " ");

const symbol = (priority: string) =>
  priority === "high"
    ? "danger"
    : priority === "medium"
      ? "warning"
      : priority === "review_required"
        ? "review"
        : "success";

// ============================================================
// DATA LOADER
// Fetches backend data without modifying React state.
// ============================================================

async function loadCollectionsData() {
  const [summary, queue, prioritySummary, reminders] =
    await Promise.all([
      getCollectionSummary(),
      getCollectionQueue(),
      getPrioritySummary(),
      listCollectionReminders(),
    ]);

  return {
    summary,
    queue,
    prioritySummary,
    reminders,
  };
}

// ============================================================
// COLLECTIONS WORKSPACE
// ============================================================

function Workspace() {
  const router = useRouter();

  const [summary, setSummary] =
    useState<CollectionSummary | null>(null);

  const [prioritySummary, setPrioritySummary] =
    useState<PrioritySummary | null>(null);

  const [queue, setQueue] =
    useState<CollectionQueue | null>(null);

  const [reminders, setReminders] =
    useState<SavedReminder[]>([]);

  const [tab, setTab] = useState<Tab>("queue");
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("all");

  const [selected, setSelected] =
    useState<PriorityInvoice | null>(null);

  const [payments, setPayments] =
    useState<Payment[]>([]);
  const [paymentHistoryLoading, setPaymentHistoryLoading] = useState(false);
  const [paymentHistoryReady, setPaymentHistoryReady] = useState(false);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentDate, setPaymentDate] = useState(today);
  const [paymentReference, setPaymentReference] = useState("");
  const [paymentNotes, setPaymentNotes] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("bank_transfer");
  const [receiptConfirmed, setReceiptConfirmed] = useState(false);
  const deepLinkHandled = useRef(false);

  const [tone, setTone] = useState<Tone>("professional");
  const [draft, setDraft] = useState<ReminderDraft | null>(null);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftMessage, setDraftMessage] = useState("");

  const [editingReminderId, setEditingReminderId] =
    useState<number | null>(null);

  // ==========================================================
  // APPLY LOADED DATA
  // ==========================================================

  const applyCollectionsData = useCallback(
    (result: Awaited<ReturnType<typeof loadCollectionsData>>) => {
      setSummary(result.summary);
      setQueue(result.queue);
      setPrioritySummary(result.prioritySummary);
      setReminders(result.reminders);

      setSelected((current) =>
        current
          ? result.queue.invoices.find(
              (item) => item.invoice_id === current.invoice_id,
            ) || null
          : null,
      );
    },
    [],
  );

  // ==========================================================
  // MANUAL REFRESH
  // ==========================================================

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) {
        setLoading(true);
      }

      setError("");

      try {
        const result = await loadCollectionsData();
        applyCollectionsData(result);
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to load collection data.",
        );
      } finally {
        setLoading(false);
      }
    },
    [applyCollectionsData],
  );

  // ==========================================================
  // INITIAL DATA LOAD
  // State updates happen after the asynchronous request resolves.
  // A cleanup flag prevents stale responses after unmount.
  // ==========================================================

  useEffect(() => {
    let active = true;

    loadCollectionsData()
      .then((result) => {
        if (!active) return;

        applyCollectionsData(result);
        setError("");
      })
      .catch((cause: unknown) => {
        if (!active) return;

        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to load collection data.",
        );
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [applyCollectionsData]);

  // ==========================================================
  // FILTERS AND SUMMARY
  // ==========================================================

  const visible = useMemo(
    () =>
      (queue?.invoices || []).filter((invoice) => {
        const term = search.trim().toLowerCase();

        const textMatch =
          !term ||
          `${invoice.invoice_number} ${invoice.customer_name}`
            .toLowerCase()
            .includes(term);

        return (
          textMatch &&
          (priority === "all" ||
            invoice.priority_level === priority)
        );
      }),
    [queue, search, priority],
  );

  const maxBucket = Math.max(
    1,
    ...(summary?.aging_buckets || []).map((bucket) =>
      number(bucket.amount),
    ),
  );

  const unapproved = reminders.filter(
    (reminder) => reminder.approval_status === "pending",
  ).length;

  // ==========================================================
  // OPEN INVOICE
  // ==========================================================

  const openInvoice = useCallback(async (invoice: PriorityInvoice) => {
    setSelected(invoice);
    setDraft(null);
    setDraftSubject("");
    setDraftMessage("");
    setEditingReminderId(null);

    setPaymentHistoryLoading(true);
    setPaymentHistoryReady(false);
    setPayments([]);
    setPaymentAmount(invoice.outstanding_amount);
    setPaymentReference("");
    setPaymentNotes("");
    setPaymentMethod("bank_transfer");
    setReceiptConfirmed(false);
    setPaymentDate(today());

    setError("");

    try {
      const history = await getCollectionPayments(invoice.invoice_id);
      setPayments(history);
      setPaymentHistoryReady(true);
    } catch (cause) {
      setPayments([]);
      setPaymentHistoryReady(false);
      setError(
        cause instanceof Error
          ? `Unable to verify payment history: ${cause.message}`
          : "Unable to verify payment history. Refresh before recording a payment.",
      );
    } finally {
      setPaymentHistoryLoading(false);
    }
  }, []);

  // Open an invoice directly from Overview or Invoice Management.
  // The query contains only an invoice ID and does not bypass auth.
  useEffect(() => {
    if (!queue || deepLinkHandled.current) return;
    deepLinkHandled.current = true;

    const rawId = new URLSearchParams(window.location.search).get("invoice");
    if (!rawId) return;

    const requestedId = Number(rawId);
    if (!Number.isSafeInteger(requestedId) || requestedId <= 0) {
      setNotice("Invalid invoice link. Select an invoice from the queue.");
      return;
    }

    setTab("queue");
    setPriority("all");
    setSearch("");
    const invoice = queue.invoices.find((item) => item.invoice_id === requestedId);
    if (invoice) {
      void openInvoice(invoice);
    } else {
      setNotice(
        `Invoice #${requestedId} is not in the outstanding collections queue. ` +
        "It may already be fully settled; check the invoice register."
      );
    }
  }, [queue, openInvoice]);

  // When opened from the invoice register, show the selected detail panel
  // without forcing the administrator to search through the entire queue.
  useEffect(() => {
    if (selected?.invoice_id == null) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("selected-collection-invoice")?.scrollIntoView({
        block: "start",
        behavior: "smooth",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selected?.invoice_id]);

  // Payment capture is allowed for reconciliation-only review records.
  // Other manual-review blocks remain in place.
  const reconciliationOnly = selected?.priority_level === "review_required" &&
    selected.warnings.some((warning) => warning.startsWith("RECONCILIATION_REQUIRED:")) &&
    selected.priority_warnings.every((warning) => warning.startsWith("RECONCILIATION_REQUIRED:"));

  const paymentBlocked = !selected ||
    (selected.priority_level === "review_required" && !reconciliationOnly);

  // ==========================================================
  // GENERIC COLLECTION ACTION
  // ==========================================================

  async function perform(
    action: () => Promise<unknown>,
    success: string,
    closeDraft = false,
  ) {
    setBusy(true);
    setError("");
    setNotice("");

    try {
      await action();
      setNotice(success);

      if (closeDraft) {
        setDraft(null);
        setEditingReminderId(null);
        setDraftSubject("");
        setDraftMessage("");
      }

      await refresh(true);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Action failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  // ==========================================================
  // RECORD PAYMENT
  // ==========================================================

  async function submitPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || busy || paymentBlocked || !paymentHistoryReady) {
      setError("Review the existing payment history before recording another payment.");
      return;
    }

    const amount = Number(paymentAmount);
    if (!Number.isFinite(amount) || amount <= 0 ||
        !/^\d+(?:\.\d{1,2})?$/.test(paymentAmount.trim()) ||
        amount > number(selected.outstanding_amount)) {
      setError("Enter a valid positive amount (up to 2 decimals), not greater than the remaining balance.");
      return;
    }
    if (!paymentReference.trim()) {
      setError("Enter a unique receipt or payment reference.");
      return;
    }
    if (!paymentDate || paymentDate > today()) {
      setError("Select the actual receipt date (not a future date).");
      return;
    }
    if (!receiptConfirmed) {
      setError("Confirm that the payment was actually received before recording it.");
      return;
    }
    if (!window.confirm(
      `Record an administrator-confirmed payment of ${aed(paymentAmount)} for ` +
      `${selected.invoice_number}? This creates a payment ledger entry and audit trail. ` +
      "Only continue if the payment was actually received."
    )) return;

    const id = selected.invoice_id;
    setBusy(true);
    setError("");
    setNotice("");

    // First persist the manual payment. Never re-submit if subsequent
    // status synchronization or optional UI refreshing fails.
    let recorded: Awaited<ReturnType<typeof recordCollectionPayment>>;
    try {
      recorded = await recordCollectionPayment({
        invoice_id: id,
        amount_aed: paymentAmount.trim(),
        payment_date: paymentDate,
        payment_reference: paymentReference.trim(),
        notes: [
          `Admin-confirmed receipt via ${paymentMethod.replaceAll("_", " ")}; not bank-integrated.`,
          paymentNotes.trim(),
        ].filter(Boolean).join(" "),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to record payment.");
      setBusy(false);
      return;
    }

    // Use the backend-calculated remaining ledger balance; never infer
    // settlement from the previous invoice status displayed in the register.
    const fullySettled = Number(recorded.receivable.outstanding_amount) === 0;
    let statusSyncError = "";
    try {
      // Payment Service intentionally does not mutate the legacy Invoice.status.
      // Keep that status consistent with the now-recorded ledger balance.
      if (fullySettled) {
        await updateInvoiceStatus(id, "paid");
      } else if (reconciliationOnly) {
        // The legacy 'paid' flag was incorrect for a partially settled invoice.
        await updateInvoiceStatus(id, "unpaid");
      }
    } catch (cause) {
      statusSyncError = cause instanceof Error ? cause.message : "Status update failed.";
    }

    setPaymentReference("");
    setPaymentNotes("");
    setReceiptConfirmed(false);
    setPaymentAmount("");

    setPaymentHistoryReady(false);
    setPaymentHistoryLoading(true);
    try {
      setPayments(await getCollectionPayments(id));
      setPaymentHistoryReady(true);
    } catch {
      // The payment is committed. Prevent another payment entry until
      // the history can be fetched and verified.
      setPaymentHistoryReady(false);
    } finally {
      setPaymentHistoryLoading(false);
    }
    await refresh(true);

    setNotice(fullySettled
      ? "Payment recorded in the ledger; invoice balance is fully settled."
      : "Partial payment recorded in the ledger; remaining balance stays outstanding.");
    if (statusSyncError) {
      setError(
        "Payment WAS RECORDED, but the invoice status could not be synchronized: " +
        statusSyncError +
        ". Do not record the same payment again. Check the invoice status or contact the administrator."
      );
    }
    setBusy(false);
  }

  // ==========================================================
  // If staff marked an invoice paid in error, clear only the
  // incorrect status flag. The payment ledger is untouched.
  async function correctUnreceivedPaidStatus() {
    if (!selected || busy || !reconciliationOnly) return;
    if (!window.confirm(
      `Correct ${selected.invoice_number} from paid to unpaid/overdue? ` +
      "Choose this only if the remaining payment was NOT received. " +
      "Existing payment records will not be deleted."
    )) return;

    setBusy(true);
    setError("");
    setNotice("");
    try {
      await updateInvoiceStatus(selected.invoice_id, "unpaid");
      await refresh(true);
      setNotice("Incorrect paid status corrected. Payment ledger entries were not changed.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to correct invoice status.");
    } finally {
      setBusy(false);
    }
  }

  // ==========================================================
  // GENERATE REMINDER
  // ==========================================================

  async function generateDraft() {
    if (!selected) return;

    setBusy(true);
    setError("");
    setNotice("");
    setEditingReminderId(null);

    try {
      const result = await generateCollectionDraft(
        selected.invoice_id,
        tone,
      );

      setDraft(result);
      setDraftSubject(result.subject);
      setDraftMessage(result.message);

      setNotice(
        result.ai_used
          ? "AI draft ready for your review."
          : "Local reminder draft ready for your review.",
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to generate reminder.",
      );
    } finally {
      setBusy(false);
    }
  }

  // ==========================================================
  // SAVE REMINDER DRAFT
  // ==========================================================

  async function saveDraft() {
    if (!selected || !draft) return;

    await perform(
      () =>
        saveCollectionReminder({
          invoice_id: selected.invoice_id,
          subject: draftSubject,
          message: draftMessage,
        }),
      "Reminder draft saved as pending review. Nothing was sent.",
      true,
    );

    setTab("reminders");
  }

  // ==========================================================
  // EDIT REMINDER
  // ==========================================================

  async function saveEditedReminder() {
    if (editingReminderId === null) return;

    await perform(
      () =>
        editCollectionReminder(
          editingReminderId,
          draftSubject,
          draftMessage,
        ),
      "Reminder changes saved.",
      true,
    );
  }

  function startEditReminder(item: SavedReminder) {
    setEditingReminderId(item.id);
    setDraft(null);
    setDraftSubject(item.subject);
    setDraftMessage(item.message);
    setTab("reminders");
    setError("");
    setNotice("");
  }

  // ==========================================================
  // SIGN OUT
  // ==========================================================

  function signOut() {
    clearToken();
    router.replace("/");
  }

  // ==========================================================
  // PAGE
  // ==========================================================

  return (
    <div className="app-shell">
      <WorkspaceSidebar activeView="Payment Collections" />
      <div className="main-area" style={{ minWidth: 0 }}>
        <header className="topbar">
          <div>
            <div className="welcome-title">Good morning, Administrator</div>
            <div className="welcome-sub">Review receivables, confirm payments and manage collections.</div>
          </div>
          <div className="top-actions">
            <span className="admin-label">Administrator</span>
            <button
              className="icon-button"
              type="button"
              aria-label="Sign out"
              title="Sign out"
              onClick={signOut}
            >
              <i className="bi bi-box-arrow-right" />
            </button>
          </div>
        </header>
        <main className="collections-page" style={{ width: "100%", maxWidth: "100%", minWidth: 0 }}>
      <div className="collections-container">
        {/* PAGE HEADING */}

        <div className="collections-heading">
          <div>
            <div className="collections-kicker">
              ACCOUNTS RECEIVABLE / MODULE 02
            </div>

            <h1>Payment Collections</h1>

            <p>
              Monitor outstanding invoices, record payments
              and prepare intelligent follow-ups.
            </p>
          </div>

          <div className="collections-heading-actions">
            <span className="collections-date">
              <i className="bi bi-calendar3" /> {day(today())}
            </span>

            <button
              className="collections-primary-btn"
              type="button"
              disabled={loading || busy}
              onClick={() => void refresh()}
            >
              <i className="bi bi-arrow-clockwise" /> Refresh
            </button>
          </div>
        </div>

        {/* ALERTS */}

        {error && (
          <div
            role="alert"
            className="collections-alert danger"
          >
            <i className="bi bi-exclamation-triangle" />{" "}
            {error}

            <button
              aria-label="Dismiss error"
              type="button"
              onClick={() => setError("")}
            >
              ×
            </button>
          </div>
        )}

        {notice && (
          <div
            role="status"
            className="collections-alert success"
          >
            <i className="bi bi-check-circle" />{" "}
            {notice}

            <button
              aria-label="Dismiss message"
              type="button"
              onClick={() => setNotice("")}
            >
              ×
            </button>
          </div>
        )}

        {/* LOADING */}

        {loading ? (
          <div className="collections-loading">
            <div
              className="spinner-border text-info"
              role="status"
            />
            <span>
              Loading receivables from Neon PostgreSQL...
            </span>
          </div>
        ) : (
          <>
            {/* SUMMARY CARDS */}

            <div className="collections-stats">
              {[
                {
                  label: "Total outstanding",
                  value: aed(summary?.total_outstanding),
                  icon: "bi-wallet2",
                  tone: "blue",
                  sub: `${summary?.total_invoices ?? 0} approved invoices`,
                },
                {
                  label: "Overdue receivables",
                  value: aed(summary?.total_overdue),
                  icon: "bi-exclamation-circle",
                  tone: "rose",
                  sub: `${summary?.overdue_invoice_count ?? 0} overdue invoices`,
                },
                {
                  label: "Due within 7 days",
                  value: aed(summary?.total_due_soon),
                  icon: "bi-calendar-week",
                  tone: "amber",
                  sub: `${summary?.due_soon_invoice_count ?? 0} invoices approaching due date`,
                },
                {
                  label: "Collection rate",
                  value: `${number(
                    summary?.collection_rate_percent,
                  ).toFixed(1)}%`,
                  icon: "bi-graph-up-arrow",
                  tone: "mint",
                  sub: `${summary?.paid_invoice_count ?? 0} fully settled invoices`,
                },
              ].map((card) => (
                <article
                  className={`collections-stat ${card.tone}`}
                  key={card.label}
                >
                  <div className="collections-stat-top">
                    <span>{card.label}</span>
                    <span className="collections-stat-icon">
                      <i className={`bi ${card.icon}`} />
                    </span>
                  </div>

                  <strong>{card.value}</strong>
                  <small>{card.sub}</small>
                </article>
              ))}
            </div>

            {/* INSIGHTS */}

            <div className="collections-insights">
              {/* RECEIVABLES AGING */}

              <section className="collections-panel">
                <div className="collections-panel-header">
                  <div>
                    <h2>Receivables aging</h2>
                    <p>
                      Outstanding balances grouped by due date
                    </p>
                  </div>

                  <span className="collections-panel-tag">
                    AED
                  </span>
                </div>

                <div className="collections-aging">
                  {(summary?.aging_buckets || [])
                    .filter(
                      (bucket) =>
                        bucket.key !== "unknown_due_date",
                    )
                    .map((bucket) => (
                      <div
                        className="collections-aging-item"
                        key={bucket.key}
                      >
                        <div className="collections-aging-info">
                          <span>{bucket.label}</span>
                          <strong>{aed(bucket.amount)}</strong>
                        </div>

                        <div className="collections-bar-track">
                          <div
                            className={`collections-bar ${bucket.key}`}
                            style={{
                              width: `${
                                number(bucket.amount) > 0
                                  ? Math.max(
                                      2,
                                      (number(bucket.amount) /
                                        maxBucket) *
                                        100,
                                    )
                                  : 0
                              }%`,
                            }}
                          />
                        </div>

                        <span className="collections-aging-count">
                          {bucket.invoice_count} invoice
                          {bucket.invoice_count === 1
                            ? ""
                            : "s"}
                        </span>
                      </div>
                    ))}

                  {(summary?.aging_buckets || []).some(
                    (bucket) =>
                      bucket.key === "unknown_due_date" &&
                      number(bucket.amount) > 0,
                  ) && (
                    <p className="collections-muted">
                      Some invoices have missing due dates
                      and require review.
                    </p>
                  )}
                </div>
              </section>

              {/* PRIORITIES */}

              <section className="collections-panel">
                <div className="collections-panel-header">
                  <div>
                    <h2>Collection priorities</h2>
                    <p>Explainable rule-based scoring</p>
                  </div>

                  <i className="bi bi-shield-check collections-section-icon" />
                </div>

                <div className="collections-priority-grid">
                  {[
                    {
                      name: "High priority",
                      count:
                        prioritySummary?.high_priority_count ||
                        0,
                      tone: "high",
                      hint: "Urgent collection attention",
                    },
                    {
                      name: "Medium priority",
                      count:
                        prioritySummary?.medium_priority_count ||
                        0,
                      tone: "medium",
                      hint: "Follow-up recommended",
                    },
                    {
                      name: "Low priority",
                      count:
                        prioritySummary?.low_priority_count ||
                        0,
                      tone: "low",
                      hint: "Monitor upcoming payments",
                    },
                    {
                      name: "Manual review",
                      count:
                        prioritySummary?.manual_review_count ||
                        0,
                      tone: "review_required",
                      hint: "Verify before contacting",
                    },
                  ].map((item) => (
                    <div
                      className="collections-priority-tile"
                      key={item.tone}
                    >
                      <div>
                        <span
                          className={`collections-priority-dot ${item.tone}`}
                        />
                        {item.name}
                      </div>

                      <strong>{item.count}</strong>
                      <small>{item.hint}</small>
                    </div>
                  ))}
                </div>

                <div className="collections-summary-foot">
                  <i className="bi bi-info-circle" />{" "}
                  Scores are operational heuristics, not
                  predictions of payment default.
                </div>
              </section>
            </div>

            {/* COLLECTIONS WORKSPACE */}

            <section className="collections-panel collections-workspace">
              <div className="collections-panel-header collections-workspace-head">
                <div>
                  <h2>Collections workspace</h2>
                  <p>
                    View invoices, review payments and manage
                    reminder approvals
                  </p>
                </div>

                <span className="collections-panel-tag">
                  {queue?.total || 0} outstanding
                </span>
              </div>

              {/* TABS */}

              <div
                className="collections-tabs"
                role="tablist"
                aria-label="Collections sections"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === "queue"}
                  className={tab === "queue" ? "active" : ""}
                  onClick={() => setTab("queue")}
                >
                  Invoice queue
                  <span>{queue?.total || 0}</span>
                </button>

                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === "reminders"}
                  className={
                    tab === "reminders" ? "active" : ""
                  }
                  onClick={() => setTab("reminders")}
                >
                  Reminder approvals
                  <span>{unapproved}</span>
                </button>
              </div>

              {tab === "queue" ? (
                <>
                  {/* FILTERS */}

                  <div className="collections-filters">
                    <label className="collections-search">
                      <i className="bi bi-search" />
                      <input
                        aria-label="Search invoices"
                        placeholder="Search invoice number or customer..."
                        value={search}
                        onChange={(event) =>
                          setSearch(event.target.value)
                        }
                      />
                    </label>

                    <select
                      aria-label="Filter priority"
                      value={priority}
                      onChange={(event) =>
                        setPriority(event.target.value)
                      }
                    >
                      <option value="all">
                        All priorities
                      </option>
                      <option value="high">
                        High priority
                      </option>
                      <option value="medium">
                        Medium priority
                      </option>
                      <option value="low">
                        Low priority
                      </option>
                      <option value="review_required">
                        Manual review
                      </option>
                    </select>
                  </div>

                  {/* INVOICE TABLE */}

                  <div className="collections-table-scroll">
                    <table className="collections-table">
                      <thead>
                        <tr>
                          <th>Invoice</th>
                          <th>Customer</th>
                          <th>Due date</th>
                          <th>Outstanding</th>
                          <th>Overdue</th>
                          <th>Priority</th>
                          <th>Actions</th>
                        </tr>
                      </thead>

                      <tbody>
                        {visible.map((item) => (
                          <tr
                            key={item.invoice_id}
                            className={
                              selected?.invoice_id ===
                              item.invoice_id
                                ? "selected"
                                : ""
                            }
                          >
                            <td>
                              <strong>
                                {item.invoice_number}
                              </strong>
                              <small>#{item.invoice_id}</small>
                            </td>

                            <td>{item.customer_name}</td>
                            <td>{day(item.due_date)}</td>

                            <td className="collections-amount">
                              {aed(item.outstanding_amount)}
                            </td>

                            <td>
                              {item.days_overdue
                                ? `${item.days_overdue}d`
                                : item.due_soon
                                  ? "Due soon"
                                  : "Not due"}
                            </td>

                            <td>
                              <span
                                className={`collections-badge ${symbol(
                                  item.priority_level,
                                )}`}
                              >
                                {statusLabel(
                                  item.priority_level,
                                )}
                              </span>
                            </td>

                            <td>
                              <button
                                type="button"
                                className="collections-row-btn"
                                onClick={() =>
                                  void openInvoice(item)
                                }
                              >
                                Manage{" "}
                                <i className="bi bi-arrow-up-right" />
                              </button>
                            </td>
                          </tr>
                        ))}

                        {!visible.length && (
                          <tr>
                            <td
                              colSpan={7}
                              className="collections-empty"
                            >
                              No matching outstanding invoices.
                              Approved AED invoices will appear
                              here once available.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  {/* SELECTED INVOICE */}

                  {selected && (
                    <section
                      id="selected-collection-invoice"
                      className="collections-detail"
                      aria-label="Selected invoice details"
                    >
                      <div className="collections-detail-head">
                        <div>
                          <div className="collections-kicker">
                            SELECTED INVOICE
                          </div>

                          <h3>{selected.invoice_number}</h3>

                          <p>
                            {selected.customer_name} · Due{" "}
                            {day(selected.due_date)}
                          </p>
                        </div>

                        <button
                          aria-label="Close invoice details"
                          type="button"
                          className="collections-close"
                          onClick={() => {
                            setSelected(null);
                            setDraft(null);
                          }}
                        >
                          ×
                        </button>
                      </div>

                      <div className="collections-detail-numbers">
                        <div>
                          <span>Invoice total</span>
                          <strong>
                            {aed(selected.invoice_total)}
                          </strong>
                        </div>

                        <div>
                          <span>Recorded payments</span>
                          <strong>
                            {aed(selected.paid_amount)}
                          </strong>
                        </div>

                        <div>
                          <span>Outstanding</span>
                          <strong>
                            {aed(selected.outstanding_amount)}
                          </strong>
                        </div>

                        <div>
                          <span>Collection priority</span>
                          <strong>
                            {selected.priority_score}/100
                          </strong>
                        </div>
                      </div>

                      <p className="collections-reasons">
                        <i className="bi bi-lightbulb" />{" "}
                        {selected.priority_reasons.join(" · ")}
                      </p>

                      <div className="collections-detail-columns">
                        {/* PAYMENT FORM */}

                        <div className="collections-subpanel">
                          <h4>
                            <i className="bi bi-credit-card" />{" "}
                            Record a payment
                          </h4>

                          <p>
                            Record an externally received payment manually.
                            This is an administrator confirmation, not bank verification.
                          </p>
                          {reconciliationOnly && (
                            <div className="collections-alert" role="status" style={{ padding: 12, background: "#fff8e8", border: "1px solid #efdfb3", borderRadius: 9, marginBottom: 12 }}>
                              <strong>Payment reconciliation required</strong>
                              <div className="small mt-1">
                                This invoice is marked paid, but its recorded payments do not cover the invoice total.
                                Check the payment history below and enter only the genuinely received, missing amount.
                                If it was not paid, use the status-correction button below instead.
                              </div>
                              <button
                                type="button"
                                className="btn btn-sm btn-outline-warning mt-2"
                                disabled={busy}
                                onClick={() => void correctUnreceivedPaidStatus()}
                              >
                                Payment not received? Correct paid status
                              </button>
                            </div>
                          )}
                          {paymentBlocked && (
                            <div className="small text-warning mb-3">
                              Manual payment entry is unavailable because this invoice has other data-validation issues.
                              Review those issues before recording a payment.
                            </div>
                          )}

                          <form
                            onSubmit={(event) =>
                              void submitPayment(event)
                            }
                            className="collections-form"
                          >
                            <label>
                              Payment amount (AED)
                              <input
                                type="number"
                                required
                                min="0.01"
                                step="0.01"
                                max={selected.outstanding_amount}
                                value={paymentAmount}
                                onChange={(event) =>
                                  setPaymentAmount(
                                    event.target.value,
                                  )
                                }
                                placeholder="0.00"
                              />
                            </label>

                            <label>
                              Payment date
                              <input
                                type="date"
                                required
                                max={today()}
                                value={paymentDate}
                                onChange={(event) =>
                                  setPaymentDate(
                                    event.target.value,
                                  )
                                }
                              />
                            </label>

                            <label>
                              How was the payment received?
                              <select
                                value={paymentMethod}
                                onChange={(event) => setPaymentMethod(event.target.value)}
                                required
                              >
                                <option value="bank_transfer">Bank transfer (manual confirmation)</option>
                                <option value="cash">Cash</option>
                                <option value="cheque">Cheque</option>
                                <option value="card">Card / POS</option>
                                <option value="other">Other</option>
                              </select>
                            </label>

                            <label>
                              Unique payment reference
                              <input
                                required
                                maxLength={150}
                                value={paymentReference}
                                onChange={(event) =>
                                  setPaymentReference(
                                    event.target.value,
                                  )
                                }
                                placeholder="Actual bank reference or unique internal receipt ID"
                              />
                              <button
                                type="button"
                                className="btn btn-sm btn-outline-secondary mt-2"
                                disabled={busy}
                                onClick={() => setPaymentReference(
                                  `MANUAL-${selected.invoice_id}-${Date.now().toString(36).toUpperCase()}`
                                )}
                              >
                                Generate internal receipt ID
                              </button>
                              <small className="d-block mt-1 text-secondary">
                                Internal receipt IDs identify manual entries; they are not proof of bank settlement.
                              </small>
                            </label>

                            <label>
                              Notes (optional)
                              <textarea
                                rows={2}
                                maxLength={1800}
                                value={paymentNotes}
                                onChange={(event) =>
                                  setPaymentNotes(
                                    event.target.value,
                                  )
                                }
                                placeholder="Internal reconciliation note"
                              />
                            </label>

                            <label style={{ display: "flex", alignItems: "flex-start", gap: 9, fontSize: 12 }}>
                              <input
                                type="checkbox"
                                checked={receiptConfirmed}
                                onChange={(event) => setReceiptConfirmed(event.target.checked)}
                                style={{ marginTop: 4, width: 16, height: 16, flex: "0 0 auto" }}
                              />
                              <span>I confirm this payment has actually been received outside ReceivAI and is not already recorded in the payment history.</span>
                            </label>
                            <button
                              className="collections-primary-btn"
                              type="submit"
                              disabled={busy || paymentBlocked || paymentHistoryLoading || !paymentHistoryReady || !receiptConfirmed}
                            >
                              {busy ? "Saving..." : "Confirm received payment"}
                            </button>
                          </form>

                          {/* PAYMENT HISTORY */}

                          <div className="collections-payment-history">
                            <h5>Payment history</h5>

                            {paymentHistoryLoading ? (
                              <p>Checking recorded payments…</p>
                            ) : !paymentHistoryReady ? (
                              <div className="small text-warning">
                                Payment history could not be verified. Close and reopen this invoice before recording another payment.
                              </div>
                            ) : payments.length ? (
                              payments.map((payment) => (
                                <div key={payment.id}>
                                  <span>
                                    {day(payment.payment_date)}
                                    <small>
                                      {payment.payment_reference ||
                                        "No reference"}
                                    </small>
                                  </span>

                                  <strong>
                                    {aed(payment.amount_aed)}
                                  </strong>
                                </div>
                              ))
                            ) : (
                              <p>
                                No recorded payments for this
                                invoice.
                              </p>
                            )}
                          </div>
                        </div>

                        {/* REMINDER ASSISTANT */}

                        <div className="collections-subpanel">
                          <h4>
                            <i className="bi bi-stars" />{" "}
                            AI Collection Assistant
                          </h4>

                          <p>
                            Create a privacy-safe,
                            administrator-reviewed email reminder.
                          </p>

                          <div className="collections-form">
                            <label>
                              Reminder tone
                              <select
                                value={tone}
                                onChange={(event) =>
                                  setTone(
                                    event.target.value as Tone,
                                  )
                                }
                              >
                                <option value="friendly">
                                  Friendly
                                </option>
                                <option value="professional">
                                  Professional
                                </option>
                                <option value="firm">
                                  Firm and respectful
                                </option>
                              </select>
                            </label>

                            <button
                              className="collections-primary-btn"
                              type="button"
                              disabled={
                                busy ||
                                !selected.collection_eligible
                              }
                              onClick={() =>
                                void generateDraft()
                              }
                            >
                              {busy
                                ? "Working..."
                                : "Generate reminder draft"}
                            </button>
                          </div>

                          {/* GENERATED DRAFT */}

                          {draft && (
                            <div className="collections-draft">
                              <div className="collections-draft-method">
                                <span className="collections-badge success">
                                  {draft.ai_used
                                    ? "AI template"
                                    : "Local template"}
                                </span>

                                <span>Draft · Not sent</span>
                              </div>

                              <label>
                                Subject
                                <input
                                  value={draftSubject}
                                  maxLength={255}
                                  onChange={(event) =>
                                    setDraftSubject(
                                      event.target.value,
                                    )
                                  }
                                />
                              </label>

                              <label>
                                Email body
                                <textarea
                                  rows={10}
                                  maxLength={5000}
                                  value={draftMessage}
                                  onChange={(event) =>
                                    setDraftMessage(
                                      event.target.value,
                                    )
                                  }
                                />
                              </label>

                              {draft.warnings?.map(
                                (warning, index) => (
                                  <p
                                    key={index}
                                    className="collections-muted"
                                  >
                                    {warning}
                                  </p>
                                ),
                              )}

                              <button
                                className="collections-primary-btn"
                                type="button"
                                disabled={
                                  busy ||
                                  !draftSubject.trim() ||
                                  !draftMessage.trim()
                                }
                                onClick={() =>
                                  void saveDraft()
                                }
                              >
                                Save for approval
                              </button>

                              <small>
                                Saving creates a pending draft;
                                no message will be delivered.
                              </small>
                            </div>
                          )}
                        </div>
                      </div>
                    </section>
                  )}
                </>
              ) : (
                <>
                  {/* EDIT REMINDER */}

                  {editingReminderId !== null && (
                    <div className="collections-edit-box">
                      <h3>
                        Edit pending reminder #
                        {editingReminderId}
                      </h3>

                      <label>
                        Subject
                        <input
                          value={draftSubject}
                          maxLength={255}
                          onChange={(event) =>
                            setDraftSubject(
                              event.target.value,
                            )
                          }
                        />
                      </label>

                      <label>
                        Message
                        <textarea
                          rows={8}
                          maxLength={5000}
                          value={draftMessage}
                          onChange={(event) =>
                            setDraftMessage(
                              event.target.value,
                            )
                          }
                        />
                      </label>

                      <div className="collections-edit-actions">
                        <button
                          type="button"
                          className="collections-primary-btn"
                          disabled={busy}
                          onClick={() =>
                            void saveEditedReminder()
                          }
                        >
                          Save changes
                        </button>

                        <button
                          type="button"
                          className="collections-secondary-btn"
                          onClick={() =>
                            setEditingReminderId(null)
                          }
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* REMINDER LIST */}

                  <div className="collections-reminder-list">
                    {reminders.length ? (
                      reminders.map((item) => (
                        <article
                          className="collections-reminder"
                          key={item.id}
                        >
                          <div className="collections-reminder-header">
                            <div>
                              <span className="collections-kicker">
                                INVOICE #{item.invoice_id} ·
                                REMINDER #{item.id}
                              </span>

                              <h3>{item.subject}</h3>
                              <small>
                                Created {day(item.created_at)}
                              </small>
                            </div>

                            <span
                              className={`collections-badge ${
                                item.approval_status ===
                                "approved"
                                  ? "success"
                                  : item.approval_status ===
                                      "rejected"
                                    ? "danger"
                                    : "warning"
                              }`}
                            >
                              {statusLabel(
                                item.approval_status,
                              )}
                            </span>
                          </div>

                          <p className="collections-reminder-preview">
                            {item.message}
                          </p>

                          <div className="collections-reminder-actions">
                            <span>
                              <i className="bi bi-envelope" />{" "}
                              {item.channel} · Not confirmed sent
                            </span>

                            {item.approval_status ===
                              "pending" && (
                              <div>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() =>
                                    startEditReminder(item)
                                  }
                                >
                                  Edit
                                </button>

                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() =>
                                    void perform(
                                      () =>
                                        approveCollectionReminder(
                                          item.id,
                                        ),
                                      "Reminder approved. It has not been sent.",
                                    )
                                  }
                                >
                                  Approve
                                </button>

                                <button
                                  type="button"
                                  disabled={busy}
                                  className="danger"
                                  onClick={() => {
                                    const reason = window.prompt(
                                      "Reason for rejecting this reminder:",
                                    );

                                    if (
                                      reason &&
                                      reason.trim().length >= 3
                                    ) {
                                      void perform(
                                        () =>
                                          rejectCollectionReminder(
                                            item.id,
                                            reason.trim(),
                                          ),
                                        "Reminder rejected.",
                                      );
                                    }
                                  }}
                                >
                                  Reject
                                </button>
                              </div>
                            )}
                          </div>
                        </article>
                      ))
                    ) : (
                      <div className="collections-empty">
                        No saved reminder drafts yet.
                        Generate a draft from an outstanding
                        invoice and save it for approval.
                      </div>
                    )}
                  </div>
                </>
              )}
            </section>
          </>
        )}

        <footer className="collections-footer">
          ReceivAI UAE · Privacy-first collections ·
          Administrative approval required ·
          No automatic message delivery
        </footer>
      </div>
        </main>
      </div>
    </div>
  );
}

// ============================================================
// AUTHENTICATED PAGE
// ============================================================

export default function CollectionsPage() {
  return (
    <AuthenticatedPage>
      <Workspace />
    </AuthenticatedPage>
  );
}
