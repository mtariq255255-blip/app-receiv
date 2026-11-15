
"use client";

import { useId } from "react";
import type { CSSProperties } from "react";

import {
  INVOICE_GENERATION_LIMITS,
  createEmptyInvoiceLineItem,
  type InvoiceCustomColumn,
  type InvoiceCustomField,
  type InvoiceFinancialSummary,
  type InvoiceLineItemInput,
} from "@/lib/invoice-generation-types";

/**
 * ReceivAI UAE — controlled invoice line-item editor.
 *
 * The parent owns the items and calls FastAPI for validation.
 * This component does not calculate financial totals.
 * All monetary inputs remain decimal strings.
 */

export interface InvoiceLineItemsEditorProps {
  items: InvoiceLineItemInput[];
  onChange: (items: InvoiceLineItemInput[]) => void;
  customColumns?: InvoiceCustomColumn[];
  calculated?: InvoiceFinancialSummary | null;
  errors?: string[];
  disabled?: boolean;
}

const MAX_ITEMS = INVOICE_GENERATION_LIMITS.maxItems;
const MAX_ITEM_FIELDS = INVOICE_GENERATION_LIMITS.maxCustomFields;

// ============================================================
// 1. STYLES
// ============================================================

const sectionStyle: CSSProperties = {
  background: "#ffffff",
  border: "1px solid #e1eaf2",
  borderRadius: 18,
  boxShadow: "0 5px 20px rgba(24, 54, 84, 0.045)",
};

const rowStyle: CSSProperties = {
  background: "#fbfdff",
  border: "1px solid #e1eaf2",
  borderRadius: 14,
};

const labelStyle: CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: "#506581",
};

const mutedStyle: CSSProperties = {
  fontSize: 12,
  color: "#73859b",
};

const moneyStyle: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  color: "#142b45",
};

// ============================================================
// 2. DECIMAL INPUT HELPERS
// ============================================================

type NumericField =
  | "quantity"
  | "unit_price_aed"
  | "discount_aed"
  | "vat_rate";

const DECIMAL_LIMITS: Record<
  NumericField,
  { integer: number; fraction: number }
> = {
  quantity: { integer: 11, fraction: 3 },
  unit_price_aed: { integer: 12, fraction: 2 },
  discount_aed: { integer: 12, fraction: 2 },
  vat_rate: { integer: 3, fraction: 2 },
};

/**
 * Accept unsigned decimal input only.
 * Never use Number or parseFloat for invoice money.
 */
function cleanDecimalInput(
  value: string,
  field: NumericField,
): string | null {
  if (value === "") return "";

  const normalized = value.startsWith(".")
    ? `0${value}`
    : value;

  if (!/^\d+(?:\.\d*)?$/.test(normalized)) {
    return null;
  }

  const [integer, fraction = ""] = normalized.split(".");
  const limit = DECIMAL_LIMITS[field];

  if (
    integer.length > limit.integer ||
    fraction.length > limit.fraction
  ) {
    return null;
  }

  return normalized;
}

function withOrder(
  items: InvoiceLineItemInput[],
): InvoiceLineItemInput[] {
  return items.map((item, index) => ({
    ...item,
    sort_order: index,
  }));
}

function newClientId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }

  return (
    `item-${Date.now()}-` +
    Math.random().toString(36).slice(2, 10)
  );
}

function newCustomField(
  position: number,
): InvoiceCustomField {
  return {
    label: `Additional detail ${position + 1}`,
    value: "",
    show_on_pdf: true,
    sort_order: position,
  };
}

/**
 * Format a backend-calculated decimal string.
 * Does not recalculate or round financial values.
 */
function serverMoney(
  value: string | null | undefined,
): string {
  if (value == null || value === "") return "—";

  const [whole, fraction = ""] = value.split(".");

  const grouped = whole.replace(
    /\B(?=(\d{3})+(?!\d))/g,
    ",",
  );

  return `${grouped}.${fraction.padEnd(2, "0")}`;
}

// ============================================================
// 3. MAIN COMPONENT
// ============================================================

export default function InvoiceLineItemsEditor({
  items,
  onChange,
  customColumns = [],
  calculated = null,
  errors = [],
  disabled = false,
}: InvoiceLineItemsEditorProps) {
  const idPrefix = useId().replace(/:/g, "");
  const limitReached = items.length >= MAX_ITEMS;

  // ----------------------------------------------------------
  // UPDATE A SINGLE ITEM
  // ----------------------------------------------------------

  function updateItem(
    index: number,
    patch: Partial<InvoiceLineItemInput>,
  ) {
    if (disabled) return;

    onChange(
      items.map((item, i) =>
        i === index
          ? { ...item, ...patch }
          : item,
      ),
    );
  }

  function setNullableText(
    index: number,
    field: "description" | "unit",
    value: string,
  ) {
    updateItem(index, {
      [field]: value === "" ? null : value,
    });
  }

  function setDecimal(
    index: number,
    field: NumericField,
    raw: string,
  ) {
    const value = cleanDecimalInput(raw, field);

    if (value === null) return;

    updateItem(index, {
      [field]:
        value === "" && field !== "discount_aed"
          ? null
          : value,
    });
  }

  // ----------------------------------------------------------
  // ADD / DUPLICATE / REMOVE / REORDER
  // ----------------------------------------------------------

  function addItem() {
    if (disabled || limitReached) return;

    onChange(
      withOrder([
        ...items,
        createEmptyInvoiceLineItem(
          items.length,
          newClientId(),
        ),
      ]),
    );
  }

  function duplicateItem(index: number) {
    if (disabled || limitReached) return;

    const original = items[index];
    if (!original) return;

    const copy: InvoiceLineItemInput = {
      ...original,
      client_id: newClientId(),
      custom_values: {
        ...original.custom_values,
      },
      custom_fields: original.custom_fields.map(
        (field) => ({ ...field }),
      ),
    };

    const next = [...items];
    next.splice(index + 1, 0, copy);

    onChange(withOrder(next));
  }

  function removeItem(index: number) {
    if (disabled) return;

    onChange(
      withOrder(
        items.filter((_, i) => i !== index),
      ),
    );
  }

  function moveItem(
    index: number,
    direction: -1 | 1,
  ) {
    if (disabled) return;

    const target = index + direction;

    if (target < 0 || target >= items.length) {
      return;
    }

    const next = [...items];

    [next[index], next[target]] = [
      next[target],
      next[index],
    ];

    onChange(withOrder(next));
  }

  // ----------------------------------------------------------
  // CUSTOM COLUMN VALUES
  // ----------------------------------------------------------

  function setColumnValue(
    index: number,
    key: string,
    value: string,
  ) {
    const current = items[index];
    if (!current) return;

    updateItem(index, {
      custom_values: {
        ...current.custom_values,
        [key]: value,
      },
    });
  }

  // ----------------------------------------------------------
  // PER-ITEM CUSTOM FIELDS
  // ----------------------------------------------------------

  function addItemCustomField(index: number) {
    const current = items[index];

    if (
      !current ||
      current.custom_fields.length >= MAX_ITEM_FIELDS
    ) {
      return;
    }

    updateItem(index, {
      custom_fields: [
        ...current.custom_fields,
        newCustomField(
          current.custom_fields.length,
        ),
      ],
    });
  }

  function updateItemCustomField(
    itemIndex: number,
    fieldIndex: number,
    patch: Partial<InvoiceCustomField>,
  ) {
    const current = items[itemIndex];
    if (!current) return;

    updateItem(itemIndex, {
      custom_fields: current.custom_fields.map(
        (field, i) =>
          i === fieldIndex
            ? { ...field, ...patch }
            : field,
      ),
    });
  }

  function removeItemCustomField(
    itemIndex: number,
    fieldIndex: number,
  ) {
    const current = items[itemIndex];
    if (!current) return;

    updateItem(itemIndex, {
      custom_fields: current.custom_fields
        .filter((_, i) => i !== fieldIndex)
        .map((field, i) => ({
          ...field,
          sort_order: i,
        })),
    });
  }

  // ==========================================================
  // 4. RENDER
  // ==========================================================

  return (
    <section
      className="p-3 p-md-4"
      style={sectionStyle}
      aria-labelledby={`${idPrefix}-heading`}
    >
      {/* HEADER */}

      <div className="d-flex flex-wrap align-items-start justify-content-between gap-3 mb-3">
        <div>
          <h2
            id={`${idPrefix}-heading`}
            className="h5 fw-bold mb-1"
            style={{ color: "#142b45" }}
          >
            Invoice line items
          </h2>

          <p className="mb-0" style={mutedStyle}>
            Enter tax-exclusive unit prices. Set VAT
            explicitly for each item.
          </p>
        </div>

        <div className="d-flex align-items-center gap-2">
          <span className="badge rounded-pill border bg-light text-secondary px-3 py-2">
            {items.length} / {MAX_ITEMS} items
          </span>

          <button
            type="button"
            className="btn btn-primary btn-sm px-3"
            onClick={addItem}
            disabled={disabled || limitReached}
          >
            <i
              className="bi bi-plus-lg me-1"
              aria-hidden="true"
            />
            Add item
          </button>
        </div>
      </div>

      {/* VALIDATION ERRORS */}

      {errors.length > 0 && (
        <div
          className="alert alert-danger py-2"
          role="alert"
        >
          <strong className="d-block mb-1">
            Check invoice items
          </strong>

          <ul className="mb-0 ps-3">
            {errors.map((message, index) => (
              <li key={`${index}-${message}`}>
                {message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* EMPTY STATE */}

      {items.length === 0 && (
        <div
          className="text-center py-5"
          style={rowStyle}
        >
          <i
            className="bi bi-receipt fs-2 d-block mb-2"
            style={{ color: "#08a99d" }}
            aria-hidden="true"
          />

          <p
            className="fw-semibold mb-1"
            style={{ color: "#142b45" }}
          >
            No line items yet
          </p>

          <p
            className="mb-3"
            style={mutedStyle}
          >
            Add at least one item to finalize an invoice.
          </p>

          <button
            type="button"
            className="btn btn-outline-primary btn-sm"
            onClick={addItem}
            disabled={disabled}
          >
            Add first item
          </button>
        </div>
      )}

      {/* INVOICE ROWS */}

      <div className="d-grid gap-3">
        {items.map((item, index) => {
          const rowId = `${idPrefix}-row-${index}`;

          const backendLine =
            calculated?.line_items?.[index];

          return (
            <div
              className="p-3"
              style={rowStyle}
              key={item.client_id || `row-${index}`}
              aria-label={`Invoice item ${index + 1}`}
            >
              {/* ITEM HEADER AND CONTROLS */}

              <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
                <div className="d-flex align-items-center gap-2">
                  <span
                    className="d-inline-flex align-items-center justify-content-center rounded-circle fw-bold"
                    style={{
                      background: "#e5f8f5",
                      color: "#087f7b",
                      width: 30,
                      height: 30,
                    }}
                  >
                    {index + 1}
                  </span>

                  <span
                    className="fw-semibold"
                    style={{ color: "#203551" }}
                  >
                    Line item {index + 1}
                  </span>
                </div>

                <div className="d-flex flex-wrap gap-1">
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    aria-label={`Move item ${index + 1} up`}
                    title="Move up"
                    onClick={() => moveItem(index, -1)}
                    disabled={disabled || index === 0}
                  >
                    <i
                      className="bi bi-arrow-up"
                      aria-hidden="true"
                    />
                  </button>

                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    aria-label={`Move item ${index + 1} down`}
                    title="Move down"
                    onClick={() => moveItem(index, 1)}
                    disabled={
                      disabled ||
                      index === items.length - 1
                    }
                  >
                    <i
                      className="bi bi-arrow-down"
                      aria-hidden="true"
                    />
                  </button>

                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    onClick={() => duplicateItem(index)}
                    disabled={disabled || limitReached}
                  >
                    <i
                      className="bi bi-copy me-1"
                      aria-hidden="true"
                    />
                    Duplicate
                  </button>

                  <button
                    type="button"
                    className="btn btn-outline-danger btn-sm"
                    onClick={() => removeItem(index)}
                    disabled={disabled}
                    aria-label={`Remove item ${index + 1}`}
                  >
                    <i
                      className="bi bi-trash me-1"
                      aria-hidden="true"
                    />
                    Remove
                  </button>
                </div>
              </div>

              {/* ITEM FORM */}

              <div className="row g-3">
                {/* DESCRIPTION */}

                <div className="col-12">
                  <label
                    className="form-label mb-1"
                    htmlFor={`${rowId}-description`}
                    style={labelStyle}
                  >
                    Description{" "}
                    <span className="text-danger">*</span>
                  </label>

                  <textarea
                    id={`${rowId}-description`}
                    className="form-control"
                    rows={2}
                    maxLength={500}
                    placeholder="e.g. Website development — monthly maintenance"
                    value={item.description ?? ""}
                    onChange={(event) =>
                      setNullableText(
                        index,
                        "description",
                        event.target.value,
                      )
                    }
                    disabled={disabled}
                  />
                </div>

                {/* QUANTITY */}

                <div className="col-6 col-md-3 col-xl-2">
                  <label
                    className="form-label mb-1"
                    htmlFor={`${rowId}-quantity`}
                    style={labelStyle}
                  >
                    Quantity{" "}
                    <span className="text-danger">*</span>
                  </label>

                  <input
                    id={`${rowId}-quantity`}
                    className="form-control"
                    type="text"
                    inputMode="decimal"
                    placeholder="1"
                    value={item.quantity ?? ""}
                    onChange={(event) =>
                      setDecimal(
                        index,
                        "quantity",
                        event.target.value,
                      )
                    }
                    disabled={disabled}
                    aria-describedby={`${rowId}-quantity-help`}
                  />

                  <span
                    id={`${rowId}-quantity-help`}
                    className="visually-hidden"
                  >
                    Up to three decimal places; must be
                    greater than zero.
                  </span>
                </div>

                {/* UNIT */}

                <div className="col-6 col-md-3 col-xl-2">
                  <label
                    className="form-label mb-1"
                    htmlFor={`${rowId}-unit`}
                    style={labelStyle}
                  >
                    Unit
                  </label>

                  <input
                    id={`${rowId}-unit`}
                    className="form-control"
                    type="text"
                    maxLength={40}
                    placeholder="pcs / hours"
                    value={item.unit ?? ""}
                    onChange={(event) =>
                      setNullableText(
                        index,
                        "unit",
                        event.target.value,
                      )
                    }
                    disabled={disabled}
                  />
                </div>

                {/* UNIT PRICE */}

                <div className="col-6 col-md-3 col-xl-3">
                  <label
                    className="form-label mb-1"
                    htmlFor={`${rowId}-price`}
                    style={labelStyle}
                  >
                    Unit price (AED){" "}
                    <span className="text-danger">*</span>
                  </label>

                  <input
                    id={`${rowId}-price`}
                    className="form-control"
                    type="text"
                    inputMode="decimal"
                    placeholder="0.00"
                    value={item.unit_price_aed ?? ""}
                    onChange={(event) =>
                      setDecimal(
                        index,
                        "unit_price_aed",
                        event.target.value,
                      )
                    }
                    disabled={disabled}
                  />
                </div>

                {/* DISCOUNT */}

                <div className="col-6 col-md-3 col-xl-2">
                  <label
                    className="form-label mb-1"
                    htmlFor={`${rowId}-discount`}
                    style={labelStyle}
                  >
                    Discount (AED)
                  </label>

                  <input
                    id={`${rowId}-discount`}
                    className="form-control"
                    type="text"
                    inputMode="decimal"
                    placeholder="0.00"
                    value={item.discount_aed}
                    onChange={(event) =>
                      setDecimal(
                        index,
                        "discount_aed",
                        event.target.value,
                      )
                    }
                    onBlur={() => {
                      if (item.discount_aed === "") {
                        updateItem(index, {
                          discount_aed: "0.00",
                        });
                      }
                    }}
                    disabled={disabled}
                  />
                </div>

                {/* VAT RATE */}

                <div className="col-12 col-md-6 col-xl-3">
                  <label
                    className="form-label mb-1"
                    htmlFor={`${rowId}-vat`}
                    style={labelStyle}
                  >
                    VAT rate (%){" "}
                    <span className="text-danger">*</span>
                  </label>

                  <div className="input-group">
                    <input
                      id={`${rowId}-vat`}
                      className="form-control"
                      type="text"
                      inputMode="decimal"
                      placeholder="Select"
                      value={item.vat_rate ?? ""}
                      onChange={(event) =>
                        setDecimal(
                          index,
                          "vat_rate",
                          event.target.value,
                        )
                      }
                      disabled={disabled}
                    />

                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      title="Set VAT to zero percent"
                      onClick={() =>
                        updateItem(index, {
                          vat_rate: "0.00",
                        })
                      }
                      disabled={disabled}
                    >
                      0%
                    </button>

                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      title="Set VAT to five percent"
                      onClick={() =>
                        updateItem(index, {
                          vat_rate: "5.00",
                        })
                      }
                      disabled={disabled}
                    >
                      5%
                    </button>
                  </div>
                </div>
              </div>

              {/* BACKEND LINE TOTAL */}

              <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mt-3 pt-3 border-top">
                <span style={mutedStyle}>
                  <i
                    className="bi bi-shield-check me-1"
                    aria-hidden="true"
                  />
                  Totals are verified by the backend.
                </span>

                <div className="d-flex align-items-center gap-2">
                  <span
                    className="fw-semibold"
                    style={labelStyle}
                  >
                    Line total:
                  </span>

                  <strong style={moneyStyle}>
                    {backendLine?.line_total_aed != null
                      ? `AED ${serverMoney(
                          backendLine.line_total_aed,
                        )}`
                      : "—"}
                  </strong>
                </div>
              </div>

              {/* CUSTOM LINE-ITEM DETAILS */}

              <details className="mt-3">
                <summary
                  className="fw-semibold"
                  style={{
                    color: "#087f7b",
                    fontSize: 13,
                    cursor: "pointer",
                  }}
                >
                  Custom item details

                  {(
                    customColumns.length > 0 ||
                    item.custom_fields.length > 0
                  ) && (
                    <span className="ms-2 text-secondary fw-normal">
                      ({customColumns.length} columns,{" "}
                      {item.custom_fields.length} fields)
                    </span>
                  )}
                </summary>

                <div className="pt-3">
                  {/* REUSABLE CUSTOM COLUMNS */}

                  {customColumns.length > 0 && (
                    <div className="row g-3 mb-3">
                      {customColumns.map((column) => (
                        <div
                          className="col-12 col-md-6"
                          key={column.key}
                        >
                          <label
                            className="form-label mb-1"
                            style={labelStyle}
                            htmlFor={`${rowId}-column-${column.key}`}
                          >
                            {column.label}

                            {!column.show_on_pdf && (
                              <span className="fw-normal text-muted ms-1">
                                (hidden on PDF)
                              </span>
                            )}
                          </label>

                          <input
                            id={`${rowId}-column-${column.key}`}
                            className="form-control form-control-sm"
                            type="text"
                            maxLength={500}
                            value={
                              item.custom_values[column.key] ??
                              ""
                            }
                            onChange={(event) =>
                              setColumnValue(
                                index,
                                column.key,
                                event.target.value,
                              )
                            }
                            disabled={disabled}
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  {/* PER-ITEM CUSTOM FIELDS */}

                  {item.custom_fields.map(
                    (field, fieldIndex) => (
                      <div
                        className="row g-2 align-items-end mb-2"
                        key={`${rowId}-field-${fieldIndex}`}
                      >
                        <div className="col-12 col-md-4">
                          <label
                            className="form-label mb-1"
                            style={labelStyle}
                            htmlFor={`${rowId}-field-label-${fieldIndex}`}
                          >
                            Field label
                          </label>

                          <input
                            id={`${rowId}-field-label-${fieldIndex}`}
                            className="form-control form-control-sm"
                            type="text"
                            maxLength={80}
                            value={field.label}
                            onChange={(event) =>
                              updateItemCustomField(
                                index,
                                fieldIndex,
                                {
                                  label: event.target.value,
                                },
                              )
                            }
                            disabled={disabled}
                          />
                        </div>

                        <div className="col-12 col-md-5">
                          <label
                            className="form-label mb-1"
                            style={labelStyle}
                            htmlFor={`${rowId}-field-value-${fieldIndex}`}
                          >
                            Value
                          </label>

                          <input
                            id={`${rowId}-field-value-${fieldIndex}`}
                            className="form-control form-control-sm"
                            type="text"
                            maxLength={500}
                            value={field.value}
                            onChange={(event) =>
                              updateItemCustomField(
                                index,
                                fieldIndex,
                                {
                                  value: event.target.value,
                                },
                              )
                            }
                            disabled={disabled}
                          />
                        </div>

                        <div className="col-8 col-md-2">
                          <div className="form-check mb-2">
                            <input
                              id={`${rowId}-field-pdf-${fieldIndex}`}
                              type="checkbox"
                              className="form-check-input"
                              checked={field.show_on_pdf}
                              onChange={(event) =>
                                updateItemCustomField(
                                  index,
                                  fieldIndex,
                                  {
                                    show_on_pdf:
                                      event.target.checked,
                                  },
                                )
                              }
                              disabled={disabled}
                            />

                            <label
                              className="form-check-label"
                              htmlFor={`${rowId}-field-pdf-${fieldIndex}`}
                              style={{ fontSize: 12 }}
                            >
                              Show on PDF
                            </label>
                          </div>
                        </div>

                        <div className="col-4 col-md-1 text-end">
                          <button
                            type="button"
                            className="btn btn-outline-danger btn-sm"
                            title="Remove custom field"
                            aria-label={`Remove custom field ${
                              fieldIndex + 1
                            } from item ${index + 1}`}
                            onClick={() =>
                              removeItemCustomField(
                                index,
                                fieldIndex,
                              )
                            }
                            disabled={disabled}
                          >
                            <i
                              className="bi bi-x-lg"
                              aria-hidden="true"
                            />
                          </button>
                        </div>
                      </div>
                    ),
                  )}

                  <button
                    type="button"
                    className="btn btn-outline-primary btn-sm mt-2"
                    onClick={() =>
                      addItemCustomField(index)
                    }
                    disabled={
                      disabled ||
                      item.custom_fields.length >=
                        MAX_ITEM_FIELDS
                    }
                  >
                    <i
                      className="bi bi-plus-lg me-1"
                      aria-hidden="true"
                    />
                    Add custom field
                  </button>

                  <p
                    className="mt-2 mb-0"
                    style={mutedStyle}
                  >
                    Add per-item details here. Define
                    reusable custom columns in the
                    Custom Fields editor.
                  </p>
                </div>
              </details>
            </div>
          );
        })}
      </div>

      {/* ADD ANOTHER ITEM */}

      {items.length > 0 && (
        <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mt-3">
          <p className="mb-0" style={mutedStyle}>
            VAT 0% and exempt supplies can require
            different tax treatment. Verify the correct
            rate before finalizing.
          </p>

          <button
            type="button"
            className="btn btn-outline-primary btn-sm"
            onClick={addItem}
            disabled={disabled || limitReached}
          >
            <i
              className="bi bi-plus-lg me-1"
              aria-hidden="true"
            />
            Add another item
          </button>
        </div>
      )}
    </section>
  );
}
