
"use client";

import { useId, useMemo, useState } from "react";
import type { CSSProperties } from "react";

import type {
  InvoiceDraftListStatus,
  InvoiceDraftResponse,
  InvoiceDraftStatus,
} from "@/lib/invoice-generation-types";

/**
 * ReceivAI UAE — saved invoice drafts list.
 *
 * The parent fetches drafts from GET /api/invoice-generation/drafts,
 * owns pagination, and performs authenticated API actions.
 *
 * This component makes no network requests.
 */

export interface InvoiceDraftsListProps {
  drafts: InvoiceDraftResponse[];

  /** Total records matching the server-side status filter. */
  total: number;

  statusFilter: InvoiceDraftListStatus;

  onStatusChange: (
    status: InvoiceDraftListStatus,
  ) => void;

  onResumeDraft: (
    draft: InvoiceDraftResponse,
  ) => void;

  onCancelDraft: (
    draft: InvoiceDraftResponse,
  ) => Promise<void> | void;

  onViewFinalizedInvoice?: (
    invoiceId: number,
    draft: InvoiceDraftResponse,
  ) => void;

  onViewDraft?: (
    draft: InvoiceDraftResponse,
  ) => void;

  onRefresh?: () => void;
  onCreateNew?: () => void;

  loading?: boolean;
  error?: string | null;

  /** Optional server-side pagination, starting at page 1. */
  page?: number;
  pageSize?: number;

  onPageChange?: (
    page: number,
  ) => void;

  busyDraftId?: number | null;
}

// ============================================================
// 1. DESIGN STYLES
// ============================================================

const CARD: CSSProperties = {
  background: "#ffffff",
  border: "1px solid #e1eaf2",
  borderRadius: 18,
  boxShadow: "0 5px 20px rgba(24,54,84,0.045)",
};

const MUTED: CSSProperties = {
  color: "#73859b",
  fontSize: 12,
};

const TEXT: CSSProperties = {
  color: "#203551",
};

// ============================================================
// 2. STATUS CONFIGURATION
// ============================================================

const STATUS_OPTIONS: Array<{
  value: InvoiceDraftListStatus;
  label: string;
}> = [
  {
    value: "draft",
    label: "Editable drafts",
  },
  {
    value: "finalized",
    label: "Finalized",
  },
  {
    value: "cancelled",
    label: "Cancelled",
  },
  {
    value: "all",
    label: "All statuses",
  },
];

const STATUS_DISPLAY: Record<
  InvoiceDraftStatus,
  {
    label: string;
    background: string;
    color: string;
  }
> = {
  draft: {
    label: "Draft",
    background: "#e8f2ff",
    color: "#2457a7",
  },

  finalized: {
    label: "Finalized",
    background: "#e6f7f2",
    color: "#087f7b",
  },

  cancelled: {
    label: "Cancelled",
    background: "#f1f3f6",
    color: "#68788c",
  },
};

// ============================================================
// 3. DATE HELPERS
// ============================================================

function formatTimestamp(
  value: string,
): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return new Intl.DateTimeFormat("en-AE", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDate(
  value: string | null,
): string {
  if (!value) {
    return "Not set";
  }

  const match =
    /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);

  if (!match) {
    return value;
  }

  const date = new Date(
    `${value}T12:00:00Z`,
  );

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-AE", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

// ============================================================
// 4. DRAFT DISPLAY HELPERS
// ============================================================

function titleFor(
  draft: InvoiceDraftResponse,
): string {
  return (
    draft.draft_title?.trim() ||
    draft.data.invoice.invoice_number?.trim() ||
    draft.data.buyer.name?.trim() ||
    `Invoice draft #${draft.id}`
  );
}

function matchesSearch(
  draft: InvoiceDraftResponse,
  query: string,
): boolean {
  const text = [
    draft.id,
    draft.draft_title,
    draft.data.seller.name,
    draft.data.buyer.name,
    draft.data.invoice.invoice_number,
    draft.data.invoice.reference_number,
  ]
    .filter((value) => value != null)
    .join(" ")
    .toLowerCase();

  return text.includes(query);
}

// ============================================================
// 5. MAIN COMPONENT
// ============================================================

export default function InvoiceDraftsList({
  drafts,
  total,
  statusFilter,
  onStatusChange,
  onResumeDraft,
  onCancelDraft,
  onViewFinalizedInvoice,
  onViewDraft,
  onRefresh,
  onCreateNew,
  loading = false,
  error = null,
  page = 1,
  pageSize = 50,
  onPageChange,
  busyDraftId = null,
}: InvoiceDraftsListProps) {
  const prefix = useId().replace(/:/g, "");

  const [search, setSearch] = useState("");

  const [confirmCancelId, setConfirmCancelId] =
    useState<number | null>(null);

  const [cancellingId, setCancellingId] =
    useState<number | null>(null);

  const [cancelError, setCancelError] =
    useState<string | null>(null);

  // ==========================================================
  // 6. FILTER LOADED DRAFTS
  // ==========================================================

  const filteredDrafts = useMemo(() => {
    const query = search.trim().toLowerCase();

    return query
      ? drafts.filter((draft) =>
          matchesSearch(draft, query),
        )
      : drafts;
  }, [drafts, search]);

  // ==========================================================
  // 7. PAGINATION
  // ==========================================================

  const safePage = Math.max(
    1,
    Math.floor(page),
  );

  const safeSize = Math.max(
    1,
    Math.floor(pageSize),
  );

  const safeTotal = Math.max(
    0,
    total,
  );

  const totalPages = Math.max(
    1,
    Math.ceil(
      safeTotal / safeSize,
    ),
  );

  const showPagination =
    Boolean(onPageChange) &&
    totalPages > 1;

  // ==========================================================
  // 8. CONFIRM DRAFT CANCELLATION
  // ==========================================================

  async function confirmCancellation(
    draft: InvoiceDraftResponse,
  ) {
    if (
      loading ||
      cancellingId !== null ||
      busyDraftId !== null
    ) {
      return;
    }

    if (draft.status !== "draft") {
      return;
    }

    setCancelError(null);
    setCancellingId(draft.id);

    try {
      await onCancelDraft(draft);

      setConfirmCancelId(null);
    } catch {
      // The parent owns API error reporting.
      // Do not claim cancellation succeeded.

      setCancelError(
        "Cancellation failed. Please try again or refresh the list.",
      );
    } finally {
      setCancellingId(null);
    }
  }

  // ==========================================================
  // 9. RENDER
  // ==========================================================

  return (
    <section
      className="p-3 p-md-4"
      style={CARD}
      aria-labelledby={`${prefix}-title`}
    >
      {/* ====================================================
          SECTION HEADER
      ==================================================== */}

      <div className="d-flex flex-wrap align-items-start justify-content-between gap-3 mb-4">
        <div>
          <h2
            id={`${prefix}-title`}
            className="h5 fw-bold mb-1"
            style={TEXT}
          >
            Saved invoices
          </h2>

          <p className="mb-0" style={MUTED}>
            Resume drafts, review finalized invoices,
            or cancel unfinished work.
          </p>
        </div>

        <div className="d-flex flex-wrap gap-2">
          {onRefresh && (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={onRefresh}
              disabled={loading}
              aria-label="Refresh saved invoices"
            >
              <i
                className="bi bi-arrow-clockwise me-1"
                aria-hidden="true"
              />
              Refresh
            </button>
          )}

          {onCreateNew && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={onCreateNew}
            >
              <i
                className="bi bi-plus-lg me-1"
                aria-hidden="true"
              />
              New invoice
            </button>
          )}
        </div>
      </div>

      {/* ====================================================
          STATUS AND SEARCH FILTERS
      ==================================================== */}

      <div className="row g-3 align-items-end mb-3">
        <div className="col-12 col-md-5">
          <label
            htmlFor={`${prefix}-status`}
            className="form-label fw-semibold small"
          >
            Status
          </label>

          <select
            id={`${prefix}-status`}
            className="form-select form-select-sm"
            value={statusFilter}
            disabled={loading}
            onChange={(event) => {
              setSearch("");
              setConfirmCancelId(null);
              setCancelError(null);

              onStatusChange(
                event.target.value as InvoiceDraftListStatus,
              );
            }}
          >
            {STATUS_OPTIONS.map((option) => (
              <option
                key={option.value}
                value={option.value}
              >
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="col-12 col-md-7">
          <label
            htmlFor={`${prefix}-search`}
            className="form-label fw-semibold small"
          >
            Search loaded invoices
          </label>

          <input
            id={`${prefix}-search`}
            type="search"
            className="form-control form-control-sm"
            placeholder="Draft title, customer, invoice number..."
            value={search}
            onChange={(event) =>
              setSearch(event.target.value)
            }
          />
        </div>
      </div>

      {/* ====================================================
          TOTAL RECORD COUNT
      ==================================================== */}

      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <span style={MUTED}>
          {safeTotal} total matching the status filter

          {search.trim() &&
            ` · ${filteredDrafts.length} matching on this page`}
        </span>

        {loading && (
          <span
            className="d-inline-flex align-items-center gap-2"
            style={MUTED}
            role="status"
          >
            <span
              className="spinner-border spinner-border-sm"
              aria-hidden="true"
            />
            Loading invoices...
          </span>
        )}
      </div>

      {/* ====================================================
          API ERROR MESSAGE
      ==================================================== */}

      {error && (
        <div
          className="alert alert-danger py-2"
          role="alert"
        >
          {error}
        </div>
      )}

      {cancelError && (
        <div
          className="alert alert-danger py-2"
          role="alert"
        >
          {cancelError}
        </div>
      )}

      {/* ====================================================
          EMPTY STATE
      ==================================================== */}

      {!loading && filteredDrafts.length === 0 && (
        <div
          className="text-center p-4 p-md-5 rounded-3"
          style={{
            background: "#f8fbfd",
            border: "1px dashed #cbd9e5",
          }}
        >
          <i
            className="bi bi-file-earmark-text d-block fs-2 mb-2"
            style={{
              color: "#087f7b",
            }}
            aria-hidden="true"
          />

          <p
            className="fw-semibold mb-1"
            style={TEXT}
          >
            {search.trim()
              ? "No matches on this page"
              : "No invoices found"}
          </p>

          <p
            className="mb-0"
            style={MUTED}
          >
            {search.trim()
              ? "Try a different search or clear the search field."
              : "Choose another status or create your first invoice draft."}
          </p>
        </div>
      )}

      {/* ====================================================
          SAVED DRAFT CARDS
      ==================================================== */}

      <div className="d-grid gap-3">
        {filteredDrafts.map((draft) => {
          const statusStyle =
            STATUS_DISPLAY[draft.status];

          const isBusy =
            loading ||
            busyDraftId === draft.id ||
            cancellingId === draft.id;

          const isConfirming =
            confirmCancelId === draft.id;

          const invoiceId =
            draft.finalized_invoice_id;

          const itemCount =
            draft.data.items.length;

          return (
            <article
              key={draft.id}
              className="rounded-3 p-3"
              style={{
                background: "#fbfdff",
                border: "1px solid #e1eaf2",
              }}
            >
              <div className="d-flex flex-wrap justify-content-between align-items-start gap-3">
                {/* DRAFT DETAILS */}

                <div
                  style={{
                    flex: "1 1 230px",
                    minWidth: 0,
                  }}
                >
                  {/* STATUS BADGE */}

                  <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
                    <span
                      className="rounded-pill px-2 py-1 fw-semibold"
                      style={{
                        background:
                          statusStyle.background,
                        color:
                          statusStyle.color,
                        fontSize: 11,
                      }}
                    >
                      {statusStyle.label}
                    </span>

                    <span style={MUTED}>
                      Draft #{draft.id} · Version{" "}
                      {draft.version}
                    </span>
                  </div>

                  {/* DRAFT TITLE */}

                  <h3
                    className="h6 fw-bold mb-2"
                    style={{
                      ...TEXT,
                      overflowWrap: "anywhere",
                    }}
                  >
                    {titleFor(draft)}
                  </h3>

                  {/* SELLER / CUSTOMER / ITEMS */}

                  <div
                    className="d-flex flex-wrap gap-3"
                    style={MUTED}
                  >
                    <span>
                      <i
                        className="bi bi-building me-1"
                        aria-hidden="true"
                      />
                      {draft.data.seller.name?.trim() ||
                        "Seller not entered"}
                    </span>

                    <span>
                      <i
                        className="bi bi-person me-1"
                        aria-hidden="true"
                      />
                      {draft.data.buyer.name?.trim() ||
                        "Customer not entered"}
                    </span>

                    <span>
                      <i
                        className="bi bi-list-ul me-1"
                        aria-hidden="true"
                      />
                      {itemCount}{" "}
                      {itemCount === 1
                        ? "item"
                        : "items"}
                    </span>
                  </div>
                </div>

                {/* ==================================================
                    DRAFT ACTIONS
                ================================================== */}

                <div className="d-flex flex-wrap align-items-center gap-2">
                  {/* RESUME EDITING */}

                  {draft.status === "draft" && (
                    <>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() =>
                          onResumeDraft(draft)
                        }
                        disabled={isBusy}
                      >
                        <i
                          className="bi bi-pencil-square me-1"
                          aria-hidden="true"
                        />
                        Resume editing
                      </button>

                      {/* CANCEL DRAFT */}

                      <button
                        type="button"
                        className="btn btn-outline-danger btn-sm"
                        onClick={() => {
                          setCancelError(null);

                          setConfirmCancelId(
                            isConfirming
                              ? null
                              : draft.id,
                          );
                        }}
                        disabled={isBusy}
                        aria-expanded={isConfirming}
                        aria-controls={`${prefix}-cancel-${draft.id}`}
                      >
                        Cancel draft
                      </button>
                    </>
                  )}

                  {/* VIEW FINALIZED INVOICE */}

                  {draft.status === "finalized" &&
                    invoiceId !== null &&
                    onViewFinalizedInvoice && (
                      <button
                        type="button"
                        className="btn btn-outline-primary btn-sm"
                        onClick={() =>
                          onViewFinalizedInvoice(
                            invoiceId,
                            draft,
                          )
                        }
                        disabled={isBusy}
                      >
                        <i
                          className="bi bi-eye me-1"
                          aria-hidden="true"
                        />
                        View invoice
                      </button>
                    )}

                  {/* OPTIONAL READ-ONLY DETAILS */}

                  {draft.status !== "draft" &&
                    onViewDraft && (
                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm"
                        onClick={() =>
                          onViewDraft(draft)
                        }
                        disabled={isBusy}
                      >
                        View details
                      </button>
                    )}
                </div>
              </div>

              {/* ==================================================
                  INVOICE METADATA
              ================================================== */}

              <div
                className="d-flex flex-wrap gap-3 mt-3 pt-3"
                style={{
                  borderTop: "1px solid #e1eaf2",
                  ...MUTED,
                }}
              >
                <span>
                  Issue:{" "}
                  {formatDate(
                    draft.data.invoice.issue_date,
                  )}
                </span>

                <span>
                  Due:{" "}
                  {formatDate(
                    draft.data.invoice.due_date,
                  )}
                </span>

                <span>
                  Updated:{" "}
                  {formatTimestamp(
                    draft.updated_at,
                  )}
                </span>

                {draft.status === "finalized" &&
                  invoiceId !== null && (
                    <span>
                      Invoice register ID: #{invoiceId}
                    </span>
                  )}
              </div>

              {/* ==================================================
                  CANCEL CONFIRMATION
              ================================================== */}

              {draft.status === "draft" &&
                isConfirming && (
                  <div
                    id={`${prefix}-cancel-${draft.id}`}
                    className="mt-3 p-3 rounded-3"
                    style={{
                      background: "#fff7f5",
                      border: "1px solid #f2d0ca",
                    }}
                  >
                    <p
                      className="fw-semibold mb-1"
                      style={{
                        color: "#9c372a",
                        fontSize: 13,
                      }}
                    >
                      Cancel this draft?
                    </p>

                    <p
                      className="mb-3"
                      style={MUTED}
                    >
                      It will be marked cancelled and
                      cannot be edited or finalized.
                      This does not delete any
                      finalized invoice.
                    </p>

                    <div className="d-flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        onClick={() =>
                          void confirmCancellation(
                            draft,
                          )
                        }
                        disabled={isBusy}
                      >
                        {cancellingId === draft.id
                          ? "Cancelling..."
                          : "Yes, cancel draft"}
                      </button>

                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm"
                        onClick={() => {
                          setConfirmCancelId(null);
                          setCancelError(null);
                        }}
                        disabled={isBusy}
                      >
                        Keep draft
                      </button>
                    </div>
                  </div>
                )}
            </article>
          );
        })}
      </div>

      {/* ====================================================
          SERVER-SIDE PAGINATION
      ==================================================== */}

      {showPagination && (
        <nav
          className="d-flex flex-wrap align-items-center justify-content-between gap-2 mt-4 pt-3 border-top"
          aria-label="Saved invoice pages"
        >
          <span style={MUTED}>
            Page {safePage} of {totalPages}

            {search.trim()
              ? " · Search only applies to the current page"
              : ""}
          </span>

          <div className="d-flex gap-2">
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              disabled={
                loading ||
                safePage <= 1
              }
              onClick={() =>
                onPageChange?.(
                  safePage - 1,
                )
              }
            >
              Previous
            </button>

            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              disabled={
                loading ||
                safePage >= totalPages
              }
              onClick={() =>
                onPageChange?.(
                  safePage + 1,
                )
              }
            >
              Next
            </button>
          </div>
        </nav>
      )}
    </section>
  );
}
