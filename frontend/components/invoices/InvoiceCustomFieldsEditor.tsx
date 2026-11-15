
"use client";

import { useId } from "react";
import type { CSSProperties } from "react";

import {
  INVOICE_GENERATION_LIMITS,
  type InvoiceCustomColumn,
  type InvoiceCustomField,
  type InvoiceGenerationInput,
} from "@/lib/invoice-generation-types";

/**
 * ReceivAI UAE — Custom Invoice Fields Editor
 *
 * Features:
 * - Invoice-level additional fields
 * - Reusable custom line-item columns
 * - Show/hide fields on PDF
 * - Reorder and delete fields
 * - Automatically remove deleted column values from items
 *
 * This component is controlled by its parent.
 * No API calls or financial calculations are performed here.
 */

export type InvoiceCustomizationValue = Pick<
  InvoiceGenerationInput,
  "custom_fields" | "custom_columns" | "items"
>;

export interface InvoiceCustomFieldsEditorProps
  extends InvoiceCustomizationValue {
  onChange: (value: InvoiceCustomizationValue) => void;
  disabled?: boolean;
  errors?: string[];
}

// ============================================================
// 1. CONFIGURATION
// ============================================================

const MAX_FIELDS =
  INVOICE_GENERATION_LIMITS.maxCustomFields;

const MAX_COLUMNS =
  INVOICE_GENERATION_LIMITS.maxCustomColumns;

// ============================================================
// 2. STYLES
// ============================================================

const sectionStyle: CSSProperties = {
  background: "#ffffff",
  border: "1px solid #e1eaf2",
  borderRadius: 18,
  boxShadow: "0 5px 20px rgba(24,54,84,0.045)",
};

const rowStyle: CSSProperties = {
  background: "#fbfdff",
  border: "1px solid #e1eaf2",
  borderRadius: 12,
};

const labelStyle: CSSProperties = {
  color: "#506581",
  fontSize: 12,
  fontWeight: 600,
};

const mutedStyle: CSSProperties = {
  color: "#73859b",
  fontSize: 12,
};

// ============================================================
// 3. UTILITY FUNCTIONS
// ============================================================

function sortByOrder<
  T extends { sort_order: number }
>(values: T[]): T[] {
  return [...values].sort(
    (a, b) => a.sort_order - b.sort_order,
  );
}

function assignOrder<
  T extends { sort_order: number }
>(values: T[]): T[] {
  return values.map((value, index) => ({
    ...value,
    sort_order: index,
  }));
}

/**
 * Generate a unique, stable backend column key.
 *
 * Example:
 * custom_1, custom_2, custom_3
 *
 * The key is not changed when the display label changes.
 */
function nextColumnKey(
  columns: InvoiceCustomColumn[],
): string {
  const existingKeys = new Set(
    columns.map((column) => column.key),
  );

  let index = 1;

  while (
    existingKeys.has(`custom_${index}`)
  ) {
    index += 1;
  }

  return `custom_${index}`;
}

// ============================================================
// 4. COMPONENT
// ============================================================

export default function InvoiceCustomFieldsEditor({
  custom_fields,
  custom_columns,
  items,
  onChange,
  disabled = false,
  errors = [],
}: InvoiceCustomFieldsEditorProps) {
  const prefix = useId().replace(/:/g, "");

  const fields = sortByOrder(custom_fields);
  const columns = sortByOrder(custom_columns);

  /**
   * Update all related customization data together.
   * This prevents invalid references between custom
   * columns and existing line-item values.
   */
  function emit(
    patch: Partial<InvoiceCustomizationValue>,
  ) {
    if (disabled) return;

    onChange({
      custom_fields,
      custom_columns,
      items,
      ...patch,
    });
  }

  // ==========================================================
  // 5. INVOICE-LEVEL CUSTOM FIELDS
  // ==========================================================

  function addInvoiceField() {
    if (fields.length >= MAX_FIELDS) return;

    const nextField: InvoiceCustomField = {
      label: `Custom field ${fields.length + 1}`,
      value: "",
      show_on_pdf: true,
      sort_order: fields.length,
    };

    emit({
      custom_fields: assignOrder([
        ...fields,
        nextField,
      ]),
    });
  }

  function editInvoiceField(
    index: number,
    patch: Partial<InvoiceCustomField>,
  ) {
    emit({
      custom_fields: assignOrder(
        fields.map((field, fieldIndex) =>
          fieldIndex === index
            ? { ...field, ...patch }
            : field,
        ),
      ),
    });
  }

  function removeInvoiceField(
    index: number,
  ) {
    emit({
      custom_fields: assignOrder(
        fields.filter(
          (_, fieldIndex) =>
            fieldIndex !== index,
        ),
      ),
    });
  }

  function moveInvoiceField(
    index: number,
    direction: -1 | 1,
  ) {
    const target = index + direction;

    if (
      target < 0 ||
      target >= fields.length
    ) {
      return;
    }

    const next = [...fields];

    [next[index], next[target]] = [
      next[target],
      next[index],
    ];

    emit({
      custom_fields: assignOrder(next),
    });
  }

  // ==========================================================
  // 6. REUSABLE LINE-ITEM CUSTOM COLUMNS
  // ==========================================================

  function addColumn() {
    if (columns.length >= MAX_COLUMNS) {
      return;
    }

    const key = nextColumnKey(columns);

    const nextColumn: InvoiceCustomColumn = {
      key,
      label: `Custom item field ${columns.length + 1}`,
      show_on_pdf: true,
      sort_order: columns.length,
    };

    emit({
      custom_columns: assignOrder([
        ...columns,
        nextColumn,
      ]),
    });
  }

  function editColumn(
    key: string,
    patch: Partial<
      Pick<
        InvoiceCustomColumn,
        "label" | "show_on_pdf"
      >
    >,
  ) {
    emit({
      custom_columns: assignOrder(
        columns.map((column) =>
          column.key === key
            ? { ...column, ...patch }
            : column,
        ),
      ),
    });
  }

  /**
   * Remove the custom column and delete its
   * corresponding values from every invoice item.
   *
   * The backend requires each custom_values key
   * to exist in custom_columns.
   */
  function removeColumn(
    key: string,
  ) {
    emit({
      custom_columns: assignOrder(
        columns.filter(
          (column) =>
            column.key !== key,
        ),
      ),

      items: items.map((item) => ({
        ...item,

        custom_values: Object.fromEntries(
          Object.entries(
            item.custom_values,
          ).filter(
            ([valueKey]) =>
              valueKey !== key,
          ),
        ),
      })),
    });
  }

  function moveColumn(
    index: number,
    direction: -1 | 1,
  ) {
    const target = index + direction;

    if (
      target < 0 ||
      target >= columns.length
    ) {
      return;
    }

    const next = [...columns];

    [next[index], next[target]] = [
      next[target],
      next[index],
    ];

    emit({
      custom_columns: assignOrder(next),
    });
  }

  // ==========================================================
  // 7. RENDER COMPONENT
  // ==========================================================

  return (
    <section
      className="p-3 p-md-4"
      style={sectionStyle}
      aria-labelledby={`${prefix}-title`}
    >
      {/* SECTION HEADER */}

      <div className="mb-4">
        <h2
          id={`${prefix}-title`}
          className="h5 fw-bold mb-1"
          style={{
            color: "#142b45",
          }}
        >
          Custom fields and columns
        </h2>

        <p
          className="mb-0"
          style={mutedStyle}
        >
          Personalize invoice details without
          changing calculated financial amounts.
        </p>
      </div>

      {/* VALIDATION ERRORS */}

      {errors.length > 0 && (
        <div
          className="alert alert-danger py-2"
          role="alert"
        >
          <strong>
            Check your custom fields
          </strong>

          <ul className="mb-0 mt-1 ps-3">
            {errors.map(
              (error, index) => (
                <li
                  key={`${index}-${error}`}
                >
                  {error}
                </li>
              ),
            )}
          </ul>
        </div>
      )}

      {/* ====================================================
          INVOICE-LEVEL CUSTOM FIELDS
      ==================================================== */}

      <div className="mb-4">
        <div className="d-flex flex-wrap align-items-start justify-content-between gap-2 mb-3">
          <div>
            <h3
              className="h6 fw-bold mb-1"
              style={{
                color: "#203551",
              }}
            >
              Invoice information fields
            </h3>

            <p
              className="mb-0"
              style={mutedStyle}
            >
              Add project references, contract
              numbers, departments or other details.
            </p>
          </div>

          <div className="d-flex align-items-center gap-2">
            <span className="badge rounded-pill border bg-light text-secondary px-3 py-2">
              {fields.length} / {MAX_FIELDS}
            </span>

            <button
              type="button"
              className="btn btn-outline-primary btn-sm"
              onClick={addInvoiceField}
              disabled={
                disabled ||
                fields.length >= MAX_FIELDS
              }
            >
              <i
                className="bi bi-plus-lg me-1"
                aria-hidden="true"
              />
              Add field
            </button>
          </div>
        </div>

        {/* EMPTY STATE */}

        {fields.length === 0 ? (
          <div
            className="border rounded-3 p-4 text-center"
            style={mutedStyle}
          >
            No additional invoice fields.
            Select <strong>Add field</strong> to start.
          </div>
        ) : (
          <div className="d-grid gap-2">
            {fields.map(
              (field, index) => (
                <div
                  className="p-3"
                  style={rowStyle}
                  key={`field-${index}`}
                >
                  <div className="row g-2 align-items-end">

                    {/* FIELD LABEL */}

                    <div className="col-12 col-md-4">
                      <label
                        className="form-label mb-1"
                        htmlFor={`${prefix}-field-label-${index}`}
                        style={labelStyle}
                      >
                        Field name{" "}
                        <span className="text-danger">
                          *
                        </span>
                      </label>

                      <input
                        id={`${prefix}-field-label-${index}`}
                        className="form-control form-control-sm"
                        type="text"
                        value={field.label}
                        maxLength={80}
                        required
                        placeholder="e.g. Project reference"
                        onChange={(event) =>
                          editInvoiceField(
                            index,
                            {
                              label:
                                event.target.value,
                            },
                          )
                        }
                        onBlur={() => {
                          if (
                            !field.label.trim()
                          ) {
                            editInvoiceField(
                              index,
                              {
                                label:
                                  `Custom field ${index + 1}`,
                              },
                            );
                          }
                        }}
                        disabled={disabled}
                      />
                    </div>

                    {/* FIELD VALUE */}

                    <div className="col-12 col-md-5">
                      <label
                        className="form-label mb-1"
                        htmlFor={`${prefix}-field-value-${index}`}
                        style={labelStyle}
                      >
                        Value
                      </label>

                      <input
                        id={`${prefix}-field-value-${index}`}
                        className="form-control form-control-sm"
                        type="text"
                        value={field.value}
                        maxLength={500}
                        placeholder="e.g. PRJ-2026-0042"
                        onChange={(event) =>
                          editInvoiceField(
                            index,
                            {
                              value:
                                event.target.value,
                            },
                          )
                        }
                        disabled={disabled}
                      />
                    </div>

                    {/* SHOW ON PDF */}

                    <div className="col-8 col-md-2">
                      <div className="form-check mb-2">
                        <input
                          id={`${prefix}-field-pdf-${index}`}
                          className="form-check-input"
                          type="checkbox"
                          checked={field.show_on_pdf}
                          onChange={(event) =>
                            editInvoiceField(
                              index,
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
                          style={{
                            fontSize: 12,
                          }}
                          htmlFor={`${prefix}-field-pdf-${index}`}
                        >
                          Show on PDF
                        </label>
                      </div>
                    </div>

                    {/* FIELD ACTIONS */}

                    <div className="col-4 col-md-1 d-flex justify-content-end gap-1">
                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm"
                        title="Move field up"
                        aria-label={`Move field ${index + 1} up`}
                        disabled={
                          disabled ||
                          index === 0
                        }
                        onClick={() =>
                          moveInvoiceField(
                            index,
                            -1,
                          )
                        }
                      >
                        <i
                          className="bi bi-arrow-up"
                          aria-hidden="true"
                        />
                      </button>

                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm"
                        title="Move field down"
                        aria-label={`Move field ${index + 1} down`}
                        disabled={
                          disabled ||
                          index === fields.length - 1
                        }
                        onClick={() =>
                          moveInvoiceField(
                            index,
                            1,
                          )
                        }
                      >
                        <i
                          className="bi bi-arrow-down"
                          aria-hidden="true"
                        />
                      </button>

                      <button
                        type="button"
                        className="btn btn-outline-danger btn-sm"
                        title="Remove field"
                        aria-label={`Remove field ${index + 1}`}
                        onClick={() =>
                          removeInvoiceField(
                            index,
                          )
                        }
                        disabled={disabled}
                      >
                        <i
                          className="bi bi-trash"
                          aria-hidden="true"
                        />
                      </button>
                    </div>

                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </div>

      {/* DIVIDER */}

      <hr
        style={{
          borderColor: "#dce5ef",
        }}
      />

      {/* ====================================================
          REUSABLE ITEM CUSTOM COLUMNS
      ==================================================== */}

      <div className="mt-4">
        <div className="d-flex flex-wrap align-items-start justify-content-between gap-2 mb-3">
          <div>
            <h3
              className="h6 fw-bold mb-1"
              style={{
                color: "#203551",
              }}
            >
              Reusable line-item fields
            </h3>

            <p
              className="mb-0"
              style={mutedStyle}
            >
              Define fields such as SKU or service
              period for every invoice item.
              Their values are edited in the
              line-item editor.
            </p>
          </div>

          <div className="d-flex align-items-center gap-2">
            <span className="badge rounded-pill border bg-light text-secondary px-3 py-2">
              {columns.length} / {MAX_COLUMNS}
            </span>

            <button
              type="button"
              className="btn btn-outline-primary btn-sm"
              onClick={addColumn}
              disabled={
                disabled ||
                columns.length >= MAX_COLUMNS
              }
            >
              <i
                className="bi bi-plus-lg me-1"
                aria-hidden="true"
              />
              Add item field
            </button>
          </div>
        </div>

        {/* EMPTY STATE */}

        {columns.length === 0 ? (
          <div
            className="border rounded-3 p-4 text-center"
            style={mutedStyle}
          >
            No reusable item fields. Add one
            to display it under each line item.
          </div>
        ) : (
          <div className="d-grid gap-2">
            {columns.map(
              (column, index) => (
                <div
                  className="p-3"
                  style={rowStyle}
                  key={column.key}
                >
                  <div className="row g-2 align-items-end">

                    {/* COLUMN LABEL */}

                    <div className="col-12 col-md-6">
                      <label
                        className="form-label mb-1"
                        style={labelStyle}
                        htmlFor={`${prefix}-column-label-${column.key}`}
                      >
                        Item field name{" "}
                        <span className="text-danger">
                          *
                        </span>
                      </label>

                      <input
                        id={`${prefix}-column-label-${column.key}`}
                        className="form-control form-control-sm"
                        type="text"
                        value={column.label}
                        maxLength={60}
                        required
                        placeholder="e.g. SKU / Service period"
                        onChange={(event) =>
                          editColumn(
                            column.key,
                            {
                              label:
                                event.target.value,
                            },
                          )
                        }
                        onBlur={() => {
                          if (
                            !column.label.trim()
                          ) {
                            editColumn(
                              column.key,
                              {
                                label:
                                  `Custom item field ${index + 1}`,
                              },
                            );
                          }
                        }}
                        disabled={disabled}
                      />

                      <small
                        className="d-block mt-1"
                        style={mutedStyle}
                      >
                        Internal key:{" "}
                        <code>
                          {column.key}
                        </code>{" "}
                        (unchanged on rename)
                      </small>
                    </div>

                    {/* PDF VISIBILITY */}

                    <div className="col-8 col-md-3">
                      <div className="form-check mb-2">
                        <input
                          id={`${prefix}-column-pdf-${column.key}`}
                          className="form-check-input"
                          type="checkbox"
                          checked={column.show_on_pdf}
                          onChange={(event) =>
                            editColumn(
                              column.key,
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
                          htmlFor={`${prefix}-column-pdf-${column.key}`}
                          style={{
                            fontSize: 12,
                          }}
                        >
                          Show on PDF
                        </label>
                      </div>
                    </div>

                    {/* COLUMN ACTIONS */}

                    <div className="col-4 col-md-3 d-flex justify-content-end gap-1">
                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm"
                        title="Move item field up"
                        aria-label={`Move item field ${index + 1} up`}
                        disabled={
                          disabled ||
                          index === 0
                        }
                        onClick={() =>
                          moveColumn(
                            index,
                            -1,
                          )
                        }
                      >
                        <i
                          className="bi bi-arrow-up"
                          aria-hidden="true"
                        />
                      </button>

                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm"
                        title="Move item field down"
                        aria-label={`Move item field ${index + 1} down`}
                        disabled={
                          disabled ||
                          index === columns.length - 1
                        }
                        onClick={() =>
                          moveColumn(
                            index,
                            1,
                          )
                        }
                      >
                        <i
                          className="bi bi-arrow-down"
                          aria-hidden="true"
                        />
                      </button>

                      <button
                        type="button"
                        className="btn btn-outline-danger btn-sm"
                        title="Remove item field and its values"
                        aria-label={`Remove item field ${index + 1} and its values`}
                        onClick={() =>
                          removeColumn(
                            column.key,
                          )
                        }
                        disabled={disabled}
                      >
                        <i
                          className="bi bi-trash"
                          aria-hidden="true"
                        />
                      </button>
                    </div>

                  </div>
                </div>
              ),
            )}
          </div>
        )}

        <p
          className="mb-0 mt-3"
          style={mutedStyle}
        >
          Reusable item fields appear as
          additional details beneath each item
          in the PDF. Removing one removes its
          entered values from all current line
          items; hiding it keeps those values
          stored in the draft.
        </p>
      </div>
    </section>
  );
}
