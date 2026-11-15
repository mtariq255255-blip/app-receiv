
"""ReceivAI UAE - Phase 2 Docling smoke test.

Runs standalone using the isolated .venv-docling environment.
Does not connect to FastAPI, Neon, or external AI APIs.

Usage:
    python test_docling_smoke.py "C:/path/to/invoice.pdf"
"""

import argparse
from pathlib import Path
from time import perf_counter

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path", help="Path to a PDF invoice")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve()

    if not pdf_path.is_file():
        raise SystemExit(f"File not found: {pdf_path}")

    if pdf_path.suffix.lower() != ".pdf":
        raise SystemExit("This test only supports PDF files.")

    # Disable remote AI services and external plugins.
    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        enable_remote_services=False,
        allow_external_plugins=False,
    )
    options.table_structure_options.mode = TableFormerMode.ACCURATE

    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=options
            )
        },
    )

    print("RECEIVAI - DOCLING EXTRACTION TEST")
    print("Input:", pdf_path.name)
    print("Mode: CPU / Local document inference")
    print("OCR: Disabled")
    print("Table detection: Enabled")
    print("-" * 55)

    started = perf_counter()

    result = converter.convert(str(pdf_path))
    elapsed = perf_counter() - started

    print("Conversion status:", result.status)
    print("Processing seconds:", round(elapsed, 2))

    if str(result.status).lower().endswith("failure"):
        raise SystemExit("Docling conversion failed.")

    document = result.document
    markdown = document.export_to_markdown()

    print("Detected tables:", len(document.tables))
    print("Extracted characters:", len(markdown))

    print("\nDOCUMENT TEXT PREVIEW")
    print("-" * 55)
    print(markdown[:2000] or "[No readable text]")

    for index, table in enumerate(document.tables, start=1):
        print(f"\nTABLE {index}")
        print("-" * 55)

        frame = table.export_to_dataframe(doc=document)
        print("Columns:", list(frame.columns))
        print("Rows:", len(frame))
        print(frame.head(10).to_string(index=False))

    print("\nTEST COMPLETED")


if __name__ == "__main__":
    main()
