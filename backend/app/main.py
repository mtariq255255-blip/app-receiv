
import os

# Keep NumPy/OpenBLAS from spawning a large thread pool
# in this API process.
# Must run before route imports load pandas or NumPy.
os.environ["OPENBLAS_NUM_THREADS"] = "1"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_admin

from app.api.routes import (
    health,
    auth,
    dashboard,
    invoices,
    payments,
    reminders,
    documents,
    invoice_generation,
    cash_flow_forecast,
    finance_assistant,
    reports,
    audit_logs,
)

from app.api.routes.collections import create_collections_router


# =====================================================
# 1. FASTAPI APPLICATION
# =====================================================

app = FastAPI(
    title="ReceivAI UAE API",
    description=(
        "Agentic Finance Operations, Invoice Intelligence, "
        "Invoice Generation, AI-Powered Payment Collections, "
        "Intelligent Cash Flow Forecasting, AI Financial Assistant, "
        "Financial Reporting and Administrator Audit Logs"
    ),
    version="1.6.0",
)


# =====================================================
# 2. CORS CONFIGURATION
# =====================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(
        dict.fromkeys(
            [
                settings.frontend_origin,
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
        )
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],

    # Allow frontend JavaScript to read audit export status.
    expose_headers=[
        "X-Audit-Export-Truncated",
        "X-Audit-Export-Limit",
        "X-Report-Export-Scope",
    ],
)


# =====================================================
# 3. PUBLIC ENDPOINTS
# =====================================================

app.include_router(health.router)


# =====================================================
# 4. ADMINISTRATOR AUTHENTICATION
# =====================================================

app.include_router(auth.router)


# =====================================================
# 5. MODULE 1 — INVOICE MANAGEMENT
# =====================================================

# Existing dashboard and financial summaries
app.include_router(dashboard.router)

# Existing invoice register and management
app.include_router(invoices.router)

# Manual Invoice Generation
#
# Supports:
# - Create invoice drafts
# - Update and retrieve drafts
# - Validate financial calculations
# - Preview invoice PDFs
# - Finalize invoices
# - Download generated invoice PDFs
#
# Finalized invoices use the existing Invoice
# and InvoiceItem database tables.

app.include_router(invoice_generation.router)

# Existing payment tracking
app.include_router(payments.router)

# Existing reminders
app.include_router(reminders.router)

# Existing document uploads and intelligence
#
# PDF, CSV, DOCX and Excel workflows remain unchanged.

app.include_router(documents.router)


# =====================================================
# 6. MODULE 2 — PAYMENT COLLECTIONS
# =====================================================

collections_router = create_collections_router(
    get_db_dependency=get_db,
    require_admin_dependency=get_current_admin,
)

app.include_router(collections_router)


# =====================================================
# 7. MODULE 3 — CASH FLOW FORECAST
# =====================================================

# Uses existing invoice and payment records.
#
# Supports:
# - 7, 30, 60 and 90-day forecasts
# - Daily, weekly and monthly timelines
# - Receivables risk analysis
# - Documented forecasting assumptions
# - AI-assisted forecast insights
#
# Protected API endpoints:
#
# GET /api/forecast/summary
# GET /api/forecast/timeline
# GET /api/forecast/invoices
# GET /api/forecast/scenarios
# GET /api/forecast/assumptions
# GET /api/forecast/insights
# GET /api/forecast/dashboard
# GET /api/forecast/agent-insights
#
# Existing scenario APIs remain available.
# This module is read-only and uses
# administrator authentication.

app.include_router(cash_flow_forecast.router)


# =====================================================
# 8. MODULE 4 — AI FINANCIAL ASSISTANT
# =====================================================

# Uses the finance assistant agent, read-only tools,
# invoice and payment services, collections data,
# and cash flow forecasting.
#
# Protected API endpoints:
#
# POST /api/assistant/chat
# GET  /api/assistant/suggestions
# GET  /api/assistant/capabilities
#
# The assistant cannot directly modify financial data.
# Authentication is enforced by the assistant router.

app.include_router(finance_assistant.router)


# =====================================================
# 9. MODULE 5 — FINANCIAL REPORTS
# =====================================================

# Read-only financial reporting using:
# - Approved invoices
# - Recorded payments
# - Receivables aging
# - Collection reminders
# - Document processing records
# - Cash flow forecast estimates
# - Payment reconciliation checks
#
# Protected API endpoints:
#
# GET /api/reports/dashboard
# GET /api/reports/export
#
# Supports date and customer filters, summary metrics,
# and authenticated CSV exports.
#
# Does not create or change financial records.

app.include_router(reports.router)


# =====================================================
# 10. MODULE 6 — ADMINISTRATOR AUDIT LOGS
# =====================================================

# Provides read-only access to existing audit events.
#
# Uses the existing:
# - AuditLog database model
# - AdminUser database model
# - Administrator JWT authentication
#
# Features:
# - Administrator activity history
# - Invoice and document action history
# - Payment and reminder audit events
# - Search by action, administrator, or entity ID
# - Action and entity-type filters
# - UAE date range filtering
# - Pagination
# - Safe event metadata
# - Authenticated CSV exports
#
# Protected API endpoints:
#
# GET /api/audit-logs
# GET /api/audit-logs/actions
# GET /api/audit-logs/export
#
# The audit router enforces administrator authentication.
# It does not allow editing or deleting audit records.

app.include_router(audit_logs.router)


# =====================================================
# 11. ROOT ENDPOINT
# =====================================================

@app.get(
    "/",
    tags=["System"],
    summary="ReceivAI UAE API information",
)
def root():
    return {
        "message": "Welcome to ReceivAI UAE API",
        "status": "running",
        "version": app.version,
        "modules": [
            "Invoice Management",
            "Invoice Generation",
            "Document Intelligence",
            "Payment Collections",
            "Cash Flow Forecast",
            "AI Financial Assistant",
            "Financial Reports",
            "Audit Logs",
        ],
        "documentation": "/docs",
    }
