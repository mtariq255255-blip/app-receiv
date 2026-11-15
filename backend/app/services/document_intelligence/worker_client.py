
"""ReceivAI UAE - Persistent Docling worker HTTP client.

Communicates with the local Docling worker running in .venv-docling.

Security:
- Only IPv4 loopback connections are permitted.
- Worker authentication uses a shared secret.
- Only generated private PDF filenames are accepted.
- No PDF bytes or invoice text are sent in requests.
- Redirects and external network destinations are rejected.
- Failures never silently authorize financial actions.

This module does not start Docling, approve invoices,
or modify the database.

Public API:
    DoclingWorkerClient
    DoclingWorkerError
    get_docling_worker_client
"""

from __future__ import annotations

import hmac
import json
import os
import re
import socket

from dataclasses import dataclass
from http.client import (
    HTTPConnection,
    HTTPException,
)
from typing import Any


# Matches the filename policy in worker_server.py.
PRIVATE_PDF_FILENAME = re.compile(
    r"[a-f0-9]{32}\.pdf\Z"
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8791
DEFAULT_TIMEOUT = 120.0

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class DoclingWorkerError(RuntimeError):
    """Raised when the private Docling worker cannot return a valid result."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DoclingWorkerConfig:
    """Immutable client settings for the local Docling service."""

    host: str
    port: int
    token: str
    timeout: float


class DoclingWorkerClient:
    """Authenticated HTTP client for a loopback-only Docling worker."""

    def __init__(
        self,
        *,
        token: str,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:

        if host != DEFAULT_HOST:
            raise ValueError(
                "Docling worker connections must use 127.0.0.1"
            )

        if not isinstance(token, str) or len(token) < 32:
            raise ValueError(
                "Docling worker token must contain at least "
                "32 characters"
            )

        if not isinstance(port, int) or isinstance(port, bool):
            raise ValueError(
                "Docling worker port must be an integer"
            )

        if not 1 <= port <= 65535:
            raise ValueError(
                "Docling worker port is outside the valid range"
            )

        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not 0 < timeout <= 600
        ):
            raise ValueError(
                "Docling worker timeout must be between "
                "0 and 600 seconds"
            )

        self.config = DoclingWorkerConfig(
            host=host,
            port=port,
            token=token,
            timeout=float(timeout),
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make one authenticated local HTTP request.

        Only known endpoints are allowed. HTTP redirects
        are never followed by http.client.
        """

        if (method, endpoint) not in {
            ("GET", "/health"),
            ("POST", "/extract"),
        }:
            raise ValueError(
                "Unsupported worker request"
            )

        body: bytes | None = None

        headers = {
            "X-ReceivAI-Worker-Token": self.config.token,
            "Accept": "application/json",
            "Cache-Control": "no-store",
        }

        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")

            if len(body) > 4096:
                raise ValueError(
                    "Worker request body is too large"
                )

            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))

        connection = HTTPConnection(
            self.config.host,
            self.config.port,
            timeout=self.config.timeout,
        )

        try:
            connection.request(
                method,
                endpoint,
                body=body,
                headers=headers,
            )

            response = connection.getresponse()
            status = response.status

            # Read one byte beyond the maximum to detect
            # oversized responses without unbounded memory use.
            raw = response.read(MAX_RESPONSE_BYTES + 1)

            if len(raw) > MAX_RESPONSE_BYTES:
                raise DoclingWorkerError(
                    "Worker response exceeded the allowed size",
                    status_code=status,
                )

            # No redirects or unexpected success codes.
            if status != 200:
                raise DoclingWorkerError(
                    self._safe_error(status, raw),
                    status_code=status,
                )

            try:
                decoded = json.loads(
                    raw.decode("utf-8")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise DoclingWorkerError(
                    "Worker returned invalid JSON"
                ) from exc

            if not isinstance(decoded, dict):
                raise DoclingWorkerError(
                    "Worker returned an invalid response structure"
                )

            return decoded

        except DoclingWorkerError:
            raise

        except (
            OSError,
            socket.timeout,
            TimeoutError,
            HTTPException,
        ) as exc:
            # Avoid exposing invoice content or authentication data.
            raise DoclingWorkerError(
                "Local Docling worker is unavailable "
                "or did not respond successfully"
            ) from exc

        finally:
            connection.close()

    @staticmethod
    def _safe_error(
        status: int,
        raw: bytes,
    ) -> str:
        """Convert worker errors into bounded, generic messages."""

        allowed_errors = {
            "unauthorized",
            "not_found",
            "request_limit",
            "invalid_request",
            "extraction_failed",
            "response_limit",
        }

        try:
            payload = json.loads(
                raw.decode("utf-8")
            )

            code = (
                payload.get("error")
                if isinstance(payload, dict)
                else None
            )

            if code in allowed_errors:
                return (
                    f"Docling worker error: {code}"
                )

        except (
            ValueError,
            UnicodeDecodeError,
            TypeError,
        ):
            pass

        return (
            f"Docling worker returned HTTP {status}"
        )

    def health(self) -> bool:
        """Check whether the worker is reachable and authenticated."""

        response = self._request(
            "GET",
            "/health",
        )

        return response.get("status") == "ready"

    def extract(
        self,
        filename: str,
        *,
        mode: str = "accurate",
    ) -> dict[str, Any]:
        """Extract a private PDF using the persistent Docling service.

        filename:
            Generated private-storage filename, not an arbitrary path.

        mode:
            fast or accurate.

        Returns the Docling layout dictionary.
        """

        if (
            not isinstance(filename, str)
            or not PRIVATE_PDF_FILENAME.fullmatch(filename)
        ):
            raise ValueError(
                "Invalid private PDF filename"
            )

        if mode not in {
            "fast",
            "accurate",
        }:
            raise ValueError(
                "Mode must be 'fast' or 'accurate'"
            )

        response = self._request(
            "POST",
            "/extract",
            {
                "filename": filename,
                "mode": mode,
            },
        )

        layout = response.get("layout")

        if not isinstance(layout, dict):
            raise DoclingWorkerError(
                "Worker returned no valid layout"
            )

        if layout.get("engine") != "docling":
            raise DoclingWorkerError(
                "Unexpected document extraction engine"
            )

        if layout.get("conversion_status") not in {
            "success",
            "partial_success",
        }:
            raise DoclingWorkerError(
                "Worker did not report a successful conversion"
            )

        if not isinstance(
            layout.get("tables"),
            list,
        ):
            raise DoclingWorkerError(
                "Worker response contains invalid tables"
            )

        if not isinstance(
            layout.get("text_blocks"),
            list,
        ):
            raise DoclingWorkerError(
                "Worker response contains invalid text blocks"
            )

        return layout


def get_docling_worker_client() -> DoclingWorkerClient:
    """Build a worker client from server-side environment variables.

    Do not expose RECEIVAI_DOCLING_TOKEN to the frontend.
    """

    token = os.environ.get(
        "RECEIVAI_DOCLING_TOKEN",
        "",
    )

    port_raw = os.environ.get(
        "RECEIVAI_DOCLING_PORT",
        str(DEFAULT_PORT),
    )

    timeout_raw = os.environ.get(
        "RECEIVAI_DOCLING_TIMEOUT",
        str(DEFAULT_TIMEOUT),
    )

    try:
        port = int(port_raw)
        timeout = float(timeout_raw)

    except ValueError as exc:
        raise ValueError(
            "Invalid Docling worker environment configuration"
        ) from exc

    return DoclingWorkerClient(
        token=token,
        host=DEFAULT_HOST,
        port=port,
        timeout=timeout,
    )
