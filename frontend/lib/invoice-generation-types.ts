
/**
 * ReceivAI UAE — Generate Invoice API contracts and form defaults.
 *
 * Mirrors backend/app/schemas/invoice_generation.py (Pydantic v2).
 * This file contains no API calls, React components, or monetary calculations.
 *
 * IMPORTANT: Represent decimal quantities, prices and VAT as strings.
 * Never convert invoice money into JavaScript floating-point numbers when
 * preparing API payloads. The backend validates and calculates final totals.
 */

// ============================================================
// 1. COMMON TYPES
// ============================================================

/** Decimal serialized as a JSON string, for example "1250.00" or "5.00". */
export type DecimalString = string;

/** Local calendar date in YYYY-MM-DD format, or null for an incomplete draft. */
export type InvoiceDateString = string;

/** ISO 8601 date-time returned by FastAPI, including its timezone if supplied. */
export type InvoiceDateTimeString = string;

export type InvoiceDocumentType =
  | "tax_invoice"
  | "invoice"
  | "proforma_invoice";

export type InvoiceDraftStatus = "draft" | "finalized" | "cancelled";

export type InvoiceWordmarkStyle = "modern" | "classic" | "minimal";

export type InvoiceCurrency = "AED";

export type InvoiceFinalStatus = "unpaid" | "overdue";

export type InvoiceDraftListStatus = InvoiceDraftStatus | "all";

// ============================================================
// 2. SELLER / BUYER AND INVOICE HEADER
// ============================================================

export interface InvoicePartyInput {
  name: string | null;
  address: string | null;
  emirate: string | null;
  country: string | null;
  trn: string | null;
  email: string | null;
  phone: string | null;
  contact_person: string | null;
}

export interface InvoiceHeaderInput {
  document_type: InvoiceDocumentType;

  /** Leave null to allocate a number automatically on finalization. */
  invoice_number: string | null;

  issue_date: InvoiceDateString | null;
  supply_date: InvoiceDateString | null;
  due_date: InvoiceDateString | null;

  payment_terms: string | null;
  place_of_supply: string | null;
  purchase_order_number: string | null;
  reference_number: string | null;

  currency: InvoiceCurrency;
}

// ============================================================
// 3. TEXT-ONLY COMPANY WORDMARK AND CUSTOM FIELDS
// ============================================================

export interface InvoiceWordmarkSettings {
  style: InvoiceWordmarkStyle;

  /** Six-digit hex color, for example #2463D4. */
  accent_color: string;

  /** Backend range: 14–40 pt. */
  font_size_pt: number;

  uppercase: boolean;
  subtitle: string | null;
  show_accent_line: boolean;
}

export interface InvoiceCustomField {
  label: string;
  value: string;
  show_on_pdf: boolean;
  sort_order: number;
}

export interface InvoiceCustomColumn {
  /** Lowercase identifier matching ^[a-z][a-z0-9_]{0,39}$. */
  key: string;

  label: string;
  show_on_pdf: boolean;
  sort_order: number;
}

// ============================================================
// 4. INVOICE LINE ITEMS AND BANK DETAILS
// ============================================================

export interface InvoiceLineItemInput {
  /** Stable frontend identifier; optional in the backend. */
  client_id: string | null;

  description: string | null;

  /** Decimal string, up to three decimal places, or null in a draft. */
  quantity: DecimalString | null;

  unit: string | null;

  /** Tax-exclusive AED unit price. */
  unit_price_aed: DecimalString | null;

  /** Fixed AED discount, not a percentage. */
  discount_aed: DecimalString;

  /** Explicit percentage such as "5.00" or "0.00". */
  vat_rate: DecimalString | null;

  sort_order: number;

  /** Keys must correspond to declared custom_columns. */
  custom_values: Record<string, string>;

  custom_fields: InvoiceCustomField[];
}

export interface InvoiceBankDetails {
  account_name: string | null;
  bank_name: string | null;
  iban: string | null;
  swift_code: string | null;
  payment_instructions: string | null;
}

// ============================================================
// 5. API REQUEST PAYLOADS
// ============================================================

/** Core editable form. Used by /validate and in-memory PDF previews. */
export interface InvoiceGenerationInput {
  seller: InvoicePartyInput;
  buyer: InvoicePartyInput;
  invoice: InvoiceHeaderInput;

  items: InvoiceLineItemInput[];

  wordmark: InvoiceWordmarkSettings;

  custom_columns: InvoiceCustomColumn[];
  custom_fields: InvoiceCustomField[];

  bank_details: InvoiceBankDetails;

  notes: string | null;
  declaration_text: string | null;
  footer_text: string | null;
}

/** POST /api/invoice-generation/drafts */
export interface InvoiceDraftCreate extends InvoiceGenerationInput {
  draft_title: string | null;
}

/** PUT /api/invoice-generation/drafts/{draft_id} */
export interface InvoiceDraftUpdate extends InvoiceDraftCreate {
  /** Current draft.version; server rejects stale writes with HTTP 409. */
  expected_version: number;
}

/** POST /api/invoice-generation/preview */
export interface InvoicePreviewRequest extends InvoiceGenerationInput {
  watermark: "DRAFT";
}

/** POST /api/invoice-generation/drafts/{draft_id}/finalize */
export interface InvoiceFinalizeRequest {
  expected_version: number;

  /** Unique per finalization attempt: 16–128 characters. Reuse on retries. */
  idempotency_key: string;
}

// ============================================================
// 6. BACKEND-CALCULATED FINANCIAL RESPONSES
// ============================================================

/** Read-only values calculated by the backend, never trusted as form input. */
export interface InvoiceLineCalculation {
  description: string;

  gross_value_aed: DecimalString | null;
  discount_aed: DecimalString | null;
  taxable_value_aed: DecimalString | null;
  vat_amount_aed: DecimalString | null;
  line_total_aed: DecimalString | null;
}

export interface InvoiceFinancialSummary {
  currency: InvoiceCurrency;

  subtotal_aed: DecimalString | null;
  discount_aed: DecimalString | null;
  vat_amount_aed: DecimalString | null;
  total_amount_aed: DecimalString | null;

  line_items: InvoiceLineCalculation[];
}

/** POST /api/invoice-generation/validate or /drafts/{id}/validate */
export interface InvoiceGenerationValidationResponse {
  is_valid: boolean;

  errors: string[];
  warnings: string[];

  calculated: InvoiceFinancialSummary | null;
}

// ============================================================
// 7. DRAFT AND FINALIZATION RESPONSES
// ============================================================

export interface InvoiceDraftResponse {
  id: number;
  version: number;

  status: InvoiceDraftStatus;

  data: InvoiceGenerationInput;

  draft_title: string | null;
  finalized_invoice_id: number | null;

  created_at: InvoiceDateTimeString;
  updated_at: InvoiceDateTimeString;
}

/** GET /api/invoice-generation/drafts */
export interface InvoiceDraftListResponse {
  drafts: InvoiceDraftResponse[];
  total: number;
}

/** POST /api/invoice-generation/drafts/{draft_id}/finalize */
export interface InvoiceGenerationResponse {
  invoice_id: number;
  draft_id: number;
  invoice_number: string;

  amount_aed: DecimalString;

  status: InvoiceFinalStatus;

  source_type: "manual";
  review_status: "reviewed";

  pdf_available: boolean;
  message: string;
}

// ============================================================
// 8. FRONTEND DEFAULTS
// ============================================================

/** Keep frontend editor limits aligned with Pydantic constraints. */
export const INVOICE_GENERATION_LIMITS = {
  maxItems: 300,
  maxCustomColumns: 10,
  maxCustomFields: 20,
  maxWordmarkFontSizePt: 40,
  minWordmarkFontSizePt: 14,
} as const;

export const DEFAULT_INVOICE_WORDMARK: Readonly<InvoiceWordmarkSettings> = {
  style: "modern",
  accent_color: "#2463D4",
  font_size_pt: 24,
  uppercase: true,
  subtitle: null,
  show_accent_line: true,
};

// ============================================================
// 9. CREATE EMPTY COMPANY / CUSTOMER DETAILS
// ============================================================

export function createEmptyInvoiceParty(): InvoicePartyInput {
  return {
    name: null,
    address: null,
    emirate: null,
    country: null,
    trn: null,
    email: null,
    phone: null,
    contact_person: null,
  };
}

// ============================================================
// 10. CREATE EMPTY INVOICE ITEM
// ============================================================

export function createEmptyInvoiceLineItem(
  sortOrder = 0,
  clientId: string | null = null,
): InvoiceLineItemInput {
  return {
    client_id: clientId,
    description: null,

    quantity: "1",
    unit: null,

    unit_price_aed: null,
    discount_aed: "0.00",
    vat_rate: null,

    sort_order: sortOrder,

    custom_values: {},
    custom_fields: [],
  };
}

// ============================================================
// 11. CREATE DEFAULT INVOICE FORM
// ============================================================

export function createEmptyInvoiceForm(): InvoiceGenerationInput {
  return {
    // Seller company details
    seller: createEmptyInvoiceParty(),

    // Customer details
    buyer: createEmptyInvoiceParty(),

    // Invoice information
    invoice: {
      document_type: "tax_invoice",

      // Generated by backend when finalizing
      invoice_number: null,

      issue_date: null,
      supply_date: null,
      due_date: null,

      payment_terms: null,
      place_of_supply: null,

      purchase_order_number: null,
      reference_number: null,

      currency: "AED",
    },

    // First blank line item
    items: [
      createEmptyInvoiceLineItem(),
    ],

    // Text-based company wordmark
    wordmark: {
      ...DEFAULT_INVOICE_WORDMARK,
    },

    // Additional invoice fields
    custom_columns: [],
    custom_fields: [],

    // Bank information
    bank_details: {
      account_name: null,
      bank_name: null,
      iban: null,
      swift_code: null,
      payment_instructions: null,
    },

    // Additional information
    notes: null,
    declaration_text: null,
    footer_text: null,
  };
}

// ============================================================
// 12. CREATE DEFAULT INVOICE DRAFT
// ============================================================

export function createEmptyInvoiceDraft(): InvoiceDraftCreate {
  return {
    ...createEmptyInvoiceForm(),
    draft_title: null,
  };
}

// ============================================================
// 13. PREPARE PDF PREVIEW REQUEST
// ============================================================

/** Explicitly add the required DRAFT watermark for the preview endpoint. */
export function toInvoicePreviewRequest(
  form: InvoiceGenerationInput,
): InvoicePreviewRequest {
  return {
    ...form,
    watermark: "DRAFT",
  };
}
