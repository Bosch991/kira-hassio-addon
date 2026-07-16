"""Typed configuration loaded from environment variables and ``.env``."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    """Return the project root inferred from the installed source layout."""
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings for Kira."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Kira"
    environment: str = "development"
    log_level: str = "INFO"
    addon_mode: bool = Field(default=False, alias="KIRA_ADDON_MODE")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    stt_provider: str = Field(default="openai", alias="STT_PROVIDER")
    stt_model: str = Field(default="whisper-1", alias="STT_MODEL")
    homeassistant_url: str | None = Field(default=None, alias="HOMEASSISTANT_URL")
    homeassistant_token: str | None = Field(default=None, alias="HOMEASSISTANT_TOKEN")
    openart_api_key: str | None = Field(default=None, alias="OPENART_API_KEY")
    openart_kira_model_id: str | None = Field(
        default=None,
        alias="OPENART_KIRA_MODEL_ID",
    )
    openart_kira_style_id: str | None = Field(
        default=None,
        alias="OPENART_KIRA_STYLE_ID",
    )
    openart_kira_world_id: str | None = Field(
        default=None,
        alias="OPENART_KIRA_WORLD_ID",
    )
    openart_default_project_id: str | None = Field(
        default=None,
        alias="OPENART_DEFAULT_PROJECT_ID",
    )
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str | None = Field(default=None, alias="ELEVENLABS_VOICE_ID")
    audio_record_seconds: int = Field(default=8, alias="AUDIO_RECORD_SECONDS")
    audio_input_device: str | None = Field(default=None, alias="AUDIO_INPUT_DEVICE")
    audio_output_device: str | None = Field(default=None, alias="AUDIO_OUTPUT_DEVICE")
    kira_media_server_host: str = Field(
        default="0.0.0.0",
        alias="KIRA_MEDIA_SERVER_HOST",
    )
    kira_media_server_port: int = Field(default=8765, alias="KIRA_MEDIA_SERVER_PORT")
    kira_media_base_url: str | None = Field(default=None, alias="KIRA_MEDIA_BASE_URL")
    kira_live_notifications: bool = Field(
        default=False,
        alias="KIRA_LIVE_NOTIFICATIONS",
    )
    desktop_theme: str = Field(default="dark", alias="KIRA_DESKTOP_THEME")
    avatar_path: Path = Field(
        default=Path("assets/avatar/kira.png"),
        alias="KIRA_AVATAR_PATH",
    )
    start_minimized: bool = Field(default=False, alias="KIRA_START_MINIMIZED")
    companion_show_on_start: bool = Field(
        default=True,
        alias="KIRA_COMPANION_SHOW_ON_START",
    )
    companion_always_on_top: bool = Field(
        default=True,
        alias="KIRA_COMPANION_ALWAYS_ON_TOP",
    )
    companion_bubble_auto_hide: bool = Field(
        default=True,
        alias="KIRA_COMPANION_BUBBLE_AUTO_HIDE",
    )
    companion_size: str = Field(default="small", alias="KIRA_COMPANION_SIZE")

    root_dir: Path = Field(default_factory=project_root, alias="KIRA_ROOT_DIR")
    data_dir: Path | None = Field(default=None, alias="KIRA_DATA_DIR")
    log_dir: Path | None = Field(default=None, alias="KIRA_LOG_DIR")
    config_dir: Path | None = Field(default=None, alias="KIRA_CONFIG_DIR")
    prompts_dir: Path | None = Field(default=None, alias="KIRA_PROMPTS_DIR")
    knowledge_dir: Path | None = Field(default=None, alias="KIRA_KNOWLEDGE_DIR")
    plugins_dir: Path | None = Field(default=None, alias="KIRA_PLUGINS_DIR")
    plugin_config_dir: Path | None = Field(
        default=None,
        alias="KIRA_PLUGIN_CONFIG_DIR",
    )
    voice_dir: Path | None = Field(default=None, alias="KIRA_VOICE_DIR")
    audio_input_dir: Path | None = Field(default=None, alias="KIRA_AUDIO_INPUT_DIR")
    audio_settings_path: Path | None = Field(
        default=None,
        alias="KIRA_AUDIO_SETTINGS_PATH",
    )
    companion_settings_path: Path | None = Field(
        default=None,
        alias="KIRA_COMPANION_SETTINGS_PATH",
    )
    ha_live_events_path: Path | None = Field(
        default=None,
        alias="KIRA_HA_LIVE_EVENTS_PATH",
    )
    ha_event_filters_path: Path | None = Field(
        default=None,
        alias="KIRA_HA_EVENT_FILTERS_PATH",
    )
    ha_permissions_path: Path | None = Field(
        default=None,
        alias="KIRA_HA_PERMISSIONS_PATH",
    )
    ha_action_log_path: Path | None = Field(
        default=None,
        alias="KIRA_HA_ACTION_LOG_PATH",
    )
    profile_path: Path | None = Field(default=None, alias="KIRA_PROFILE_PATH")
    telemetry_path: Path | None = Field(default=None, alias="KIRA_TELEMETRY_PATH")
    openart_dir: Path | None = Field(default=None, alias="KIRA_OPENART_DIR")
    openart_history_path: Path | None = Field(
        default=None,
        alias="KIRA_OPENART_HISTORY_PATH",
    )
    api_host: str = Field(default="0.0.0.0", alias="KIRA_API_HOST")
    api_port: int = Field(default=8787, alias="KIRA_API_PORT")
    api_token: str | None = Field(default=None, alias="KIRA_API_TOKEN")

    def model_post_init(self, __context: object) -> None:
        """Derive project-relative paths when they are not configured."""
        if self.data_dir is None:
            self.data_dir = self.root_dir / "data"
        if self.log_dir is None:
            self.log_dir = self.root_dir / "logs"
        if self.config_dir is None:
            self.config_dir = self.root_dir / "config"
        if self.prompts_dir is None:
            self.prompts_dir = self.root_dir / "prompts"
        if self.knowledge_dir is None:
            self.knowledge_dir = self.root_dir / "knowledge"
        if self.plugins_dir is None:
            self.plugins_dir = self.root_dir / "plugins"
        if self.plugin_config_dir is None:
            self.plugin_config_dir = self.config_dir / "plugins"
        if self.voice_dir is None:
            self.voice_dir = self.data_dir / "voice"
        if self.audio_input_dir is None:
            self.audio_input_dir = self.data_dir / "audio" / "input"
        if self.audio_settings_path is None:
            self.audio_settings_path = self.data_dir / "audio" / "settings.json"
        if self.companion_settings_path is None:
            self.companion_settings_path = (
                self.data_dir / "desktop" / "companion_settings.json"
            )
        if self.ha_live_events_path is None:
            self.ha_live_events_path = (
                self.data_dir / "homeassistant" / "live_events.json"
            )
        if self.ha_event_filters_path is None:
            self.ha_event_filters_path = self.config_dir / "ha_event_filters.yaml"
        if self.ha_permissions_path is None:
            self.ha_permissions_path = self.config_dir / "ha_permissions.yaml"
        if self.ha_action_log_path is None:
            self.ha_action_log_path = (
                self.data_dir / "homeassistant" / "action_log.json"
            )
        if self.profile_path is None:
            self.profile_path = self.data_dir / "profile.json"
        if self.telemetry_path is None:
            self.telemetry_path = self.data_dir / "telemetry.json"
        if self.openart_dir is None:
            self.openart_dir = self.data_dir / "openart"
        if self.openart_history_path is None:
            self.openart_history_path = self.openart_dir / "history.json"


def load_settings() -> Settings:
    """Load settings and ensure required local directories exist."""
    settings = Settings()
    if settings.addon_mode:
        if not settings.homeassistant_url:
            settings.homeassistant_url = "http://supervisor/core"
        if not settings.homeassistant_token:
            settings.homeassistant_token = os.environ.get("SUPERVISOR_TOKEN")
    if not settings.openai_api_key:
        settings.openai_api_key = _read_env_value(
            settings.root_dir / ".env",
            "OPENAI_API_KEY",
        )
    for directory in (
        settings.data_dir,
        settings.log_dir,
        settings.config_dir,
        settings.prompts_dir,
        settings.knowledge_dir,
        settings.plugins_dir,
        settings.plugin_config_dir,
        settings.voice_dir,
        settings.audio_input_dir,
        settings.openart_dir,
    ):
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
    return settings


def _read_env_value(path: Path, name: str) -> str | None:
    """Read one dotenv value without logging or expanding secrets."""
    if not path.exists():
        return None
    prefix = f"{name}="
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value or None
    return None
