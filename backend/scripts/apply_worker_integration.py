
"""ReceivAI UAE - Safe Docling worker route integration.

File:
    backend/scripts/apply_worker_integration.py

Usage from project root:

    python backend/scripts/apply_worker_integration.py
        Preview only; no changes.

    python backend/scripts/apply_worker_integration.py --apply
        Back up documents.py and insert the worker integration.

    python backend/scripts/apply_worker_integration.py --check
        Check whether the integration is already installed.

Safety:
- Modifies only the known processing hook in documents.py.
- Verifies the surrounding processing function.
- Refuses unfamiliar or ambiguous source code.
- Creates a backup before writing.
- Validates Python syntax before replacing the file.
- Does not change the approval or rejection endpoints.
- Does not enable the Docling worker automatically.
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import tempfile

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]

DOCUMENTS_FILE = (
    BACKEND_ROOT
    / "app"
    / "api"
    / "routes"
    / "documents.py"
)

BACKUP_FILE = DOCUMENTS_FILE.with_name(
    "documents.py.before_docling_worker.bak"
)

TARGET_FUNCTION = "_process_document_record"

ANCHOR = (
    "        structured = "
    "document_agent.extract_document(raw_extraction)\n"
)

INTEGRATION_MARKER = (
    "# RECEIVAI_DOCLING_WORKER_INTEGRATION"
)

WORKER_HOOK = (
    "\n"
    "        # RECEIVAI_DOCLING_WORKER_INTEGRATION\n"
    "        # Optional, native-first local Docling enrichment.\n"
    "        # Existing validation and approval remain authoritative.\n"
    "        if extension == \".pdf\":\n"
    "            from app.services.document_intelligence."
    "worker_integration import (\n"
    "                enhance_document_with_worker,\n"
    "            )\n"
    "            structured = enhance_document_with_worker(\n"
    "                structured,\n"
    "                file_path,\n"
    "                storage_root,\n"
    "            )\n"
)


def _read_source() -> str:
    """Read the route without silently changing encoding."""

    if not DOCUMENTS_FILE.is_file():
        raise RuntimeError(
            "FastAPI documents.py was not found: "
            f"{DOCUMENTS_FILE}"
        )

    return DOCUMENTS_FILE.read_text(
        encoding="utf-8"
    )


def _processing_function(
    source: str,
) -> ast.FunctionDef | None:
    """Locate the expected document-processing function."""

    tree = ast.parse(
        source,
        filename=str(DOCUMENTS_FILE),
    )

    functions = [
        node
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
        and node.name == TARGET_FUNCTION
    ]

    if len(functions) != 1:
        return None

    return functions[0]


def _check_insertion_point(
    source: str,
) -> None:
    """Ensure the hook is in the expected authenticated workflow."""

    if source.count(ANCHOR) != 1:
        raise RuntimeError(
            "Expected native extraction call was not "
            "found exactly once. No changes made."
        )

    function = _processing_function(source)

    if function is None:
        raise RuntimeError(
            "Expected document processing function was "
            "not found. No changes made."
        )

    source_lines = source.splitlines(
        keepends=True
    )

    anchor_line = next(
        (
            index + 1
            for index, line in enumerate(source_lines)
            if line == ANCHOR
        ),
        None,
    )

    if (
        anchor_line is None
        or function.end_lineno is None
        or not (
            function.lineno
            < anchor_line
            < function.end_lineno
        )
    ):
        raise RuntimeError(
            "Native extraction call is not inside "
            "the expected processing function."
        )

    # These local variables are required by the hook.
    # Inspect the function before the native extraction call.
    preceding_code = "".join(
        source_lines[
            function.lineno - 1:
            anchor_line - 1
        ]
    )

    required_tokens = (
        "storage_root =",
        "file_path =",
        "extension =",
        "raw_extraction =",
    )

    for token in required_tokens:
        if token not in preceding_code:
            raise RuntimeError(
                "The processing route differs from the "
                f"expected implementation: missing {token}"
            )

    following_code = "".join(
        source_lines[
            anchor_line:
            function.end_lineno
        ]
    )

    if "structured_invoices = structured.get(" not in following_code:
        raise RuntimeError(
            "Expected structured invoice validation "
            "was not found after the insertion point."
        )


def _prepare_patch(
    source: str,
) -> str:
    """Construct the modified source without writing to disk."""

    if (
        INTEGRATION_MARKER in source
        or "enhance_document_with_worker(" in source
    ):
        raise RuntimeError(
            "A Docling worker integration already appears "
            "in documents.py. No changes made."
        )

    _check_insertion_point(source)

    patched = source.replace(
        ANCHOR,
        ANCHOR + WORKER_HOOK,
        1,
    )

    # Reject invalid Python before touching the source file.
    ast.parse(
        patched,
        filename=str(DOCUMENTS_FILE),
    )

    return patched


def _atomic_write(
    path: Path,
    content: str,
) -> None:
    """Replace a file using a temporary file in the same directory."""

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".py",
            prefix=".receivai_worker_",
            dir=path.parent,
            delete=False,
        ) as stream:
            stream.write(content)
            temporary_path = Path(stream.name)

        os.replace(
            temporary_path,
            path,
        )

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()


def check() -> int:
    """Report integration status without changing files."""

    source = _read_source()

    ast.parse(
        source,
        filename=str(DOCUMENTS_FILE),
    )

    if INTEGRATION_MARKER in source:
        print(
            "Worker integration marker is present."
        )
        print(
            "The route has valid Python syntax."
        )
        return 0

    if "enhance_document_with_worker(" in source:
        print(
            "A worker integration call already exists, "
            "but does not use the expected marker."
        )
        print(
            "Review documents.py before applying changes."
        )
        return 1

    print(
        "Worker integration is not installed."
    )

    return 0


def preview() -> int:
    """Check whether the known route can be safely patched."""

    source = _read_source()

    patched = _prepare_patch(source)

    print()
    print("RECEIVAI DOCLING INTEGRATION PREVIEW")
    print("-" * 45)
    print("Target:", DOCUMENTS_FILE)
    print("Function:", TARGET_FUNCTION)
    print("Integration: Optional PDF worker enrichment")
    print("Python syntax:", "valid")
    print("Existing validation:", "retained")
    print("Existing approval routes:", "unchanged")
    print("Backup destination:", BACKUP_FILE)
    print("Changes written:", "none")
    print()
    print("Preview completed successfully.")
    print(
        "Use --apply to create the backup and apply the patch."
    )

    assert patched != source

    return 0


def apply() -> int:
    """Create a backup and install the worker integration once."""

    source = _read_source()

    patched = _prepare_patch(source)

    if BACKUP_FILE.exists():
        raise RuntimeError(
            "The backup file already exists. "
            "No changes made. Inspect the previous "
            "integration attempt before proceeding."
        )

    # Back up the original before modifying anything.
    shutil.copy2(
        DOCUMENTS_FILE,
        BACKUP_FILE,
    )

    try:
        _atomic_write(
            DOCUMENTS_FILE,
            patched,
        )

        # Confirm that the written file remains valid Python.
        written = _read_source()

        ast.parse(
            written,
            filename=str(DOCUMENTS_FILE),
        )

        if INTEGRATION_MARKER not in written:
            raise RuntimeError(
                "Integration marker was not saved correctly."
            )

    except Exception:
        # Restore the original if installation fails.
        shutil.copy2(
            BACKUP_FILE,
            DOCUMENTS_FILE,
        )
        raise

    print()
    print("RECEIVAI DOCLING WORKER INTEGRATION")
    print("-" * 45)
    print("Status: PATCH APPLIED")
    print("Updated:", DOCUMENTS_FILE)
    print("Backup:", BACKUP_FILE)
    print()
    print(
        "The integration remains disabled until "
        "RECEIVAI_DOCLING_ENABLED=true."
    )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Safely integrate the optional persistent "
            "Docling worker into the ReceivAI document route."
        )
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--apply",
        action="store_true",
        help="Create a backup and apply the integration.",
    )

    mode.add_argument(
        "--check",
        action="store_true",
        help="Check integration status.",
    )

    args = parser.parse_args()

    try:
        if args.check:
            return check()

        if args.apply:
            return apply()

        return preview()

    except (
        RuntimeError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        print()
        print("Integration stopped safely.")
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
