
"""Private Docling-worker integration for ReceivAI UAE.

Public API:
    enhance_document_with_worker(
        structured,
        pdf_path,
        storage_root,
        *,
        mode="accurate",
    )

Feature flags:
    RECEIVAI_DOCLING_ENABLED=true
    RECEIVAI_DOCLING_PRIMARY=true

The existing native-first conditional route remains the default
for compatibility.

Source-currency evidence is kept separately from legacy AED-only
schema fields. No currency conversion or invoice approval occurs here.
"""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .document_router import route_document
from .orchestrator import interpret_layout
from .worker_client import (
    DoclingWorkerError,
    get_docling_worker_client,
)

LOG = logging.getLogger(__name__)

SUPPLEMENT_FIELDS = frozenset({
    "invoice_number",
    "invoice_type",
    "document_type",
    "supplier_name",
    "supplier_trn",
    "customer_name",
    "customer_trn",
    "issue_date",
    "supply_date",
    "due_date",
    "payment_terms",
    "currency",
    "subtotal_aed",
    "subtotal_before_discount_aed",
    "discount_aed",
    "vat_amount_aed",
    "total_amount_aed",
})

AED_FINANCIAL_FIELDS = frozenset({
    "subtotal_aed",
    "subtotal_before_discount_aed",
    "discount_aed",
    "vat_amount_aed",
    "total_amount_aed",
})

MAX_HYBRID_ITEMS = 1000
MAX_FIELD_EVIDENCE = 15
MAX_NOTES = 100
MAX_NOTE_CHARS = 400

def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(
        name,
        default,
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

def worker_enabled() -> bool:
    """Retain the existing worker feature-flag API."""
    return _flag("RECEIVAI_DOCLING_ENABLED")

def _missing(value: Any) -> bool:
    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    if isinstance(value, (list, dict)):
        return not value

    return False

def _unique(messages: list[Any]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    for message in messages:
        if message is None:
            continue

        value = str(message).strip()[:MAX_NOTE_CHARS]

        if value and value not in seen:
            found.append(value)
            seen.add(value)

        if len(found) >= MAX_NOTES:
            break

    return found

def _notes(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []

    if isinstance(value, (list, tuple)):
        return [
            str(item)
            for item in value
            if item is not None and str(item).strip()
        ]

    return []

def _private_pdf_filename(
    pdf_path: str | Path,
    storage_root: str | Path,
) -> str:
    """Validate a PDF within the configured private storage folder.

    User/document authorization must also occur in the API route.
    The worker independently authenticates requests and checks paths.
    """

    root = Path(
        storage_root
    ).expanduser().resolve(strict=True)

    if not root.is_dir():
        raise ValueError(
            "Invoice private storage directory is invalid"
        )

    source = Path(pdf_path).expanduser()

    if source.is_symlink():
        raise ValueError(
            "Document symlinks are not permitted"
        )

    resolved = source.resolve(strict=True)

    if (
        not resolved.is_file()
        or resolved.suffix.lower() != ".pdf"
    ):
        raise ValueError(
            "A stored PDF document is required"
        )

    if resolved.parent != root:
        raise ValueError(
            "Document is outside the private storage directory"
        )

    return resolved.name

def _mark_worker_failure(
    original: dict[str, Any],
) -> dict[str, Any]:
    """Retain native extraction and explicitly require review."""

    result = deepcopy(original)

    result["manual_review_required"] = True

    result["extraction_notes"] = _unique(
        _notes(result.get("extraction_notes"))
        + [
            "Local Docling enrichment was unavailable or invalid. "
            "Native extraction was retained; administrator review "
            "is required."
        ]
    )

    result["docling_enrichment"] = {
        "used": False,
        "status": "unavailable_or_invalid",
        "requires_review": True,
    }

    result["processing_mode"] = "MANUAL_REVIEW_REQUIRED"

    return result

def _evidence_for_schema(
    evidence: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Convert existing resolver evidence to review-compatible data."""

    converted: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    if not isinstance(evidence, dict):
        return converted

    for field, observations in evidence.items():

        if not isinstance(observations, list):
            continue

        entries = []

        for candidate in observations[:MAX_FIELD_EVIDENCE]:

            if not isinstance(candidate, dict):
                continue

            entries.append({
                "source_text": candidate.get("source_text"),
                "source_page": candidate.get("source_page"),
                "bbox": candidate.get("bbox"),
                "extraction_method": candidate.get("method"),
                "confidence": candidate.get("confidence"),
            })

        if entries:
            converted[field] = entries

    return converted

def _safe_decimal(value: Any) -> Decimal | None:
    """Validate numeric evidence without float conversion."""

    if (
        value is None
        or isinstance(value, (bool, float))
    ):
        return None

    try:
        amount = Decimal(
            str(value).strip().replace(",", "")
        )

    except (InvalidOperation, ValueError):
        return None

    return amount if amount.is_finite() else None

def _source_currency(
    items: list[dict[str, Any]],
    *others: Any,
) -> tuple[str | None, bool]:
    """Identify explicit currencies and detect disagreements.

    Does not infer USD or AED from company location.
    """

    currencies = {
        str(item["currency"]).strip().upper()
        for item in items
        if (
            isinstance(item, dict)
            and not _missing(item.get("currency"))
        )
    }

    for candidate in others:
        if isinstance(candidate, str) and candidate.strip():
            currencies.add(candidate.strip().upper())

    currencies.discard("")

    if len(currencies) == 1:
        return next(iter(currencies)), False

    return None, len(currencies) > 1

def _load_native_evidence(
    pdf_path: Path,
    structured: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Get supporting PyMuPDF evidence without blocking Docling.

    Reuse already-supplied native evidence where possible.
    Otherwise extract it locally from the authorized stored PDF.
    """

    for key in (
        "raw_extraction",
        "native_extraction",
    ):
        current = structured.get(key)

        if (
            isinstance(current, dict)
            and isinstance(
                current.get("layout_pages"),
                list,
            )
        ):
            return current, []

    try:
        from app.services.pdf_extractor import extract_pdf

        data = pdf_path.read_bytes()

        if len(data) > 20 * 1024 * 1024:
            return {}, [
                "Native supporting evidence skipped: "
                "PDF size exceeds 20 MB."
            ]

        return extract_pdf(
            data,
            pdf_path.name,
        ), []

    except Exception as exc:
        LOG.warning(
            "Supporting PyMuPDF extraction unavailable (%s)",
            type(exc).__name__,
        )

        return {}, [
            "Supporting PyMuPDF evidence could not be obtained."
        ]

def _project_aed_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project supported AED source items into the legacy schema.

    Never insert USD into AED fields.
    Never synthesize quantities, VAT amounts or prices.
    """

    projected = []

    for item in items:

        if not isinstance(item, dict):
            continue

        if str(
            item.get("currency") or ""
        ).upper() != "AED":
            continue

        if (
            _missing(item.get("description"))
            or _safe_decimal(
                item.get("line_amount")
            ) is None
        ):
            continue

        mapped: dict[str, Any] = {
            "description": item["description"],
            "line_total_aed": item["line_amount"],
        }

        for source, target in (
            ("quantity", "quantity"),
            ("unit", "unit"),
            ("unit_price", "unit_price_aed"),
            ("discount", "discount_aed"),
            ("taxable_value", "taxable_value_aed"),
        ):
            value = item.get(source)

            if not _missing(value):
                mapped[target] = value

        rate = item.get("tax_rate_text")

        if not _missing(rate):
            rate_text = str(rate).strip()

            if (
                rate_text.endswith("%")
                and _safe_decimal(
                    rate_text[:-1]
                ) is not None
            ):
                mapped["vat_rate"] = (
                    rate_text[:-1].strip()
                )

        projected.append(mapped)

    return projected

def _compact_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep source-currency items without embedding the entire PDF."""

    keys = (
        "description",
        "quantity",
        "unit",
        "unit_price",
        "line_amount",
        "currency",
        "container",
        "other_quantity_text",
        "discount",
        "taxable_value",
        "tax_rate_text",
        "source_page",
        "source_table",
        "source_rows",
        "source_representation",
        "source_bbox",
        "evidence",
    )

    return [
        {
            key: deepcopy(item[key])
            for key in keys
            if key in item
        }
        for item in items[:MAX_HYBRID_ITEMS]
        if isinstance(item, dict)
    ]

def enhance_document_with_worker(
    structured: dict[str, Any],
    pdf_path: str | Path,
    storage_root: str | Path,
    *,
    mode: str = "accurate",
) -> dict[str, Any]:
    """Enrich structured invoices using the authenticated Docling worker.

    Primary mode:
        Docling processes every supported PDF.

    Compatibility mode:
        Existing routing determines when Docling runs.

    This function returns a new dictionary and never approves invoices.
    """

    if not isinstance(structured, dict):
        raise TypeError(
            "structured must be a dictionary"
        )

    if mode not in {"fast", "accurate"}:
        raise ValueError(
            "mode must be 'fast' or 'accurate'"
        )

    if (
        not worker_enabled()
        or Path(pdf_path).suffix.lower() != ".pdf"
    ):
        return structured

    original = deepcopy(structured)

    native_invoices = original.get("invoices")

    if not isinstance(native_invoices, list):
        return _mark_worker_failure(original)

    # Never merge multiple invoice documents without segmentation.
    if len(native_invoices) > 1:
        original["manual_review_required"] = True

        original["extraction_notes"] = _unique(
            _notes(original.get("extraction_notes"))
            + [
                "Multiple invoices detected; automatic merging "
                "skipped pending segmentation."
            ]
        )

        original["docling_enrichment"] = {
            "used": False,
            "status": "multiple_invoices",
            "requires_review": True,
        }

        return original

    # -------------------------------------------------
    # 1. Choose primary or legacy routing mode
    # -------------------------------------------------

    primary_mode = _flag(
        "RECEIVAI_DOCLING_PRIMARY"
    )

    if not primary_mode:
        decision = route_document({
            "invoices": native_invoices
        })

        if not decision.get("use_docling"):
            return original

    stage = "validate_private_pdf"
    try:
        # ---------------------------------------------
        # 2. Validate source and call private worker
        # ---------------------------------------------

        filename = _private_pdf_filename(
            pdf_path,
            storage_root,
        )

        source_path = (
            Path(storage_root)
            .expanduser()
            .resolve(strict=True)
            / filename
        )

        client = get_docling_worker_client()

        stage = "worker_request"
        layout = client.extract(
            filename,
            mode=mode,
        )

        if not isinstance(layout, dict):
            raise ValueError(
                "Worker response is not a layout dictionary"
            )

        conversion_status = str(
            layout.get(
                "conversion_status",
                "success",
            )
        ).lower()

        if conversion_status not in {
            "success",
            "partial_success",
        }:
            raise ValueError(
                "Worker conversion was not successful"
            )

        native_invoice = (
            native_invoices[0]
            if (
                native_invoices
                and isinstance(
                    native_invoices[0],
                    dict,
                )
            )
            else None
        )

        # ---------------------------------------------
        # 3. Existing document interpretation
        # ---------------------------------------------

        stage = "layout_interpretation"
        interpretation = interpret_layout(
            layout,
            native_invoice=native_invoice,
        )

        proposed_invoice = interpretation.get(
            "invoice"
        )

        if not isinstance(proposed_invoice, dict):
            raise ValueError(
                "Docling interpretation did not return an invoice"
            )

        # ---------------------------------------------
        # 4. Reconstruct Docling table cells
        # ---------------------------------------------

        from .table_reconstructor import (
            reconstruct_tables,
        )

        from .layout_fusion import (
            fuse_layout_evidence,
        )

        stage = "table_reconstruction"
        reconstruction = reconstruct_tables(
            layout
        )

        # ---------------------------------------------
        # 5. Load complementary PyMuPDF evidence
        # ---------------------------------------------

        native_raw, supporting_warnings = (
            _load_native_evidence(
                source_path,
                original,
            )
        )

        # ---------------------------------------------
        # 6. Fuse both engines
        # ---------------------------------------------

        stage = "layout_fusion"
        fusion = fuse_layout_evidence(
            docling_layout=layout,
            native_extraction=native_raw,
            reconstruction=reconstruction,
            native_invoices=native_invoices,
        )

        source_items = [
            item
            for item in fusion.get(
                "items",
                [],
            )
            if isinstance(item, dict)
        ]

        source_currency, mixed_currency = (
            _source_currency(
                source_items,
                proposed_invoice.get(
                    "currency"
                ),
                (
                    native_invoice.get(
                        "currency"
                    )
                    if native_invoice
                    else None
                ),
            )
        )

        # ---------------------------------------------
        # 7. Start from existing native record
        # ---------------------------------------------

        merged = (
            deepcopy(native_invoice)
            if native_invoice
            else {}
        )

        unresolved = {
            str(value)
            for value in (
                interpretation.get(
                    "unresolved_fields"
                )
                or []
            )
        }

        conflicts = (
            interpretation.get(
                "field_conflicts"
            )
            or {}
        )

        if not isinstance(conflicts, dict):
            conflicts = {}

        # Supplement source-backed missing fields.
        # Do not overwrite conflicting native fields.
        for field in SUPPLEMENT_FIELDS:

            if (
                field in unresolved
                or field in conflicts
            ):
                continue

            # Never put foreign-currency values
            # into AED-specific legacy fields.
            if (
                field in AED_FINANCIAL_FIELDS
                and source_currency != "AED"
            ):
                continue

            current = merged.get(field)

            proposed = proposed_invoice.get(
                field
            )

            if (
                _missing(current)
                and not _missing(proposed)
            ):
                merged[field] = deepcopy(
                    proposed
                )

        # ---------------------------------------------
        # 8. Handle invoice items conservatively
        # ---------------------------------------------

        native_items = (
            native_invoice.get("items")
            if native_invoice
            else None
        )

        proposed_items = proposed_invoice.get(
            "items"
        )

        # Preserve existing nonempty native items.
        # Their accuracy will require comparison in
        # the subsequent item-resolution phase.
        if (
            isinstance(native_items, list)
            and native_items
        ):
            merged["items"] = deepcopy(
                native_items
            )

        elif (
            source_currency == "AED"
            and source_items
            and not mixed_currency
            and "items" not in unresolved
            and interpretation.get(
                "item_comparison_status"
            ) != "conflicting"
        ):
            projected = _project_aed_items(
                source_items
            )

            if len(projected) == len(
                source_items
            ):
                merged["items"] = projected

        elif (
            isinstance(proposed_items, list)
            and proposed_items
            and source_currency == "AED"
            and "items" not in unresolved
            and interpretation.get(
                "item_comparison_status"
            ) != "conflicting"
        ):
            merged["items"] = deepcopy(
                proposed_items
            )

        # ---------------------------------------------
        # 9. Preserve non-AED amounts separately
        # ---------------------------------------------

        if (
            source_currency
            and source_currency != "AED"
        ):
            merged["currency"] = (
                source_currency
            )

            for field in AED_FINANCIAL_FIELDS:
                merged[field] = None

            # Prevent the legacy AED item schema from
            # misrepresenting foreign-currency amounts.
            merged["items"] = []

            unresolved.update(
                AED_FINANCIAL_FIELDS
            )

        elif mixed_currency:
            unresolved.add(
                "currency"
            )

        elif source_currency == "AED":
            merged["currency"] = "AED"

        # ---------------------------------------------
        # 10. Merge field evidence
        # ---------------------------------------------

        previous_evidence = merged.get(
            "field_evidence"
        )

        evidence = (
            deepcopy(previous_evidence)
            if isinstance(
                previous_evidence,
                dict,
            )
            else {}
        )

        docling_evidence = (
            _evidence_for_schema(
                interpretation.get(
                    "field_evidence"
                )
                or {}
            )
        )

        for field, entries in (
            docling_evidence.items()
        ):
            existing = evidence.get(
                field
            )

            if not isinstance(
                existing,
                list,
            ):
                existing = []

            evidence[field] = (
                existing + entries
            )[:MAX_FIELD_EVIDENCE]

        merged["field_evidence"] = evidence

        merged["unresolved_fields"] = sorted(
            set(
                str(value)
                for value in (
                    list(
                        merged.get(
                            "unresolved_fields"
                        )
                        or []
                    )
                    + list(unresolved)
                )
            )
        )

        # ---------------------------------------------
        # 11. Collect interpretation warnings
        # ---------------------------------------------

        notes = _unique(
            _notes(
                merged.get(
                    "extraction_notes"
                )
            )
            + _notes(
                interpretation.get(
                    "extraction_notes"
                )
            )
            + _notes(
                reconstruction.get(
                    "warnings"
                )
            )
            + _notes(
                fusion.get(
                    "warnings"
                )
            )
            + supporting_warnings
        )

        if (
            source_currency
            and source_currency != "AED"
        ):
            notes = _unique(
                notes + [
                    f"Source currency {source_currency}: "
                    "source amounts are preserved in "
                    "hybrid_extraction, not in AED "
                    "accounting fields. Review required."
                ]
            )

        if mixed_currency:
            notes = _unique(
                notes + [
                    "Conflicting source currencies; "
                    "review required."
                ]
            )

        if not source_items:
            notes = _unique(
                notes + [
                    "Docling did not reconstruct any "
                    "complete source charge rows."
                ]
            )

        merged["extraction_notes"] = notes

        merged["extraction_method"] = (
            "docling_primary_plus_pymupdf"
            if primary_mode
            else "native_plus_docling"
        )

        # ---------------------------------------------
        # 12. Preserve source-currency data before schema validation
        # ---------------------------------------------

        # The orchestrator already resolved source-currency financial
        # values. They must survive validation inside result["invoices"],
        # not only in the document-level hybrid_extraction metadata.
        # Keep its source items (including charge provenance), and
        # supplement with fused rows only when none were returned.
        proposed_source_items = proposed_invoice.get("source_items")
        if isinstance(proposed_source_items, list) and proposed_source_items:
            merged["source_items"] = deepcopy(
                proposed_source_items[:MAX_HYBRID_ITEMS]
            )
        elif source_items:
            merged["source_items"] = _compact_items(source_items)
        else:
            merged["source_items"] = []

        for field in (
            "source_subtotal",
            "source_subtotal_before_discount",
            "source_discount",
            "source_tax_amount",
            "source_total_amount",
        ):
            proposed_value = proposed_invoice.get(field)
            if proposed_value is not None:
                merged[field] = deepcopy(proposed_value)

        source_reconciled = proposed_invoice.get(
            "source_totals_reconciled"
        )
        merged["source_totals_reconciled"] = (
            source_reconciled
            if source_reconciled is None
            or isinstance(source_reconciled, bool)
            else None
        )

        # Do not interpret a conflict as evidence for a chosen currency.
        currency_unresolved = (
            mixed_currency
            or "currency" in unresolved
            or "currency" in conflicts
        )
        if currency_unresolved:
            merged["currency"] = None
            merged["source_totals_reconciled"] = None
            merged["items"] = []
            for field in AED_FINANCIAL_FIELDS:
                merged[field] = None
        elif source_currency:
            merged["currency"] = source_currency
            if source_currency != "AED":
                merged["items"] = []
                for field in AED_FINANCIAL_FIELDS:
                    merged[field] = None

        # A declared source total is not a sum we are guessing.
        # If it is missing in Docling, leave it unknown.

        # ---------------------------------------------
        # 12. Validate legacy invoice structure
        # ---------------------------------------------

        from app.schemas.uae_invoice import (
            UAEInvoiceExtractionSchema,
        )

        stage = "schema_validation"
        validated_model = (
            UAEInvoiceExtractionSchema.model_validate(
                merged
            )
        )

        validated = validated_model.model_dump(
            mode="json"
        )

        # Preserve review metadata not explicitly
        # declared in the installed Pydantic schema.
        for field in (
            "field_evidence",
            "unresolved_fields",
            "extraction_method",
        ):
            if (
                field not in validated
                and field in merged
            ):
                validated[field] = deepcopy(
                    merged[field]
                )

        # ---------------------------------------------
        # 13. Build currency-neutral hybrid response
        # ---------------------------------------------

        hybrid_warnings = _unique(
            _notes(
                reconstruction.get(
                    "warnings"
                )
            )
            + _notes(
                fusion.get(
                    "warnings"
                )
            )
            + supporting_warnings
        )

        hybrid_payload = {
            "schema_version": "1.0",
            "currency": source_currency,
            "mixed_currency": mixed_currency,
            "items": _compact_items(
                source_items
            ),
            "item_count": len(
                source_items
            ),
            "table_count": len(
                layout.get(
                    "tables"
                )
                or []
            ),
            "page_count": layout.get(
                "page_count"
            ),
            "primary_engine": "docling",
            "supporting_engine": "pymupdf",
            "warnings": hybrid_warnings,
            "conflicts": deepcopy(
                fusion.get(
                    "conflicts"
                )
                or []
            ),
            "field_candidates": deepcopy(
                fusion.get(
                    "field_candidates"
                )
                or {}
            ),
            # Complete raw evidence can be stored
            # separately in the next persistence phase.
            "raw_evidence_in_response": False,
        }

        # ---------------------------------------------
        # 14. Determine review requirements
        # ---------------------------------------------

        review_required = bool(
            original.get(
                "manual_review_required"
            )
            or interpretation.get(
                "manual_review_required"
            )
            or validated.get(
                "unresolved_fields"
            )
            or conflicts
            or fusion.get(
                "conflicts"
            )
            or hybrid_warnings
            or mixed_currency
            or (
                source_currency
                and source_currency != "AED"
            )
            or not source_items
            or conversion_status == (
                "partial_success"
            )
        )

        # ---------------------------------------------
        # 15. Preserve document response structure
        # ---------------------------------------------

        result = deepcopy(
            original
        )

        result["invoices"] = [
            validated
        ]

        result["processed_record_count"] = len(
            validated.get(
                "items"
            )
            or []
        )

        result["source_record_count"] = len(
            validated.get("source_items") or []
        )

        result["hybrid_extraction"] = (
            hybrid_payload
        )

        result["manual_review_required"] = (
            review_required
        )

        result["extraction_notes"] = _unique(
            _notes(
                original.get(
                    "extraction_notes"
                )
            )
            + notes
        )

        if review_required:
            result["processing_mode"] = (
                "MANUAL_REVIEW_REQUIRED"
            )

            result["processing_reason"] = (
                "Document evidence requires "
                "administrator review."
            )

        # ---------------------------------------------
        # 16. Add Docling processing metadata
        # ---------------------------------------------

        result["docling_enrichment"] = {
            "used": True,
            "status": "completed",
            "mode": mode,
            "primary": primary_mode,
            "processing_seconds": layout.get(
                "processing_seconds",
                interpretation.get(
                    "processing_seconds"
                ),
            ),
            "unresolved_fields": sorted(
                unresolved
            ),
            "field_conflicts": deepcopy(
                conflicts
            ),
            "item_comparison_status": (
                interpretation.get(
                    "item_comparison_status"
                )
            ),
            "financial_status": (
                interpretation.get(
                    "financial_status"
                )
            ),
            "reconstructed_item_count": len(
                source_items
            ),
            "requires_review": (
                review_required
            ),
        }

        return result

    except Exception as exc:
        # Never log invoice text, filenames, paths, request bodies,
        # credentials or unfiltered exception messages.
        safe_worker_errors = {
            "Worker returned no valid layout",
            "Unexpected document extraction engine",
            "Worker did not report a successful conversion",
            "Worker response contains invalid tables",
            "Worker response contains invalid text blocks",
        }
        diagnostic = "Request, conversion, or validation failed"

        if isinstance(exc, DoclingWorkerError):
            message = str(exc)
            if message in safe_worker_errors:
                diagnostic = message
            else:
                # A numeric HTTP status is safe to log; a server response
                # body or arbitrary error text is not.
                import re

                match = re.fullmatch(
                    r"Docling worker returned HTTP ([1-5][0-9]{2})",
                    message,
                )
                if match:
                    diagnostic = f"Worker HTTP {match.group(1)}"

        LOG.warning(
            "Docling enrichment failed at %s (%s): %s",
            stage,
            type(exc).__name__,
            diagnostic,
        )

        return _mark_worker_failure(original)
