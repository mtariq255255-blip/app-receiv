
"""
ReceivAI UAE
Module 2 - Payment Collections

Agent: Receivables Monitoring Agent

Responsibilities:
- Monitor approved AED invoices
- Calculate receivables summaries
- Identify overdue and due-soon invoices
- Prioritize collection work
- Recommend appropriate follow-up actions
- Produce structured monitoring reports

This agent is deterministic and privacy-first.

It does not:
- Call OpenAI
- Modify invoices
- Record payments
- Generate or send customer communications
- Approve reminders
"""

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.services.receivables_service import (
    list_invoice_receivables,
    get_receivables_summary,
)

from app.services.collection_priority import (
    prioritize_receivables,
    summarize_collection_priorities,
)


class ReceivablesMonitoringAgent:
    """
    Coordinates receivables and collection scoring.

    This agent uses local Python financial calculations
    and existing PostgreSQL invoice/payment records.
    """

    def __init__(
        self,
        db: Session,
        as_of_date: date | None = None,
    ):
        self.db = db
        self.as_of_date = as_of_date or date.today()

    # =================================================
    # 1. READ RECEIVABLES
    # =================================================

    def get_receivables(self) -> list[dict]:
        """
        Return approved invoices with balances
        and calculated payment statuses.
        """

        return list_invoice_receivables(
            db=self.db,
            as_of_date=self.as_of_date,
        )

    # =================================================
    # 2. GET DASHBOARD SUMMARY
    # =================================================

    def get_summary(self) -> dict:
        """Return receivables dashboard statistics."""

        return get_receivables_summary(
            db=self.db,
            as_of_date=self.as_of_date,
        )

    # =================================================
    # 3. GET PRIORITIZED QUEUE
    # =================================================

    def get_collection_queue(
        self,
        receivables: list[dict] | None = None,
        reminder_counts: dict[int, int] | None = None,
    ) -> list[dict]:
        """
        Prioritize outstanding invoices.

        reminder_counts should include only
        confirmed historical contact attempts.

        Because current Reminder records cannot
        confirm delivery, the default is zero.
        """

        if receivables is None:
            receivables = self.get_receivables()

        return prioritize_receivables(
            receivables=receivables,
            reminder_counts=reminder_counts or {},
            as_of_date=self.as_of_date,
        )

    # =================================================
    # 4. IDENTIFY ATTENTION ITEMS
    # =================================================

    def get_attention_items(
        self,
        queue: list[dict],
    ) -> dict:
        """
        Separate invoice monitoring results into
        operational categories.
        """

        high_priority = []
        medium_priority = []
        due_soon = []
        manual_review = []
        routine_monitoring = []

        for item in queue:

            priority = item["priority_level"]
            action = item["recommended_action"]

            if priority == "review_required":
                manual_review.append(item)
                continue

            if action == "prepare_due_date_reminder":
                due_soon.append(item)

            if priority == "high":
                high_priority.append(item)

            elif priority == "medium":
                medium_priority.append(item)

            else:
                routine_monitoring.append(item)

        return {
            "high_priority": high_priority,
            "medium_priority": medium_priority,
            "due_soon": due_soon,
            "manual_review": manual_review,
            "routine_monitoring": routine_monitoring,
        }

    # =================================================
    # 5. RECOMMENDED ACTIONS
    # =================================================

    def build_action_plan(
        self,
        queue: list[dict],
    ) -> list[dict]:
        """
        Produce recommended collection actions.

        Recommendations require administrator review.

        No messages are sent automatically.
        """

        actions = []

        for item in queue:

            action = item["recommended_action"]

            if action in (
                "monitor_invoice",
                "no_action",
            ):
                continue

            actions.append({
                "invoice_id": item["invoice_id"],
                "invoice_number": (
                    item["invoice_number"]
                ),
                "customer_name": (
                    item["customer_name"]
                ),
                "outstanding_amount": (
                    item["outstanding_amount"]
                ),
                "days_overdue": (
                    item["days_overdue"]
                ),
                "priority_level": (
                    item["priority_level"]
                ),
                "priority_score": (
                    item["priority_score"]
                ),
                "recommended_action": action,
                "reasons": (
                    item["priority_reasons"]
                ),
                "requires_admin_approval": True,
                "executed": False,
            })

        return actions

    # =================================================
    # 6. COMPLETE MONITORING REPORT
    # =================================================

    def run(
        self,
        reminder_counts: dict[int, int] | None = None,
    ) -> dict:
        """
        Run the complete receivables monitoring workflow.

        Returns a structured report suitable for
        the dashboard or an administrative review.

        This method is read-only.
        """

        receivables = self.get_receivables()

        summary = self.get_summary()

        queue = self.get_collection_queue(
            receivables=receivables,
            reminder_counts=reminder_counts,
        )

        priority_summary = (
            summarize_collection_priorities(
                receivables=receivables,
                as_of_date=self.as_of_date,
                reminder_counts=reminder_counts or {},
            )
        )

        attention = self.get_attention_items(queue)

        actions = self.build_action_plan(queue)

        return {
            "agent": "receivables_monitoring_agent",
            "agent_version": "1.0.0",
            "run_date": self.as_of_date.isoformat(),
            "currency": "AED",
            "execution_mode": "read_only",
            "ai_api_calls": 0,
            "summary": summary,
            "priority_summary": priority_summary,
            "collection_queue": queue,
            "attention_items": attention,
            "recommended_actions": actions,
            "action_count": len(actions),
            "requires_admin_approval": True,
        }


def run_receivables_monitoring(
    db: Session,
    as_of_date: date | None = None,
    reminder_counts: dict[int, int] | None = None,
) -> dict:
    """
    Convenience function for invoking the agent.

    Example:

        result = run_receivables_monitoring(db)

    Does not modify database records.
    """

    agent = ReceivablesMonitoringAgent(
        db=db,
        as_of_date=as_of_date,
    )

    return agent.run(
        reminder_counts=reminder_counts,
    )
