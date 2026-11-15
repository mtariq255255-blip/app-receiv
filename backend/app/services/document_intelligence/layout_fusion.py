
"""Fuse Docling and PyMuPDF evidence without silently resolving conflicts.

Public API:
    fuse_layout_evidence(
        docling_layout,
        native_extraction,
        reconstruction=None,
        native_invoices=None,
    )

All inputs are already-extracted dictionaries.

Docling is the primary layout source.
PyMuPDF provides supporting text and coordinates.

This module performs no OCR, file I/O, currency conversion,
tax inference, financial calculation or invoice approval.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any


MAX_PAGES = 25
MAX_NATIVE_LINES = 2500
MAX_DOCLING_BLOCKS = 1500
MAX_ITEMS = 1000
MAX_EVIDENCE_MATCHES = 3

MAX_MATCH_DISTANCE = 55.0


FIELD_NAMES = (
    "invoice_number",
    "supplier_name",
    "supplier_trn",
    "customer_name",
    "customer_trn",
    "issue_date",
    "supply_date",
    "due_date",
    "currency",
    "subtotal_aed",
    "discount_aed",
    "vat_amount_aed",
    "total_amount_aed",
)


AMOUNT_FIELDS = {
    "subtotal_aed",
    "discount_aed",
    "vat_amount_aed",
    "total_amount_aed",
}


def _text(value: Any) -> str:
    """Normalize source text without changing its meaning."""

    return " ".join(
        str(
            value if value is not None else ""
        ).split()
    )


def _tokens(value: Any) -> set[str]:
    """Extract meaningful tokens for independent text matching."""

    ignored = {
        "the",
        "and",
        "for",
        "with",
        "per",
        "of",
        "in",
    }

    return {
        word
        for word in re.findall(
            r"[a-z0-9]+",
            _text(value).casefold(),
        )
        if len(word) >= 2
        and word not in ignored
    }


def _bbox(
    value: Any,
) -> list[float] | None:
    """Validate a top-left-oriented bounding box."""

    if (
        not isinstance(
            value,
            (list, tuple),
        )
        or len(value) != 4
    ):
        return None

    try:
        result = [
            float(v)
            for v in value
        ]

        if not all(
            math.isfinite(v)
            for v in result
        ):
            return None

        x0, y0, x1, y1 = result

        if x1 < x0 or y1 < y0:
            return None

        return [
            round(v, 2)
            for v in result
        ]

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):
        return None


def _page(
    value: Any,
) -> int | None:
    """Accept only valid one-based source page numbers."""

    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    ):
        return value

    return None


def _center_distance(
    a: list[float],
    b: list[float],
) -> float:
    """Calculate distance between two rectangle centers."""

    ax = (
        a[0] + a[2]
    ) / 2

    ay = (
        a[1] + a[3]
    ) / 2

    bx = (
        b[0] + b[2]
    ) / 2

    by = (
        b[1] + b[3]
    ) / 2

    return (
        (ax - bx) ** 2
        + (ay - by) ** 2
    ) ** 0.5


def _normalize_value(
    field: str,
    value: Any,
) -> str | None:
    """Normalize candidate values for conflict comparison."""

    if value is None or value == "":
        return None

    raw = _text(value)

    if field == "currency":
        return raw.upper()

    if field in AMOUNT_FIELDS:

        try:
            number = Decimal(
                raw.replace(",", "")
                .replace("AED", "")
                .strip()
            )

            if number.is_finite():
                return str(number)

        except InvalidOperation:
            pass

    return raw.casefold()


def _native_lines(
    native: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract bounded PyMuPDF text-line evidence."""

    output: list[dict[str, Any]] = []

    for page in (
        native.get("layout_pages") or []
    )[:MAX_PAGES]:

        if not isinstance(page, dict):
            continue

        number = _page(
            page.get("page_number")
        )

        for line in (
            page.get("lines") or []
        ):

            if len(output) >= MAX_NATIVE_LINES:
                return output

            if (
                not isinstance(line, dict)
                or not _text(
                    line.get("text")
                )
            ):
                continue

            output.append({
                "engine": "pymupdf",
                "source_page": number,
                "text": _text(
                    line.get("text")
                ),
                "bbox_top_left": _bbox(
                    line.get("bbox")
                ),
            })

    return output


def _docling_blocks(
    docling: dict[str, Any],
) -> list[dict[str, Any]]:
    """Read Docling text-block evidence and normalized geometry."""

    output: list[dict[str, Any]] = []

    for block in (
        docling.get("text_blocks") or []
    )[:MAX_DOCLING_BLOCKS]:

        if (
            not isinstance(block, dict)
            or not _text(
                block.get("text")
            )
        ):
            continue

        output.append({
            "engine": "docling",
            "source_page": _page(
                block.get("source_page")
            ),
            "text": _text(
                block.get("text")
            ),
            # Do not interpret Docling's original
            # bbox as top-left when its origin is unknown.
            "bbox_top_left": _bbox(
                block.get("bbox_top_left")
            ),
            "bbox_original": deepcopy(
                block.get("bbox")
            ),
            "bbox_origin": block.get(
                "bbox_origin"
            ),
            "label": block.get("label"),
        })

    return output


def _matches(
    query: str,
    page: int | None,
    docling_bbox: list[float] | None,
    native_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match Docling text against PyMuPDF source lines.

    Matching uses text overlap and, when available,
    normalized page coordinates.

    Matches are evidence suggestions, not validation
    or proof that all source text was recovered.
    """

    terms = _tokens(query)

    if not terms:
        return []

    candidates = []

    for line in native_lines:

        if (
            page is not None
            and line["source_page"] != page
        ):
            continue

        other = _tokens(
            line["text"]
        )

        if not other:
            continue

        overlap = len(
            terms & other
        )

        if overlap < min(
            2,
            len(terms),
        ):
            continue

        score = (
            overlap
            / len(terms | other)
        )

        if score < 0.35:
            continue

        distance = None

        if (
            docling_bbox is not None
            and line["bbox_top_left"] is not None
        ):
            distance = _center_distance(
                docling_bbox,
                line["bbox_top_left"],
            )

            if distance > MAX_MATCH_DISTANCE:
                continue

        candidates.append((
            score,
            (
                distance
                if distance is not None
                else 1e6
            ),
            line,
        ))

    candidates.sort(
        key=lambda result: (
            -result[0],
            result[1],
        )
    )

    return [
        {
            **deepcopy(line),
            "text_similarity": round(
                score,
                3,
            ),
            "coordinate_distance_points": (
                round(distance, 2)
                if distance < 1e6
                else None
            ),
        }
        for score, distance, line in candidates[
            :MAX_EVIDENCE_MATCHES
        ]
    ]


def _item_bbox_from_cells(
    docling: dict[str, Any],
    item: dict[str, Any],
) -> list[float] | None:
    """Find the original Docling description-cell bounding box.

    Reconstructed source_rows are zero-based indices
    into the original raw Docling table grid.
    """

    table_id = item.get(
        "source_table"
    )

    rows = (
        item.get("source_rows") or []
    )

    if not isinstance(rows, list):
        return None

    for table in (
        docling.get("tables") or []
    ):

        if (
            not isinstance(table, dict)
            or table.get("table_index")
            != table_id
        ):
            continue

        candidates = []

        for cell in (
            table.get("raw_cells") or []
        ):

            if (
                not isinstance(cell, dict)
                or cell.get("start_row")
                not in rows
            ):
                continue

            box = _bbox(
                cell.get("bbox_top_left")
            )

            if (
                box is not None
                and _text(
                    cell.get("text")
                )
            ):
                candidates.append((
                    cell.get("start_row"),
                    cell.get(
                        "start_col",
                        99,
                    ),
                    box,
                ))

        if candidates:
            return min(
                candidates,
                key=lambda candidate: (
                    candidate[0],
                    candidate[1],
                ),
            )[2]

    return None


def _find_docling_items(
    reconstruction: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return bounded Docling-first reconstructed items."""

    if reconstruction is None:
        return []

    values = (
        reconstruction.get("items")
        or []
    )

    return (
        values[:MAX_ITEMS]
        if isinstance(values, list)
        else []
    )


def fuse_layout_evidence(
    docling_layout: dict[str, Any],
    native_extraction: dict[str, Any],
    reconstruction: dict[str, Any] | None = None,
    native_invoices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine Docling and PyMuPDF evidence conservatively.

    Docling reconstructed items are the primary
    candidate invoice lines.

    Native invoice fields are retained as independent
    candidates and never automatically overwrite
    Docling values.

    Input dictionaries are not mutated.

    Results remain in original source currency.
    """

    # --------------------------------------------------
    # 1. Validate arguments
    # --------------------------------------------------

    if (
        not isinstance(
            docling_layout,
            dict,
        )
        or not isinstance(
            native_extraction,
            dict,
        )
    ):
        raise TypeError(
            "docling_layout and native_extraction "
            "must be dictionaries"
        )

    if (
        reconstruction is not None
        and not isinstance(
            reconstruction,
            dict,
        )
    ):
        raise TypeError(
            "reconstruction must be a "
            "dictionary or None"
        )

    if (
        native_invoices is not None
        and not isinstance(
            native_invoices,
            list,
        )
    ):
        raise TypeError(
            "native_invoices must be "
            "a list or None"
        )

    warnings: list[str] = []
    conflicts: list[dict[str, Any]] = []

    candidates: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    # --------------------------------------------------
    # 2. Load engine evidence
    # --------------------------------------------------

    docling_lines = _docling_blocks(
        docling_layout
    )

    native_lines = _native_lines(
        native_extraction
    )

    layout_pages = (
        native_extraction.get(
            "layout_pages"
        ) or []
    )

    dimensions = (
        docling_layout.get(
            "page_dimensions"
        ) or []
    )

    # --------------------------------------------------
    # 3. Normalize page metadata
    # --------------------------------------------------

    page_numbers = {
        _page(
            value.get("page_number")
        )
        for value in (
            layout_pages + dimensions
        )
        if isinstance(value, dict)
    }

    page_numbers.discard(None)

    if not page_numbers:
        count = max(
            int(
                docling_layout.get(
                    "page_count"
                ) or 0
            ),
            len(layout_pages),
        )

        page_numbers = set(
            range(
                1,
                min(
                    count,
                    MAX_PAGES,
                ) + 1,
            )
        )

    pages = []

    for page_no in sorted(
        page_numbers
    )[:MAX_PAGES]:

        doc_dim = next(
            (
                value
                for value in dimensions
                if (
                    isinstance(value, dict)
                    and value.get(
                        "page_number"
                    ) == page_no
                )
            ),
            {},
        )

        native_page = next(
            (
                value
                for value in layout_pages
                if (
                    isinstance(value, dict)
                    and value.get(
                        "page_number"
                    ) == page_no
                )
            ),
            {},
        )

        dw = doc_dim.get("width")
        dh = doc_dim.get("height")

        nw = native_page.get("width")
        nh = native_page.get("height")

        if all(
            isinstance(
                value,
                (int, float),
            )
            and value > 0
            for value in (
                dw,
                dh,
                nw,
                nh,
            )
        ):

            if (
                abs(dw - nw) > 2
                or abs(dh - nh) > 2
            ):
                warnings.append(
                    f"Page {page_no}: Docling and "
                    "PyMuPDF page dimensions differ; "
                    "coordinate matches need review."
                )

        pages.append({
            "page_number": page_no,
            "docling_width": dw,
            "docling_height": dh,
            "pymupdf_width": nw,
            "pymupdf_height": nh,
            "docling_text_block_count": sum(
                block["source_page"]
                == page_no
                for block in docling_lines
            ),
            "pymupdf_line_count": sum(
                line["source_page"]
                == page_no
                for line in native_lines
            ),
        })

    # --------------------------------------------------
    # 4. Retain native invoice field candidates
    # --------------------------------------------------

    for index, invoice in enumerate(
        (native_invoices or [])[:20],
        start=1,
    ):

        if not isinstance(invoice, dict):
            continue

        for field in FIELD_NAMES:
            value = invoice.get(
                field
            )

            if (
                value is not None
                and value != ""
            ):
                candidates.setdefault(
                    field,
                    [],
                ).append({
                    "value": deepcopy(
                        value
                    ),
                    "engine": (
                        "pymupdf_native_parser"
                    ),
                    "invoice_index": index,
                    "source_page": _page(
                        invoice.get(
                            "source_page"
                        )
                    ),
                })

    # --------------------------------------------------
    # 5. Check native candidate disagreements
    # --------------------------------------------------

    for field, options in candidates.items():

        distinct = {
            _normalize_value(
                field,
                candidate["value"],
            )
            for candidate in options
        }

        if len(distinct) > 1:
            conflicts.append({
                "type": "field_disagreement",
                "field": field,
                "candidates": deepcopy(
                    options
                ),
                "requires_review": True,
            })

    # --------------------------------------------------
    # 6. Enrich Docling reconstructed items
    # --------------------------------------------------

    items = []

    source_items = _find_docling_items(
        reconstruction
    )

    for index, source_item in enumerate(
        source_items,
        start=1,
    ):

        if not isinstance(
            source_item,
            dict,
        ):
            warnings.append(
                f"Reconstructed item {index} "
                "has invalid structure."
            )
            continue

        item = deepcopy(
            source_item
        )

        page = _page(
            item.get("source_page")
        )

        box = _item_bbox_from_cells(
            docling_layout,
            item,
        )

        item["evidence"] = {
            "primary_engine": "docling",
            "source_page": page,
            "source_table": item.get(
                "source_table"
            ),
            "source_rows": deepcopy(
                item.get(
                    "source_rows"
                ) or []
            ),
            "description_bbox_top_left": (
                box
            ),
            "native_text_matches": _matches(
                item.get(
                    "description",
                    "",
                ),
                page,
                box,
                native_lines,
            ),
        }

        items.append(item)

    # --------------------------------------------------
    # 7. Collect warnings
    # --------------------------------------------------

    if reconstruction is not None:
        warnings.extend(
            str(warning)
            for warning in (
                reconstruction.get(
                    "warnings"
                ) or []
            )
        )

    warnings.extend(
        str(warning)
        for warning in (
            docling_layout.get(
                "warnings"
            ) or []
        )
    )

    warnings.extend(
        str(warning)
        for warning in (
            native_extraction.get(
                "warnings"
            ) or []
        )
    )

    if not items:
        warnings.append(
            "No reconstructed Docling line items; "
            "review raw layout tables."
        )

    # --------------------------------------------------
    # 8. Return source-aware fusion evidence
    # --------------------------------------------------

    return {
        "fusion_schema_version": "1.0",

        "primary_engine": "docling",

        "supporting_engine": "pymupdf",

        "pages": pages,

        "items": items,

        "field_candidates": candidates,

        "conflicts": conflicts,

        "warnings": list(
            dict.fromkeys(warnings)
        ),

        "requires_review": bool(
            conflicts or warnings
        ),

        # Preserve original evidence independently.
        "raw_evidence": {
            "docling": deepcopy(
                docling_layout
            ),
            "pymupdf": deepcopy(
                native_extraction
            ),
            "reconstruction": deepcopy(
                reconstruction
            ),
        },
    }


# Shorter public alias.
fuse_layouts = fuse_layout_evidence
