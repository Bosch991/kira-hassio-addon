"""FastAPI server for Kira platform integrations."""

from __future__ import annotations

import secrets
import time
from typing import Any

from pydantic import BaseModel, Field

from kira.addon import AddonDiagnosticsService
from kira.chat.session import ChatSession
from kira.core.app import KiraApplication
from kira.version import KIRA_VERSION


class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    message: str
    user: str = "api-user"
    source: str = "api"
    conversation_id: str | None = None
    device_id: str | None = None
    area_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class UpdateResponse(BaseModel):
    """Response body for update endpoints."""

    success: bool
    version: str
    branch: str | None = None
    commit: str | None = None
    clean: bool | None = None
    remote_status: str
    message: str


def create_api(app: KiraApplication) -> Any:
    """Create the FastAPI application."""
    from fastapi import Depends, FastAPI, Header, HTTPException, status

    api = FastAPI(title="Kira Platform API", version=KIRA_VERSION)

    def collect_plugin_health() -> tuple[bool, dict[str, bool], dict[str, str]]:
        """Collect plugin health without letting diagnostics break /health."""
        try:
            results = app.plugin_manager.health()
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            return False, {"plugin_manager": False}, {"plugin_manager": str(exc)}
        plugins = {name: result.ok for name, result in results.items()}
        details = {name: result.message for name, result in results.items()}
        return all(plugins.values()), plugins, details

    def require_bearer(authorization: str | None = Header(default=None)) -> None:
        expected = app.settings.api_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="KIRA_API_TOKEN is not configured.",
            )
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token.",
            )

    @api.get("/")
    def root() -> dict[str, str]:
        return {"name": "Kira", "version": KIRA_VERSION}

    @api.get("/health")
    def health() -> dict[str, object]:
        plugins_ok, plugins, details = collect_plugin_health()
        addon = AddonDiagnosticsService(app.settings).collect()
        return {
            "ok": plugins_ok and addon.ok,
            "version": KIRA_VERSION,
            "addon": addon.ok,
            "plugins": plugins,
            "details": details,
        }

    @api.get("/version")
    def version() -> dict[str, str]:
        return {"version": KIRA_VERSION}

    @api.get("/addon/status")
    def addon_status() -> dict[str, object]:
        return (
            AddonDiagnosticsService(app.settings)
            .collect(check_homeassistant=True)
            .as_dict()
        )

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

    @api.get("/updates/status")
    def updates_status() -> UpdateResponse:
        status_result = app.update_service.local_status()
        return UpdateResponse(
            success=True,
            version=status_result.version,
            branch=status_result.branch,
            commit=status_result.commit,
            clean=status_result.clean,
            remote_status=status_result.remote_status,
            message=status_result.message,
        )

    @api.get("/updates/check")
    def updates_check() -> UpdateResponse:
        check_result = app.update_service.check_remote()
        status_result = app.update_service.local_status(
            remote_status=check_result.remote_status
        )
        return UpdateResponse(
            success=check_result.success,
            version=status_result.version,
            branch=status_result.branch,
            commit=status_result.commit,
            clean=status_result.clean,
            remote_status=check_result.remote_status,
            message=check_result.message,
        )

    @api.post("/updates/pull", dependencies=[Depends(require_bearer)])
    def updates_pull() -> UpdateResponse:
        result = app.update_service.pull_updates()
        status_result = app.update_service.local_status()
        return UpdateResponse(
            success=result.success,
            version=result.version or status_result.version,
            branch=status_result.branch,
            commit=result.new_commit or status_result.commit,
            clean=status_result.clean,
            remote_status=status_result.remote_status,
            message=result.message,
        )

    @api.post("/updates/restart", dependencies=[Depends(require_bearer)])
    def updates_restart() -> UpdateResponse:
        status_result = app.update_service.local_status()
        return UpdateResponse(
            success=True,
            version=status_result.version,
            branch=status_result.branch,
            commit=status_result.commit,
            clean=status_result.clean,
            remote_status=status_result.remote_status,
            message=app.update_service.restart_hint(),
        )

    @api.post("/chat", dependencies=[Depends(require_bearer)])
    def chat(request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        session = ChatSession.from_app(app)
        response = session.handle_assist_message(
            request.message,
            context={
                "user": request.user,
                "source": request.source,
                "conversation_id": request.conversation_id,
                "device_id": request.device_id,
                "area_id": request.area_id,
                "metadata": request.metadata,
            },
        )
        app.telemetry.record_response_time("api.chat", time.perf_counter() - started)
        return ChatResponse(response=response)

    @api.post("/assist", dependencies=[Depends(require_bearer)])
    def assist(request: AssistRequest) -> AssistResponse:
        started = time.perf_counter()
        session = ChatSession.from_app(app)
        response = session.handle_assist_message(
            request.text,
            context={
                "user": request.user,
                "source": request.source,
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
