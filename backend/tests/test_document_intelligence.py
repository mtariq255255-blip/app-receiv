"""Fast no-Docling tests. Run from backend: python -m pytest tests/test_document_intelligence.py -v"""
from app.services.document_intelligence.document_router import route_document
from app.services.document_intelligence.semantic_mapper import map_header_fields
from app.services.document_intelligence.table_interpreter import interpret_tables
from app.services.document_intelligence.evidence_resolver import resolve_fields
from app.services.document_intelligence.financial_reconciler import reconcile_finances
from app.services.document_intelligence.orchestrator import interpret_layout


def example_layout():
    return {
        "engine": "docling", "page_count": 1, "processing_seconds": 1.3,
        "text_blocks": [
            {"text": "Invoice No: INV-2026-001", "source_page": 1, "bbox": None},
            {"text": "Issued by: Nova Test Services", "source_page": 1, "bbox": None},
            {"text": "Invoice to: Example Pearl Ventures LLC", "source_page": 1, "bbox": None},
            {"text": "Invoice date: 12 Nov 2026", "source_page": 1, "bbox": None},
            {"text": "Due date: 12 Dec 2026", "source_page": 1, "bbox": None},
            {"text": "Grand Total: 3675.00", "source_page": 1, "bbox": None},
        ],
        "tables": [{
            "table_index": 1, "source_page": 1, "bbox": None,
            "headers": ["Description", "Qty", "Rate", "VAT %", "VAT AED", "Total"],
            "rows": [
                ["Service A", "1", "1000", "5", "50", "1050"],
                ["Service B", "1", "1500", "5", "75", "1575"],
                ["Service C", "1", "1000", "5", "50", "1050"],
            ],
        }],
        "warnings": [],
    }


def test_docling_six_column_table_and_identity_fields():
    layout = example_layout()
    fields = map_header_fields(layout)
    assert fields["supplier_name"][0]["value"] == "Nova Test Services"
    assert fields["customer_name"][0]["value"] == "Example Pearl Ventures LLC"
    rows = interpret_tables(layout)
    assert len(rows["items"]) == 3
    assert rows["items"][0]["vat_rate"] == "5"
    assert rows["items"][0]["vat_amount_aed"] == "50"
    assert rows["items"][0]["line_total_aed"] == "1050"


def test_conflicting_invoice_numbers_are_not_silently_selected():
    result = resolve_fields({"invoice_number": [
        {"value": "INV-001"}, {"value": "INV-002"}
    ]})
    assert result["fields"]["invoice_number"] is None
    assert "invoice_number" in result["unresolved_fields"]


def test_unknown_vat_kept_unknown():
    result = reconcile_finances({"items": [{
        "description": "Service", "quantity": "1", "unit_price_aed": "100",
        "vat_rate": None, "line_total_aed": "100",
    }], "total_amount_aed": "100"})
    assert result["calculated_vat_aed"] is None
    assert result["requires_review"]


def test_orchestrator_keeps_unknown_currency_and_requires_review():
    result = interpret_layout(example_layout())
    assert result["invoice"]["invoice_number"] == "INV-2026-001"
    assert result["invoice"]["total_amount_aed"] == "3675.00"
    assert len(result["invoice"]["items"]) == 3
    assert "currency" in result["unresolved_fields"]
    assert result["manual_review_required"]


def test_native_routing_is_conditional():
    assert route_document(None)["use_docling"]
    result = {"invoices": [{"invoice_number": "X1", "customer_name": "C", "total_amount_aed": "100"}]}
    assert not route_document(result)["use_docling"]
    assert route_document(result, force_docling=True)["use_docling"]


def test_missing_qty_not_fabricated():
    layout = {"tables": [{"table_index": 1, "headers": ["Item", "Rate", "Total"],
                           "rows": [["Consulting", "500", "500"]]}]}
    row = interpret_tables(layout)["items"][0]
    assert row["quantity"] is None


def test_aed_parenthesized_total_label():
    fields = map_header_fields({"text_blocks": [{"text": "TOTAL DUE (AED): 3,675.00", "source_page": 1}]})
    assert fields["total_amount_aed"][0]["value"] == "3675.00"
