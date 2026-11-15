
"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import AuthenticatedPage from "@/components/documents/AuthenticatedPage";
import DocumentDetails from "@/components/documents/DocumentDetails";
import DocumentStatusBadge from "@/components/documents/DocumentStatusBadge";
import InvoiceReview from "@/components/documents/InvoiceReview";
import WorkspaceSidebar from "@/components/WorkspaceSidebar";

import {
  DocumentDetails as DocumentDetailsRecord,
  clearToken,
  getDocument,
  processDocument,
  retryDocument,
} from "@/lib/api";

function DocumentDetailWorkspace() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const documentId = Number(params.id);
  const validDocumentId =
    /^\d+$/.test(params.id ?? "") &&
    Number.isSafeInteger(documentId) &&
    documentId > 0;

  const [document, setDocument] =
    useState<DocumentDetailsRecord | null>(null);

  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  // Load the document from the backend API.
  const refresh = useCallback(async () => {
    if (!validDocumentId) {
      setDocument(null);
      setLoading(false);
      setError("Document ID is invalid.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const result = await getDocument(documentId);
      setDocument(result);
    } catch (reason) {
      setDocument(null);

      setError(
        reason instanceof Error
          ? reason.message
          : "Could not load this document."
      );
    } finally {
      setLoading(false);
    }
  }, [documentId, validDocumentId]);

  // Reload the document whenever its route ID changes.
  useEffect(() => {
    let active = true;

    async function loadDocument() {
      if (!validDocumentId) {
        if (active) {
          setDocument(null);
          setLoading(false);
          setError("Document ID is invalid.");
        }
        return;
      }

      setLoading(true);
      setDocument(null);
      setError("");

      try {
        const result = await getDocument(documentId);

        if (active) {
          setDocument(result);
        }
      } catch (reason) {
        if (active) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load this document."
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadDocument();

    return () => {
      active = false;
    };
  }, [documentId, validDocumentId]);

  // Process a newly uploaded document or retry failed processing.
  async function process() {
    if (!document || working) {
      return;
    }

    if (
      document.processing_status !== "uploaded" &&
      document.processing_status !== "processing_failed"
    ) {
      return;
    }

    setWorking(true);
    setError("");

    try {
      const result =
        document.processing_status === "uploaded"
          ? await processDocument(document.id)
          : await retryDocument(document.id);

      setDocument(result.document);
    } catch (reason) {
      const message =
        reason instanceof Error
          ? reason.message
          : "Document processing failed.";

      // Reload the latest backend status after a failed operation.
      await refresh();

      setError(message);
    } finally {
      setWorking(false);
    }
  }

  // Logout and redirect to the login page.
  function logout() {
    clearToken();
    router.replace("/");
  }

  const isProcessingAvailable =
    document?.processing_status === "uploaded" ||
    document?.processing_status === "processing_failed";

  const isPendingReview =
    document?.processing_status === "pending_review";

  const isApproved =
    document?.processing_status === "approved";

  return (
    <div className="app-shell">
      <WorkspaceSidebar
        activeView="Document Intelligence"
        onLogout={logout}
      />

      <div className="main-area">
        <main className="document-workspace">
          {/* Document navigation header */}
          <header className="document-topbar">
            <Link
              className="document-brand"
              href="/documents"
            >
              <span className="document-brand-mark">
                R
              </span>

              <span>
                <strong>ReceivAI UAE</strong>
                <small>Document Intelligence</small>
              </span>
            </Link>

            <div className="d-flex align-items-center gap-2">
              {document && (
                <DocumentStatusBadge
                  status={document.processing_status}
                />
              )}

              <button
                className="btn btn-light btn-sm"
                type="button"
                onClick={() => router.push("/documents")}
              >
                <i className="bi bi-arrow-left me-2" />
                All documents
              </button>
            </div>
          </header>

          {/* Main document content */}
          <div className="document-page-container">
            {!validDocumentId ? (
              <div
                className="alert alert-danger"
                role="alert"
              >
                Document ID is invalid.
              </div>
            ) : loading ? (
              <div className="document-loading">
                <span className="spinner-border spinner-border-sm me-2" />
                Loading document…
              </div>
            ) : error && !document ? (
              <div
                className="alert alert-danger"
                role="alert"
              >
                {error}

                <button
                  type="button"
                  className="btn btn-sm btn-outline-danger ms-3"
                  onClick={() => void refresh()}
                >
                  Retry
                </button>
              </div>
            ) : document ? (
              <>
                {/* Display API errors without hiding the document */}
                {error && (
                  <div
                    className="alert alert-danger py-2"
                    role="alert"
                  >
                    {error}
                  </div>
                )}

                {/* Document processing actions */}
                {isProcessingAvailable && (
                  <div className="document-card mb-3 d-flex flex-wrap justify-content-between align-items-center gap-3">
                    <div>
                      <h1 className="document-page-title mb-1">
                        {document.processing_status === "uploaded"
                          ? "Process uploaded document"
                          : "Retry document processing"}
                      </h1>

                      <div className="small text-secondary">
                        Processing retains this document
                        record and its private source file.
                      </div>
                    </div>

                    <button
                      className="btn btn-primary"
                      type="button"
                      onClick={() => void process()}
                      disabled={working}
                    >
                      {working ? (
                        <>
                          <span className="spinner-border spinner-border-sm me-2" />
                          Processing…
                        </>
                      ) : (
                        <>
                          <i className="bi bi-play-fill me-2" />
                          {document.processing_status === "uploaded"
                            ? "Process document"
                            : "Retry processing"}
                        </>
                      )}
                    </button>
                  </div>
                )}

                {/* Administrator invoice review */}
                {isPendingReview ? (
                  <InvoiceReview
                    key={document.id}
                    document={document}
                    onUpdated={setDocument}
                  />
                ) : (
                  <div className="row g-3">
                    <div className="col-12 col-xl-8">
                      <div className="document-card">
                        <h1 className="document-page-title text-break">
                          {document.original_filename}
                        </h1>

                        <p className="text-secondary">
                          Document #{document.id} ·{" "}
                          {document.processing_status.replaceAll(
                            "_",
                            " "
                          )}
                        </p>

                        {/* Approved invoice details link */}
                        {isApproved &&
                          document.invoice_id != null && (
                            <Link
                              className="btn btn-success"
                              href={`/invoices/${document.invoice_id}`}
                            >
                              <i className="bi bi-receipt me-2" />
                              View approved invoice
                            </Link>
                          )}
                      </div>
                    </div>

                    <div className="col-12 col-xl-4">
                      <DocumentDetails document={document} />
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div
                className="alert alert-warning"
                role="alert"
              >
                No document information is available.
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

export default function DocumentDetailsPage() {
  return (
    <AuthenticatedPage>
      <DocumentDetailWorkspace />
    </AuthenticatedPage>
  );
}
