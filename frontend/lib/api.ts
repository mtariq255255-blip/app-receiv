
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

const TOKEN_KEY = "receivai_token";

// ============================================================
// DOCUMENT STATUS
// ============================================================

export type DocumentProcessingStatus =
  | "uploaded"
  | "processing"
  | "processing_failed"
  | "pending_review"
  | "approved"
  | "rejected"
  | (string & {});

// ============================================================
// SHARED FINANCIAL TYPES
// ============================================================

export type InvoiceAmount = string | number | null;

export type InvoiceFieldEvidence = {
  source_text?: string | null;
  source_page?: number | null;
  bbox?: unknown;
  extraction_method?: string | null;
  confidence?: number | null;
  [key: string]: unknown;
};

// ============================================================
// LEGACY AED ACCOUNTING ITEMS
// ============================================================

export type UAEInvoiceItem = {
  description?: string | null;
  quantity?: InvoiceAmount;
  unit?: string | null;
  unit_price_aed?: InvoiceAmount;
  discount_aed?: InvoiceAmount;
  taxable_value_aed?: InvoiceAmount;
  vat_rate?: InvoiceAmount;
  vat_amount_aed?: InvoiceAmount;
  line_total_aed?: InvoiceAmount;
};

// ============================================================
// ORIGINAL-CURRENCY SOURCE ITEMS
// These are extracted values, not approved accounting entries.
// ============================================================

export type SourceInvoiceItem = {
  description?: string | null;
  quantity?: InvoiceAmount;
  unit?: string | null;
  unit_price?: InvoiceAmount;
  line_amount?: InvoiceAmount;
  currency?: string | null;

  container?: string | null;
  other_quantity_text?: string | null;

  discount?: InvoiceAmount;
  taxable_value?: InvoiceAmount;
  tax_rate_text?: string | null;

  source_page?: number | null;
  source_table?: number | string | null;
  source_rows?: unknown;
  source_representation?: string | null;
  source_bbox?: unknown;
  evidence?: unknown;

  [key: string]: unknown;
};

// ============================================================
// STRUCTURED UAE INVOICE
// Both AED accounting values and original source-currency
// evidence are represented separately.
// ============================================================

export type UAEInvoice = {
  // Invoice identity
  invoice_number?: string | null;
  invoice_type?: string | null;
  document_type?: string | null;

  // Supplier
  supplier_name?: string | null;
  supplier_address?: string | null;
  supplier_emirate?: string | null;
  supplier_trn?: string | null;

  // Customer
  customer_name?: string | null;
  customer_address?: string | null;
  customer_emirate?: string | null;
  customer_email?: string | null;
  customer_trn?: string | null;

  // Dates and currency
  issue_date?: string | null;
  supply_date?: string | null;
  due_date?: string | null;
  place_of_supply?: string | null;
  currency?: string | null;

  // Legacy AED accounting items
  items?: UAEInvoiceItem[];

  // AED accounting amounts
  subtotal_aed?: InvoiceAmount;
  subtotal_before_discount_aed?: InvoiceAmount;
  discount_aed?: InvoiceAmount;
  vat_amount_aed?: InvoiceAmount;
  total_amount_aed?: InvoiceAmount;
  amount_aed?: InvoiceAmount;

  // Original-currency extracted items
  source_items?: SourceInvoiceItem[];

  // Original-currency financial values
  source_subtotal?: InvoiceAmount;
  source_subtotal_before_discount?: InvoiceAmount;
  source_discount?: InvoiceAmount;
  source_tax_amount?: InvoiceAmount;
  source_total_amount?: InvoiceAmount;

  // Source financial reconciliation
  source_totals_reconciled?: boolean | null;

  // Payment and document text
  payment_terms?: string | null;
  amount_in_words?: string | null;
  declaration_text?: string | null;
  notes?: string | null;

  // Extraction and review metadata
  field_evidence?: Record<string, InvoiceFieldEvidence[]>;
  unresolved_fields?: string[];
  field_conflicts?: Record<string, unknown>;
  extraction_method?: string | null;
  parser_version?: string | null;
  extraction_confidence?: number | null;
  extraction_notes?: string[];

  manual_review_required?: boolean;
  item_comparison_status?: string | null;
  financial_status?: string | null;

  // Preserve compatibility with additional backend fields.
  [key: string]: unknown;
};

// ============================================================
// DOCLING WORKER METADATA
// ============================================================

export type DoclingEnrichment = {
  used?: boolean;
  status?: string;
  mode?: "fast" | "accurate" | string;
  primary?: boolean;

  processing_seconds?: number | null;

  unresolved_fields?: string[];
  field_conflicts?: Record<string, unknown>;

  item_comparison_status?: string | null;
  financial_status?: string | null;

  reconstructed_item_count?: number;
  requires_review?: boolean;

  [key: string]: unknown;
};

// ============================================================
// HYBRID EXTRACTION METADATA
// ============================================================

export type HybridExtraction = {
  schema_version?: string;
  currency?: string | null;
  mixed_currency?: boolean;

  items?: SourceInvoiceItem[];
  item_count?: number;

  table_count?: number;
  page_count?: number | null;

  primary_engine?: string;
  supporting_engine?: string;

  warnings?: string[];
  conflicts?: unknown[];
  field_candidates?: Record<string, unknown>;

  raw_evidence_in_response?: boolean;

  [key: string]: unknown;
};

// ============================================================
// COMPLETE STRUCTURED EXTRACTION RESULT
// ============================================================

export type StructuredExtraction = {
  invoices?: UAEInvoice[];

  processed_record_count?: number;
  source_record_count?: number;

  manual_review_required?: boolean;
  extraction_notes?: string[];

  processing_mode?: string;
  processing_reason?: string;

  parser_version?: string;

  docling_enrichment?: DoclingEnrichment;
  hybrid_extraction?: HybridExtraction;

  [key: string]: unknown;
};

// ============================================================
// DOCUMENT EXTRACTED DATA
// ============================================================

export type DocumentExtractedData = {
  file_type?: string;
  file_size?: number;

  fields?: UAEInvoice;
  structured_invoice?: UAEInvoice;
  structured_extraction?: StructuredExtraction;

  validated_invoices?: Array<
    UAEInvoice & {
      validation?: ValidationResult;
    }
  >;

  validation?: ValidationResult;
  warnings?: string[];

  confidence?: number | null;

  privacy_processing?: Record<string, unknown>;
  extraction_engine?: Record<string, unknown>;
  processing_metadata?: Record<string, unknown>;

  processing_error?: string;
  review_status?: string;

  [key: string]: unknown;
};

// ============================================================
// VALIDATION
// ============================================================

export type ValidationResult = {
  is_valid: boolean;
  review_required: boolean;
  errors: string[];
  warnings: string[];
  checks: Record<string, unknown>;
  calculated_totals: Record<
    string,
    string | number | null
  >;
};

// ============================================================
// DOCUMENT RESPONSES
// ============================================================

export type DocumentRecord = {
  id: number;
  document_id: number;
  invoice_id: number | null;

  original_filename: string;
  mime_type: string | null;
  file_type: string | null;

  processing_status: DocumentProcessingStatus;
  extraction_notes: string | null;
  uploaded_at: string | null;
};

export type DocumentDetails = DocumentRecord & {
  file_size: number | null;
  extracted_data: DocumentExtractedData | null;
};

export type DocumentListResponse = {
  documents: DocumentRecord[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type DocumentUploadResponse = {
  document_id: number;
  original_filename: string;
  file_type: string;
  file_size: number;
  status: DocumentProcessingStatus;
  uploaded_at: string | null;
  message: string;
};

export type DocumentProcessingResponse = {
  message: string;
  status: DocumentProcessingStatus;
  document: DocumentDetails;
};

export type DocumentRejectionResponse = {
  message: string;
  document_id: number;
  status: DocumentProcessingStatus;
};

export type InvoiceApprovalResponse = {
  message: string;
  invoice_id: number;
  invoice_number: string;
  review_status: string;
  status: string;
  amount_aed: string;
};

// ============================================================
// APPROVED INVOICE RECORD
// ============================================================

export type InvoiceRecord = {
  id: number;
  invoice_number: string;
  customer_name: string;
  customer_email: string | null;

  amount_aed: number | string;

  issue_date: string;
  due_date: string;

  status: string;
  source_type: string;
  review_status: string;

  notes?: string | null;
  supplier_name?: string | null;
  supplier_trn?: string | null;
};

// ============================================================
// DOCUMENT CORRECTIONS
// ============================================================

// Review requests retain the existing API contract.
// Source evidence must not be converted into AED values.
export type DocumentCorrectionPayload = UAEInvoice & {
  invoice_index: number;
};

// ============================================================
// DOCUMENT LIST QUERY
// ============================================================

export type DocumentQuery = {
  status?: DocumentProcessingStatus;
  fileType?: string;
  search?: string;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
};

// ============================================================
// AUTHENTICATION TOKEN MANAGEMENT
// ============================================================

export function getToken(): string {
  if (typeof window === "undefined") return "";

  return (
    window.localStorage.getItem(TOKEN_KEY) || ""
  );
}

export function saveToken(token: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(
      TOKEN_KEY,
      token
    );
  }
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(
      TOKEN_KEY
    );
  }
}

function notifyUnauthorized(): void {
  if (typeof window !== "undefined") {
    clearToken();

    window.dispatchEvent(
      new Event("receivai:unauthorized")
    );
  }
}

// ============================================================
// CENTRAL API REQUEST FUNCTION
// ============================================================

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = true
): Promise<T> {
  const headers = new Headers(
    options.headers || {}
  );

  const token = getToken();

  if (auth && token) {
    headers.set(
      "Authorization",
      `Bearer ${token}`
    );
  }

  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set(
      "Content-Type",
      "application/json"
    );
  }

  let response: Response;

  try {
    response = await fetch(
      `${API_BASE}${path}`,
      {
        ...options,
        headers,
        cache: "no-store",
      }
    );
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(
        `Unable to reach the ReceivAI API: ${error.message}`
      );
    }

    throw new Error(
      "Unable to reach the ReceivAI API."
    );
  }

  const body = await response
    .json()
    .catch(() => ({}));

  if (
    response.status === 401 &&
    auth
  ) {
    notifyUnauthorized();

    throw new Error(
      "Your session has expired. Please sign in again."
    );
  }

  if (!response.ok) {
    const detail = body.detail;

    if (typeof detail === "string") {
      throw new Error(detail);
    }

    if (
      typeof detail === "object" &&
      detail !== null
    ) {
      const payload = detail as {
        message?: unknown;
        errors?: unknown;
        warnings?: unknown;
      };

      const messages = Array.isArray(
        payload.errors
      )
        ? payload.errors.filter(
            (item): item is string =>
              typeof item === "string"
          )
        : [];

      const validationMessages =
        Array.isArray(detail)
          ? detail
              .map((item) => {
                if (
                  typeof item === "object" &&
                  item !== null &&
                  "msg" in item &&
                  typeof item.msg === "string"
                ) {
                  return item.msg;
                }

                return "";
              })
              .filter(Boolean)
          : [];

      const message =
        typeof payload.message === "string"
          ? payload.message
          : [
              ...messages,
              ...validationMessages,
            ].join(" ");

      if (message) {
        throw new Error(message);
      }
    }

    const statusMessages: Record<
      number,
      string
    > = {
      403:
        "You do not have permission to perform this action.",
      404:
        "The requested record could not be found.",
      409:
        "This action conflicts with the document's current workflow status.",
      413:
        "The file exceeds the maximum permitted upload size.",
      422:
        "The submitted data could not be processed. Check the invoice details.",
    };

    throw new Error(
      statusMessages[response.status] ||
        `Request failed (${response.status})`
    );
  }

  return body as T;
}

// ============================================================
// GENERIC API HELPERS
// ============================================================

export const apiGet = <T,>(
  path: string
) => request<T>(path);

export const apiPost = <T,>(
  path: string,
  body: unknown
) =>
  request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const apiPut = <T,>(
  path: string,
  body: unknown
) =>
  request<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const apiPatch = <T,>(
  path: string,
  body: unknown
) =>
  request<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const apiUpload = <T,>(
  path: string,
  file: File
) => {
  const form = new FormData();

  form.append(
    "file",
    file
  );

  return request<T>(path, {
    method: "POST",
    body: form,
  });
};

// ============================================================
// DOCUMENT UPLOAD
// ============================================================

export function uploadDocument(
  file: File
): Promise<DocumentUploadResponse> {
  return apiUpload<DocumentUploadResponse>(
    "/api/documents/upload",
    file
  );
}

// ============================================================
// DOCUMENT PROCESSING
// ============================================================

export function processDocument(
  documentId: number
): Promise<DocumentProcessingResponse> {
  return apiPost<DocumentProcessingResponse>(
    `/api/documents/${documentId}/process`,
    {}
  );
}

export function retryDocument(
  documentId: number
): Promise<DocumentProcessingResponse> {
  return apiPost<DocumentProcessingResponse>(
    `/api/documents/${documentId}/retry`,
    {}
  );
}

// ============================================================
// DOCUMENT LISTING
// ============================================================

export function getDocuments(
  query: DocumentQuery = {}
): Promise<DocumentListResponse> {
  const params = new URLSearchParams();

  if (query.status) {
    params.set(
      "status",
      query.status
    );
  }

  if (query.fileType) {
    params.set(
      "file_type",
      query.fileType
    );
  }

  if (query.search) {
    params.set(
      "search",
      query.search
    );
  }

  if (query.dateFrom) {
    params.set(
      "date_from",
      query.dateFrom
    );
  }

  if (query.dateTo) {
    params.set(
      "date_to",
      query.dateTo
    );
  }

  params.set(
    "page",
    String(query.page ?? 1)
  );

  params.set(
    "page_size",
    String(query.pageSize ?? 20)
  );

  return apiGet<DocumentListResponse>(
    `/api/documents/?${params.toString()}`
  );
}

// ============================================================
// DOCUMENT DETAILS
// ============================================================

export function getDocument(
  documentId: number
): Promise<DocumentDetails> {
  return apiGet<DocumentDetails>(
    `/api/documents/${documentId}`
  );
}

// ============================================================
// AUTHENTICATED DOCUMENT PREVIEW
// ============================================================

export async function getDocumentPreview(
  documentId: number
): Promise<Blob> {
  const headers = new Headers();

  const token = getToken();

  if (token) {
    headers.set(
      "Authorization",
      `Bearer ${token}`
    );
  }

  let response: Response;

  try {
    response = await fetch(
      `${API_BASE}/api/documents/${documentId}/preview`,
      {
        headers,
        cache: "no-store",
      }
    );
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(
        `Unable to reach the ReceivAI API: ${error.message}`
      );
    }

    throw new Error(
      "Unable to reach the ReceivAI API."
    );
  }

  if (response.status === 401) {
    notifyUnauthorized();

    throw new Error(
      "Your session has expired. Please sign in again."
    );
  }

  if (!response.ok) {
    const body = (await response
      .json()
      .catch(() => ({}))) as {
      detail?: unknown;
    };

    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Unable to load source document (${response.status}).`
    );
  }

  return response.blob();
}

// ============================================================
// DOCUMENT CORRECTIONS
// ============================================================

export function correctDocument(
  documentId: number,
  payload: DocumentCorrectionPayload
): Promise<DocumentDetails> {
  return apiPut<DocumentDetails>(
    `/api/documents/${documentId}/corrections`,
    payload
  );
}

// ============================================================
// DOCUMENT VALIDATION
// ============================================================

export function validateDocument(
  documentId: number,
  payload: DocumentCorrectionPayload
): Promise<ValidationResult> {
  return apiPost<ValidationResult>(
    `/api/documents/${documentId}/validate`,
    payload
  );
}

// ============================================================
// DOCUMENT APPROVAL
// ============================================================

export function approveDocument(
  documentId: number,
  payload: DocumentCorrectionPayload
): Promise<InvoiceApprovalResponse> {
  return apiPost<InvoiceApprovalResponse>(
    `/api/documents/${documentId}/approve`,
    payload
  );
}

// ============================================================
// DOCUMENT REJECTION
// ============================================================

export function rejectDocument(
  documentId: number,
  reason: string
): Promise<DocumentRejectionResponse> {
  return apiPost<DocumentRejectionResponse>(
    `/api/documents/${documentId}/reject`,
    { reason }
  );
}

// ============================================================
// GET APPROVED INVOICE
// ============================================================

export function getInvoice(
  invoiceId: number
): Promise<InvoiceRecord> {
  return apiGet<InvoiceRecord>(
    `/api/invoices/${invoiceId}`
  );
}

// ============================================================
// UPDATE INVOICE PAYMENT STATUS
// ============================================================

export function updateInvoiceStatus(
  invoiceId: number,
  status: "paid" | "unpaid"
): Promise<InvoiceRecord> {
  return apiPatch<InvoiceRecord>(
    `/api/invoices/${invoiceId}/status`,
    { status }
  );
}

// ============================================================
// APPROVED INVOICE CORRECTIONS
// ============================================================

export type InvoiceCorrection = {
  reason: string;
  invoice_number?: string;
  customer_name?: string;
  customer_email?: string | null;
  supplier_name?: string | null;
  supplier_trn?: string | null;
  issue_date?: string;
  due_date?: string;
  notes?: string | null;
};

export function correctApprovedInvoice(
  invoiceId: number,
  correction: InvoiceCorrection
): Promise<InvoiceRecord> {
  return apiPatch<InvoiceRecord>(
    `/api/invoices/${invoiceId}/correction`,
    correction
  );
}

// ============================================================
// LOGIN
// ============================================================

export const login = (
  email: string,
  password: string
) =>
  request<{
    access_token: string;
    token_type: string;
    expires_in: number;
    admin: {
      name?: string;
      email: string;
    };
  }>(
    "/api/auth/login",
    {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
      }),
    },
    false
  );

// ============================================================
// CURRENT ADMIN
// ============================================================

export const getCurrentAdmin = () =>
  request<{
    admin?: {
      name?: string;
      email: string;
    };
  }>("/api/auth/me");
