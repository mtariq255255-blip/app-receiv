
"""Private local PDF evidence extraction for ReceivAI UAE.

Preserves extract_pdf(...) / extract_pdf_text(...) and layout_pages structure.
Uses selective page OCR for sparse, suspicious or image-backed content.
Financial decisions and supplier/VAT inference belong to later modules.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from time import perf_counter
from typing import Any

import pymupdf

from app.core.config import settings
from app.services.extraction_result import build_extraction_result

logger = logging.getLogger(__name__)

MIN_NATIVE_CHARACTERS = 25
SPARSE_NATIVE_CHARACTERS = 90
MIN_NATIVE_WORDS = 8
MIN_SIGNIFICANT_IMAGE_COVERAGE = 0.12
OCR_DPI = 200


def _box(values: Any) -> list[float]:
    return [round(float(value), 2) for value in list(values)[:4]]


def _get_page_words(
    page: Any,
    textpage: Any = None,
) -> list[dict[str, Any]]:
    options: dict[str, Any] = {"sort": True}
    if textpage is not None:
        options["textpage"] = textpage
    words: list[dict[str, Any]] = []
    for word in page.get_text("words", **options):
        if len(word) < 8 or not str(word[4]).strip():
            continue
        words.append({
            "text": str(word[4]),
            "bbox": _box(word[:4]),
            "block_no": int(word[5]),
            "line_no": int(word[6]),
            "word_no": int(word[7]),
        })
    return words


def _get_page_lines(
    page: Any,
    textpage: Any = None,
) -> list[dict[str, Any]]:
    options: dict[str, Any] = {"sort": True}
    if textpage is not None:
        options["textpage"] = textpage
    content = page.get_text("dict", **options)
    lines: list[dict[str, Any]] = []
    for block_number, block in enumerate(content.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_number, line in enumerate(block.get("lines", [])):
            text = "".join(
                str(span.get("text", ""))
                for span in line.get("spans", [])
            ).strip()
            if not text:
                continue
            lines.append({
                "text": text,
                "bbox": _box(line.get("bbox", (0, 0, 0, 0))),
                "block_no": block_number,
                "line_no": line_number,
            })
    return sorted(
        lines,
        key=lambda item: (
            round(item["bbox"][1], 1),
            item["bbox"][0],
            item["block_no"],
            item["line_no"],
        ),
    )


def _get_page_tables(page: Any) -> list[dict[str, Any]]:
    if not hasattr(page, "find_tables"):
        return []
    try:
        finder = page.find_tables()
        tables: list[dict[str, Any]] = []
        for index, table in enumerate(finder.tables):
            try:
                rows = table.extract() or []
                if rows:
                    tables.append({
                        "table_index": index,
                        "bbox": _box(table.bbox),
                        "rows": rows,
                    })
            except Exception as exc:
                logger.warning(
                    "Skipping native PDF table %s (%s)",
                    index,
                    type(exc).__name__,
                )
        return tables
    except Exception as exc:
        logger.warning(
            "Native PDF table detection failed (%s)",
            type(exc).__name__,
        )
        return []


def _quality(text: str) -> tuple[int, int]:
    return (
        sum(ch.isalnum() for ch in text),
        len(text.split()),
    )


def _garbled(text: str) -> bool:
    if not text:
        return False
    bad = sum(
        ch == "\ufffd" or "\ue000" <= ch <= "\uf8ff"
        for ch in text
    )
    return bad >= 3 and bad / max(len(text), 1) >= 0.03


def _image_coverage(page: Any) -> float:
    """Approximate fraction of page covered by embedded raster images.

    A cap avoids large overlapping logos exceeding 100%; this is a routing
    hint, not a measurement of the actual amount of missing text.
    """
    area = max(float(page.rect.width * page.rect.height), 1.0)
    total = 0.0
    try:
        images = page.get_image_info(xrefs=False)
        for image in images:
            bbox = image.get("bbox")
            if not bbox:
                continue
            rect = pymupdf.Rect(bbox) & page.rect
            if not rect.is_empty:
                total += max(
                    0.0,
                    float(rect.width * rect.height),
                )
    except Exception:
        return 0.0
    return min(1.0, total / area)


def _should_try_ocr(
    native_text: str,
    native_words: list[dict[str, Any]],
    has_images: bool,
    image_coverage: float = 0.0,
) -> bool:
    characters = _quality(native_text)[0]
    return (
        characters < MIN_NATIVE_CHARACTERS
        or _garbled(native_text)
        or (
            has_images
            and (
                image_coverage >= MIN_SIGNIFICANT_IMAGE_COVERAGE
                or characters < SPARSE_NATIVE_CHARACTERS
                or len(native_words) < MIN_NATIVE_WORDS
            )
        )
    )


def _ocr_adds_evidence(
    native_words: list[dict[str, Any]],
    candidate_words: list[dict[str, Any]],
) -> bool:
    """Prefer OCR if it supplies additional word evidence."""
    original = Counter(
        re.sub(r"\W+", "", w["text"]).casefold()
        for w in native_words
    )
    observed = Counter(
        re.sub(r"\W+", "", w["text"]).casefold()
        for w in candidate_words
    )
    additional = sum((observed - original).values())
    return additional >= 1


def extract_pdf(
    file_bytes: bytes,
    filename: str = "invoice.pdf",
) -> dict:
    """Extract native text, selectively OCR pages, keep layout provenance.

    OCR failure is non-fatal and does not discard original PDF text.
    A well-populated text layer with broken tables still needs Docling routing.
    """
    if (
        not isinstance(file_bytes, bytes)
        or not file_bytes.startswith(b"%PDF-")
    ):
        raise ValueError(
            "The PDF is empty or has an invalid file signature."
        )

    started = perf_counter()
    try:
        document = pymupdf.open(
            stream=file_bytes,
            filetype="pdf",
        )
    except Exception as exc:
        raise ValueError(
            "Unable to open the PDF document."
        ) from exc

    try:
        if document.is_encrypted:
            raise ValueError(
                "Password-protected PDFs are not supported."
            )
        if document.page_count == 0:
            raise ValueError(
                "The PDF contains no pages."
            )
        if document.page_count > settings.max_pdf_pages:
            raise ValueError(
                "PDF exceeds the maximum allowed page count."
            )

        pages: list[str] = []
        layout_pages: list[dict[str, Any]] = []
        warnings: list[str] = []
        native_pages = 0
        ocr_pages = 0
        ocr_attempted_pages = 0

        for page_number, page in enumerate(
            document,
            start=1,
        ):
            native_text = page.get_text(
                "text",
                sort=True,
            ).strip()
            native_words = _get_page_words(page)
            image_coverage = _image_coverage(page)
            has_images = (
                image_coverage > 0
                or bool(page.get_images(full=False))
            )
            quality_problem = _garbled(native_text)

            text = native_text
            selected_textpage = None
            ocr_used = False
            ocr_attempted = False
            ocr_was_helpful = False

            if _should_try_ocr(
                native_text,
                native_words,
                has_images,
                image_coverage,
            ):
                ocr_attempted = True
                ocr_attempted_pages += 1
                try:
                    options: dict[str, Any] = {
                        "language": "eng",
                        "dpi": OCR_DPI,
                        # Partial OCR supplements sound digital text.
                        # Full OCR handles missing or broken text layers.
                        "full": (
                            not native_text
                            or quality_problem
                        ),
                    }
                    if settings.tesseract_data_path:
                        options["tessdata"] = (
                            settings.tesseract_data_path
                        )

                    candidate_textpage = (
                        page.get_textpage_ocr(**options)
                    )
                    candidate_text = page.get_text(
                        "text",
                        textpage=candidate_textpage,
                        sort=True,
                    ).strip()
                    candidate_words = _get_page_words(
                        page,
                        textpage=candidate_textpage,
                    )

                    ocr_was_helpful = (
                        bool(candidate_text)
                        and (
                            (
                                quality_problem
                                and not _garbled(
                                    candidate_text
                                )
                                and _quality(
                                    candidate_text
                                )[0] >= 10
                            )
                            or not native_text
                            or (
                                _quality(candidate_text)
                                >= _quality(native_text)
                                and _ocr_adds_evidence(
                                    native_words,
                                    candidate_words,
                                )
                            )
                        )
                    )

                    if ocr_was_helpful:
                        text = candidate_text
                        selected_textpage = candidate_textpage
                        ocr_used = True
                        ocr_pages += 1
                    elif (
                        not native_text
                        and not candidate_text
                    ):
                        warnings.append(
                            "No readable text found by OCR "
                            f"on page {page_number}."
                        )
                except Exception as exc:
                    logger.warning(
                        "PDF OCR unavailable or failed on page %s (%s)",
                        page_number,
                        type(exc).__name__,
                    )
                    warnings.append(
                        "OCR unavailable or failed "
                        f"on page {page_number}."
                    )

            if not ocr_used:
                native_pages += 1

            lines = _get_page_lines(
                page,
                textpage=selected_textpage,
            )
            words = (
                _get_page_words(
                    page,
                    textpage=selected_textpage,
                )
                if selected_textpage is not None
                else native_words
            )
            native_tables = (
                _get_page_tables(page)
                if native_text
                else []
            )

            layout_pages.append({
                "page_number": page_number,
                "width": round(
                    float(page.rect.width), 2
                ),
                "height": round(
                    float(page.rect.height), 2
                ),
                "lines": lines,
                "words": words,
                "tables": native_tables,
                "ocr_used": ocr_used,
                "ocr_attempted": ocr_attempted,
                "has_images": has_images,
                "image_coverage": round(
                    image_coverage, 3
                ),
                "native_text_char_count": len(
                    native_text
                ),
                "text_char_count": len(text),
                "word_count": len(words),
                "suspected_broken_text_layer": (
                    quality_problem
                ),
            })

            pages.append(
                f"--- Page {page_number} ---\n{text}"
            )
            if not text:
                warnings.append(
                    f"No readable text on page {page_number}."
                )
            if (
                has_images
                and image_coverage
                >= MIN_SIGNIFICANT_IMAGE_COVERAGE
                and not ocr_used
            ):
                warnings.append(
                    f"Page {page_number} contains substantial "
                    "image regions; verify that OCR or advanced "
                    "layout extraction captured their contents."
                )

        extraction_method = (
            "pymupdf_and_tesseract"
            if ocr_pages and native_pages
            else "tesseract_ocr"
            if ocr_pages
            else "pymupdf"
        )
        result = build_extraction_result(
            filename=filename,
            file_type="pdf",
            extraction_method=extraction_method,
            text="\n\n".join(pages),
            metadata={
                "page_count": document.page_count,
                "is_encrypted": False,
                "native_page_count": native_pages,
                "ocr_page_count": ocr_pages,
                "ocr_attempted_page_count": (
                    ocr_attempted_pages
                ),
                "extraction_duration_ms": round(
                    (perf_counter() - started)
                    * 1000,
                    1,
                ),
            },
            warnings=list(dict.fromkeys(warnings)),
        )
        result["layout_pages"] = layout_pages
        return result
    finally:
        document.close()


def extract_pdf_text(file_bytes: bytes) -> dict:
    """Preserve the earlier compact PDF text extraction API."""
    result = extract_pdf(file_bytes)
    method = result["extraction_method"]
    compatibility_method = (
        "ocr" if method == "tesseract_ocr"
        else "mixed" if method == "pymupdf_and_tesseract"
        else "native_text"
    )
    return {
        "text": result["text"][:30000],
        "extraction_method": compatibility_method,
        "page_count": result["metadata"]["page_count"],
        "warnings": result["warnings"],
    }
