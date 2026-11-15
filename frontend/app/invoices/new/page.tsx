"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import AuthenticatedPage from "@/components/documents/AuthenticatedPage";
import InvoiceGenerationForm from "@/components/invoices/InvoiceGenerationForm";
import WorkspaceSidebar from "@/components/WorkspaceSidebar";
import { clearToken } from "@/lib/api";

function GenerateInvoiceWorkspace() {
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.replace("/");
  }

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
              <span className="document-brand-mark">R</span>
              <span>
                <strong>ReceivAI UAE</strong>
                <small>Finance Operations · Invoice Generation</small>
              </span>
            </Link>

            <nav className="d-flex flex-wrap gap-2">
              <Link
                href="/?view=Invoice%20Management"
                className="btn btn-outline-secondary btn-sm"
              >
                Invoice Register
              </Link>

              <Link
                href="/"
                className="btn btn-light btn-sm"
              >
                Dashboard
              </Link>

              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={handleLogout}
              >
                Sign Out
              </button>
            </nav>
          </header>

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
