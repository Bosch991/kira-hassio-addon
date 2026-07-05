"""Application startup orchestration."""

from __future__ import annotations

from kira.audio.devices import AudioDeviceManager
from kira.audio.media_server import MediaServer
from kira.audio.player import AudioPlayer
from kira.audio.recorder import AudioRecorder
from kira.audio.router import AudioRouter
from kira.audio.speech_to_text import SpeechToTextClient
from kira.backup.service import BackupService
from kira.core.config import Settings, load_settings
from kira.core.logging import configure_logging
from kira.desktop.desktop import DesktopRuntime
from kira.events.bus import EventBus
from kira.homeassistant.action_log import HomeAssistantActionLog
from kira.homeassistant.client import HomeAssistantClient
from kira.homeassistant.context import HomeAssistantContextResolver
from kira.homeassistant.events import HomeAssistantEventFilter, HomeAssistantEventStore
from kira.homeassistant.permissions import (
    HomeAssistantPermissionConfig,
    HomeAssistantPermissionEngine,
)
from kira.homeassistant.services import HomeAssistantServices
from kira.homeassistant.status import HomeStatusService
from kira.homeassistant.undo import HomeAssistantUndoPlanner
from kira.homeassistant.websocket import HomeAssistantLiveClient
from kira.homeassistant.world_model import HomeAssistantWorldModel
from kira.knowledge.base import KnowledgeBase
from kira.memory.conversation import ConversationStore
from kira.memory.store import MemoryStore
from kira.openart.client import OpenArtClient, OpenArtKiraConfig
from kira.openart.history import OpenArtHistoryStore
from kira.openart.prompt_builder import OpenArtPromptBuilder
from kira.plugins.plugin_manager import PluginManager
from kira.profile.store import ProfileStore
from kira.scheduler.scheduler import Scheduler
from kira.telemetry.store import TelemetryStore
from kira.voice.providers import ElevenLabsVoiceProvider


class KiraApplication:
    """Main application object coordinating Kira's core services."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the application with already loaded settings."""
        self.settings = settings
        self.event_bus = EventBus()
        self.telemetry = TelemetryStore(settings.telemetry_path)
        self.scheduler = Scheduler()
        self.desktop = DesktopRuntime()
        self.profile_store = ProfileStore(settings.profile_path)
        self.memory = MemoryStore(settings.data_dir / "memory.json")
        self.conversation = ConversationStore(settings.data_dir / "conversation.json")
        self.knowledge = KnowledgeBase(settings.knowledge_dir)
        self.openart_prompt_builder = OpenArtPromptBuilder(
            settings.prompts_dir / "openart_kira_style.md"
        )
        self.openart_history = OpenArtHistoryStore(settings.openart_history_path)
        self.openart = OpenArtClient(
            api_key=settings.openart_api_key,
            kira_config=OpenArtKiraConfig(
                model_id=settings.openart_kira_model_id,
                style_id=settings.openart_kira_style_id,
                world_id=settings.openart_kira_world_id,
                default_project_id=settings.openart_default_project_id,
            ),
            output_dir=settings.openart_dir,
        )
        self.homeassistant = HomeAssistantClient(
            base_url=settings.homeassistant_url,
            token=settings.homeassistant_token,
        )
        self.homeassistant_services = HomeAssistantServices(self.homeassistant)
        self.home_status = HomeStatusService(self.homeassistant)
        self.homeassistant_context = HomeAssistantContextResolver()
        self.ha_permissions = HomeAssistantPermissionEngine(
            HomeAssistantPermissionConfig.load(settings.ha_permissions_path)
        )
        self.ha_action_log = HomeAssistantActionLog(settings.ha_action_log_path)
        self.ha_event_store = HomeAssistantEventStore(settings.ha_live_events_path)
        self.ha_event_filter = HomeAssistantEventFilter.from_file(
            settings.ha_event_filters_path
        )
        self.homeassistant_live = HomeAssistantLiveClient(
            base_url=settings.homeassistant_url,
            token=settings.homeassistant_token,
            event_store=self.ha_event_store,
            event_filter=self.ha_event_filter,
            notifications_enabled=settings.kira_live_notifications,
        )
        self.homeassistant_world = HomeAssistantWorldModel(
            client=self.homeassistant,
            event_store=self.ha_event_store,
        )
        self.ha_undo = HomeAssistantUndoPlanner(
            action_log=self.ha_action_log,
            services=self.homeassistant_services,
        )
        self.voice = ElevenLabsVoiceProvider(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            output_dir=settings.voice_dir,
        )
        self.audio_recorder = AudioRecorder(
            settings.audio_input_dir,
            seconds=settings.audio_record_seconds,
            input_device=settings.audio_input_device,
        )
        self.audio_device_manager = AudioDeviceManager(settings.audio_settings_path)
        self.audio_player = AudioPlayer()
        self.media_server = MediaServer(
            root_dir=settings.voice_dir,
            host=settings.kira_media_server_host,
            port=settings.kira_media_server_port,
        )
        self.audio_router = AudioRouter(
            device_manager=self.audio_device_manager,
            player=self.audio_player,
            homeassistant=self.homeassistant,
            media_server=self.media_server,
            media_base_url=settings.kira_media_base_url,
        )
        self.speech_to_text = SpeechToTextClient(
            provider=settings.stt_provider,
            model=settings.stt_model,
            api_key=settings.openai_api_key,
        )
        self.backup = BackupService(
            root_dir=settings.root_dir,
            data_dir=settings.data_dir,
            config_dir=settings.config_dir,
        )
        self.plugin_manager = PluginManager(
            plugins_dir=settings.plugins_dir,
            config_dir=settings.plugin_config_dir,
            context=self,
        )

    def start(self) -> None:
        """Start Kira and verify that core services are ready."""
        self.memory.initialize()
        self.conversation.initialize()
        self.knowledge.reload()
        self.openart_history.initialize()
        self.ha_event_store.initialize()
        self.ha_action_log.initialize()
        self.homeassistant_world.refresh()
        self.profile_store.load()
        self.plugin_manager.load_all()
        self.telemetry.save()


def create_app() -> KiraApplication:
    """Create a configured Kira application instance."""
    settings = load_settings()
    configure_logging(settings)
    return KiraApplication(settings)


def main() -> None:
    """Run Kira from the command line."""
    from kira.core.cli import main as cli_main

    cli_main()
