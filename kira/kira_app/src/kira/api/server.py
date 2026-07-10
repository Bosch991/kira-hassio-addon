"""FastAPI server for Kira platform integrations."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from kira.chat.session import ChatSession
from kira.core.app import KiraApplication

KIRA_VERSION = "1.6.0"


class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    message: str


class ChatResponse(BaseModel):
    """Response body for POST /chat."""

    response: str


class AssistRequest(BaseModel):
    """Request body for POST /assist."""

    text: str
    user: str = "unknown"
    source: str = "api"
    conversation_id: str | None = None
    output_target: str | None = None
    device_id: str | None = None
    agent_id: str | None = None
    area_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssistResponse(BaseModel):
    """Response body for POST /assist."""

    response: str
    handled: bool = True
    speak: bool = False
    output_target: str | None = None


def create_api(app: KiraApplication) -> Any:
    """Create the FastAPI application."""
    from fastapi import Depends, FastAPI, Header, HTTPException, status

    api = FastAPI(title="Kira Platform API", version=KIRA_VERSION)

    def require_bearer(authorization: str | None = Header(default=None)) -> None:
        expected = app.settings.api_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="KIRA_API_TOKEN is not configured.",
            )
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token.",
            )

    @api.get("/")
    def root() -> dict[str, str]:
        return {"name": "Kira", "version": KIRA_VERSION}

    @api.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "version": KIRA_VERSION,
            "plugins": {
                name: result.ok for name, result in app.plugin_manager.health().items()
            },
        }

    @api.get("/version")
    def version() -> dict[str, str]:
        return {"version": KIRA_VERSION}

    @api.get("/plugins")
    def plugins() -> list[dict[str, object]]:
        return [
            {
                "name": record.manifest.name,
                "version": record.manifest.version,
                "description": record.manifest.description,
                "state": record.state,
                "error": record.error,
            }
            for record in app.plugin_manager.list_plugins()
        ]

    @api.post("/chat", dependencies=[Depends(require_bearer)])
    def chat(request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        session = ChatSession.from_app(app)
        response = session.handle_message(request.message)
        app.telemetry.record_response_time("api.chat", time.perf_counter() - started)
        return ChatResponse(response=response)

    @api.post("/assist", dependencies=[Depends(require_bearer)])
    def assist(request: AssistRequest) -> AssistResponse:
        started = time.perf_counter()
        session = ChatSession.from_app(app)
        response = session.handle_assist_message(
            request.text,
            context={
                "device_id": request.device_id,
                "conversation_id": request.conversation_id,
                "agent_id": request.agent_id,
                "area_id": request.area_id,
                "metadata": request.metadata,
            },
        )
        output_target = request.output_target
        speak = False
        if output_target:
            speak = session.speak_to_target(output_target, response)
        app.telemetry.record_response_time("api.assist", time.perf_counter() - started)
        return AssistResponse(
            response=response,
            handled=True,
            speak=speak,
            output_target=output_target,
        )

    return api
