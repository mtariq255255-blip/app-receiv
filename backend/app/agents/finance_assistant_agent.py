"""Read-only finance question orchestration for ReceivAI UAE.

Works with the existing FinanceAssistantTools and Pydantic response schemas.
A caller MUST authenticate the administrator before constructing this agent.

This version is deterministic and grounded in backend services; it does not
call an external LLM, execute generated SQL, modify data, or send reminders.
A privacy-reviewed language-model layer can be added later without handing
it the database session or confidential raw financial records.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from app.schemas.finance_assistant import (
    AssistantIntent,
    DataSource,
    FinanceAssistantCapability,
    FinanceAssistantCapabilitiesResponse,
    FinanceAssistantChatRequest,
    FinanceAssistantChatResponse,
    FinanceAssistantSuggestionsResponse,
    FinanceDataTable,
    FinanceInvoiceReference,
    FinanceSuggestedQuestion,
    FinanceNavigationAction,
    ResponseStatus,
)
from app.services.finance_assistant_tools import FinanceAssistantTools, FinanceToolResult

LOGGER = logging.getLogger(__name__)

# Restrict all money and invoice calculations to the existing Python tools.
# These are question-routing rules, not training-derived payment predictions.
_INVOICE_ID = re.compile(
    r"(?i)(?:\binvoice\s*(?:id|number|no\.?|#)\s*[:#]?\s*|(?<!\w)#)([1-9]\d{0,8})\b"
)
_INVOICE_NUMBER = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,14}(?:-[A-Za-z0-9]{2,18}){1,5}\b")
_QUOTED_TERM = re.compile(r"[\"'“‘]([^\"'”’]{2,100})[\"'”’]")
_CUSTOMER_TERM = re.compile(
    r"(?i)\b(?:customer|client|supplier)\s+(?:named\s+|called\s+)?"
    r"([A-Za-z][A-Za-z0-9 .,&'-]{2,100})"
)
_TOP_LIMIT = re.compile(r"(?i)\b(?:top|first|highest|prioriti[sz]e|which|show\s+me)\s+(\d{1,3})\b")
_DAYS = re.compile(r"(?i)\b(\d{1,3})\s*days?\b")

_FORECAST = re.compile(
    r"\b(?:forecast|predict(?:ion|ed)?|project(?:ion|ed)?|future\s+cash|cash\s*flow|"
    r"cashflow|expected\s+(?:cash|receipts?|collections?)|estimated\s+(?:cash|receipts?|collections?)|"
    r"(?:collect|receive)\s+(?:in|within|over)\s+(?:the\s+)?(?:next\s+)?(?:\d+\s+days?|week|month))\b",
    re.IGNORECASE,
)
_RECONCILIATION = re.compile(
    r"\b(?:reconcil\w*|mismatch(?:es)?|discrepanc\w*|marked\s+paid|"
    r"paid\s+but\s+(?:unpaid|outstanding)|payment\s+status\s+(?:error|issue)|"
    r"payment\s+ledger\s+(?:error|issue))\b",
    re.IGNORECASE,
)
_PAYMENT_HISTORY = re.compile(
    r"\b(?:payment\s+histor\w*|payment\s+records?|payments?\s+(?:for|against|on)\s+"
    r"(?:invoice|#)|transaction\s+histor\w*|receipt\s+histor\w*|"
    r"recorded\s+payments?\s+(?:for|on)\s+(?:invoice|#))\b",
    re.IGNORECASE,
)
_OVERDUE = re.compile(r"\b(?:overdue|past\s+due|aged?\s+receivables?|aging|late\s+invoices?)\b", re.IGNORECASE)
_PRIORITY = re.compile(
    r"\b(?:priorit\w*|follow[ -]?ups?|chase|collection\s+queue|high(?:est)?\s+risk|"
    r"contact\s+first|urgent\s+invoices?|which\s+invoices?\s+first)\b",
    re.IGNORECASE,
)
_DOCUMENTS = re.compile(
    r"\b(?:documents?|uploads?|extraction|extract(?:ed)?\s+(?:invoices?|fields?)|"
    r"document\s+reviews?|OCR|pending\s+reviews?|validation\s+issues?)\b",
    re.IGNORECASE,
)
_REMINDERS = re.compile(r"\b(?:reminders?|drafts?|approval\s+status|reminder\s+approvals?)\b", re.IGNORECASE)
_BALANCES = re.compile(
    r"\b(?:outstanding|receivables?|unpaid|balances?|amounts?\s+owed|money\s+owed|"
    r"how\s+much\s+(?:is\s+)?(?:due|owed)|recorded\s+collections?|"
    r"financial\s+(?:summary|overview)|overview|summary|total\s+invoices?|\bowe)\b",
    re.IGNORECASE,
)
_INVOICE_WORD = re.compile(r"\b(?:invoices?|customers?|clients?|bills?)\b", re.IGNORECASE)

# A query which requests mutation is never executed by the assistant.
# Questions *about* processes, such as "How do I record a payment?", are safe.
_MUTATION_REQUEST = re.compile(
    r"(?i)^\s*(?:(?:please|can\s+you|could\s+you|would\s+you|i\s+want\s+you\s+to)\s+)?"
    r"(?:mark\s+(?:invoice\s+)?(?:paid|unpaid)|undo\s+paid|record\s+(?:a\s+)?payment|"
    r"send\s+(?:an?\s+)?(?:email|reminder)|approve\s+(?:an?\s+)?(?:invoice|reminder|payment)|"
    r"reject\s+(?:an?\s+)?(?:invoice|reminder)|delete\s+(?:an?\s+)?(?:invoice|payment|record)|"
    r"create\s+(?:an?\s+)?(?:invoice|payment)|update\s+(?:an?\s+)?(?:invoice|payment))\b"
)


@dataclass(frozen=True, slots=True)
class _Step:
    intent: AssistantIntent
    label: str
    invoke: Callable[[], FinanceToolResult]
    overdue_only: bool = False


def _unique_strings(values: list[str], *, limit: int) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))[:limit]


def _invoice_id(question: str) -> int | None:
    found = _INVOICE_ID.search(question)
    return int(found.group(1)) if found else None


def _invoice_search(question: str) -> str | None:
    # Require digits to differentiate real invoice numbers from terms like
    # 'cash-flow' or 'payment-ledger'. Customer search is never an SQL fragment;
    # FinanceAssistantTools escapes its parameterized ILIKE search.
    for candidate in _INVOICE_NUMBER.findall(question):
        if any(char.isdigit() for char in candidate):
            return candidate
    quoted = _QUOTED_TERM.search(question)
    if quoted:
        return quoted.group(1).strip()
    customer = _CUSTOMER_TERM.search(question)
    if customer:
        term = re.split(r"(?i)\s+(?:and|with|who|that|which|whose|has|have|owe|owes|due|outstanding|invoice|invoices)\b", customer.group(1))[0]
        term = term.rstrip(" ?.!,")
        if term.lower() not in {"payment", "payments", "invoices", "invoice", "who", "which", "total"}:
            return term[:100]
    return None


def _horizon(question: str, default: int) -> tuple[int | None, str | None]:
    match = _DAYS.search(question)
    if match:
        value = int(match.group(1))
        if value not in {7, 30, 60, 90}:
            return None, "This forecast supports only 7, 30, 60 or 90 days."
        return value, None
    if re.search(r"\b(?:next\s+week|in\s+a\s+week)\b", question, re.I):
        return 7, None
    if re.search(r"\b(?:next\s+(?:3|three)\s+months?)\b", question, re.I):
        return 90, None
    if re.search(r"\b(?:next\s+(?:2|two)\s+months?)\b", question, re.I):
        return 60, None
    if re.search(r"\b(?:next\s+month)\b", question, re.I):
        return 30, None
    return default, None


def _requested_limit(question: str, default: int = 15) -> int:
    found = _TOP_LIMIT.search(question)
    return min(100, max(1, int(found.group(1)))) if found else default


def _navigations_for_help() -> list[FinanceNavigationAction]:
    return [
        FinanceNavigationAction(label="Invoice Management", href="/?view=Invoice%20Management"),
        FinanceNavigationAction(label="Payment Collections", href="/collections"),
        FinanceNavigationAction(label="Cash Flow Forecast", href="/?view=Cash%20Flow%20Forecast"),
    ]


def _overdue_rows(result: FinanceToolResult) -> FinanceToolResult:
    """Filter the existing scored queue; never invent a second set of balances."""
    if not result.tables:
        return result
    table = result.tables[0]
    rows = [row for row in table.rows if int(row.get("overdue_days") or 0) > 0]
    result.tables[0] = FinanceDataTable(
        title="Overdue invoices in the current collection queue",
        columns=table.columns,
        rows=rows,
        nature=table.nature,
        source=table.source,
        total_rows=None if table.total_rows is None or table.total_rows > len(table.rows) else len(rows),
        description="Listed rows are overdue; the separate receivables summary provides the total overdue AED balance.",
    )
    result.metrics = []  # original priority-count metrics covered ALL outstanding invoices
    result.summary = f"Showing {len(rows)} overdue invoice(s) from the retrieved collection queue."
    if table.total_rows is None or table.total_rows > len(table.rows):
        result.warnings.append("This overdue list may be incomplete; the collection queue result was limited.")
    return result


class FinanceAssistantAgent:
    """Single, deterministic orchestrator over existing read-only tools.

    Example after JWT authentication and obtaining a SQLAlchemy Session::

        tools = FinanceAssistantTools(db)
        agent = FinanceAssistantAgent(tools)
        response = agent.chat(FinanceAssistantChatRequest(question="Outstanding?"))

    Chat history is optional and not persisted. It is used solely to resolve a
    narrow follow-up referent, never as financial evidence or instructions.
    """

    def __init__(self, tools: FinanceAssistantTools) -> None:
        self.tools = tools

    @staticmethod
    def get_suggestions() -> FinanceAssistantSuggestionsResponse:
        examples = [
            ("outstanding", "How much money is outstanding and overdue?", AssistantIntent.RECEIVABLES_SUMMARY,
             "Ledger-backed receivables totals and reconciliation count"),
            ("overdue", "Show overdue invoices and their remaining balances", AssistantIntent.OVERDUE_ANALYSIS,
             "Aged collection queue and due-date information"),
            ("priorities", "Which 3 invoices should I prioritize for collections?", AssistantIntent.COLLECTION_PRIORITIES,
             "Existing rule-based collection priorities"),
            ("forecast", "What are estimated cash collections in the next 30 days?", AssistantIntent.CASH_FLOW_FORECAST,
             "Forecast estimates and disclosed assumptions"),
            ("reconciliation", "Are any invoices awaiting payment reconciliation?", AssistantIntent.RECONCILIATION,
             "Status and recorded-payment mismatches"),
            ("payment", "Show payment history for invoice #13", AssistantIntent.PAYMENT_HISTORY,
             "Recorded manual receipts for a specific invoice"),
            ("documents", "Which uploaded documents need review?", AssistantIntent.DOCUMENT_REVIEWS,
             "Pending invoice document processing and review"),
            ("reminders", "How many collection reminder drafts await approval?", AssistantIntent.REMINDER_STATUS,
             "Saved reminder draft approval statuses"),
        ]
        return FinanceAssistantSuggestionsResponse(suggestions=[
            FinanceSuggestedQuestion(id=key, question=question, category=intent, description=description)
            for key, question, intent, description in examples
        ])

    @staticmethod
    def get_capabilities() -> FinanceAssistantCapabilitiesResponse:
        data = [
            ("receivables", "Receivables overview", "Recorded ledger balances and overdue amounts", [DataSource.FORECAST, DataSource.COLLECTIONS]),
            ("invoices", "Invoice lookup", "Find approved AED invoices by number, ID or customer", [DataSource.INVOICES, DataSource.COLLECTIONS]),
            ("payments", "Payment history", "View recorded payments for an invoice ID (not bank verification)", [DataSource.PAYMENTS]),
            ("reconciliation", "Payment reconciliation", "Find invoice-status and payment-ledger mismatches", [DataSource.COLLECTIONS]),
            ("priorities", "Collection priorities", "Explain deterministic operational follow-up scoring", [DataSource.COLLECTIONS]),
            ("forecast", "Cash-in forecast", "Assumption-based 7/30/60/90-day estimates", [DataSource.FORECAST]),
            ("documents", "Document review status", "View pending processing and review metadata", [DataSource.DOCUMENTS]),
            ("reminders", "Reminder approval status", "Inspect saved draft and approval states, not delivery", [DataSource.REMINDERS]),
        ]
        return FinanceAssistantCapabilitiesResponse(capabilities=[
            FinanceAssistantCapability(id=key, title=title, description=description,
                                       available=True, sources=sources)
            for key, title, description, sources in data
        ])

    def chat(self, request: FinanceAssistantChatRequest) -> FinanceAssistantChatResponse:
        """Execute authorized GET-only analysis and return validated UI data."""
        question = request.question.strip()

        # Do not interpret prompt-injection instructions or allow the chat to
        # mutate financial records. All links are navigation-only.
        if _MUTATION_REQUEST.search(question):
            return self._help(
                request,
                "This assistant is read-only. To record an actual received payment, "
                "correct an invoice or approve a reminder, use the existing admin "
                "screens and confirm the action there. No change was made.",
                AssistantIntent.UNSUPPORTED,
            )

        invoice_id = _invoice_id(question)
        if invoice_id is None and re.search(r"\b(?:it|its|that invoice|this invoice|same invoice)\b", question, re.I):
            for message in reversed(request.history):
                if message.role == "user":
                    invoice_id = _invoice_id(message.content)
                    if invoice_id is not None:
                        break

        invoice_term = _invoice_search(question)
        normalized = question.casefold()
        if not (_FORECAST.search(question) or _INVOICE_WORD.search(question)) and (
            re.search(r"\b(?:what about|and for|how about)\s+(?:the\s+)?(?:7|30|60|90)\s+days\b", normalized)
        ):
            # A short horizon follow-up is a forecast ONLY if the prior user
            # question was explicitly about forecasting.
            recent_forecast = next((message for message in reversed(request.history)
                                    if message.role == "user"), None)
            if recent_forecast and _FORECAST.search(recent_forecast.content):
                normalized += " forecast"

        is_forecast = bool(_FORECAST.search(normalized))
        is_reconciliation = bool(_RECONCILIATION.search(normalized))
        is_payments = bool(_PAYMENT_HISTORY.search(normalized))
        is_overdue = bool(_OVERDUE.search(normalized))
        is_priority = bool(_PRIORITY.search(normalized))
        is_document = bool(_DOCUMENTS.search(normalized))
        is_reminder = bool(_REMINDERS.search(normalized))
        is_balances = bool(_BALANCES.search(normalized))
        has_invoice = bool(_INVOICE_WORD.search(normalized))

        if re.search(r"\b(?:conservative|optimistic|scenario\s+comparison)\b", normalized) and is_forecast:
            return self._help(
                request,
                "The current ReceivAI forecast uses one disclosed base methodology; "
                "conservative and optimistic scenario comparisons are not available.",
                AssistantIntent.UNSUPPORTED,
            )

        days, horizon_error = _horizon(question, request.horizon_days)
        if is_forecast and horizon_error:
            return self._help(request, horizon_error, AssistantIntent.UNSUPPORTED)
        assert days is not None

        if is_payments and invoice_id is None:
            return self._help(
                request,
                "Payment history requires an invoice ID, for example: "
                "'Show payment history for invoice #13'. No transaction data was guessed.",
                AssistantIntent.PAYMENT_HISTORY,
            )

        steps: list[_Step] = []
        if is_reconciliation:
            steps.append(_Step(AssistantIntent.RECONCILIATION, "payment reconciliation", self.tools.reconciliation))

        if is_payments and invoice_id is not None:
            steps.append(_Step(AssistantIntent.PAYMENT_HISTORY, "payment history",
                               lambda: self.tools.payment_history(invoice_id=invoice_id)))

        if is_forecast:
            steps.append(_Step(AssistantIntent.CASH_FLOW_FORECAST, "cash-flow forecast",
                               lambda: self.tools.cash_flow_forecast(horizon_days=days, limit=25)))

        # A requested overdue list needs the exact ledger total PLUS a separate
        # list of rows. Do not sum partial displayed rows for a portfolio total.
        if is_overdue:
            steps.append(_Step(AssistantIntent.RECEIVABLES_SUMMARY, "receivables balances",
                               lambda: self.tools.receivables_summary(horizon_days=days)))
            steps.append(_Step(AssistantIntent.OVERDUE_ANALYSIS, "overdue invoice list",
                               lambda: _overdue_rows(self.tools.collection_priorities(limit=100))))
        elif is_balances and not is_forecast:
            steps.append(_Step(AssistantIntent.RECEIVABLES_SUMMARY, "receivables balances",
                               lambda: self.tools.receivables_summary(horizon_days=days)))

        list_open_invoices = (
            has_invoice
            and re.search(r"\b(?:show|list|find|display)\b", normalized)
            and re.search(r"\b(?:open|unpaid|outstanding)\b", normalized)
        )
        if (is_priority or list_open_invoices) and not is_overdue:
            limit = _requested_limit(question, default=25 if list_open_invoices else 15)
            steps.append(_Step(AssistantIntent.COLLECTION_PRIORITIES, "collection priorities",
                               lambda: self.tools.collection_priorities(limit=limit)))

        if is_document:
            steps.append(_Step(AssistantIntent.DOCUMENT_REVIEWS, "document reviews",
                               lambda: self.tools.document_reviews(limit=25)))

        if is_reminder:
            steps.append(_Step(AssistantIntent.REMINDER_STATUS, "reminder approval statuses",
                               lambda: self.tools.reminder_status(limit=25)))

        # Require an explicit target when looking up already-paid invoices; the
        # priority queue only includes outstanding invoices. An ID, invoice
        # number, quoted customer, or named customer is enough to search.
        if (invoice_id is not None or invoice_term is not None) and has_invoice and not is_payments:
            if not (is_forecast or is_reconciliation or is_overdue or is_priority or is_document):
                steps.append(_Step(AssistantIntent.INVOICE_LOOKUP, "invoice lookup",
                                   lambda: self.tools.invoice_lookup(invoice_id=invoice_id,
                                                                     search=invoice_term if invoice_id is None else None,
                                                                     limit=25)))

        if not steps:
            if has_invoice and re.search(r"\b(?:show|list|find|display|which|all)\b", normalized):
                # A general invoice register listing has no broad list-all
                # interface in tool 2. An outstanding queue can be shown;
                # never label that as an exhaustive register including paid.
                if re.search(r"\b(?:open|unpaid|outstanding)\b", normalized):
                    steps.append(_Step(AssistantIntent.COLLECTION_PRIORITIES, "open invoices",
                                       lambda: self.tools.collection_priorities(limit=25)))
                else:
                    return self._help(
                        request,
                        "To look up an invoice, provide its number, ID or customer name. "
                        "For the outstanding-only queue, ask 'Show unpaid invoices'. "
                        "I cannot list all paid and unpaid register records from the current read-only lookup tool.",
                        AssistantIntent.INVOICE_LOOKUP,
                    )
            else:
                # Friendly general financial questions map to the exact
                # receivables summary; unrelated topics do not.
                if re.search(r"\b(?:finance|financial|business|doing|performance|position)\b", normalized):
                    steps.append(_Step(AssistantIntent.RECEIVABLES_SUMMARY, "receivables overview",
                                       lambda: self.tools.receivables_summary(horizon_days=days)))
                else:
                    return self._help(
                        request,
                        "I can analyze invoice balances, recorded payments, overdue invoices, "
                        "collection priorities, payment reconciliation, estimated receipts, "
                        "document reviews, and reminder approval status. "
                        "Try one of the suggested finance questions.",
                        AssistantIntent.UNSUPPORTED,
                    )

        # One request may mention several topics. Deduplicate the same endpoint
        # intent but never drop distinct financial evidence (e.g., overdue list).
        unique_steps: list[_Step] = []
        seen: set[AssistantIntent] = set()
        for step in steps:
            if step.intent not in seen:
                seen.add(step.intent)
                unique_steps.append(step)

        successes: list[FinanceToolResult] = []
        failures: list[str] = []
        for step in unique_steps[:5]:
            try:
                result = step.invoke()
                if not isinstance(result, FinanceToolResult):
                    raise TypeError("A finance tool returned an unexpected result type")
                successes.append(result)
            except Exception:
                # Keep traceback only in server logs, never in the browser.
                LOGGER.exception("Finance assistant tool failed: %s", step.label)
                failures.append(f"{step.label.capitalize()} could not be retrieved.")

        if not successes:
            return FinanceAssistantChatResponse(
                session_id=request.session_id, question=question,
                answer="Unable to retrieve the requested financial data. No figures have been estimated or invented.",
                intent=unique_steps[0].intent,
                status=ResponseStatus.NO_DATA, data_as_of=None,
                actions=_navigations_for_help(), warnings=failures[:20],
                follow_up_questions=["How much money is outstanding?"],
            )

        status = ResponseStatus.PARTIAL if failures or len(unique_steps) > 5 else ResponseStatus.SUCCESS
        tables: list[FinanceDataTable] = []
        metrics = []
        invoice_refs: list[FinanceInvoiceReference] = []
        insights = []
        actions = []
        evidence = []
        warnings = []
        metric_keys: set[tuple[str, str]] = set()
        invoice_ids: set[int] = set()
        action_links: set[str] = set()
        evidence_keys: set[tuple[str, str]] = set()

        for result in successes:
            for metric in result.metrics:
                key = (metric.source.value, metric.key)
                if key not in metric_keys and len(metrics) < 20:
                    metrics.append(metric)
                    metric_keys.add(key)
            tables.extend(result.tables[:max(0, 5 - len(tables))])
            for invoice in result.invoices:
                if invoice.invoice_id not in invoice_ids and len(invoice_refs) < 100:
                    invoice_refs.append(invoice)
                    invoice_ids.add(invoice.invoice_id)
            insights.extend(result.insights[:max(0, 20 - len(insights))])
            for action in result.actions:
                if action.href not in action_links and len(actions) < 10:
                    actions.append(action)
                    action_links.add(action.href)
            for item in result.evidence:
                key = (item.source.value, item.description)
                if key not in evidence_keys and len(evidence) < 15:
                    evidence.append(item)
                    evidence_keys.add(key)
            warnings.extend(result.warnings)

        warnings.extend(failures)
        if len(unique_steps) > 5:
            warnings.append("Only the first five requested analyses were run. Ask a narrower follow-up for the rest.")
        if not is_forecast and re.search(r"\b(?:cash\s+position|net\s+cash|profit|expenses?|bank\s+balance)\b", normalized):
            warnings.append("ReceivAI currently analyzes receivables cash-in, not bank balances, expenses, profit or net cash flow.")

        answer = " ".join(result.summary.strip() for result in successes if result.summary.strip())
        if failures:
            answer += " Some requested information was unavailable; see the notices below."
        # Bound all model output to the existing Pydantic contract.
        if len(answer) > 8000:
            answer = answer[:7997].rstrip() + "..."
            warnings.append("Answer text was shortened; use the attached data tables for details.")
        if not answer:
            answer = "No financial information was returned by the available services."
            status = ResponseStatus.NO_DATA

        # A no-match invoice query must not be represented as a successful lookup.
        if (len(successes) == 1 and successes[0].intent == AssistantIntent.INVOICE_LOOKUP
                and not successes[0].invoices):
            status = ResponseStatus.NO_DATA

        followups = self._followups([step.intent for step in unique_steps])
        return FinanceAssistantChatResponse(
            session_id=request.session_id,
            question=question,
            answer=answer,
            intent=unique_steps[0].intent if len(unique_steps) == 1 else self._primary_intent(unique_steps),
            status=status,
            data_as_of=max(result.as_of for result in successes),
            metrics=metrics, tables=tables, invoices=invoice_refs,
            insights=insights, actions=actions, evidence=evidence,
            warnings=_unique_strings(warnings, limit=20),
            follow_up_questions=followups,
        )

    # Route convenience alias; preserves a single implementation.
    respond = chat

    @staticmethod
    def _primary_intent(steps: list[_Step]) -> AssistantIntent:
        priority = (
            AssistantIntent.RECONCILIATION,
            AssistantIntent.PAYMENT_HISTORY,
            AssistantIntent.CASH_FLOW_FORECAST,
            AssistantIntent.OVERDUE_ANALYSIS,
            AssistantIntent.COLLECTION_PRIORITIES,
            AssistantIntent.INVOICE_LOOKUP,
            AssistantIntent.DOCUMENT_REVIEWS,
            AssistantIntent.REMINDER_STATUS,
            AssistantIntent.RECEIVABLES_SUMMARY,
        )
        for intent in priority:
            if any(step.intent == intent for step in steps):
                return intent
        return steps[0].intent

    @staticmethod
    def _followups(intents: list[AssistantIntent]) -> list[str]:
        suggestions = []
        if AssistantIntent.RECEIVABLES_SUMMARY in intents:
            suggestions.extend(["Show overdue invoices", "What are estimated collections in the next 30 days?"])
        if AssistantIntent.CASH_FLOW_FORECAST in intents:
            suggestions.extend(["Which invoices should I prioritize?", "Are there reconciliation exceptions?"])
        if AssistantIntent.OVERDUE_ANALYSIS in intents or AssistantIntent.COLLECTION_PRIORITIES in intents:
            suggestions.extend(["What is our current outstanding balance?", "Which payment records need reconciliation?"])
        if AssistantIntent.RECONCILIATION in intents:
            suggestions.append("What is the outstanding balance now?")
        if AssistantIntent.PAYMENT_HISTORY in intents or AssistantIntent.INVOICE_LOOKUP in intents:
            suggestions.append("Are there any payment reconciliation issues?")
        if AssistantIntent.DOCUMENT_REVIEWS in intents:
            suggestions.append("How many reminder drafts await approval?")
        if AssistantIntent.REMINDER_STATUS in intents:
            suggestions.append("Which invoices need collection attention?")
        return _unique_strings(suggestions, limit=6)

    @staticmethod
    def _help(
        request: FinanceAssistantChatRequest, answer: str, intent: AssistantIntent,
    ) -> FinanceAssistantChatResponse:
        return FinanceAssistantChatResponse(
            session_id=request.session_id, question=request.question.strip(),
            answer=answer, intent=intent, status=ResponseStatus.NO_DATA,
            actions=_navigations_for_help(),
            follow_up_questions=[
                "How much money is outstanding?",
                "What are estimated cash collections in the next 30 days?",
                "Are there any payment reconciliation exceptions?",
            ],
        )
