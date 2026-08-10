"""Diagnostics for Kira running as a Home Assistant add-on."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kira.core.config import Settings
from kira.homeassistant.client import HomeAssistantClient, HomeAssistantStatus
from kira.version import KIRA_VERSION


@dataclass(frozen=True, slots=True)
class AddonDiagnosticLine:
    """One add-on diagnostic item."""

    name: str
    ok: bool
    level: str
    message: str


@dataclass(frozen=True, slots=True)
class AddonDiagnostics:
    """Add-on diagnostic summary safe for API responses."""

    ok: bool
    version: str
    addon_mode: bool
    checks: list[AddonDiagnosticLine] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """Return JSON-serializable diagnostics."""
        return {
            "ok": self.ok,
            "version": self.version,
            "addon_mode": self.addon_mode,
            "checks": [
                {
                    "name": check.name,
                    "ok": check.ok,
                    "level": check.level,
                    "message": check.message,
                }
                for check in self.checks
            ],
        }


class AddonDiagnosticsService:
    """Build add-on diagnostics without exposing secrets."""

    def __init__(
        self,
        settings: Settings,
        *,
        homeassistant_client: HomeAssistantClient | None = None,
    ) -> None:
        """Initialize diagnostics with runtime settings."""
        self.settings = settings
        self.homeassistant_client = homeassistant_client

    def collect(self, *, check_homeassistant: bool = False) -> AddonDiagnostics:
        """Collect add-on stability checks."""
        checks = [
            self._addon_mode_check(),
            self._supervisor_token_check(),
            self._api_token_check(),
            self._path_check("data_dir", self.settings.data_dir),
            self._path_check("config_dir", self.settings.config_dir),
            self._path_check("log_dir", self.settings.log_dir),
            self._path_check("voice_dir", self.settings.voice_dir),
            self._media_target_check(),
        ]
        if check_homeassistant:
            checks.append(self._homeassistant_api_check())
        ok = all(check.ok for check in checks if check.level == "error")
        return AddonDiagnostics(
            ok=ok,
            version=KIRA_VERSION,
            addon_mode=self.settings.addon_mode,
            checks=checks,
        )

    def _addon_mode_check(self) -> AddonDiagnosticLine:
        if self.settings.addon_mode:
            return AddonDiagnosticLine(
                "addon_mode",
                True,
                "info",
                "Kira laeuft im Home-Assistant-Add-on-Modus.",
            )
        return AddonDiagnosticLine(
            "addon_mode",
            True,
            "warning",
            "Kira laeuft nicht im Add-on-Modus.",
        )

    def _supervisor_token_check(self) -> AddonDiagnosticLine:
        configured = bool(self.settings.homeassistant_token)
        if configured:
            return AddonDiagnosticLine(
                "supervisor_token",
                True,
                "info",
                "Supervisor/Home-Assistant-Token ist gesetzt.",
            )
        level = "error" if self.settings.addon_mode else "warning"
        return AddonDiagnosticLine(
            "supervisor_token",
            False,
            level,
            "Supervisor/Home-Assistant-Token fehlt.",
        )

    def _api_token_check(self) -> AddonDiagnosticLine:
        if self.settings.api_token:
            return AddonDiagnosticLine(
                "api_token",
                True,
                "info",
                "Kira API Token ist gesetzt.",
            )
        return AddonDiagnosticLine(
            "api_token",
            True,
            "warning",
            "KIRA_API_TOKEN fehlt; /chat und /assist lehnen externe POSTs ab.",
        )

    def _path_check(self, name: str, path: Path | None) -> AddonDiagnosticLine:
        if path is None:
            return AddonDiagnosticLine(name, False, "error", "Pfad ist nicht gesetzt.")
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".kira-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError:
            return AddonDiagnosticLine(
                name,
                False,
                "error",
                f"{path} ist nicht beschreibbar.",
            )
        return AddonDiagnosticLine(name, True, "info", f"{path} ist beschreibbar.")

    def _media_target_check(self) -> AddonDiagnosticLine:
        configured = bool(self.settings.kira_media_base_url)
        if configured:
            return AddonDiagnosticLine(
                "media_base_url",
                True,
                "info",
                "Media Base URL ist gesetzt.",
            )
        return AddonDiagnosticLine(
            "media_base_url",
            True,
            "warning",
            "Media Base URL fehlt; HA-media_player kann lokale MP3s ggf. nicht laden.",
        )

    def _homeassistant_api_check(self) -> AddonDiagnosticLine:
        client = self.homeassistant_client or HomeAssistantClient(
            base_url=self.settings.homeassistant_url,
            token=self.settings.homeassistant_token,
            timeout=5.0,
        )
        result = client.ping()
        if result.ok:
            return AddonDiagnosticLine(
                "homeassistant_api",
                True,
                "info",
                "Home-Assistant-Core-API ist erreichbar.",
            )
        if result.status is HomeAssistantStatus.AUTHENTICATION_ERROR:
            return AddonDiagnosticLine(
                "homeassistant_api",
                False,
                "error",
                "Home Assistant lehnt den Token ab.",
            )
        if result.status is HomeAssistantStatus.NOT_CONFIGURED:
            return AddonDiagnosticLine(
                "homeassistant_api",
                False,
                "error",
                "HOMEASSISTANT_URL oder HOMEASSISTANT_TOKEN fehlt.",
            )
        return AddonDiagnosticLine(
            "homeassistant_api",
            True,
            "warning",
            f"Home Assistant ist gerade nicht erreichbar: {result.status.value}.",
        )


def diagnostics_as_dict(settings: Settings) -> dict[str, Any]:
    """Return diagnostics as a plain dictionary."""
    return AddonDiagnosticsService(settings).collect().as_dict()
