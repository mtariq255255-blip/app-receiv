
"use client";

import { Fragment } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

// ============================================================
// 1. WORKSPACE NAVIGATION
// ============================================================

const workspaceViews = [
  {
    name: "Overview",
    icon: "bi-grid-1x2-fill",
  },
  {
    name: "Invoice Management",
    icon: "bi-receipt-cutoff",
  },
  {
    name: "Payment Collections",
    icon: "bi-wallet2",
  },
  {
    name: "Cash Flow Forecast",
    icon: "bi-graph-up-arrow",
  },
  {
    name: "AI Finance Assistant",
    icon: "bi-robot",
  },
];

// ============================================================
// 2. COMPONENT PROPS
// ============================================================

type Props = {
  activeView: string;
  pendingCount?: number;
  onSelect?: (view: string) => void;
  onLogout?: () => void;
};

// ============================================================
// 3. MAIN SIDEBAR COMPONENT
// ============================================================

export default function WorkspaceSidebar({
  activeView,
  pendingCount = 0,
  onSelect,
  onLogout,
}: Props) {
  const pathname = usePathname();

  // ----------------------------------------------------------
  // ROUTE HELPERS
  // ----------------------------------------------------------

  const viewLink = (name: string) =>
    `/?view=${encodeURIComponent(name)}`;

  const isWorkspacePage = pathname === "/";

  const isGenerateInvoicePage =
    pathname === "/invoices/new" ||
    pathname.startsWith("/invoices/new/");

  const isInvoiceDetailPage =
    pathname.startsWith("/invoices/") &&
    !isGenerateInvoicePage;

  const isCollectionsPage =
    pathname === "/collections" ||
    pathname.startsWith("/collections/");

  const isDocumentsPage =
    pathname === "/documents" ||
    pathname.startsWith("/documents/");

  // ----------------------------------------------------------
  // WORKSPACE ACTIVE STATES
  // ----------------------------------------------------------

  const isViewActive = (name: string) => {
    // Dedicated Payment Collections page.
    if (name === "Payment Collections") {
      return (
        isCollectionsPage ||
        (isWorkspacePage &&
          activeView === "Payment Collections")
      );
    }

    // Invoice detail and invoice edit pages.
    // Generate Invoice has a separate active state.
    if (
      name === "Invoice Management" &&
      isInvoiceDetailPage
    ) {
      return true;
    }

    // Main dashboard tabs.
    return (
      isWorkspacePage &&
      activeView === name
    );
  };

  // ----------------------------------------------------------
  // MANAGEMENT ACTIVE STATES
  // ----------------------------------------------------------

  const isManagementActive = (
    name: string
  ) => {
    return (
      isWorkspacePage &&
      activeView === name
    );
  };

  // ----------------------------------------------------------
  // SHARED MANAGEMENT NAVIGATION
  // ----------------------------------------------------------

  const renderManagementView = (
    name: string,
    icon: string
  ) => {
    const active = isManagementActive(name);

    const className = `nav-view ${
      active ? "active" : ""
    }`;

    if (onSelect) {
      return (
        <button
          type="button"
          className={className}
          aria-current={
            active ? "page" : undefined
          }
          onClick={() => onSelect(name)}
        >
          <i
            className={`bi ${icon} nav-icon`}
            aria-hidden="true"
          />

          {name}
        </button>
      );
    }

    return (
      <Link
        href={viewLink(name)}
        className={className}
        aria-current={
          active ? "page" : undefined
        }
      >
        <i
          className={`bi ${icon} nav-icon`}
          aria-hidden="true"
        />

        {name}
      </Link>
    );
  };

  // ==========================================================
  // 4. SIDEBAR LAYOUT
  // ==========================================================

  return (
    <aside className="sidebar">

      {/* ====================================================
          BRAND LOGO
      ==================================================== */}

      <Link
        className="brand text-decoration-none"
        href="/"
        aria-label="ReceivAI UAE Home"
      >
        <Image
          className="brand-image"
          src="/receivai-logo.png"
          alt="ReceivAI UAE"
          width={170}
          height={80}
          priority
        />
      </Link>

      {/* ====================================================
          WORKSPACE SECTION
      ==================================================== */}

      <div className="nav-caption">
        Workspace
      </div>

      <nav aria-label="Workspace navigation">
        {workspaceViews.map((item) => {
          const active = isViewActive(
            item.name
          );

          const className = `nav-view ${
            active ? "active" : ""
          }`;

          return (
            <Fragment key={item.name}>

              {/* STANDARD WORKSPACE ITEM */}

              {onSelect ? (
                <button
                  type="button"
                  className={className}
                  aria-current={
                    active
                      ? "page"
                      : undefined
                  }
                  onClick={() =>
                    onSelect(item.name)
                  }
                >
                  <i
                    className={`bi ${item.icon} nav-icon`}
                    aria-hidden="true"
                  />

                  {item.name}
                </button>
              ) : (
                <Link
                  className={className}
                  href={viewLink(item.name)}
                  aria-current={
                    active
                      ? "page"
                      : undefined
                  }
                >
                  <i
                    className={`bi ${item.icon} nav-icon`}
                    aria-hidden="true"
                  />

                  {item.name}
                </Link>
              )}

              {/* GENERATE INVOICE PAGE */}

              {item.name === "Invoice Management" && (
                <Link
                  className={`nav-view ${
                    isGenerateInvoicePage
                      ? "active"
                      : ""
                  }`}
                  href="/invoices/new"
                  aria-current={
                    isGenerateInvoicePage
                      ? "page"
                      : undefined
                  }
                >
                  <i
                    className="bi bi-file-earmark-plus nav-icon"
                    aria-hidden="true"
                  />

                  <span>
                    Generate Invoice
                  </span>
                </Link>
              )}

            </Fragment>
          );
        })}
      </nav>

      {/* ====================================================
          MANAGEMENT SECTION
      ==================================================== */}

      <div className="mt-4 nav-caption">
        Management
      </div>

      <nav aria-label="Management navigation">

        {/* MODULE 5 — FINANCIAL REPORTS */}

        {renderManagementView(
          "Reports",
          "bi-file-earmark-bar-graph"
        )}

        {/* DOCUMENT INTELLIGENCE */}

        <Link
          className={`nav-view document-nav-link ${
            isDocumentsPage
              ? "active"
              : ""
          }`}
          href="/documents"
          aria-current={
            isDocumentsPage
              ? "page"
              : undefined
          }
        >
          <i
            className="bi bi-file-earmark-text nav-icon"
            aria-hidden="true"
          />

          <span>
            Document Intelligence
          </span>

          {pendingCount > 0 && (
            <span
              className="badge rounded-pill bg-warning text-dark ms-auto"
              aria-label={`${pendingCount} pending documents`}
            >
              {pendingCount}
            </span>
          )}
        </Link>

        {/* MODULE 6 — AUDIT LOGS */}

        {renderManagementView(
          "Audit Logs",
          "bi-shield-check"
        )}

      </nav>

      {/* ====================================================
          SIDEBAR FOOTER
      ==================================================== */}

      <div className="sidebar-bottom">

        <div className="sidebar-foot">
          UAE · AI · Finance
          <br />
          MVP workspace · Administrator
        </div>

        {/* OPTIONAL LOGOUT BUTTON */}

        {onLogout && (
          <button
            className="btn btn-sm btn-outline-light mt-3 w-100"
            type="button"
            onClick={onLogout}
          >
            <i
              className="bi bi-box-arrow-right me-2"
              aria-hidden="true"
            />

            Sign out
          </button>
        )}

      </div>

    </aside>
  );
}
