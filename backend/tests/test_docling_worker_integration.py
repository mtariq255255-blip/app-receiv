
"""ReceivAI UAE: offline tests for the persistent Docling worker.

Run from the project root with PYTHONPATH pointing to backend.
No Docling models, external network, database, or FastAPI server are required.
"""

from __future__ import annotations

import json
import threading
import types
import sys

from http.client import HTTPConnection
from pathlib import Path

import pytest

from app.services.document_intelligence.worker_server import (
    _private_file,
    build_server,
)
from app.services.document_intelligence.worker_client import (
    DoclingWorkerClient,
    DoclingWorkerError,
)
from app.services.document_intelligence import worker_integration


TOKEN = "test-token-" + "a" * 48
FILENAME = "a" * 32 + ".pdf"


@pytest.fixture
def worker(tmp_path):
    """Start a real loopback HTTP server with a fake extractor."""

    pdf = tmp_path / FILENAME
    pdf.write_bytes(b"%PDF-1.4\nsynthetic data only")

    calls = []

    def fake_extract(path, *, mode):
        calls.append((Path(path).name, mode))

        return {
            "engine": "docling",
            "conversion_status": "success",
            "page_count": 1,
            "text": "synthetic layout",
            "text_blocks": [],
            "tables": [],
            "warnings": [],
        }

    server = build_server(
        root=str(tmp_path),
        token=TOKEN,
        port=0,
        extractor=fake_extract,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        client = DoclingWorkerClient(
            token=TOKEN,
            port=server.server_port,
        )

        yield tmp_path, pdf, server, client, calls

    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_health_requires_valid_token(worker):
    """The health endpoint must reject invalid credentials."""

    _, _, server, client, _ = worker

    assert client.health() is True

    bad = DoclingWorkerClient(
        token="b" * 40,
        port=server.server_port,
    )

    with pytest.raises(DoclingWorkerError) as exc:
        bad.health()

    assert exc.value.status_code == 401


def test_worker_extracts_valid_private_pdf(worker):
    """The worker can process an authorized private PDF."""

    _, pdf, _, client, calls = worker

    layout = client.extract(
        pdf.name,
        mode="accurate",
    )

    assert layout["text"] == "synthetic layout"
    assert layout["engine"] == "docling"
    assert calls == [(FILENAME, "accurate")]


def test_worker_accepts_fast_mode(worker):
    """FAST mode must be forwarded to the extractor."""

    _, pdf, _, client, calls = worker

    result = client.extract(
        pdf.name,
        mode="fast",
    )

    assert result["engine"] == "docling"
    assert calls == [(FILENAME, "fast")]


def test_worker_rejects_traversal_and_arbitrary_filenames(worker):
    """Client and server must reject unsafe filenames."""

    root, _, _, client, _ = worker

    invalid_names = (
        "../invoice.pdf",
        "invoice.pdf",
        "C:\\secret.pdf",
        "b" * 32 + ".PDF",
    )

    for filename in invalid_names:

        with pytest.raises(ValueError):
            _private_file(root, filename)

        with pytest.raises(ValueError):
            client.extract(filename)


def test_worker_rejects_symlink(tmp_path):
    """A private PDF filename must not be a symlink."""

    original = tmp_path / ("b" * 32 + ".pdf")
    original.write_bytes(b"%PDF-1.4")

    link = tmp_path / FILENAME

    try:
        link.symlink_to(original)

    except (OSError, NotImplementedError):
        pytest.skip(
            "Symlink creation is unavailable on this Windows setup"
        )

    with pytest.raises(ValueError):
        _private_file(tmp_path, link.name)


def test_worker_rejects_invalid_mode(worker):
    """Unsupported extraction modes must be rejected."""

    _, pdf, _, client, _ = worker

    with pytest.raises(ValueError):
        client.extract(
            pdf.name,
            mode="remote",
        )


def test_worker_rejects_oversized_request(worker):
    """The worker must reject HTTP request bodies over its limit."""

    _, _, server, _, calls = worker

    connection = HTTPConnection(
        "127.0.0.1",
        server.server_port,
        timeout=5,
    )

    try:
        connection.request(
            "POST",
            "/extract",
            body=b"x" * 4097,
            headers={
                "X-ReceivAI-Worker-Token": TOKEN,
                "Content-Type": "application/json",
            },
        )

        response = connection.getresponse()

        assert response.status == 413
        response.read()

    finally:
        connection.close()

    assert not calls


def test_worker_rejects_short_secret(tmp_path):
    """Short authentication secrets must be rejected."""

    with pytest.raises(ValueError):
        build_server(
            root=str(tmp_path),
            token="short",
            port=0,
            extractor=lambda *_args, **kwargs: {},
        )


def test_integration_is_disabled_by_default(monkeypatch, tmp_path):
    """The integration must remain opt-in."""

    monkeypatch.delenv(
        "RECEIVAI_DOCLING_ENABLED",
        raising=False,
    )

    original = {
        "invoices": [],
        "manual_review_required": False,
    }

    result = worker_integration.enhance_document_with_worker(
        original,
        tmp_path / "not-a-real.pdf",
        tmp_path,
    )

    assert result == original


def test_native_only_route_does_not_call_worker(
    monkeypatch,
    tmp_path,
):
    """Usable native results must not trigger Docling."""

    monkeypatch.setenv(
        "RECEIVAI_DOCLING_ENABLED",
        "true",
    )

    monkeypatch.setattr(
        worker_integration,
        "route_document",
        lambda _native: {
            "use_docling": False,
            "reason": "native usable",
        },
    )

    def unexpected_client():
        raise AssertionError(
            "Worker must not be called for a native-only document"
        )

    monkeypatch.setattr(
        worker_integration,
        "get_docling_worker_client",
        unexpected_client,
    )

    original = {
        "invoices": [
            {"invoice_number": "INV-1"}
        ]
    }

    result = worker_integration.enhance_document_with_worker(
        original,
        tmp_path / "not-needed.pdf",
        tmp_path,
    )

    assert result == original


def test_worker_failure_retains_native_and_requires_review(
    monkeypatch,
    tmp_path,
):
    """Worker failure must not discard native extraction."""

    monkeypatch.setenv(
        "RECEIVAI_DOCLING_ENABLED",
        "true",
    )

    monkeypatch.setattr(
        worker_integration,
        "route_document",
        lambda _native: {
            "use_docling": True,
            "reason": "missing table",
        },
    )

    pdf = tmp_path / FILENAME
    pdf.write_bytes(b"%PDF-1.4\nsynthetic")

    class BrokenClient:
        def extract(self, filename, *, mode):
            raise DoclingWorkerError(
                "simulated worker failure"
            )

    monkeypatch.setattr(
        worker_integration,
        "get_docling_worker_client",
        lambda: BrokenClient(),
    )

    original = {
        "invoices": [],
        "manual_review_required": False,
    }

    result = worker_integration.enhance_document_with_worker(
        original,
        pdf,
        tmp_path,
    )

    assert result["invoices"] == []
    assert result["manual_review_required"] is True
    assert result["docling_enrichment"]["used"] is False

    # The original object must remain unchanged.
    assert original["manual_review_required"] is False


def test_successful_enrichment_preserves_native_values(
    monkeypatch,
    tmp_path,
):
    """Missing fields can be added; existing values must be preserved."""

    monkeypatch.setenv(
        "RECEIVAI_DOCLING_ENABLED",
        "true",
    )

    monkeypatch.setattr(
        worker_integration,
        "route_document",
        lambda _native: {
            "use_docling": True,
            "reason": "missing fields",
        },
    )

    pdf = tmp_path / FILENAME
    pdf.write_bytes(b"%PDF-1.4\nsynthetic")

    class FakeClient:
        def extract(self, filename, *, mode):
            assert filename == FILENAME
            assert mode == "accurate"

            return {
                "engine": "docling",
                "text": "synthetic",
                "tables": [],
                "text_blocks": [],
            }

    monkeypatch.setattr(
        worker_integration,
        "get_docling_worker_client",
        lambda: FakeClient(),
    )

    interpreted = {
        "invoice": {
            "invoice_number": "DOC-2",
            "customer_name": "Buyer LLC",
            "supplier_name": "Supplier LLC",
            "currency": "AED",
            "total_amount_aed": "150.00",
            "items": [
                {
                    "description": "Services",
                    "line_total_aed": "150.00",
                }
            ],
        },
        "unresolved_fields": [],
        "field_conflicts": {},
        "field_evidence": {},
        "extraction_notes": [],
        "manual_review_required": False,
        "processing_seconds": 1.0,
        "item_comparison_status": "single_source",
        "financial_status": "not_fully_verified",
    }

    monkeypatch.setattr(
        worker_integration,
        "interpret_layout",
        lambda layout, native_invoice=None: interpreted,
    )

    # Replace the schema only during this isolated test.
    # The production UAE invoice schema is not modified.
    fake_schema_module = types.ModuleType(
        "app.schemas.uae_invoice"
    )

    class FakeSchema:
        def __init__(self, payload):
            self.payload = payload

        @classmethod
        def model_validate(cls, payload):
            return cls(dict(payload))

        def model_dump(self, mode="json"):
            return dict(self.payload)

    fake_schema_module.UAEInvoiceExtractionSchema = FakeSchema

    monkeypatch.setitem(
        sys.modules,
        "app.schemas.uae_invoice",
        fake_schema_module,
    )

    original = {
        "invoices": [
            {
                "invoice_number": "NATIVE-1",
                "customer_name": "Buyer LLC",
            }
        ],
        "manual_review_required": False,
        "extraction_notes": [],
    }

    result = worker_integration.enhance_document_with_worker(
        original,
        pdf,
        tmp_path,
    )

    assert result["docling_enrichment"]["used"] is True

    # Native identity must not be overwritten.
    assert result["invoices"][0]["invoice_number"] == "NATIVE-1"

    # A missing field can be supplemented.
    assert result["invoices"][0]["supplier_name"] == "Supplier LLC"

    assert len(result["invoices"][0]["items"]) == 1

    # Verify no mutation of original native extraction.
    assert original["invoices"][0].get("supplier_name") is None
