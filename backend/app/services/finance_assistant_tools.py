"""Read-only financial data tools for the ReceivAI UAE Finance Assistant.

These functions run *inside* the authenticated FastAPI server. The future
assistant route must enforce the existing administrator JWT dependency before
constructing FinanceAssistantTools. This module does NOT authenticate requests.

Financial sources and responsibilities:
- Cash-flow forecast service: consistent live, approved, non-demo AED totals,
  invoice forecasts and reconciliation counts (one `base` methodology only).
- Receivables service: recorded payment-ledger balances per approved invoice.
- Collection priority service: explainable operational prioritization.
- SQLAlchemy SELECTs: document-review metadata, reminder statuses, invoice
  lookup and payment history. No document bytes or extracted-data JSON returned.

There are no INSERT/UPDATE/DELETE operations, commits, external AI calls, or
bank-verification claims. Do not pass private tool results directly to an
external LLM; use the existing privacy gateway for any later AI integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.entities import Invoice, InvoiceDocument, Reminder
from app.schemas.finance_assistant import (
    AssistantIntent,
    DataNature,
    DataSource,
    FinanceDataTable,
    FinanceEvidence,
    FinanceInsight,
    FinanceInvoiceReference,
    FinanceMetric,
    FinanceNavigationAction,
    FinanceTableColumn,
    Severity,
    ValueType,
)
from app.services.cash_flow_forecast_service import (
    get_forecast_dashboard,
    get_forecast_invoices,
    get_forecast_summary,
)
from app.services.collection_priority import prioritize_receivables
from app.services.payment_service import list_payments
from app.services.receivables_service import (
    get_invoice_receivable,
    list_invoice_receivables,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
UAE_TIMEZONE = timezone(timedelta(hours=4))
HORIZONS = frozenset((7, 30, 60, 90))
APPROVED_REVIEW_STATUSES = ("reviewed", "corrected", "approved")
BLOCKED_INVOICE_STATUSES = (
    "draft", "pending", "rejected", "cancelled", "canceled", "void", "voided", "deleted"
)
PENDING_DOCUMENT_STATUSES = ("uploaded", "pending_review", "processing_failed")
MAX_TABLE_ROWS = 100  # schema FinanceDataTable limit
MAX_INVOICE_RESULTS = 50  # bounded lookup; use invoice ID for complete details
MAX_FORECAST_PAGE = 100
MAX_DOCUMENT_SCAN = 500


@dataclass(slots=True)
class FinanceToolResult:
    """Validated components to assemble into FinanceAssistantChatResponse.

    The next orchestration layer may combine these components and produce a
    concise answer, but MUST NOT overwrite source amounts with LLM math.
    """

    intent: AssistantIntent
    summary: str
    metrics: list[FinanceMetric] = field(default_factory=list)
    tables: list[FinanceDataTable] = field(default_factory=list)
    invoices: list[FinanceInvoiceReference] = field(default_factory=list)
    insights: list[FinanceInsight] = field(default_factory=list)
    actions: list[FinanceNavigationAction] = field(default_factory=list)
    evidence: list[FinanceEvidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _aed(value: Any) -> str:
    """Only use Decimal strings/DB Decimals; never round from binary floats."""
    if isinstance(value, (float, bool)):
        raise ValueError("AED values must originate from exact Decimal amounts")
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid AED amount returned by financial service") from exc
    if not amount.is_finite():
        raise ValueError("Non-finite AED amount returned by financial service")
    return f"{amount:.2f}"


def _metric(
    key: str,
    label: str,
    value: str | int | Decimal,
    *,
    kind: ValueType = ValueType.AED,
    source: DataSource = DataSource.FORECAST,
    nature: DataNature = DataNature.CALCULATED,
    description: str | None = None,
) -> FinanceMetric:
    return FinanceMetric(
        key=key,
        label=label,
        value=_aed(value) if kind == ValueType.AED else str(value),
        value_type=kind,
        nature=nature,
        source=source,
        description=description,
    )


def _column(key: str, label: str, kind: ValueType = ValueType.TEXT) -> FinanceTableColumn:
    return FinanceTableColumn(key=key, label=label, value_type=kind)


def _evidence(
    source: DataSource, description: str, nature: DataNature,
    *, record_ids: list[int] | None = None,
) -> FinanceEvidence:
    return FinanceEvidence(
        source=source,
        description=description,
        nature=nature,
        as_of=datetime.now(timezone.utc),
        record_ids=(record_ids or [])[:100],
    )


def _warnings(items: list[str], *, max_items: int = 20) -> list[str]:
    return list(dict.fromkeys(str(item)[:500] for item in items if item))[:max_items]


def _internal_action(label: str, href: str, description: str | None = None) -> FinanceNavigationAction:
    return FinanceNavigationAction(label=label, href=href, description=description)


def _invoice_ref(invoice: Invoice, outstanding: str, overdue_days: int = 0) -> FinanceInvoiceReference:
    return FinanceInvoiceReference(
        invoice_id=int(invoice.id),
        invoice_number=str(invoice.invoice_number),
        customer_name=str(invoice.customer_name),
        due_date=invoice.due_date,
        invoice_status=str(invoice.status or "unknown"),
        outstanding_aed=_aed(outstanding),
        days_overdue=max(0, overdue_days),
    )


class FinanceAssistantTools:
    """Authorized, read-only access to existing ReceivAI finance services.

    Construct this class in the authenticated `/api/assistant/chat` route:

        tools = FinanceAssistantTools(db=db)
        result = tools.receivables_summary(horizon_days=30)

    Do not instantiate it from client input or give its DB Session to an LLM.
    The same UAE reporting date is reused by all tool calls in one request.
    """

    def __init__(self, db: Session, *, as_of_date: date | None = None) -> None:
        if as_of_date is not None and (
            not isinstance(as_of_date, date) or isinstance(as_of_date, datetime)
        ):
            raise ValueError("as_of_date must be a date")
        self.db = db
        self.as_of_date = as_of_date or datetime.now(UAE_TIMEZONE).date()

    @staticmethod
    def _horizon(days: int) -> int:
        if type(days) is not int or days not in HORIZONS:
            raise ValueError("horizon_days must be one of 7, 30, 60 or 90")
        return days

    def _live_invoice_conditions(self) -> tuple[Any, ...]:
        """Match the existing live-forecast invoice eligibility boundaries."""
        return (
            func.lower(func.coalesce(Invoice.source_type, "")) != "demo",
            func.lower(func.coalesce(Invoice.review_status, "")).in_(APPROVED_REVIEW_STATUSES),
            func.upper(func.coalesce(Invoice.currency, "AED")) == "AED",
            Invoice.issue_date <= self.as_of_date,
            ~func.lower(func.coalesce(Invoice.status, "")).in_(BLOCKED_INVOICE_STATUSES),
        )

    def _eligible_live_ids(self) -> set[int]:
        return {
            int(invoice_id)
            for invoice_id in self.db.scalars(
                select(Invoice.id).where(*self._live_invoice_conditions())
            ).all()
        }

    def _live_invoice(self, invoice_id: int) -> Invoice | None:
        if type(invoice_id) is not int or invoice_id <= 0:
            raise ValueError("invoice_id must be a positive integer")
        return self.db.scalars(
            select(Invoice).where(Invoice.id == invoice_id, *self._live_invoice_conditions())
        ).one_or_none()

    # ------------------------------------------------------------------
    # 1. Exact outstanding / overdue / recorded payment totals.
    # ------------------------------------------------------------------
    def receivables_summary(self, *, horizon_days: int = 30) -> FinanceToolResult:
        days = self._horizon(horizon_days)
        data = get_forecast_summary(
            db=self.db, horizon_days=days,
            as_of_date=self.as_of_date, scenario="base",
        )
        m = data.metrics
        return FinanceToolResult(
            intent=AssistantIntent.RECEIVABLES_SUMMARY,
            summary=(
                f"As of {self.as_of_date.isoformat()}, ledger-derived outstanding receivables "
                f"are AED {_aed(m.total_outstanding_aed)}, including "
                f"AED {_aed(m.overdue_outstanding_aed)} overdue. "
                f"{m.reconciliation_required_count} invoice(s) need reconciliation."
            ),
            metrics=[
                _metric("outstanding", "Outstanding receivables", m.total_outstanding_aed),
                _metric("overdue", "Overdue receivables", m.overdue_outstanding_aed),
                _metric("recorded_30", "Recorded payments · past 30 days",
                        m.recorded_collections_last_30_days_aed,
                        nature=DataNature.RECORDED,
                        description="Recorded payment entries, not bank-verified receipts"),
                _metric("eligible", "Eligible outstanding invoices", m.eligible_invoice_count,
                        kind=ValueType.COUNT),
                _metric("reconciliation", "Reconciliation required",
                        m.reconciliation_required_count, kind=ValueType.COUNT),
            ],
            actions=[
                _internal_action("Open Payment Collections", "/collections"),
                _internal_action("Open Cash Flow Forecast", "/?view=Cash%20Flow%20Forecast"),
            ],
            evidence=[_evidence(
                DataSource.FORECAST,
                "Existing cash-flow service computes outstanding balances from approved, non-demo AED invoices and recorded payments",
                DataNature.CALCULATED,
            )],
            warnings=_warnings(list(data.warnings) + [
                "Manual payment entries are not independently bank verified.",
                "Database eligibility excludes invoices explicitly tagged as demo; untagged test records may remain.",
            ]),
        )

    # ------------------------------------------------------------------
    # 2. Invoice lookup (includes already-settled records).
    # ------------------------------------------------------------------
    def invoice_lookup(
        self, *, invoice_id: int | None = None, search: str | None = None,
        limit: int = 25, include_settled: bool = True,
    ) -> FinanceToolResult:
        if type(limit) is not int or not 1 <= limit <= MAX_INVOICE_RESULTS:
            raise ValueError("limit must be between 1 and 50")
        if invoice_id is None and not (search and search.strip()):
            raise ValueError("Provide an invoice_id or an invoice/customer search term")

        query = select(Invoice).where(*self._live_invoice_conditions())
        if invoice_id is not None:
            if type(invoice_id) is not int or invoice_id <= 0:
                raise ValueError("invoice_id must be a positive integer")
            query = query.where(Invoice.id == invoice_id)
        else:
            term = (search or "").strip()
            if len(term) > 120:
                raise ValueError("Search text cannot exceed 120 characters")
            escaped = term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            pattern = f"%{escaped}%"
            query = query.where(or_(
                Invoice.invoice_number.ilike(pattern, escape="\\"),
                Invoice.customer_name.ilike(pattern, escape="\\"),
            ))

        invoice_rows = list(self.db.scalars(
            query.order_by(Invoice.due_date.asc(), Invoice.id.asc()).limit(limit + 1)
        ).all())
        truncated = len(invoice_rows) > limit
        invoice_rows = invoice_rows[:limit]

        rows: list[dict[str, str | int | None]] = []
        references: list[FinanceInvoiceReference] = []
        total_amount = ZERO
        for invoice in invoice_rows:
            receivable = get_invoice_receivable(self.db, int(invoice.id), self.as_of_date)
            if receivable is None:
                continue
            outstanding = _aed(receivable["outstanding_amount"])
            if not include_settled and outstanding == "0.00":
                continue
            total_amount += Decimal(outstanding)
            rows.append({
                "invoice_id": int(invoice.id),
                "number": str(invoice.invoice_number),
                "customer": str(invoice.customer_name),
                "due_date": invoice.due_date.isoformat(),
                "invoice_total": _aed(receivable["invoice_total"]),
                "recorded_paid": _aed(receivable["paid_amount"]),
                "outstanding": outstanding,
                "payment_status": str(receivable["payment_status"]),
            })
            references.append(_invoice_ref(
                invoice, outstanding, int(receivable["days_overdue"]),
            ))

        table = FinanceDataTable(
            title="Invoice register and payment-ledger balances",
            source=DataSource.COLLECTIONS,
            nature=DataNature.CALCULATED,
            columns=[
                _column("invoice_id", "ID", ValueType.COUNT),
                _column("number", "Invoice number"),
                _column("customer", "Customer"),
                _column("due_date", "Due date", ValueType.DATE),
                _column("invoice_total", "Invoice total", ValueType.AED),
                _column("recorded_paid", "Recorded paid", ValueType.AED),
                _column("outstanding", "Outstanding", ValueType.AED),
                _column("payment_status", "Ledger status"),
            ],
            rows=rows,
            total_rows=None if truncated else len(rows),
        )
        return FinanceToolResult(
            intent=AssistantIntent.INVOICE_LOOKUP,
            summary=(
                f"Found {len(rows)} matching approved, non-demo AED invoice(s) "
                f"with AED {_aed(total_amount)} outstanding in the displayed results."
                if rows else "No matching approved, non-demo AED invoices were found."
            ),
            tables=[table], invoices=references,
            actions=[_internal_action("Open Invoice Management", "/?view=Invoice%20Management")],
            evidence=[_evidence(DataSource.COLLECTIONS,
                                "Invoice register matched to the existing ledger-derived receivable service",
                                DataNature.CALCULATED,
                                record_ids=[r.invoice_id for r in references])],
            warnings=_warnings([
                "Results are limited to 50 invoices per query; narrow the search for more detail."
            ] if truncated else []),
        )

    # ------------------------------------------------------------------
    # 3. Manual payment history; does not verify bank settlement.
    # ------------------------------------------------------------------
    def payment_history(self, *, invoice_id: int) -> FinanceToolResult:
        invoice = self._live_invoice(invoice_id)
        if invoice is None:
            return FinanceToolResult(
                intent=AssistantIntent.PAYMENT_HISTORY,
                summary="Invoice not found or not eligible for the live AED ledger.",
                actions=[_internal_action("Open Invoice Management", "/?view=Invoice%20Management")],
            )

        receivable = get_invoice_receivable(self.db, invoice_id, self.as_of_date)
        if receivable is None:
            raise ValueError("Invoice found but no receivables record is available")
        payment_rows = [
            payment for payment in list_payments(self.db, invoice_id)
            if payment.payment_date <= self.as_of_date
        ]
        total = sum((Decimal(_aed(payment.amount_aed)) for payment in payment_rows), ZERO)
        rows = [
            {
                "date": payment.payment_date.isoformat(),
                "amount": _aed(payment.amount_aed),
                "reference": str(payment.payment_reference or "Not supplied")[:150],
            }
            for payment in payment_rows[:MAX_TABLE_ROWS]
        ]
        return FinanceToolResult(
            intent=AssistantIntent.PAYMENT_HISTORY,
            summary=(
                f"Invoice {invoice.invoice_number} has {len(payment_rows)} recorded payment(s) "
                f"totaling AED {_aed(total)} as of {self.as_of_date.isoformat()}; "
                f"remaining balance is AED {_aed(receivable['outstanding_amount'])}."
            ),
            metrics=[
                _metric("invoice_total", "Invoice total", receivable["invoice_total"],
                        source=DataSource.PAYMENTS),
                _metric("payments", "Recorded payments", total,
                        source=DataSource.PAYMENTS, nature=DataNature.RECORDED),
                _metric("balance", "Remaining balance", receivable["outstanding_amount"],
                        source=DataSource.COLLECTIONS),
            ],
            tables=[FinanceDataTable(
                title=f"Payments for {invoice.invoice_number}",
                source=DataSource.PAYMENTS, nature=DataNature.RECORDED,
                columns=[_column("date", "Date", ValueType.DATE),
                         _column("amount", "Amount", ValueType.AED),
                         _column("reference", "Manual payment reference")],
                rows=rows, total_rows=len(payment_rows),
            )],
            invoices=[_invoice_ref(invoice, receivable["outstanding_amount"],
                                   int(receivable["days_overdue"]))],
            actions=[_internal_action("Review payment ledger", f"/collections?invoice={invoice_id}"),
                     _internal_action("View invoice", f"/invoices/{invoice_id}")],
            evidence=[_evidence(DataSource.PAYMENTS,
                                "Existing Payment records dated on or before the reporting date; not bank verified",
                                DataNature.RECORDED, record_ids=[int(p.id) for p in payment_rows[:100]])],
            warnings=_warnings([
                "Payment history displays a maximum of 100 records." if len(payment_rows) > 100 else "",
                *list(receivable.get("warnings") or []),
                "Recorded payments are administrative entries, not independently verified bank deposits.",
            ]),
        )

    # ------------------------------------------------------------------
    # 4. Explainable collection priorities.
    # ------------------------------------------------------------------
    def collection_priorities(self, *, limit: int = 20) -> FinanceToolResult:
        if type(limit) is not int or not 1 <= limit <= MAX_TABLE_ROWS:
            raise ValueError("limit must be between 1 and 100")
        allowed_ids = self._eligible_live_ids()
        receivables = [
            entry for entry in list_invoice_receivables(self.db, self.as_of_date)
            if int(entry["invoice_id"]) in allowed_ids
        ]
        scored = prioritize_receivables(
            receivables=receivables, reminder_counts={}, as_of_date=self.as_of_date,
        )
        ranked = scored[:limit]
        rows = [
            {
                "invoice_id": int(item["invoice_id"]),
                "number": str(item["invoice_number"]),
                "customer": str(item["customer_name"]),
                "outstanding": _aed(item["outstanding_amount"]),
                "overdue_days": int(item["days_overdue"]),
                "priority": str(item["priority_level"]).replace("_", " "),
                "score": int(item["priority_score"]),
            }
            for item in ranked
        ]
        counts = {level: sum(r["priority_level"] == level for r in scored)
                  for level in ("high", "medium", "low", "review_required")}
        return FinanceToolResult(
            intent=AssistantIntent.COLLECTION_PRIORITIES,
            summary=(
                f"{len(scored)} invoices have outstanding balances: "
                f"{counts['high']} high, {counts['medium']} medium, "
                f"{counts['low']} low and {counts['review_required']} require manual review. "
                "These are operational priorities, not credit-default probabilities."
            ),
            metrics=[
                _metric(level, f"{level.replace('_', ' ').capitalize()} invoices", count,
                        kind=ValueType.COUNT, source=DataSource.COLLECTIONS)
                for level, count in counts.items()
            ],
            tables=[FinanceDataTable(
                title="Collection priority queue",
                source=DataSource.COLLECTIONS, nature=DataNature.CALCULATED,
                columns=[
                    _column("invoice_id", "ID", ValueType.COUNT),
                    _column("number", "Invoice"), _column("customer", "Customer"),
                    _column("outstanding", "Outstanding", ValueType.AED),
                    _column("overdue_days", "Days overdue", ValueType.COUNT),
                    _column("priority", "Priority"),
                    _column("score", "Operational score", ValueType.COUNT),
                ], rows=rows, total_rows=len(scored),
            )],
            actions=[_internal_action("Review collection priorities", "/collections")],
            evidence=[_evidence(DataSource.COLLECTIONS,
                                "Existing receivables and deterministic collection-priority scoring, excluding demo-tagged invoices",
                                DataNature.CALCULATED,
                                record_ids=[int(r["invoice_id"]) for r in ranked])],
            warnings=_warnings([
                "Only the highest-priority invoices are displayed." if len(scored) > limit else "",
                "Priority scores are rule-based operational heuristics; reminder drafts are not counted as sent.",
            ]),
        )

    # ------------------------------------------------------------------
    # 5. Reconciliation: status marked paid but ledger not fully settled.
    # ------------------------------------------------------------------
    def reconciliation(self) -> FinanceToolResult:
        allowed_ids = self._eligible_live_ids()
        invoices = [
            item for item in list_invoice_receivables(self.db, self.as_of_date)
            if int(item["invoice_id"]) in allowed_ids and any(
                "RECONCILIATION_REQUIRED:" in str(warning)
                for warning in (item.get("warnings") or [])
            )
        ]
        invoices.sort(key=lambda r: int(r["invoice_id"]))
        affected = sum((Decimal(_aed(r["outstanding_amount"])) for r in invoices), ZERO)
        rows = [
            {
                "invoice_id": int(item["invoice_id"]),
                "number": str(item["invoice_number"]),
                "customer": str(item["customer_name"]),
                "outstanding": _aed(item["outstanding_amount"]),
                "issue": "Marked paid without sufficient ledger payments",
            }
            for item in invoices[:MAX_TABLE_ROWS]
        ]
        result = FinanceToolResult(
            intent=AssistantIntent.RECONCILIATION,
            summary=(
                f"{len(invoices)} invoice(s) require payment/status reconciliation, "
                f"affecting AED {_aed(affected)}."
                if invoices else "No payment/status reconciliation exceptions were detected."
            ),
            metrics=[
                _metric("cases", "Reconciliation exceptions", len(invoices),
                        kind=ValueType.COUNT, source=DataSource.COLLECTIONS),
                _metric("affected", "Outstanding balance under review", affected,
                        source=DataSource.COLLECTIONS),
            ],
            tables=[FinanceDataTable(
                title="Invoices requiring payment reconciliation",
                source=DataSource.COLLECTIONS, nature=DataNature.CALCULATED,
                columns=[_column("invoice_id", "ID", ValueType.COUNT),
                         _column("number", "Invoice"), _column("customer", "Customer"),
                         _column("outstanding", "Outstanding", ValueType.AED),
                         _column("issue", "Issue")],
                rows=rows, total_rows=len(invoices),
            )],
            actions=[_internal_action("Open Payment Collections", "/collections")],
            evidence=[_evidence(DataSource.COLLECTIONS,
                                "Invoice.status compared against actual recorded payment totals by receivables service",
                                DataNature.CALCULATED,
                                record_ids=[int(item["invoice_id"]) for item in invoices[:100]])],
            warnings=_warnings([
                "Review payment evidence before adding a manual payment; never create a duplicate to clear a warning.",
                "Only the first 100 exceptions are displayed." if len(invoices) > 100 else "",
            ]),
        )
        if invoices:
            result.insights.append(FinanceInsight(
                severity=Severity.WARNING,
                title="Resolve payment/status mismatch",
                explanation="One or more invoices are marked paid although payment-ledger entries do not cover their full balance.",
                recommended_action="Inspect payment history; record only genuinely received payments or correct an incorrect paid status.",
                related_invoice_ids=[int(item["invoice_id"]) for item in invoices[:25]],
            ))
        return result

    # ------------------------------------------------------------------
    # 6. 7/30/60/90-day forecast (single existing base methodology).
    # ------------------------------------------------------------------
    def cash_flow_forecast(
        self, *, horizon_days: int = 30, limit: int = 25,
    ) -> FinanceToolResult:
        days = self._horizon(horizon_days)
        if type(limit) is not int or not 1 <= limit <= MAX_FORECAST_PAGE:
            raise ValueError("limit must be between 1 and 100")

        dashboard = get_forecast_dashboard(
            db=self.db, horizon_days=days, as_of_date=self.as_of_date,
            scenario="base", group_by="week",
        )
        projection_data = get_forecast_invoices(
            db=self.db, horizon_days=days, as_of_date=self.as_of_date,
            scenario="base", page=1, page_size=limit, include_excluded=False,
        )
        m = dashboard.summary.metrics
        projections = projection_data.invoices
        rows = [
            {
                "invoice_id": int(p.invoice_id),
                "number": str(p.invoice_number),
                "customer": str(p.customer_name),
                "due_date": p.due_date.isoformat() if p.due_date else "—",
                "outstanding": _aed(p.outstanding_aed),
                "expected_date": p.expected_receipt_date.isoformat() if p.expected_receipt_date else "—",
                "estimated_receipts": _aed(p.expected_collection_aed),
                "risk": str(p.risk_level),
            }
            for p in projections
        ]
        insights = [
            FinanceInsight(
                severity=Severity(item.severity),
                title=str(item.title), explanation=str(item.description),
                recommended_action=item.recommended_action,
                related_invoice_ids=[int(i) for i in item.related_invoice_ids[:25]],
                nature=DataNature.CALCULATED,
            )
            for item in dashboard.insights.insights[:20]
        ]
        return FinanceToolResult(
            intent=AssistantIntent.CASH_FLOW_FORECAST,
            summary=(
                f"Estimated receivables cash collections for {days} days: "
                f"AED {_aed(m.expected_collections_aed)}. "
                f"Current outstanding is AED {_aed(m.total_outstanding_aed)}. "
                "Future collection amounts and dates are estimates, not promises."
            ),
            metrics=[
                _metric("expected", f"Estimated receipts · next {days} days",
                        m.expected_collections_aed, nature=DataNature.ESTIMATED),
                _metric("outstanding", "Total outstanding receivables", m.total_outstanding_aed),
                _metric("overdue", "Overdue outstanding", m.overdue_outstanding_aed),
                _metric("due", f"Contractually due · next {days} days", m.due_within_horizon_aed),
                _metric("forecast_count", "Invoices contributing to estimate", m.forecast_invoice_count,
                        kind=ValueType.COUNT, nature=DataNature.ESTIMATED),
                _metric("reconciliation", "Reconciliation exceptions", m.reconciliation_required_count,
                        kind=ValueType.COUNT),
            ],
            tables=[FinanceDataTable(
                title=f"Invoice-level estimated receipts · next {days} days",
                source=DataSource.FORECAST, nature=DataNature.ESTIMATED,
                columns=[_column("invoice_id", "ID", ValueType.COUNT),
                         _column("number", "Invoice"), _column("customer", "Customer"),
                         _column("due_date", "Due", ValueType.DATE),
                         _column("outstanding", "Outstanding", ValueType.AED),
                         _column("expected_date", "Estimated receipt", ValueType.DATE),
                         _column("estimated_receipts", "Estimated cash", ValueType.AED),
                         _column("risk", "Risk category")],
                rows=rows, total_rows=projection_data.total,
            )],
            invoices=[FinanceInvoiceReference(
                invoice_id=int(p.invoice_id), invoice_number=str(p.invoice_number),
                customer_name=str(p.customer_name), due_date=p.due_date,
                invoice_status=str(p.forecast_status), outstanding_aed=_aed(p.outstanding_aed),
                days_overdue=int(p.days_overdue),
            ) for p in projections[:100]],
            insights=insights,
            actions=[_internal_action("View full Cash Flow Forecast", "/?view=Cash%20Flow%20Forecast")],
            evidence=[_evidence(DataSource.FORECAST,
                                "Existing rule-based cash-in projection; documented, uncalibrated payment probabilities",
                                DataNature.ESTIMATED,
                                record_ids=[int(p.invoice_id) for p in projections[:100]])],
            warnings=_warnings(
                list(dashboard.summary.warnings)
                + list(dashboard.insights.warnings)
                + list(projection_data.warnings)
                + [
                    "The table shows the first selected eligible invoices; the headline forecast includes all eligible invoices."
                    if projection_data.total > len(projections) else "",
                    "Recorded payment entries are not bank-verified deposits.",
                    "Default collection probabilities are assumptions, not trained or calibrated predictions.",
                ]
            ),
        )

    # ------------------------------------------------------------------
    # 7. Pending document-review metadata (no raw document or JSON content).
    # ------------------------------------------------------------------
    def document_reviews(self, *, limit: int = 25) -> FinanceToolResult:
        if type(limit) is not int or not 1 <= limit <= MAX_TABLE_ROWS:
            raise ValueError("limit must be between 1 and 100")
        statement = (
            select(InvoiceDocument)
            .where(InvoiceDocument.processing_status.in_(PENDING_DOCUMENT_STATUSES))
            .order_by(InvoiceDocument.id.desc())
            .limit(MAX_DOCUMENT_SCAN + 1)
        )
        documents = list(self.db.scalars(statement).all())
        scan_limited = len(documents) > MAX_DOCUMENT_SCAN
        pending = []
        for doc in documents[:MAX_DOCUMENT_SCAN]:
            extracted = doc.extracted_data if isinstance(doc.extracted_data, dict) else {}
            if extracted.get("review_status") == "rejected":
                continue
            extraction = extracted.get("structured_extraction")
            entries = extraction.get("invoices") if isinstance(extraction, dict) else None
            invoice_count = len(entries) if isinstance(entries, list) and entries else 1
            approved = extracted.get("approved_invoice_indices")
            approved_indices = set(index for index in approved if isinstance(index, int)) if isinstance(approved, list) else set()
            if len(approved_indices) < invoice_count:
                pending.append(doc)

        rows = [
            {
                "id": int(doc.id),
                "filename": str(doc.original_filename)[:255],
                "status": str(doc.processing_status),
                "invoice_id": int(doc.invoice_id) if doc.invoice_id else None,
                "uploaded_at": doc.uploaded_at.date().isoformat() if doc.uploaded_at else "—",
            }
            for doc in pending[:limit]
        ]
        return FinanceToolResult(
            intent=AssistantIntent.DOCUMENT_REVIEWS,
            summary=(
                f"{len(pending)} document(s) currently require processing or review"
                + (" in the first 500 checked documents." if scan_limited else ".")
            ),
            metrics=[_metric("pending_docs", "Documents needing review", len(pending),
                             kind=ValueType.COUNT, source=DataSource.DOCUMENTS,
                             nature=DataNature.RECORDED)],
            tables=[FinanceDataTable(
                title="Pending invoice-document reviews",
                source=DataSource.DOCUMENTS, nature=DataNature.RECORDED,
                columns=[_column("id", "Document ID", ValueType.COUNT),
                         _column("filename", "Filename"),
                         _column("status", "Processing status"),
                         _column("invoice_id", "Linked invoice", ValueType.COUNT),
                         _column("uploaded_at", "Uploaded", ValueType.DATE)],
                rows=rows, total_rows=None if scan_limited else len(pending),
            )],
            actions=[_internal_action("Open Document Intelligence", "/documents")],
            evidence=[_evidence(DataSource.DOCUMENTS,
                                "InvoiceDocument processing status and pending-review metadata; raw extracted JSON excluded",
                                DataNature.RECORDED,
                                record_ids=[int(doc.id) for doc in pending[:100]])],
            warnings=_warnings([
                "More than 500 candidate documents exist; this is a partial scan."
                if scan_limited else "",
                "Only the first selected documents are shown."
                if len(pending) > limit else "",
            ]),
        )

    # ------------------------------------------------------------------
    # 8. Reminder approval status (never infer that approval means delivery).
    # ------------------------------------------------------------------
    def reminder_status(self, *, limit: int = 25) -> FinanceToolResult:
        if type(limit) is not int or not 1 <= limit <= MAX_TABLE_ROWS:
            raise ValueError("limit must be between 1 and 100")
        conditions = self._live_invoice_conditions()
        grouped = self.db.execute(
            select(Reminder.approval_status, func.count(Reminder.id))
            .join(Invoice, Reminder.invoice_id == Invoice.id)
            .where(*conditions)
            .group_by(Reminder.approval_status)
        ).all()
        counts = {str(status): int(count) for status, count in grouped}
        total = sum(counts.values())
        reminders = list(self.db.scalars(
            select(Reminder)
            .join(Invoice, Reminder.invoice_id == Invoice.id)
            .where(*conditions)
            .order_by(Reminder.created_at.desc(), Reminder.id.desc())
            .limit(limit)
        ).all())
        rows = [
            {
                "reminder_id": int(r.id),
                "invoice_id": int(r.invoice_id),
                "subject": str(r.subject)[:255],
                "status": str(r.approval_status),
                "created": r.created_at.date().isoformat() if r.created_at else "—",
                "delivery": "Not confirmed sent",
            }
            for r in reminders
        ]
        return FinanceToolResult(
            intent=AssistantIntent.REMINDER_STATUS,
            summary=(
                f"{total} saved reminder draft(s): "
                f"{counts.get('pending', 0)} pending, "
                f"{counts.get('approved', 0)} approved, and "
                f"{counts.get('rejected', 0)} rejected. "
                "Approval does not mean delivery."
            ),
            metrics=[
                _metric(f"reminders_{status}", f"{status.capitalize()} drafts", counts.get(status, 0),
                        kind=ValueType.COUNT, source=DataSource.REMINDERS,
                        nature=DataNature.RECORDED)
                for status in ("pending", "approved", "rejected")
            ],
            tables=[FinanceDataTable(
                title="Collection reminder drafts",
                source=DataSource.REMINDERS, nature=DataNature.RECORDED,
                columns=[_column("reminder_id", "ID", ValueType.COUNT),
                         _column("invoice_id", "Invoice", ValueType.COUNT),
                         _column("subject", "Subject"), _column("status", "Approval status"),
                         _column("created", "Created", ValueType.DATE),
                         _column("delivery", "Delivery")],
                rows=rows, total_rows=total,
            )],
            actions=[_internal_action("Review reminder approvals", "/collections")],
            evidence=[_evidence(DataSource.REMINDERS,
                                "Saved reminder approval states; no delivery confirmation field exists",
                                DataNature.RECORDED,
                                record_ids=[int(r.id) for r in reminders[:100]])],
            warnings=_warnings([
                "Only the most recent drafts are displayed." if total > limit else "",
                "An approved reminder is not evidence an email has been sent.",
            ]),
        )
