
"use client";

/**
 * ReceivAI UAE — Audit Logs Dashboard
 *
 * Module 6: Administrator Audit Logs
 *
 * Features:
 * - Real database audit history
 * - Administrator activity tracking
 * - UAE-local timestamps
 * - Search and date filtering
 * - Action and entity filters
 * - Event details
 * - Pagination
 * - Authenticated CSV export
 *
 * All operations are read-only.
 */

import Link from "next/link";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  exportAuditLogsCSV,
  getAuditFilterOptions,
  listAuditLogs,
  type AuditEvent,
  type AuditFilters,
  type AuditFilterOptions,
  type AuditResponse,
} from "@/lib/audit-logs-api";

// ============================================================
// 1. CONFIGURATION
// ============================================================

const PAGE_SIZE = 25;

const INITIAL_FILTERS: AuditFilters = {
  page: 1,
  pageSize: PAGE_SIZE,
};

// ============================================================
// 2. FORMAT ACTION AND ENTITY LABELS
// ============================================================

function formatLabel(
  value: string | null | undefined
): string {
  if (!value) return "—";

  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) =>
      character.toUpperCase()
    );
}

// ============================================================
// 3. FORMAT UAE DATE AND TIME
// ============================================================

function formatUaeDateTime(
  value: string | null
): string {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Dubai",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  }).format(date);
}

function getUaeToday(): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Dubai",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).formatToParts(new Date());

  const getPart = (type: string) =>
    parts.find(
      (part) => part.type === type
    )?.value ?? "";

  return [
    getPart("year"),
    getPart("month"),
    getPart("day"),
  ].join("-");
}

// ============================================================
// 4. GET RELATED RECORD LINK
// ============================================================

function relatedRecordLink(
  item: AuditEvent
): string | null {
  const entityType =
    item.entity_type?.toLowerCase() ?? "";

  if (
    entityType === "invoice" &&
    item.entity_id !== null
  ) {
    return `/invoices/${item.entity_id}`;
  }

  if (
    (entityType === "document" ||
      entityType === "invoice_document") &&
    item.entity_id !== null
  ) {
    return `/documents/${item.entity_id}`;
  }

  if (
    entityType === "payment" ||
    entityType === "reminder"
  ) {
    const invoiceId =
      item.details.invoice_id;

    if (
      typeof invoiceId === "number" &&
      Number.isInteger(invoiceId) &&
      invoiceId > 0
    ) {
      return `/collections?invoice=${invoiceId}`;
    }

    return "/collections";
  }

  return null;
}

// ============================================================
// 5. EVENT DETAILS COMPONENT
// ============================================================

function AuditEventDetails({
  item,
}: {
  item: AuditEvent;
}) {
  const metadata = Object.entries(
    item.details ?? {}
  );

  return (
    <div
      className="al-details"
      aria-label={`Details for audit event ${item.id}`}
    >
      <div className="al-details-heading">
        <strong>
          Audit Event #{item.id}
        </strong>

        <span>
          {formatUaeDateTime(item.created_at)}
          {" · "}UAE Time
        </span>
      </div>

      <div className="al-details-grid">
        <div>
          <small>Action</small>

          <strong>
            {formatLabel(item.action)}
          </strong>
        </div>

        <div>
          <small>Administrator</small>

          <strong>
            {item.actor_name ||
              "Not recorded"}
          </strong>
        </div>

        <div>
          <small>Record type</small>

          <strong>
            {formatLabel(item.entity_type)}
          </strong>
        </div>

        <div>
          <small>Record ID</small>

          <strong>
            {item.entity_id ?? "—"}
          </strong>
        </div>

        <div>
          <small>Administrator email</small>

          <strong>
            {item.actor_email ||
              "Not recorded"}
          </strong>
        </div>

        <div>
          <small>Audit event ID</small>

          <strong>
            #{item.id}
          </strong>
        </div>
      </div>

      <h3>Recorded event metadata</h3>

      {metadata.length > 0 ? (
        <dl className="al-metadata">
          {metadata.map(([key, value]) => (
            <div key={key}>
              <dt>
                {formatLabel(key)}
              </dt>

              <dd>
                {Array.isArray(value)
                  ? value.join(", ")
                  : String(value ?? "—")}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="al-muted">
          No non-sensitive metadata is available
          for this event.
        </p>
      )}

      <div className="al-safety">
        <i
          className="bi bi-shield-lock"
          aria-hidden="true"
        />{" "}
        Only metadata supplied by the protected
        audit API is displayed. Raw invoice contents,
        passwords, tokens and private notes are not
        shown.
      </div>
    </div>
  );
}

// ============================================================
// 6. MAIN AUDIT LOGS DASHBOARD
// ============================================================

export default function AuditLogsDashboard() {
  // Applied backend filters
  const [filters, setFilters] =
    useState<AuditFilters>(INITIAL_FILTERS);

  // Filter form values
  const [search, setSearch] =
    useState("");

  const [action, setAction] =
    useState("");

  const [entityType, setEntityType] =
    useState("");

  const [startDate, setStartDate] =
    useState("");

  const [endDate, setEndDate] =
    useState("");

  // Backend data
  const [data, setData] =
    useState<AuditResponse | null>(null);

  const [filterOptions, setFilterOptions] =
    useState<AuditFilterOptions>({
      actions: [],
      entity_types: [],
    });

  // UI states
  const [expandedId, setExpandedId] =
    useState<number | null>(null);

  const [loading, setLoading] =
    useState(true);

  const [exporting, setExporting] =
    useState(false);

  const [error, setError] =
    useState("");

  const [notification, setNotification] =
    useState("");

  const [refreshKey, setRefreshKey] =
    useState(0);

  // ==========================================================
  // 7. FETCH AVAILABLE FILTER OPTIONS
  // ==========================================================

  useEffect(() => {
    let active = true;

    getAuditFilterOptions()
      .then((result) => {
        if (active) {
          setFilterOptions(result);
        }
      })
      .catch(() => {
        // Audit history remains usable even when
        // filter options cannot be loaded.
      });

    return () => {
      active = false;
    };
  }, []);

  // ==========================================================
  // 8. LOAD AUDIT HISTORY
  // ==========================================================

  useEffect(() => {
    let active = true;

    listAuditLogs(filters)
      .then((result) => {
        if (!active) return;

        setData(result);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!active) return;

        setData(null);

        setError(
          reason instanceof Error
            ? reason.message
            : "Unable to load audit history."
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
  }, [filters, refreshKey]);

  // ==========================================================
  // 9. CURRENT SELECTED EVENT
  // ==========================================================

  const selectedEvent = useMemo(() => {
    if (
      !data ||
      expandedId === null
    ) {
      return null;
    }

    return (
      data.items.find(
        (item) => item.id === expandedId
      ) ?? null
    );
  }, [data, expandedId]);

  // ==========================================================
  // 10. REFRESH AUDIT EVENTS
  // ==========================================================

  const refresh = useCallback(() => {
    setError("");
    setNotification("");
    setData(null);
    setExpandedId(null);
    setLoading(true);

    setRefreshKey(
      (current) => current + 1
    );
  }, []);

  // ==========================================================
  // 11. APPLY FILTERS
  // ==========================================================

  function applyFilters(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    if (
      startDate &&
      endDate &&
      startDate > endDate
    ) {
      setError(
        "Start date cannot be after end date."
      );
      return;
    }

    const today = getUaeToday();

    if (
      (startDate && startDate > today) ||
      (endDate && endDate > today)
    ) {
      setError(
        "Audit date filters cannot be in the future (UAE time)."
      );
      return;
    }

    setLoading(true);
    setData(null);
    setError("");
    setNotification("");
    setExpandedId(null);

    setFilters({
      startDate: startDate || undefined,
      endDate: endDate || undefined,
      search: search.trim(),
      action,
      entityType,
      page: 1,
      pageSize: PAGE_SIZE,
    });

    // Also refresh when the same filters are reapplied.
    setRefreshKey(
      (current) => current + 1
    );
  }

  // ==========================================================
  // 12. CLEAR FILTERS
  // ==========================================================

  function clearFilters() {
    setSearch("");
    setAction("");
    setEntityType("");
    setStartDate("");
    setEndDate("");

    setExpandedId(null);
    setData(null);
    setError("");
    setNotification("");
    setLoading(true);

    setFilters({
      ...INITIAL_FILTERS,
    });

    setRefreshKey(
      (current) => current + 1
    );
  }

  // ==========================================================
  // 13. PAGINATION
  // ==========================================================

  function goToPage(
    targetPage: number
  ) {
    if (
      targetPage < 1 ||
      loading ||
      !data
    ) {
      return;
    }

    const maxPage = Math.max(
      1,
      Math.ceil(
        data.total / data.page_size
      )
    );

    if (targetPage > maxPage) {
      return;
    }

    setLoading(true);
    setData(null);
    setExpandedId(null);

    setFilters((current) => ({
      ...current,
      page: targetPage,
    }));
  }

  // ==========================================================
  // 14. DOWNLOAD AUDIT CSV
  // ==========================================================

  async function downloadCSV() {
    if (
      exporting ||
      loading ||
      !data
    ) {
      return;
    }

    setExporting(true);
    setNotification("");

    try {
      const truncated =
        await exportAuditLogsCSV(filters);

      setError("");

      if (truncated) {
        setNotification(
          "CSV export contains the first 10,000 matching events. Apply narrower filters to export additional history."
        );
      } else {
        setNotification(
          "Audit history CSV download started."
        );
      }
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to export audit logs."
      );
    } finally {
      setExporting(false);
    }
  }

  // ==========================================================
  // 15. PAGINATION AND SUMMARY VALUES
  // ==========================================================

  const currentPage =
    data?.page ?? 1;

  const totalPages = Math.max(
    1,
    Math.ceil(
      (data?.total ?? 0) /
      (data?.page_size ?? PAGE_SIZE)
    )
  );

  const firstRecord =
    data && data.total > 0
      ? (currentPage - 1) *
          data.page_size +
        1
      : 0;

  const lastRecord = data
    ? Math.min(
        currentPage * data.page_size,
        data.total
      )
    : 0;

  const topAction =
    data?.top_actions[0];

  // ==========================================================
  // 16. DASHBOARD INTERFACE
  // ==========================================================

  return (
    <section
      className="al"
      aria-label="Audit Logs"
    >
      <style>{STYLES}</style>

      {/* PAGE HEADER */}

      <div className="al-header">
        <div>
          <span className="al-eyebrow">
            RECEIVAI UAE / ADMINISTRATION
          </span>

          <h1>
            <i
              className="bi bi-shield-check"
              aria-hidden="true"
            />{" "}
            Audit Logs
          </h1>

          <p>
            Review recorded administrator actions
            across invoices, documents, payments
            and collection reminders.
          </p>
        </div>

        <div className="al-header-actions">
          <button
            type="button"
            className="al-button"
            onClick={refresh}
            disabled={loading}
          >
            <i className="bi bi-arrow-clockwise" />
            {" "}Refresh
          </button>

          <button
            type="button"
            className="al-button al-primary"
            onClick={() => void downloadCSV()}
            disabled={
              loading ||
              exporting ||
              !data
            }
          >
            <i className="bi bi-download" />
            {" "}
            {exporting
              ? "Exporting…"
              : "Export CSV"}
          </button>
        </div>
      </div>

      {/* SECURITY INFORMATION */}

      <div className="al-information">
        <i
          className="bi bi-lock"
          aria-hidden="true"
        />{" "}
        Administrator only · Read-only history ·
        UAE Time (UTC+4)
      </div>

      {/* FILTERS */}

      <form
        className="al-filters"
        onSubmit={applyFilters}
      >
        <label className="al-grow">
          Search events

          <input
            type="search"
            placeholder="Action, administrator or record ID"
            value={search}
            maxLength={100}
            onChange={(event) =>
              setSearch(event.target.value)
            }
          />
        </label>

        <label>
          Action

          <select
            value={action}
            onChange={(event) =>
              setAction(event.target.value)
            }
          >
            <option value="">
              All actions
            </option>

            {filterOptions.actions.map(
              (item) => (
                <option
                  key={item}
                  value={item}
                >
                  {formatLabel(item)}
                </option>
              )
            )}
          </select>
        </label>

        <label>
          Record type

          <select
            value={entityType}
            onChange={(event) =>
              setEntityType(event.target.value)
            }
          >
            <option value="">
              All record types
            </option>

            {filterOptions.entity_types.map(
              (item) => (
                <option
                  key={item}
                  value={item}
                >
                  {formatLabel(item)}
                </option>
              )
            )}
          </select>
        </label>

        <label>
          From (UAE)

          <input
            type="date"
            value={startDate}
            onChange={(event) =>
              setStartDate(event.target.value)
            }
          />
        </label>

        <label>
          To (UAE)

          <input
            type="date"
            value={endDate}
            onChange={(event) =>
              setEndDate(event.target.value)
            }
          />
        </label>

        <div className="al-filter-actions">
          <button
            type="submit"
            className="al-button al-primary"
            disabled={loading}
          >
            <i className="bi bi-funnel" />
            {" "}Apply
          </button>

          <button
            type="button"
            className="al-button"
            onClick={clearFilters}
            disabled={loading}
          >
            Clear
          </button>
        </div>
      </form>

      {/* ERROR MESSAGE */}

      {error && (
        <div
          className="al-error"
          role="alert"
        >
          {error}

          <button
            type="button"
            onClick={refresh}
          >
            Retry
          </button>
        </div>
      )}

      {/* SUCCESS / INFO MESSAGE */}

      {notification && (
        <div
          className="al-information"
          role="status"
        >
          <i className="bi bi-info-circle" />
          {" "}
          {notification}
        </div>
      )}

      {/* LOADING */}

      {loading && (
        <div
          className="al-loading"
          role="status"
        >
          <i className="bi bi-arrow-repeat" />
          {" "}
          Loading recorded audit events…
        </div>
      )}

      {/* AUDIT HISTORY */}

      {data && !loading && (
        <>
          {/* SUMMARY METRICS */}

          <div className="al-stats">
            <div className="al-stat">
              <span>
                Matching audit events
              </span>

              <strong>
                {data.total.toLocaleString(
                  "en-AE"
                )}
              </strong>

              <small>
                Total matching records
              </small>
            </div>

            <div className="al-stat">
              <span>
                Events on this page
              </span>

              <strong>
                {data.items.length}
              </strong>

              <small>
                Page {currentPage} of {totalPages}
              </small>
            </div>

            <div className="al-stat">
              <span>
                Most common action
              </span>

              <strong className="al-stat-text">
                {topAction
                  ? formatLabel(
                      topAction.action
                    )
                  : "None recorded"}
              </strong>

              <small>
                {topAction?.count ?? 0} matching
                event(s)
              </small>
            </div>
          </div>

          {/* ACTIVITY TABLE */}

          <div className="al-panel">
            <div className="al-panel-heading">
              <div>
                <h2>
                  Activity History
                </h2>

                <p>
                  Latest events first. Select View
                  to inspect recorded event metadata.
                </p>
              </div>

              <span className="al-count">
                {data.total} events
              </span>
            </div>

            <div
              className="al-table-scroll"
              role="region"
              aria-label="Recorded audit events"
              tabIndex={0}
            >
              <table className="al-table">
                <thead>
                  <tr>
                    <th>
                      Timestamp (UAE)
                    </th>

                    <th>
                      Action
                    </th>

                    <th>
                      Performed by
                    </th>

                    <th>
                      Affected record
                    </th>

                    <th>
                      Details
                    </th>
                  </tr>
                </thead>

                <tbody>
                  {data.items.map((item) => {
                    const isExpanded =
                      expandedId === item.id;

                    const recordLink =
                      relatedRecordLink(item);

                    const recordLabel =
                      `${formatLabel(item.entity_type)}` +
                      (
                        item.entity_id !== null
                          ? ` #${item.entity_id}`
                          : ""
                      );

                    return (
                      <tr
                        key={item.id}
                        className={
                          isExpanded
                            ? "al-selected"
                            : ""
                        }
                      >
                        <td className="al-nowrap">
                          {formatUaeDateTime(
                            item.created_at
                          )}
                        </td>

                        <td>
                          <span className="al-action">
                            {formatLabel(
                              item.action
                            )}
                          </span>

                          <small className="al-event-id">
                            Event #{item.id}
                          </small>
                        </td>

                        <td>
                          <strong>
                            {item.actor_name}
                          </strong>

                          <small className="al-event-id">
                            {item.actor_email || "—"}
                          </small>
                        </td>

                        <td>
                          {recordLink ? (
                            <Link href={recordLink}>
                              {recordLabel}
                            </Link>
                          ) : (
                            <span>
                              {recordLabel}
                            </span>
                          )}
                        </td>

                        <td>
                          <button
                            type="button"
                            className="al-view"
                            aria-expanded={
                              isExpanded
                            }
                            onClick={() =>
                              setExpandedId(
                                isExpanded
                                  ? null
                                  : item.id
                              )
                            }
                          >
                            {isExpanded
                              ? "Close"
                              : "View"}

                            <i
                              className={
                                `bi bi-chevron-${
                                  isExpanded
                                    ? "up"
                                    : "down"
                                }`
                              }
                            />
                          </button>
                        </td>
                      </tr>
                    );
                  })}

                  {data.items.length === 0 && (
                    <tr>
                      <td
                        colSpan={5}
                        className="al-empty"
                      >
                        No audit events match these
                        filters. Recorded events
                        will appear here when available
                        in the database.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* SELECTED EVENT DETAILS */}

            {selectedEvent && (
              <AuditEventDetails
                item={selectedEvent}
              />
            )}

            {/* PAGINATION */}

            <div className="al-pagination">
              <span>
                Showing {firstRecord}–{lastRecord}
                {" "}of {data.total} events
              </span>

              <div>
                <button
                  type="button"
                  className="al-button"
                  disabled={
                    currentPage <= 1
                  }
                  onClick={() =>
                    goToPage(
                      currentPage - 1
                    )
                  }
                >
                  Previous
                </button>

                <span className="al-page-number">
                  {currentPage} / {totalPages}
                </span>

                <button
                  type="button"
                  className="al-button"
                  disabled={
                    !data.has_next
                  }
                  onClick={() =>
                    goToPage(
                      currentPage + 1
                    )
                  }
                >
                  Next
                </button>
              </div>
            </div>
          </div>

          {/* FOOTER DISCLAIMER */}

          <div className="al-disclaimer">
            <i
              className="bi bi-info-circle"
              aria-hidden="true"
            />

            <div>
              {data.disclaimer}

              <p>
                Audit records document application
                activity. They are not independent
                confirmation of bank payments or
                reminder delivery.
              </p>

              <p>
                CSV exports contain up to 10,000
                matching events.
              </p>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// ============================================================
// 17. STYLES — RECEIVAI UAE THEME
// ============================================================

const STYLES = `
.al {
  width: 100%;
  color: #0F1B2D;
  font-family: inherit;
}

.al * {
  box-sizing: border-box;
}

.al-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
}

.al-eyebrow {
  font-size: 11px;
  font-weight: 800;
  color: #2463D4;
  letter-spacing: 1.2px;
}

.al-header h1 {
  font-size: clamp(25px, 2.4vw, 34px);
  font-weight: 800;
  margin: 8px 0 5px;
  letter-spacing: -.5px;
}

.al-header h1 i {
  color: #2463D4;
  margin-right: 7px;
}

.al-header p {
  font-size: 13px;
  color: #66758A;
  margin: 0;
  max-width: 670px;
}

.al-header-actions,
.al-filter-actions {
  display: flex;
  gap: 9px;
  flex-wrap: wrap;
  align-items: flex-end;
}

.al-button {
  border: 1px solid #DCE3EC;
  background: #FFFFFF;
  color: #425166;
  border-radius: 9px;
  padding: 10px 13px;
  font-size: 12px;
  min-height: 40px;
  font-weight: 700;
  cursor: pointer;
}

.al-primary {
  background: #2463D4;
  color: #FFFFFF;
  border-color: #2463D4;
}

.al-button:hover:not(:disabled) {
  filter: brightness(.97);
}

.al-button:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.al-information {
  border: 1px solid #DBE6F5;
  background: #EEF3F8;
  color: #425166;
  border-radius: 11px;
  padding: 12px;
  margin-bottom: 15px;
  font-size: 12px;
}

.al-information i {
  color: #2463D4;
  margin-right: 6px;
}

.al-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 11px;
  align-items: flex-end;
  padding: 15px;
  background: #FFFFFF;
  border: 1px solid #DCE3EC;
  border-radius: 14px;
  margin-bottom: 16px;
}

.al-filters label {
  display: grid;
  gap: 6px;
  font-size: 11px;
  color: #66758A;
  font-weight: 700;
}

.al-filters input,
.al-filters select {
  background: #FFFFFF;
  color: #0F1B2D;
  border: 1px solid #DCE3EC;
  border-radius: 8px;
  padding: 9px 10px;
  font-size: 12px;
  min-height: 40px;
  max-width: 100%;
}

.al-grow {
  flex: 1;
  min-width: 210px;
}

.al-grow input {
  width: 100%;
}

.al-stats {
  display: grid;
  grid-template-columns: repeat(
    3,
    minmax(0, 1fr)
  );
  gap: 12px;
  margin-bottom: 15px;
}

.al-stat {
  background: #FFFFFF;
  border: 1px solid #DCE3EC;
  border-radius: 12px;
  padding: 17px;
  display: grid;
  gap: 8px;
  min-width: 0;
}

.al-stat span {
  color: #66758A;
  font-size: 11px;
}

.al-stat strong {
  font-size: 26px;
  font-weight: 800;
  overflow-wrap: anywhere;
}

.al-stat-text {
  font-size: 16px !important;
  line-height: 1.5;
}

.al-stat small {
  color: #66758A;
  font-size: 10px;
}

.al-panel {
  background: #FFFFFF;
  border: 1px solid #DCE3EC;
  border-radius: 14px;
  padding: 16px;
}

.al-panel-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 15px;
}

.al-panel-heading h2 {
  font-size: 17px;
  font-weight: 800;
  margin: 0;
}

.al-panel-heading p {
  font-size: 11px;
  color: #66758A;
  margin: 5px 0 0;
}

.al-count {
  background: #E7F0FC;
  color: #2463D4;
  border-radius: 30px;
  font-size: 11px;
  font-weight: 700;
  padding: 7px 10px;
}

.al-table-scroll {
  overflow-x: auto;
}

.al-table {
  border-collapse: collapse;
  width: 100%;
  min-width: 830px;
  font-size: 12px;
}

.al-table th {
  text-align: left;
  padding: 13px 10px;
  background: #F7F9FC;
  color: #66758A;
  font-size: 11px;
  border-bottom: 1px solid #DCE3EC;
}

.al-table td {
  padding: 14px 10px;
  border-bottom: 1px solid #EDF1F6;
  vertical-align: middle;
  color: #425166;
}

.al-table a {
  color: #2463D4;
  text-decoration: none;
  font-weight: 700;
}

.al-table a:hover {
  text-decoration: underline;
}

.al-table td strong {
  display: block;
  color: #0F1B2D;
}

.al-selected {
  background: #F4F8FF;
}

.al-nowrap {
  white-space: nowrap;
}

.al-action {
  display: inline-block;
  border-radius: 7px;
  padding: 6px 9px;
  background: #E7F0FC;
  color: #174EA6;
  font-size: 11px;
  font-weight: 700;
}

.al-event-id {
  display: block;
  margin-top: 5px;
  font-size: 10px;
  color: #66758A;
  overflow-wrap: anywhere;
}

.al-view {
  font-size: 12px;
  font-weight: 700;
  color: #2463D4;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.al-view i {
  margin-left: 5px;
}

.al-details {
  padding: 18px;
  margin: 15px 0;
  border: 1px solid #DCE3EC;
  background: #F7F9FC;
  border-radius: 10px;
}

.al-details-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  margin-bottom: 16px;
}

.al-details-heading span,
.al-muted,
.al-safety {
  color: #66758A;
  font-size: 11px;
}

.al-details-grid {
  display: grid;
  grid-template-columns: repeat(
    2,
    minmax(0, 1fr)
  );
  gap: 10px;
}

.al-details-grid > div {
  display: grid;
  gap: 5px;
  background: #FFFFFF;
  border: 1px solid #E7EDF5;
  padding: 10px;
  border-radius: 8px;
}

.al-details-grid small {
  font-size: 10px;
  color: #66758A;
}

.al-details-grid strong {
  font-size: 12px;
  overflow-wrap: anywhere;
}

.al-details h3 {
  font-size: 13px;
  margin: 17px 0 10px;
}

.al-metadata {
  display: grid;
  grid-template-columns: repeat(
    2,
    minmax(0, 1fr)
  );
  gap: 8px;
}

.al-metadata > div {
  padding: 10px;
  background: #FFFFFF;
  border: 1px solid #E7EDF5;
  border-radius: 8px;
  overflow-wrap: anywhere;
}

.al-metadata dt {
  color: #66758A;
  font-size: 10px;
}

.al-metadata dd {
  font-size: 12px;
  font-weight: 700;
  margin: 5px 0 0;
}

.al-safety {
  margin-top: 13px;
}

.al-pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding-top: 16px;
  font-size: 11px;
  color: #66758A;
  flex-wrap: wrap;
}

.al-pagination > div {
  display: flex;
  align-items: center;
  gap: 9px;
}

.al-page-number {
  font-weight: 700;
  color: #0F1B2D;
}

.al-disclaimer {
  display: flex;
  gap: 9px;
  margin: 13px 0;
  color: #66758A;
  font-size: 11px;
  line-height: 1.7;
}

.al-disclaimer i {
  color: #2463D4;
}

.al-disclaimer p {
  margin: 6px 0 0;
}

.al-loading,
.al-error {
  background: #EEF3F8;
  color: #425166;
  border: 1px solid #DCE3EC;
  border-radius: 10px;
  padding: 14px;
  font-size: 12px;
  margin-bottom: 15px;
}

.al-error {
  color: #922c2c;
  background: #FFF3F3;
  border-color: #EFCCCC;
}

.al-error button {
  color: #2463D4;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.al-empty {
  padding: 35px !important;
  text-align: center;
  color: #66758A !important;
}

@media (max-width: 1000px) {
  .al-stats {
    grid-template-columns: repeat(
      2,
      minmax(0, 1fr)
    );
  }
}

@media (max-width: 600px) {
  .al-stats {
    grid-template-columns: 1fr;
  }

  .al-details-grid,
  .al-metadata {
    grid-template-columns: 1fr;
  }

  .al-panel {
    padding: 10px;
  }

  .al-header {
    align-items: flex-start;
  }
}
`;
