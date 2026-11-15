
"""Persistent loopback-only Docling layout worker.

Start with .venv-docling. Authenticate every request, accept only generated
PDF filenames from the configured private storage directory, and never expose
raw source text to cloud services.

A dedicated process retains the Docling converter/model cache between jobs.

This is NOT a durable task queue.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import threading

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

from pathlib import Path
from typing import Any


LOG = logging.getLogger(__name__)

# Only internally generated document filenames are accepted.
FILENAME = re.compile(r"[a-f0-9]{32}\.pdf\Z")

MAX_BODY = 4096
MAX_RESULT = 8 * 1024 * 1024


def _private_file(
    storage_root: Path,
    filename: str,
) -> Path:
    """Resolve a PDF from the configured private storage directory.

    Prevent:
    - Directory traversal
    - Arbitrary absolute paths
    - Symlink access
    - Access outside private document storage
    """

    if (
        not isinstance(filename, str)
        or not FILENAME.fullmatch(filename)
    ):
        raise ValueError(
            "Invalid private PDF identifier"
        )

    root = storage_root.resolve(
        strict=True
    )

    path = root / filename

    if path.is_symlink():
        raise ValueError(
            "Symlinks are not permitted"
        )

    resolved = path.resolve(
        strict=True
    )

    if (
        resolved.parent != root
        or not resolved.is_file()
    ):
        raise ValueError(
            "File is outside private storage"
        )

    return resolved


def build_server(
    *,
    root: str,
    token: str,
    host: str = "127.0.0.1",
    port: int = 8791,
    extractor=None,
) -> ThreadingHTTPServer:
    """Create the authenticated local Docling HTTP server.

    The optional extractor allows tests to run without loading
    Docling models.
    """

    # Never expose the worker on a public network interface.
    if host != "127.0.0.1":
        raise ValueError(
            "Only the IPv4 loopback interface is supported"
        )

    if len(token) < 32:
        raise ValueError(
            "Set a random 32+ character Docling worker token"
        )

    storage_root = Path(
        root
    ).expanduser().resolve(
        strict=True
    )

    if not storage_root.is_dir():
        raise ValueError(
            "Private invoice storage directory is missing"
        )

    extract = extractor

    if extract is None:
        from .layout_engine import extract_pdf_layout

        extract = extract_pdf_layout

    # Docling model pipelines are not guaranteed thread-safe.
    # Process one extraction at a time within this worker.
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):

        def log_message(
            self,
            fmt: str,
            *args: Any,
        ) -> None:
            # Do not log PDF identifiers, invoice text or tokens.
            LOG.info(
                "Docling request completed"
            )

        def respond(
            self,
            code: int,
            body: dict,
        ) -> None:
            """Send a bounded JSON response."""

            payload = json.dumps(
                body,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")

            if len(payload) > MAX_RESULT:
                payload = (
                    b'{"error":"response_limit"}'
                )
                code = 507

            self.send_response(code)

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )

            self.send_header(
                "Cache-Control",
                "no-store",
            )

            self.send_header(
                "Content-Length",
                str(len(payload)),
            )

            self.end_headers()

            self.wfile.write(payload)

        def authenticated(self) -> bool:
            """Verify the local worker authentication token."""

            given = self.headers.get(
                "X-ReceivAI-Worker-Token",
                "",
            )

            return hmac.compare_digest(
                given,
                token,
            )

        def do_GET(self) -> None:
            """Authenticated worker health endpoint."""

            if not self.authenticated():
                self.respond(
                    401,
                    {"error": "unauthorized"},
                )
                return

            if self.path != "/health":
                self.respond(
                    404,
                    {"error": "not_found"},
                )
                return

            self.respond(
                200,
                {"status": "ready"},
            )

        def do_POST(self) -> None:
            """Handle an authenticated PDF extraction request."""

            if not self.authenticated():
                self.respond(
                    401,
                    {"error": "unauthorized"},
                )
                return

            if self.path != "/extract":
                self.respond(
                    404,
                    {"error": "not_found"},
                )
                return

            # -----------------------------------------
            # Validate request body size
            # -----------------------------------------

            try:
                size = int(
                    self.headers.get(
                        "Content-Length",
                        "-1",
                    )
                )

            except ValueError:
                size = -1

            if not 0 < size <= MAX_BODY:
                self.respond(
                    413,
                    {"error": "request_limit"},
                )
                return

            # -----------------------------------------
            # Validate requested PDF and mode
            # -----------------------------------------

            try:
                request = json.loads(
                    self.rfile.read(size)
                )

                if not isinstance(request, dict):
                    raise ValueError(
                        "Expected JSON object"
                    )

                filename = request.get(
                    "filename"
                )

                mode = request.get(
                    "mode",
                    "accurate",
                )

                if mode not in {
                    "fast",
                    "accurate",
                }:
                    raise ValueError(
                        "Unsupported mode"
                    )

                path = _private_file(
                    storage_root,
                    filename,
                )

            except (
                ValueError,
                OSError,
                json.JSONDecodeError,
            ):
                self.respond(
                    422,
                    {"error": "invalid_request"},
                )
                return

            # -----------------------------------------
            # Run persistent Docling extraction
            # -----------------------------------------

            try:
                with lock:
                    layout = extract(
                        path,
                        mode=mode,
                    )

                self.respond(
                    200,
                    {"layout": layout},
                )

            except Exception as exc:
                # Never expose raw exceptions or document data.
                LOG.error(
                    "Docling conversion failed (%s)",
                    type(exc).__name__,
                )

                self.respond(
                    500,
                    {"error": "extraction_failed"},
                )

    return ThreadingHTTPServer(
        (host, port),
        Handler,
    )


def main() -> None:
    """Start the persistent Docling worker."""

    logging.basicConfig(
        level=logging.INFO
    )

    root = os.environ.get(
        "RECEIVAI_DOCLING_STORAGE_ROOT",
        "",
    )

    token = os.environ.get(
        "RECEIVAI_DOCLING_TOKEN",
        "",
    )

    port = int(
        os.environ.get(
            "RECEIVAI_DOCLING_PORT",
            "8791",
        )
    )

    with build_server(
        root=root,
        token=token,
        port=port,
    ) as server:

        LOG.info(
            "Private Docling worker listening "
            "on loopback port %s",
            port,
        )

        server.serve_forever(
            poll_interval=0.25
        )


if __name__ == "__main__":
    main()
