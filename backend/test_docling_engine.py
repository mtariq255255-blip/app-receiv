r"""Standalone Phase 2 engine test (no database or web requests).

From project root:
 .\.venv-docling\Scripts\python.exe backend\test_docling_engine.py test_invoices\nova_invoice.pdf
This prints counts/status only; add --show-fields for local development.
"""
import argparse
from pathlib import Path
from app.services.document_intelligence.orchestrator import process_pdf_document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", help="Local path to a PDF")
    parser.add_argument("--show-fields", action="store_true", help="Print extracted fields (sensitive)")
    parser.add_argument("--mode", choices=("fast", "accurate"), default="accurate")
    parser.add_argument("--artifacts-path", default=None)
    args = parser.parse_args()

    result = process_pdf_document(
        Path(args.pdf), force_docling=True, mode=args.mode,
        artifacts_path=args.artifacts_path,
    )
    interpreted = result["interpretation"]
    invoice = interpreted["invoice"]
    print("Engine:", interpreted["engine"])
    print("Pages:", interpreted["page_count"])
    print("Seconds:", interpreted["processing_seconds"])
    print("Line items:", len(invoice.get("items") or []))
    print("Unresolved field keys:", interpreted["unresolved_fields"])
    print("Financial review required:", interpreted["financial_reconciliation"]["requires_review"])
    print("Manual review required:", interpreted["manual_review_required"])
    print("Warning count:", len(interpreted["extraction_notes"]))
    if args.show_fields:
        print("*** Sensitive extracted information follows ***")
        for key, value in invoice.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
