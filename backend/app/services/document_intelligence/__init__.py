"""ReceivAI private document intelligence; importing does not initialize Docling."""

from .orchestrator import interpret_layout, process_pdf_document

__all__ = ["interpret_layout", "process_pdf_document"]
