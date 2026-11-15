"""Privacy-first orchestration of local invoice extraction.

The agent never sends document text, page geometry, line items, or business
identifiers to external AI. The only supported external-AI operation is
mapping sanitized spreadsheet *headings* through private_ai_gateway.

Keeps the existing extract_document/extract_invoice output contracts.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.schemas.uae_invoice import UAEInvoiceExtractionSchema
from app.services.invoice_column_mapper import map_columns
from app.services.local_invoice_parser import parse_local_invoices
from app.services.private_ai_gateway import (
    PrivateAIError,
    map_invoice_columns_with_ai,
)
from app.services.privacy_filter import (
    PrivacyContext,
    PrivacyViolationError,
    protect_value,
)
from app.services.privacy_router import ProcessingMode, choose_processing_mode

logger = logging.getLogger(__name__)


class DocumentIntelligenceAgent:
    """Turn locally extracted, untrusted documents into reviewable invoices."""

    @staticmethod
    def _annotate_invoice(
        invoice: UAEInvoiceExtractionSchema,
        filename: str,
        warnings: list[str] | None = None,
    ) -> UAEInvoiceExtractionSchema:
        """Retain the optional annotation utility for existing callers."""
        invoice.source_filename = invoice.source_filename or filename
        fields = (
            "invoice_number", "supplier_name", "supplier_address",
            "supplier_emirate", "supplier_trn", "customer_name",
            "customer_address", "customer_emirate", "customer_trn",
            "issue_date", "supply_date", "due_date", "place_of_supply",
            "currency", "subtotal_aed", "discount_aed", "vat_amount_aed",
            "total_amount_aed",
        )
        invoice.missing_fields = sorted(set(
            invoice.missing_fields
            + [name for name in fields if getattr(invoice, name) is None]
            + (["items"] if not invoice.items else [])
        ))
        invoice.extraction_notes = list(dict.fromkeys(
            invoice.extraction_notes + (warnings or [])
        ))
        return invoice

    @staticmethod
    def _serialize_input(content: str | dict) -> tuple[str, dict]:
        """Normalize extracted input while preserving PDF layout evidence.

        The returned text is retained for backwards compatibility. It is not
        serialized or submitted to any third-party AI provider.
        """
        if isinstance(content, str):
            text = content.strip()
            return text, {"text": text}
        if not isinstance(content, dict):
            raise ValueError("Document content must be text or an extraction result.")

        expected = {
            "text": (str, ""),
            "records": (list, []),
            "tables": (list, []),
            "metadata": (dict, {}),
            "warnings": (list, []),
            "paragraphs": (list, []),
            "blocks": (list, []),
            "layout_pages": (list, []),
        }
        normalized: dict[str, Any] = {
            "filename": str(content.get("filename") or "unknown"),
            "file_type": str(content.get("file_type") or "unknown").lower(),
        }
        for field, (kind, default) in expected.items():
            value = content.get(field, default)
            if value is None and field != "text":
                value = kind()
            if not isinstance(value, kind):
                raise ValueError(
                    f"Document extraction result has invalid {field!r}."
                )
            normalized[field] = value

        # PDF layout is required for position-aware interpretation; dropping
        # it silently forces the weaker plain-text parser.
        if any(not isinstance(page, dict) for page in normalized["layout_pages"]):
            raise ValueError("Document layout pages must be objects.")

        # Preserve other extraction metadata when supplied, but expose only
        # normalized known keys to the local parser.
        return normalized["text"], normalized

    def extract_invoice(
        self,
        extracted_content: str | dict,
    ) -> UAEInvoiceExtractionSchema:
        """Parse the first reviewable invoice locally (legacy single-item API).

        Multi-invoice consumers must use extract_document(), which returns all
        invoices rather than silently selecting one.
        """
        _, normalized = self._serialize_input(extracted_content)
        parsed = parse_local_invoices(normalized)
        invoices = parsed.get("invoices") or []
        if not invoices:
            raise ValueError(
                "No invoice could be confidently parsed locally; "
                "administrator review is required."
            )
        return UAEInvoiceExtractionSchema.model_validate(invoices[0])

    @staticmethod
    def _prefer_remapping(original: dict, candidate: dict) -> bool:
        """Do not discard existing invoices for an inconclusive AI mapping."""
        old = original.get("invoices") or []
        new = candidate.get("invoices") or []
        if len(new) < len(old):
            return False
        if candidate.get("local_extraction_reliable") and not original.get(
            "local_extraction_reliable"
        ):
            return True
        if original.get("local_extraction_reliable") and not candidate.get(
            "local_extraction_reliable"
        ):
            return False
        if len(new) > len(old):
            return True
        # Keep original if remapping offers no demonstrable improvement.
        return False

    def extract_document(self, extracted_content: dict) -> dict:
        """Parse locally; optionally map *only sanitized table headings* via AI."""
        if not isinstance(extracted_content, dict):
            raise ValueError("Document extraction result must be an object.")

        if not settings.local_extraction_enabled:
            return {
                "document_classification": "unknown",
                "invoices": [],
                "extraction_notes": [
                    "Local extraction is disabled; administrator review is required."
                ],
                "processed_record_count": 0,
                "processing_mode": ProcessingMode.MANUAL_REVIEW_REQUIRED.value,
                "ai_called": False,
                "outbound_privacy_check_passed": None,
                "sensitive_data_transmitted": False,
                "manual_review_required": True,
                "processing_reason": "Local extraction is disabled.",
            }

        _, normalized = self._serialize_input(extracted_content)
        parsed = parse_local_invoices(normalized)
        ai_called = False
        privacy_gate_passed: bool | None = None
        ai_warnings: list[str] = []
        mapping_requests = parsed.get("mapping_requests") or {}

        if (
            not parsed.get("local_extraction_reliable", False)
            and settings.ai_fallback_enabled
            and mapping_requests
            and normalized["file_type"] in {"csv", "xls", "xlsx"}
        ):
            ai_mappings: dict[str, dict[str, str]] = {}
            try:
                context = self._privacy_context(normalized)
                for sheet_name, original_to_safe in mapping_requests.items():
                    if not isinstance(original_to_safe, dict):
                        continue
                    safe_to_original = {
                        safe: original
                        for original, safe in original_to_safe.items()
                        if isinstance(original, str) and isinstance(safe, str)
                    }
                    safe_columns = list(safe_to_original)
                    if not safe_columns:
                        continue
                    # The gateway itself validates allowlisted payloads before
                    # attempting a request, and never receives cell contents.
                    try:
                        mapped = map_invoice_columns_with_ai(safe_columns, context)
                        ai_called = True
                        privacy_gate_passed = True
                        valid_mappings = {
                            safe_to_original[safe]: target
                            for safe, target in mapped.get("mappings", {}).items()
                            if safe in safe_to_original and isinstance(target, str)
                        }
                        if valid_mappings:
                            ai_mappings[sheet_name] = valid_mappings
                        ai_warnings.extend(mapped.get("warnings") or [])
                    except PrivateAIError as exc:
                        ai_called = ai_called or exc.request_attempted
                        if exc.request_attempted:
                            privacy_gate_passed = True
                        ai_warnings.append(str(exc))
                    except PrivacyViolationError:
                        privacy_gate_passed = False
                        ai_warnings.append(
                            "Potentially sensitive or unsafe source context was not sent."
                        )
                        # Fail closed: no additional AI requests after a
                        # privacy violation.
                        break

                if ai_mappings:
                    remapped = parse_local_invoices(
                        normalized, ai_mappings=ai_mappings
                    )
                    if self._prefer_remapping(parsed, remapped):
                        parsed = remapped
            except PrivacyViolationError:
                privacy_gate_passed = False
                ai_warnings.append(
                    "Potentially sensitive or unsafe source context was not sent."
                )

        notes = list(dict.fromkeys(
            list(parsed.get("extraction_notes") or []) + ai_warnings
        ))
        reliable = bool(parsed.get("local_extraction_reliable"))

        if not reliable:
            mode = ProcessingMode.MANUAL_REVIEW_REQUIRED
            reason = (
                "Automated interpretation was not safe or reliable. "
                "Administrator review is required."
            )
            manual_review_required = True
        elif ai_called:
            mode = ProcessingMode.REDACTED_AI
            reason = "AI interpreted sanitized spreadsheet column headings only."
            manual_review_required = False
        else:
            decision = choose_processing_mode(
                local_extraction_reliable=True,
                sanitized_context_available=False,
            )
            mode = decision.mode
            reason = decision.reason
            manual_review_required = decision.manual_review_required

        return {
            "document_classification": parsed.get("document_classification", "unknown"),
            "invoices": parsed.get("invoices", []),
            "extraction_notes": notes,
            "processed_record_count": parsed.get("processed_record_count", 0),
            "processing_mode": mode.value,
            "ai_called": ai_called,
            "outbound_privacy_check_passed": privacy_gate_passed,
            "sensitive_data_transmitted": False,
            "manual_review_required": manual_review_required,
            "processing_reason": reason,
            "parser_version": parsed.get("parser_version"),
            "worksheet_classifications": parsed.get("worksheet_classifications", {}),
            "docx_table_count": parsed.get("docx_table_count"),
            "docx_validation_errors": parsed.get("docx_validation_errors", []),
            "financially_consistent": parsed.get("financially_consistent"),
        }

    @staticmethod
    def _privacy_context(extracted_content: dict) -> PrivacyContext:
        context = PrivacyContext()
        protect_value(extracted_content.get("filename"), "SOURCE_FILENAME", context)
        sensitive_fields = {
            "supplier_name", "supplier_trn", "supplier_address",
            "customer_name", "customer_trn", "customer_address",
            "customer_email", "invoice_number",
        }
        for table in extracted_content.get("tables", []):
            if not isinstance(table, dict):
                continue
            rows = table.get("records")
            columns = table.get("columns")
            if not isinstance(rows, list) or not isinstance(columns, list):
                continue
            mapping = map_columns([str(column) for column in columns])
            for field in sensitive_fields:
                column = mapping["resolved"].get(field)
                if column is None:
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        protect_value(
                            row.get(column),
                            f"PRIVATE_{field.upper()}",
                            context,
                        )
        return context


document_agent = DocumentIntelligenceAgent()
