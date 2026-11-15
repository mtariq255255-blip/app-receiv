
"""Authenticated, read-only API for ReceivAI UAE's Finance Assistant.

Routes:
    POST /api/assistant/chat
    GET  /api/assistant/suggestions
    GET  /api/assistant/capabilities

This route uses the existing administrator JWT authentication and SQLAlchemy
session dependencies. It delegates all financial retrieval and analysis to the
FinanceAssistantTools and FinanceAssistantAgent from Files 2 and 3. It does not
record payments, edit invoices, approve reminders, or call an external LLM.

To activate the routes, import and include this module's ``router`` in
``backend/app/main.py``. Do not register the router twice.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.finance_assistant_agent import FinanceAssistantAgent
from app.core.database import get_db
from app.core.security import get_current_admin
from app.schemas.finance_assistant import (
    FinanceAssistantCapabilitiesResponse,
    FinanceAssistantChatRequest,
    FinanceAssistantChatResponse,
    FinanceAssistantErrorResponse,
    FinanceAssistantSuggestionsResponse,
)
from app.services.finance_assistant_tools import FinanceAssistantTools

LOGGER = logging.getLogger(__name__)


def _disable_response_cache(response: Response) -> None:
    """Sensitive financial responses must not be stored in browser/proxy caches."""
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


def _failure(
    *,
    status_code: int,
    error_code: str,
    message: str,
) -> JSONResponse:
    """Return a safe error: no database, auth or server internals in the body."""
    payload = FinanceAssistantErrorResponse(
        error_code=error_code,
        message=message,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


router = APIRouter(
    prefix="/api/assistant",
    tags=["AI Financial Assistant"],
    dependencies=[
        Depends(get_current_admin),
        Depends(_disable_response_cache),
    ],
)


@router.post(
    "/chat",
    response_model=FinanceAssistantChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a read-only question about ReceivAI financial records",
    description=(
        "Returns database-grounded invoice, payment, receivables, collection, "
        "document and forecast information. Forecast values are estimates. "
        "Requires a valid administrator bearer token. Does not change any data."
    ),
    responses={
        500: {
            "model": FinanceAssistantErrorResponse,
            "description": "Assistant service error",
        },
        503: {
            "model": FinanceAssistantErrorResponse,
            "description": "Financial data unavailable",
        },
    },
)
def finance_assistant_chat(
    payload: FinanceAssistantChatRequest,
    db: Session = Depends(get_db),
):
    """Serve one authenticated finance question using existing read-only tools.

    A fresh tool instance uses the same DB session and one UAE reporting date
    for the whole question. Chat history is optional request context only; no
    conversation data is stored by this endpoint.
    """
    try:
        tools = FinanceAssistantTools(db=db)
        agent = FinanceAssistantAgent(tools=tools)
        return agent.chat(payload)

    except SQLAlchemyError as exc:
        # Log the exception class only; avoid SQL parameters or sensitive values.
        LOGGER.error(
            "Finance assistant database access failed: %s",
            type(exc).__name__,
        )
        return _failure(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="data_unavailable",
            message=(
                "Financial records are temporarily unavailable. "
                "Please try again."
            ),
        )

    except Exception as exc:
        # Do not reflect unexpected exception messages into the client response.
        LOGGER.error(
            "Finance assistant chat failed: %s",
            type(exc).__name__,
        )
        return _failure(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="service_error",
            message="The finance assistant could not complete this request.",
        )


@router.get(
    "/suggestions",
    response_model=FinanceAssistantSuggestionsResponse,
    summary="Get suggested financial questions",
)
def finance_assistant_suggestions():
    """Provide suggested prompts from the same deterministic agent."""
    return FinanceAssistantAgent.get_suggestions()


@router.get(
    "/capabilities",
    response_model=FinanceAssistantCapabilitiesResponse,
    summary="Get Finance Assistant feature availability",
)
def finance_assistant_capabilities():
    """Describe the currently supported read-only tools and forecast horizons."""
    return FinanceAssistantAgent.get_capabilities()
