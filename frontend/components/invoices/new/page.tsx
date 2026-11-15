
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import AuthenticatedPage from "@/components/documents/AuthenticatedPage";
import InvoiceGenerationForm from "@/components/invoices/InvoiceGenerationForm";
import WorkspaceSidebar from "@/components/WorkspaceSidebar";
import { clearToken } from "@/lib/api";

function GenerateInvoiceWorkspace() {
  const router = useRouter();

  const handleLogout = () => {
    clearToken();
    router.replace("/");
  };

  return (
    <div className="app-shell">
      <WorkspaceSidebar
        activeView="Invoice Management"
        onLogout={handleLogout}
      />

      <div className="main-area">
        <main
          className="document-workspace"
          style={{
            minHeight: "100vh",
            backgroundColor: "#f5f8fc",
          }}
        >
          <header className="document-topbar">
            <Link className="document-brand" href="/">
              <span
                className="document-brand-mark"
                aria-hidden="true"
              >
                R
              </span>

              <span>
                <strong>ReceivAI UAE</strong>
                <small>
                  Finance Operations · Invoice Generation
                </small>
              </span>
            </Link>

            <nav className="d-flex flex-wrap gap-2">
              <Link
                href="/?view=Invoice%20Management"
                className="btn btn-outline-secondary btn-sm"
              >
                <i className="bi bi-receipt me-2" />
                Invoice Register
              </Link>

              <Link
                href="/"
                className="btn btn-light btn-sm"
              >
                <i className="bi bi-grid me-2" />
                Dashboard
              </Link>

              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={handleLogout}
              >
                <i className="bi bi-box-arrow-right me-2" />
                Sign Out
              </button>
            </nav>
          </header>

          {/* Complete invoice generation interface */}
          <InvoiceGenerationForm />
        </main>
      </div>
    </div>
  );
}

export default function NewInvoicePage() {
  return (
    <AuthenticatedPage>
      <GenerateInvoiceWorkspace />
    </AuthenticatedPage>
  );
}
