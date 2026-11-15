
"""Private local Docling PDF layout adapter for ReceivAI UAE.

Public interface:
    extract_pdf_layout(
        pdf_path,
        *,
        mode="accurate",
        artifacts_path=None,
    )

Docling is the primary document-layout engine.
PyMuPDF runs separately as a supporting evidence engine.

This module preserves:
- Document text
- Structured tables
- Raw table grids
- Individual cell positions and spans
- Source page geometry
- Text block provenance

No currency conversion, invoice approval, tax decisions,
or financial-field inference is performed here.

Environment:
    RECEIVAI_DOCLING_OCR=auto|never|always
    RECEIVAI_TESSERACT_CMD=tesseract
"""

from __future__ import annotations

import math
import os
import shutil
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any


# -------------------------------------------------------
# Safety and extraction limits
# -------------------------------------------------------

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 25

MAX_TEXT_CHARS = 250_000
MAX_TEXT_BLOCKS = 1500
MAX_BLOCK_CHARS = 1500

MAX_TABLES = 100
MAX_ROWS_PER_TABLE = 500
MAX_COLUMNS = 40
MAX_CELL_CHARS = 1000
MAX_HEADER_CHARS = 150

MAX_RAW_CELLS_PER_TABLE = 20_000

DOCUMENT_TIMEOUT_SECONDS = 180.0


# -------------------------------------------------------
# General helpers
# -------------------------------------------------------

def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except (TypeError, ValueError, OverflowError):
        pass

    return None


def _cell_text(value: Any, max_length: int) -> str:
    """Convert cell data to bounded, JSON-safe text."""

    if value is None:
        return ""

    if isinstance(value, float) and not math.isfinite(value):
        return ""

    return str(value).strip()[:max_length]


def _bbox_information(
    bbox: Any,
    *,
    page_height: float | None = None,
) -> dict[str, Any]:
    """Preserve Docling coordinates and optionally normalize to top-left.

    Original bbox is returned unchanged in its numeric coordinate system.
    bbox_top_left is a separate derived representation.

    Unknown coordinate origins are not guessed.
    """

    result: dict[str, Any] = {
        "bbox": None,
        "bbox_origin": None,
        "bbox_top_left": None,
    }

    if bbox is None:
        return result

    values = [
        _finite_float(getattr(bbox, name, None))
        for name in ("l", "t", "r", "b")
    ]

    if any(value is None for value in values):
        return result

    left, top, right, bottom = values

    result["bbox"] = [
        round(value, 2)
        for value in values
    ]

    origin = getattr(bbox, "coord_origin", None)

    if origin is not None:
        origin = str(
            getattr(origin, "value", origin)
        ).lower().replace("_", "").replace("-", "")

        result["bbox_origin"] = origin

    if origin in {"topleft", "top left"}:
        result["bbox_top_left"] = [
            round(left, 2),
            round(top, 2),
            round(right, 2),
            round(bottom, 2),
        ]

    elif (
        origin in {"bottomleft", "bottom left"}
        and page_height is not None
    ):
        result["bbox_top_left"] = [
            round(left, 2),
            round(page_height - top, 2),
            round(right, 2),
            round(page_height - bottom, 2),
        ]

    return result


def _page_dimensions(
    document: Any,
    fallback_count: int,
) -> list[dict[str, Any]]:
    """Return page dimensions without rendering page images."""

    result = []

    pages = getattr(document, "pages", None) or {}

    for page_number in range(1, fallback_count + 1):
        if isinstance(pages, dict):
            page = pages.get(page_number)
        else:
            try:
                page = pages[page_number - 1]
            except (IndexError, TypeError, KeyError):
                page = None

        size = (
            getattr(page, "size", None)
            if page is not None
            else None
        )

        width = _finite_float(
            getattr(size, "width", None)
        )

        height = _finite_float(
            getattr(size, "height", None)
        )

        result.append({
            "page_number": page_number,
            "width": round(width, 2) if width is not None else None,
            "height": round(height, 2) if height is not None else None,
        })

    return result


def _height_for_page(
    page_number: int | None,
    dimensions: list[dict[str, Any]],
) -> float | None:

    if page_number is None:
        return None

    for page in dimensions:
        if page["page_number"] == page_number:
            return page["height"]

    return None


def _provenance(
    element: Any,
    dimensions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preserve original provenance and add normalized geometry."""

    entries = getattr(element, "prov", None) or []

    result: dict[str, Any] = {
        "source_page": None,
        "bbox": None,
        "bbox_origin": None,
        "bbox_top_left": None,
    }

    if not entries:
        return result

    first = entries[0]

    page = getattr(first, "page_no", None)

    if isinstance(page, int) and page > 0:
        result["source_page"] = page

    page_height = _height_for_page(
        result["source_page"],
        dimensions or [],
    )

    result.update(
        _bbox_information(
            getattr(first, "bbox", None),
            page_height=page_height,
        )
    )

    return result


# -------------------------------------------------------
# PDF validation
# -------------------------------------------------------

def _check_pdf(path: Path) -> int:
    """Validate a private local PDF before conversion."""

    if (
        not path.is_file()
        or path.suffix.lower() != ".pdf"
    ):
        raise ValueError(
            "A local PDF file is required"
        )

    size = path.stat().st_size

    if size == 0 or size > MAX_FILE_BYTES:
        raise ValueError(
            "PDF is empty or exceeds the 20 MB limit"
        )

    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError(
                "File does not have a PDF header"
            )

    from pypdfium2 import PdfDocument

    pdf = PdfDocument(str(path))

    try:
        count = len(pdf)
    finally:
        pdf.close()

    if not 1 <= count <= MAX_PAGES:
        raise ValueError(
            f"PDF must contain 1 to {MAX_PAGES} pages"
        )

    return count


# -------------------------------------------------------
# Local OCR configuration
# -------------------------------------------------------

def _ocr_configuration() -> tuple[
    bool,
    str,
    list[str],
]:
    """Configure private Tesseract CLI OCR."""

    choice = os.getenv(
        "RECEIVAI_DOCLING_OCR",
        "auto",
    ).strip().lower()

    if choice not in {
        "auto",
        "never",
        "always",
    }:
        raise ValueError(
            "RECEIVAI_DOCLING_OCR must be "
            "auto, never or always"
        )

    if choice == "never":
        return False, "", []

    command = os.getenv(
        "RECEIVAI_TESSERACT_CMD",
        "tesseract",
    ).strip()

    installed = shutil.which(command)

    if not installed:
        if choice == "always":
            raise RuntimeError(
                "Tesseract CLI is required for Docling OCR"
            )

        return False, "", [
            "Docling OCR unavailable: Tesseract CLI "
            "not found; scanned regions may be missing."
        ]

    return True, installed, []


# -------------------------------------------------------
# Cached Docling converter
# -------------------------------------------------------

@lru_cache(maxsize=8)
def _converter(
    mode: str,
    artifacts_path: str | None,
    ocr_enabled: bool,
    tesseract_cmd: str,
):
    """Reuse private Docling pipelines within one process."""

    from docling.datamodel.base_models import InputFormat

    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        TesseractCliOcrOptions,
    )

    from docling.document_converter import (
        DocumentConverter,
        PdfFormatOption,
    )

    options = PdfPipelineOptions(
        do_ocr=ocr_enabled,
        do_table_structure=True,
        generate_page_images=False,
        generate_picture_images=False,
        enable_remote_services=False,
        allow_external_plugins=False,
        document_timeout=DOCUMENT_TIMEOUT_SECONDS,
    )

    options.table_structure_options.mode = (
        TableFormerMode.ACCURATE
        if mode == "accurate"
        else TableFormerMode.FAST
    )

    if ocr_enabled:
        options.ocr_options = TesseractCliOcrOptions(
            lang=["eng"],
            tesseract_cmd=tesseract_cmd,
            force_full_page_ocr=False,
        )

    if artifacts_path:
        options.artifacts_path = Path(
            artifacts_path
        )

    return DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=options
            ),
        },
    )


# -------------------------------------------------------
# Raw Docling table structure
# -------------------------------------------------------

def _raw_table_structure(
    table: Any,
    dimensions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Preserve a raw table grid and original cell metadata.

    DataFrame exports can turn the first table row into headers.
    This function retains the underlying source grid instead.

    Row and column indices are zero-based.
    End offsets follow Docling's exclusive-end convention.
    """

    data = getattr(table, "data", None)

    empty_result = {
        "table_structure_available": False,
        "raw_rows": [],
        "raw_cells": [],
        "raw_row_count": None,
        "raw_column_count": None,
        "raw_cells_truncated": False,
        "raw_grid_truncated": False,
    }

    if data is None:
        return empty_result

    cells = getattr(
        data,
        "table_cells",
        None,
    )

    if cells is None:
        return empty_result

    row_count = getattr(
        data,
        "num_rows",
        0,
    )

    col_count = getattr(
        data,
        "num_cols",
        0,
    )

    if not isinstance(row_count, int) or row_count < 0:
        row_count = 0

    if not isinstance(col_count, int) or col_count < 0:
        col_count = 0

    retained_rows = min(
        row_count,
        MAX_ROWS_PER_TABLE,
    )

    retained_cols = min(
        col_count,
        MAX_COLUMNS,
    )

    grid = [
        ["" for _ in range(retained_cols)]
        for _ in range(retained_rows)
    ]

    raw_cells: list[dict[str, Any]] = []

    source_page = _provenance(
        table,
        dimensions,
    )["source_page"]

    page_height = _height_for_page(
        source_page,
        dimensions,
    )

    cell_truncated = (
        len(cells)
        > MAX_RAW_CELLS_PER_TABLE
    )

    grid_truncated = (
        row_count > MAX_ROWS_PER_TABLE
        or col_count > MAX_COLUMNS
    )

    for cell in cells[:MAX_RAW_CELLS_PER_TABLE]:

        start_row = getattr(
            cell,
            "start_row_offset_idx",
            None,
        )

        end_row = getattr(
            cell,
            "end_row_offset_idx",
            None,
        )

        start_col = getattr(
            cell,
            "start_col_offset_idx",
            None,
        )

        end_col = getattr(
            cell,
            "end_col_offset_idx",
            None,
        )

        if not all(
            isinstance(v, int) and v >= 0
            for v in (
                start_row,
                end_row,
                start_col,
                end_col,
            )
        ):
            continue

        if (
            end_row <= start_row
            or end_col <= start_col
        ):
            continue

        value = _cell_text(
            getattr(cell, "text", ""),
            MAX_CELL_CHARS,
        )

        cell_bbox = _bbox_information(
            getattr(cell, "bbox", None),
            page_height=page_height,
        )

        raw_cells.append({
            "text": value,
            "source_page": source_page,
            "start_row": start_row,
            "end_row": end_row,
            "start_col": start_col,
            "end_col": end_col,
            "row_span": getattr(
                cell,
                "row_span",
                end_row - start_row,
            ),
            "col_span": getattr(
                cell,
                "col_span",
                end_col - start_col,
            ),
            "column_header": bool(
                getattr(
                    cell,
                    "column_header",
                    False,
                )
            ),
            "row_header": bool(
                getattr(
                    cell,
                    "row_header",
                    False,
                )
            ),
            "row_section": bool(
                getattr(
                    cell,
                    "row_section",
                    False,
                )
            ),
            **cell_bbox,
        })

        # Place source text only at its original grid anchor.
        # Do not duplicate content into cells covered by a span.
        if (
            start_row < retained_rows
            and start_col < retained_cols
        ):
            grid[start_row][start_col] = value

    return {
        "table_structure_available": True,
        "raw_rows": grid,
        "raw_cells": raw_cells,
        "raw_row_count": row_count,
        "raw_column_count": col_count,
        "raw_cells_truncated": cell_truncated,
        "raw_grid_truncated": grid_truncated,
    }


# -------------------------------------------------------
# Main Docling extraction API
# -------------------------------------------------------

def extract_pdf_layout(
    pdf_path: str | Path,
    *,
    mode: str = "accurate",
    artifacts_path: str | Path | None = None,
) -> dict[str, Any]:
    """Extract layout evidence from an authorized local PDF.

    Returns both the original compatibility fields and additional
    source-table evidence for future layout fusion.

    The caller must separately authorize file and tenant access.

    All amounts are retained as source text; no AED/USD
    interpretation or conversion occurs in this module.
    """

    if mode not in {
        "accurate",
        "fast",
    }:
        raise ValueError(
            "mode must be 'accurate' or 'fast'"
        )

    path = Path(
        pdf_path
    ).expanduser().resolve(
        strict=True
    )

    page_count = _check_pdf(path)

    model_dir = None

    if artifacts_path is not None:

        model_path = Path(
            artifacts_path
        ).expanduser().resolve(
            strict=True
        )

        if not model_path.is_dir():
            raise ValueError(
                "artifacts_path must be "
                "an existing directory"
            )

        model_dir = str(
            model_path
        )

    ocr_enabled, tesseract_cmd, startup_warnings = (
        _ocr_configuration()
    )

    started = perf_counter()

    conversion = _converter(
        mode,
        model_dir,
        ocr_enabled,
        tesseract_cmd,
    ).convert(
        str(path)
    )

    status = str(
        getattr(
            conversion.status,
            "value",
            conversion.status,
        )
    ).lower()

    if status not in {
        "success",
        "partial_success",
    }:
        raise ValueError(
            "Docling conversion did not succeed: "
            f"{status}"
        )

    doc = conversion.document

    warnings: list[str] = list(
        startup_warnings
    )

    if status == "partial_success":
        warnings.append(
            "Docling reported partial conversion; "
            "administrator review required."
        )

    # ---------------------------------------------------
    # 1. Page geometry
    # ---------------------------------------------------

    dimensions = _page_dimensions(
        doc,
        page_count,
    )

    # ---------------------------------------------------
    # 2. Bounded document Markdown
    # ---------------------------------------------------

    markdown = doc.export_to_markdown()

    text_truncated = (
        len(markdown)
        > MAX_TEXT_CHARS
    )

    if text_truncated:
        warnings.append(
            "Document text was truncated; "
            "extraction may be incomplete."
        )

    markdown = markdown[
        :MAX_TEXT_CHARS
    ]

    # ---------------------------------------------------
    # 3. Structured and raw tables
    # ---------------------------------------------------

    source_tables = list(
        getattr(
            doc,
            "tables",
            [],
        ) or []
    )

    if len(source_tables) > MAX_TABLES:
        warnings.append(
            f"Only the first {MAX_TABLES} "
            "tables were retained."
        )

    tables: list[
        dict[str, Any]
    ] = []

    for index, table in enumerate(
        source_tables[:MAX_TABLES],
        start=1,
    ):

        provenance = _provenance(
            table,
            dimensions,
        )

        # Retain raw table evidence even if DataFrame export fails.
        raw_structure = _raw_table_structure(
            table,
            dimensions,
        )

        headers: list[str] = []
        rows: list[list[str]] = []
        rows_truncated = False
        columns_truncated = False
        dataframe_failed = False

        try:
            frame = table.export_to_dataframe(
                doc=doc
            )

            headers = [
                _cell_text(
                    value,
                    MAX_HEADER_CHARS,
                )
                for value in frame.columns[
                    :MAX_COLUMNS
                ]
            ]

            rows = [
                [
                    _cell_text(
                        value,
                        MAX_CELL_CHARS,
                    )
                    for value in values
                ]
                for values in frame.iloc[
                    :MAX_ROWS_PER_TABLE,
                    :MAX_COLUMNS,
                ].itertuples(
                    index=False,
                    name=None,
                )
            ]

            rows_truncated = (
                len(frame)
                > MAX_ROWS_PER_TABLE
            )

            columns_truncated = (
                len(frame.columns)
                > MAX_COLUMNS
            )

        except Exception as exc:
            dataframe_failed = True

            warnings.append(
                f"Table {index}: DataFrame export failed "
                f"({type(exc).__name__}); "
                "raw cell evidence was retained where available."
            )

        if (
            rows_truncated
            or columns_truncated
        ):
            warnings.append(
                f"Table {index}: structured rows or "
                "columns were truncated; review required."
            )

        if raw_structure[
            "raw_cells_truncated"
        ]:
            warnings.append(
                f"Table {index}: raw cells exceeded "
                "the safety limit; review required."
            )

        if raw_structure[
            "raw_grid_truncated"
        ]:
            warnings.append(
                f"Table {index}: raw grid exceeded "
                "the size limit; review required."
            )

        tables.append({
            "table_index": index,

            # Existing API fields
            **provenance,
            "headers": headers,
            "rows": rows,
            "rows_truncated": rows_truncated,
            "columns_truncated": columns_truncated,

            # Additional structural evidence
            **raw_structure,

            "dataframe_export_failed": (
                dataframe_failed
            ),
        })

    # ---------------------------------------------------
    # 4. Positioned text evidence
    # ---------------------------------------------------

    source_blocks = list(
        getattr(
            doc,
            "texts",
            [],
        ) or []
    )

    if len(source_blocks) > MAX_TEXT_BLOCKS:
        warnings.append(
            "Text blocks exceeded the retention limit; "
            "evidence may be incomplete."
        )

    text_blocks: list[
        dict[str, Any]
    ] = []

    block_truncated = False

    for item in source_blocks[
        :MAX_TEXT_BLOCKS
    ]:

        value = str(
            getattr(
                item,
                "text",
                "",
            ) or ""
        ).strip()

        if not value:
            continue

        if len(value) > MAX_BLOCK_CHARS:
            block_truncated = True

        label = getattr(
            item,
            "label",
            None,
        )

        if label is not None:
            label = str(
                getattr(
                    label,
                    "value",
                    label,
                )
            )

        text_blocks.append({
            "text": value[
                :MAX_BLOCK_CHARS
            ],
            "label": label,
            **_provenance(
                item,
                dimensions,
            ),
        })

    if block_truncated:
        warnings.append(
            "One or more source text blocks "
            "were truncated; review required."
        )

    # ---------------------------------------------------
    # 5. JSON-serializable source evidence
    # ---------------------------------------------------

    return {
        # Existing response contract
        "engine": "docling",
        "conversion_status": status,
        "processing_seconds": round(
            perf_counter() - started,
            3,
        ),
        "page_count": (
            len(doc.pages)
            if getattr(
                doc,
                "pages",
                None,
            )
            else page_count
        ),
        "text": markdown,
        "text_truncated": text_truncated,
        "text_blocks": text_blocks,
        "tables": tables,
        "ocr_enabled": ocr_enabled,
        "warnings": list(
            dict.fromkeys(warnings)
        ),

        # New additive metadata
        "layout_schema_version": "2.0",
        "primary_engine": "docling",
        "page_dimensions": dimensions,
        "table_count": len(tables),
        "text_block_count": len(text_blocks),
        "has_raw_table_structure": any(
            table.get(
                "table_structure_available",
                False,
            )
            for table in tables
        ),
        "source_currency_interpreted": False,
    }
