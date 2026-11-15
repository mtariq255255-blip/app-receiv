
"use client";

import { useId } from "react";
import type { CSSProperties } from "react";

import {
  INVOICE_GENERATION_LIMITS,
  type InvoiceWordmarkSettings,
  type InvoiceWordmarkStyle,
} from "@/lib/invoice-generation-types";

/**
 * ReceivAI UAE — editable, text-only company wordmark.
 *
 * - No images, uploaded logos, SVGs or external font requests.
 * - Uses the same wordmark settings as the backend PDF renderer.
 * - The parent owns the settings and the seller/company name.
 * - The component does not persist data or call an API.
 */

export interface InvoiceTextWordmarkProps {
  /** Usually form.seller.name. Not modified by this component. */
  companyName: string | null | undefined;

  settings: InvoiceWordmarkSettings;

  onChange?: (settings: InvoiceWordmarkSettings) => void;

  /** Hide all controls when used in InvoiceLivePreview. */
  showControls?: boolean;

  disabled?: boolean;

  /** Remove the preview frame when embedded in another component. */
  compact?: boolean;
}

// ============================================================
// 1. CONFIGURATION
// ============================================================

const DEFAULT_ACCENT = "#2463D4";

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

const MIN_SIZE =
  INVOICE_GENERATION_LIMITS.minWordmarkFontSizePt;

const MAX_SIZE =
  INVOICE_GENERATION_LIMITS.maxWordmarkFontSizePt;

const COLOR_PRESETS = [
  { name: "ReceivAI blue", hex: "#2463D4" },
  { name: "Teal", hex: "#087F7B" },
  { name: "Navy", hex: "#163252" },
  { name: "Purple", hex: "#7048C8" },
  { name: "Charcoal", hex: "#273447" },
] as const;

const STYLE_CHOICES: Array<{
  value: InvoiceWordmarkStyle;
  title: string;
  description: string;
}> = [
  {
    value: "modern",
    title: "Modern",
    description: "Bold, clean sans serif",
  },
  {
    value: "classic",
    title: "Classic",
    description: "Traditional serif lettering",
  },
  {
    value: "minimal",
    title: "Minimal",
    description: "Understated, spacious text",
  },
];

// ============================================================
// 2. STYLES
// ============================================================

const panelStyle: CSSProperties = {
  background: "#ffffff",
  border: "1px solid #e1eaf2",
  borderRadius: 18,
  boxShadow: "0 5px 20px rgba(24,54,84,0.045)",
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
// 3. HELPERS
// ============================================================

function safeAccent(value: string): string {
  return HEX_COLOR.test(value)
    ? value
    : DEFAULT_ACCENT;
}

function safeSize(value: number): number {
  if (!Number.isFinite(value)) {
    return 24;
  }

  return Math.min(
    MAX_SIZE,
    Math.max(
      MIN_SIZE,
      Math.round(value),
    ),
  );
}

function fontForStyle(
  style: InvoiceWordmarkStyle,
): string {
  if (style === "classic") {
    return 'Georgia, "Times New Roman", Times, serif';
  }

  return 'Arial, "Helvetica Neue", Helvetica, sans-serif';
}

// ============================================================
// 4. COMPONENT
// ============================================================

export default function InvoiceTextWordmark({
  companyName,
  settings,
  onChange,
  showControls,
  disabled = false,
  compact = false,
}: InvoiceTextWordmarkProps) {
  const prefix = useId().replace(/:/g, "");

  const canEdit =
    typeof onChange === "function" && !disabled;

  const displayControls =
    showControls ?? typeof onChange === "function";

  const brandName =
    companyName?.trim() || "Company Name";

  const color = safeAccent(
    settings.accent_color,
  );

  const fontSize = safeSize(
    settings.font_size_pt,
  );

  const subtitle = settings.subtitle ?? "";

  // ----------------------------------------------------------
  // UPDATE PARENT SETTINGS
  // ----------------------------------------------------------

  function update(
    patch: Partial<InvoiceWordmarkSettings>,
  ) {
    if (!canEdit || !onChange) {
      return;
    }

    onChange({
      ...settings,
      ...patch,
    });
  }

  // ----------------------------------------------------------
  // TEXT LOGO PRESENTATION
  // ----------------------------------------------------------

  const wordmarkStyle: CSSProperties = {
    color,

    fontFamily: fontForStyle(
      settings.style,
    ),

    fontSize: `${fontSize}pt`,

    fontWeight:
      settings.style === "minimal"
        ? 600
        : 700,

    lineHeight: 1.2,

    letterSpacing:
      settings.style === "minimal"
        ? "0.045em"
        : settings.style === "modern"
          ? "0.012em"
          : "0",

    textTransform:
      settings.uppercase
        ? "uppercase"
        : "none",

    overflowWrap: "anywhere",

    margin: 0,
  };

  // ==========================================================
  // 5. LIVE TEXT LOGO PREVIEW
  // ==========================================================

  const content = (
    <div
      className={
        compact ? "" : "p-3 p-md-4"
      }
      style={
        compact
          ? undefined
          : {
              background: "#fbfdff",
              border: "1px solid #dce5ef",
              borderRadius: 12,
              minHeight: 142,
            }
      }
      aria-label="Text-based company wordmark preview"
    >
      {/* The company name remains real, selectable text. */}

      <div style={wordmarkStyle}>
        {brandName}
      </div>

      {/* OPTIONAL ACCENT LINE */}

      {settings.show_accent_line && (
        <div
          aria-hidden="true"
          style={{
            width: 64,
            height: 3,

            backgroundColor: color,

            borderRadius: 10,

            marginTop: 9,

            marginBottom:
              subtitle.trim()
                ? 9
                : 0,
          }}
        />
      )}

      {/* OPTIONAL SUBTITLE */}

      {subtitle.trim() && (
        <div
          style={{
            color: "#425166",

            fontFamily: fontForStyle(
              settings.style,
            ),

            fontSize: 11,

            fontWeight: 500,

            lineHeight: 1.5,

            overflowWrap: "anywhere",

            marginTop:
              settings.show_accent_line
                ? 0
                : 8,
          }}
        >
          {subtitle}
        </div>
      )}
    </div>
  );

  // ----------------------------------------------------------
  // PREVIEW-ONLY MODE
  // ----------------------------------------------------------

  if (!displayControls) {
    return content;
  }

  // ==========================================================
  // 6. SETTINGS EDITOR
  // ==========================================================

  return (
    <section
      className="p-3 p-md-4"
      style={panelStyle}
      aria-labelledby={`${prefix}-heading`}
    >
      {/* HEADER */}

      <div className="d-flex flex-wrap align-items-start justify-content-between gap-2 mb-3">
        <div>
          <h2
            className="h5 fw-bold mb-1"
            id={`${prefix}-heading`}
            style={{
              color: "#142b45",
            }}
          >
            Company text logo
          </h2>

          <p
            className="mb-0"
            style={mutedStyle}
          >
            Customize the company name as a text-only wordmark.
            No logo upload is needed.
          </p>
        </div>

        <span className="badge bg-light text-secondary border rounded-pill px-3 py-2">
          Text only
        </span>
      </div>

      {/* LIVE PREVIEW */}

      <div className="mb-4">
        {content}
      </div>

      {!companyName?.trim() && (
        <p
          className="mb-3"
          style={mutedStyle}
          role="status"
        >
          Enter the seller company name in Company Details
          to replace the preview placeholder.
        </p>
      )}

      <fieldset
        disabled={!canEdit}
        className="border-0 p-0 m-0"
      >
        <legend className="visually-hidden">
          Company wordmark settings
        </legend>

        {/* ==================================================
            STYLE SELECTION
        ================================================== */}

        <div className="mb-4">
          <div
            className="mb-2"
            style={labelStyle}
          >
            Wordmark style
          </div>

          <div
            className="row g-2"
            role="group"
            aria-label="Wordmark style"
          >
            {STYLE_CHOICES.map(
              (choice) => {
                const selected =
                  settings.style === choice.value;

                return (
                  <div
                    key={choice.value}
                    className="col-12 col-sm-4"
                  >
                    <button
                      type="button"
                      className="w-100 text-start p-3 h-100"
                      aria-pressed={selected}
                      onClick={() =>
                        update({
                          style: choice.value,
                        })
                      }
                      disabled={!canEdit}
                      style={{
                        border: selected
                          ? "1px solid #087f7b"
                          : "1px solid #dce5ef",

                        background: selected
                          ? "#ecf8f6"
                          : "#fff",

                        borderRadius: 12,

                        color: "#203551",

                        cursor: canEdit
                          ? "pointer"
                          : "not-allowed",
                      }}
                    >
                      <span
                        className="d-block fw-semibold mb-1"
                        style={{
                          fontSize: 14,

                          fontFamily:
                            fontForStyle(
                              choice.value,
                            ),
                        }}
                      >
                        {choice.title}
                      </span>

                      <span
                        className="d-block"
                        style={mutedStyle}
                      >
                        {choice.description}
                      </span>

                      {selected && (
                        <span
                          className="d-block mt-2 fw-semibold"
                          style={{
                            color: "#087f7b",
                            fontSize: 12,
                          }}
                        >
                          <i
                            className="bi bi-check-circle-fill me-1"
                            aria-hidden="true"
                          />
                          Selected
                        </span>
                      )}
                    </button>
                  </div>
                );
              },
            )}
          </div>
        </div>

        {/* ==================================================
            ACCENT COLOR
        ================================================== */}

        <div className="mb-4">
          <label
            htmlFor={`${prefix}-accent`}
            className="form-label mb-2"
            style={labelStyle}
          >
            Company accent color
          </label>

          <div className="d-flex flex-wrap gap-2 align-items-center">
            <input
              id={`${prefix}-accent`}
              type="color"
              className="form-control form-control-color"
              value={color}
              onChange={(event) =>
                update({
                  accent_color:
                    event.target.value.toUpperCase(),
                })
              }
              disabled={!canEdit}
              title="Choose a custom accent color"
              aria-label="Choose wordmark accent color"
            />

            <output
              htmlFor={`${prefix}-accent`}
              className="font-monospace small"
              style={{
                color: "#425166",
              }}
            >
              {color.toUpperCase()}
            </output>

            {/* PREDEFINED COLOR PRESETS */}

            <div className="d-flex flex-wrap align-items-center gap-2 ms-sm-2">
              {COLOR_PRESETS.map(
                (preset) => (
                  <button
                    key={preset.hex}
                    type="button"
                    title={preset.name}
                    aria-label={`Use ${preset.name} accent color`}
                    aria-pressed={
                      color.toLowerCase() ===
                      preset.hex.toLowerCase()
                    }
                    disabled={!canEdit}
                    onClick={() =>
                      update({
                        accent_color: preset.hex,
                      })
                    }
                    style={{
                      width: 26,
                      height: 26,

                      borderRadius: "50%",

                      border:
                        color.toLowerCase() ===
                        preset.hex.toLowerCase()
                          ? "3px solid #cad8e6"
                          : "1px solid #cad8e6",

                      backgroundColor:
                        preset.hex,

                      outlineOffset: 2,

                      cursor: canEdit
                        ? "pointer"
                        : "not-allowed",
                    }}
                  />
                ),
              )}
            </div>
          </div>
        </div>

        {/* ==================================================
            FONT SIZE
        ================================================== */}

        <div className="mb-4">
          <label
            htmlFor={`${prefix}-size`}
            className="form-label d-flex justify-content-between gap-2"
            style={labelStyle}
          >
            <span>
              Wordmark font size
            </span>

            <span>
              {fontSize} pt
            </span>
          </label>

          <input
            id={`${prefix}-size`}
            className="form-range"
            type="range"
            min={MIN_SIZE}
            max={MAX_SIZE}
            step={1}
            value={fontSize}
            onChange={(event) =>
              update({
                font_size_pt: safeSize(
                  Number(
                    event.target.value,
                  ),
                ),
              })
            }
            disabled={!canEdit}
          />

          <div
            className="d-flex justify-content-between"
            style={mutedStyle}
          >
            <span>
              {MIN_SIZE} pt
            </span>

            <span>
              {MAX_SIZE} pt
            </span>
          </div>
        </div>

        {/* ==================================================
            SUBTITLE / TAGLINE
        ================================================== */}

        <div className="mb-4">
          <label
            className="form-label mb-1"
            htmlFor={`${prefix}-subtitle`}
            style={labelStyle}
          >
            Subtitle or tagline (optional)
          </label>

          <input
            id={`${prefix}-subtitle`}
            className="form-control"
            type="text"
            maxLength={120}
            placeholder="e.g. Business and technology services"
            value={subtitle}
            onChange={(event) =>
              update({
                subtitle:
                  event.target.value || null,
              })
            }
            disabled={!canEdit}
          />

          <div
            className="text-end mt-1"
            style={mutedStyle}
          >
            {subtitle.length}/120 characters
          </div>
        </div>

        {/* ==================================================
            OTHER APPEARANCE OPTIONS
        ================================================== */}

        <div className="d-flex flex-wrap gap-4">
          {/* UPPERCASE */}

          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              role="switch"
              id={`${prefix}-uppercase`}
              checked={settings.uppercase}
              onChange={(event) =>
                update({
                  uppercase:
                    event.target.checked,
                })
              }
              disabled={!canEdit}
            />

            <label
              className="form-check-label"
              htmlFor={`${prefix}-uppercase`}
              style={{
                color: "#425166",
                fontSize: 13,
              }}
            >
              Uppercase company name
            </label>
          </div>

          {/* ACCENT LINE */}

          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              role="switch"
              id={`${prefix}-line`}
              checked={
                settings.show_accent_line
              }
              onChange={(event) =>
                update({
                  show_accent_line:
                    event.target.checked,
                })
              }
              disabled={!canEdit}
            />

            <label
              className="form-check-label"
              htmlFor={`${prefix}-line`}
              style={{
                color: "#425166",
                fontSize: 13,
              }}
            >
              Show accent line
            </label>
          </div>
        </div>
      </fieldset>

      {/* FOOTER NOTE */}

      <p
        className="mt-4 mb-0"
        style={mutedStyle}
      >
        The company name comes from Seller Details.
        Appearance settings are saved with the invoice
        draft and used by the PDF renderer. Screen fonts
        may differ slightly from the exported PDF.
      </p>
    </section>
  );
}
