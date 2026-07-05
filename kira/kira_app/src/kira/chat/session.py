"""Interactive local chat session."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console

from kira.audio.devices import AudioDevice, AudioDeviceManager
from kira.audio.media_server import MediaServer
from kira.audio.recorder import AudioRecorder, RecordingResult, RecordingStatus
from kira.audio.router import AudioRouter, AudioRouteResult, AudioRouteStatus
from kira.audio.speech_to_text import (
    SpeechToTextClient,
    SpeechToTextResult,
    SpeechToTextStatus,
)
from kira.backup.service import BackupService
from kira.chat.parser import ChatCommand, parse_input
from kira.core.config import Settings
from kira.core.prompts import load_system_prompt
from kira.events.bus import EventBus
from kira.events.events import ChatMessageReceived
from kira.homeassistant.action_log import HomeAssistantActionLog
from kira.homeassistant.analysis import (
    EntityView,
    HomeAssistantAnalysis,
    HomeAssistantAnalyzer,
)
from kira.homeassistant.client import (
    HomeAssistantClient,
    HomeAssistantResult,
    HomeAssistantStatus,
    HomeAssistantSummary,
)
from kira.homeassistant.context import AssistOrigin, HomeAssistantContextResolver
from kira.homeassistant.events import HomeAssistantLiveEvent
from kira.homeassistant.media_players import MediaPlayerMatcher, MediaPlayerView
from kira.homeassistant.permissions import (
    HomeAssistantPermissionConfig,
    HomeAssistantPermissionEngine,
    PermissionDecision,
)
from kira.homeassistant.services import HomeAssistantServices
from kira.homeassistant.status import HomeStatusService
from kira.homeassistant.undo import HomeAssistantUndoPlanner
from kira.homeassistant.websocket import HomeAssistantLiveClient
from kira.homeassistant.world_model import HomeAssistantWorldModel
from kira.knowledge.base import KnowledgeBase
from kira.memory.conversation import ConversationStore
from kira.memory.models import MemoryItem
from kira.memory.store import MemoryStore
from kira.openai.client import OpenAIChatResult, OpenAIChatStatus, OpenAIClient
from kira.openart.client import OpenArtClient, OpenArtResult, OpenArtStatus
from kira.openart.history import OpenArtHistoryStore
from kira.openart.prompt_builder import OpenArtPromptBuilder
from kira.plugins.plugin_manager import PluginManager
from kira.telemetry.store import TelemetryStore
from kira.voice.providers import ElevenLabsVoiceProvider, VoiceResult, VoiceStatus

InputFn = Callable[[str], str]


class ChatSession:
    """Run Kira's local terminal chat."""

    def __init__(
        self,
        *,
        settings: Settings,
        memory: MemoryStore,
        conversation: ConversationStore,
        knowledge: KnowledgeBase,
        homeassistant: HomeAssistantClient,
        homeassistant_live: HomeAssistantLiveClient,
        voice: ElevenLabsVoiceProvider,
        audio_recorder: AudioRecorder,
        audio_device_manager: AudioDeviceManager,
        audio_router: AudioRouter,
        media_server: MediaServer,
        speech_to_text: SpeechToTextClient,
        homeassistant_services: HomeAssistantServices | None = None,
        home_status: HomeStatusService | None = None,
        homeassistant_context: HomeAssistantContextResolver | None = None,
        ha_permissions: HomeAssistantPermissionEngine | None = None,
        ha_action_log: HomeAssistantActionLog | None = None,
        ha_undo: HomeAssistantUndoPlanner | None = None,
        homeassistant_world: HomeAssistantWorldModel | None = None,
        openart: OpenArtClient | None = None,
        openart_prompt_builder: OpenArtPromptBuilder | None = None,
        openart_history: OpenArtHistoryStore | None = None,
        plugin_manager: PluginManager | None = None,
        backup_service: BackupService | None = None,
        event_bus: EventBus | None = None,
        telemetry: TelemetryStore | None = None,
        console: Console | None = None,
        input_fn: InputFn = input,
        openai_client: OpenAIClient | None = None,
    ) -> None:
        """Initialize a chat session with runtime dependencies."""
        self.settings = settings
        self.memory = memory
        self.conversation = conversation
        self.knowledge = knowledge
        self.homeassistant = homeassistant
        self.homeassistant_services = homeassistant_services or HomeAssistantServices(
            homeassistant
        )
        self.home_status = home_status or HomeStatusService(homeassistant)
        self.homeassistant_context = (
            homeassistant_context or HomeAssistantContextResolver()
        )
        self.ha_permissions = ha_permissions or HomeAssistantPermissionEngine(
            HomeAssistantPermissionConfig.default()
        )
        self.ha_action_log = ha_action_log or HomeAssistantActionLog(
            settings.data_dir / "homeassistant" / "action_log.json"
        )
        self.ha_undo = ha_undo or HomeAssistantUndoPlanner(
            action_log=self.ha_action_log,
            services=self.homeassistant_services,
        )
        self.homeassistant_world = homeassistant_world or HomeAssistantWorldModel(
            client=homeassistant
        )
        self.homeassistant_live = homeassistant_live
        self.voice = voice
        self.audio_recorder = audio_recorder
        self.audio_device_manager = audio_device_manager
        self.audio_router = audio_router
        self.media_server = media_server
        self.speech_to_text = speech_to_text
        self.openart = openart
        self.openart_prompt_builder = openart_prompt_builder
        self.openart_history = openart_history
        self.plugin_manager = plugin_manager
        self.backup_service = backup_service
        self.event_bus = event_bus
        self.telemetry = telemetry
        self.ha_analyzer = HomeAssistantAnalyzer()
        self.media_player_matcher = MediaPlayerMatcher()
        self.console = console or Console()
        self.input_fn = input_fn
        self.openai_client = openai_client or OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
        self.system_prompt = load_system_prompt(settings)
        self.total_tokens: int = 0
        self.last_response: str | None = None
        self.logger = logging.getLogger(__name__)
        self.session_log: TextIO | None = None

    @classmethod
    def from_app(cls, app: Any) -> ChatSession:
        """Create a chat session from a KiraApplication-like object."""
        return cls(
            settings=app.settings,
            memory=app.memory,
            conversation=app.conversation,
            knowledge=app.knowledge,
            homeassistant=app.homeassistant,
            homeassistant_services=getattr(app, "homeassistant_services", None),
            home_status=getattr(app, "home_status", None),
            homeassistant_context=getattr(app, "homeassistant_context", None),
            ha_permissions=getattr(app, "ha_permissions", None),
            ha_action_log=getattr(app, "ha_action_log", None),
            ha_undo=getattr(app, "ha_undo", None),
            homeassistant_world=getattr(app, "homeassistant_world", None),
            homeassistant_live=app.homeassistant_live,
            voice=app.voice,
            audio_recorder=app.audio_recorder,
            audio_device_manager=app.audio_device_manager,
            audio_router=app.audio_router,
            media_server=app.media_server,
            speech_to_text=app.speech_to_text,
            openart=app.openart,
            openart_prompt_builder=app.openart_prompt_builder,
            openart_history=app.openart_history,
            plugin_manager=app.plugin_manager,
            backup_service=app.backup,
            event_bus=app.event_bus,
            telemetry=app.telemetry,
        )

    def run(self) -> None:
        """Start the interactive terminal chat loop."""
        self.memory.initialize()
        self.conversation.initialize()
        self.knowledge.reload()
        with self._open_session_log() as session_log:
            self.session_log = session_log
            self._print_welcome()
            self._write_session_line("system", "Chat session started.")

            while True:
                try:
                    raw_input = self.input_fn("Du: ")
                except EOFError:
                    self._respond("Bis bald. Ich beende die Session.")
                    break

                parsed = parse_input(raw_input)
                self._write_session_line("user", raw_input)

                if parsed.command is ChatCommand.EXIT:
                    self._respond("Bis bald. Ich bin hier, wenn du weiterbauen willst.")
                    break
                if parsed.command is ChatCommand.ABOUT:
                    self._show_about()
                    continue
                if parsed.command is ChatCommand.AUDIO:
                    self._handle_audio(parsed.text)
                    continue
                if parsed.command is ChatCommand.BACKUP:
                    self._backup()
                    continue
                if parsed.command is ChatCommand.EXPORT:
                    self._export(parsed.text)
                    continue
                if parsed.command is ChatCommand.HELP:
                    self._show_help()
                    continue
                if parsed.command is ChatCommand.LISTEN:
                    self._listen()
                    continue
                if parsed.command is ChatCommand.HA:
                    self._handle_homeassistant(parsed.text)
                    continue
                if parsed.command is ChatCommand.IMPORT:
                    self._import(parsed.text)
                    continue
                if parsed.command is ChatCommand.MEMORY:
                    self._show_memory()
                    continue
                if parsed.command is ChatCommand.MEDIA:
                    self._handle_media(parsed.text)
                    continue
                if parsed.command is ChatCommand.OPENART:
                    self._handle_openart(parsed.text)
                    continue
                if parsed.command is ChatCommand.PLUGINS:
                    self._show_plugins()
                    continue
                if parsed.command is ChatCommand.PLUGIN:
                    self._handle_plugin(parsed.text)
                    continue
                if parsed.command is ChatCommand.PROJECTS:
                    self._show_projects()
                    continue
                if parsed.command is ChatCommand.RELOAD:
                    self.reload_context()
                    self._respond("Prompts und Wissensdateien neu geladen.")
                    continue
                if parsed.command is ChatCommand.REMEMBER:
                    self._remember(parsed.text)
                    continue
                if parsed.command is ChatCommand.STATS:
                    self._show_stats()
                    continue
                if parsed.command is ChatCommand.SAY:
                    self._say(parsed.text)
                    continue
                if parsed.command is ChatCommand.SERVER:
                    self._handle_server(parsed.text)
                    continue
                if parsed.command is ChatCommand.SPEAK:
                    self._speak_command(parsed.text)
                    continue
                if parsed.command is ChatCommand.SPEAK_LAST:
                    self._speak_last(parsed.text)
                    continue
                if parsed.command is ChatCommand.UNDO:
                    self._undo(parsed.text)
                    continue
                if parsed.command is ChatCommand.VOICE:
                    self._voice_turn(parsed.text)
                    continue
                if parsed.command is ChatCommand.VOICES:
                    self._show_voices()
                    continue
                if parsed.command is ChatCommand.UNKNOWN:
                    self._respond(
                        "Diesen Befehl kenne ich noch nicht. Nutze /help fuer Hilfe."
                    )
                    continue

                self.conversation.append(role="user", content=parsed.text)
                response = self.handle_message(parsed.text)
                self.conversation.append(role="assistant", content=response)
                self._respond(response)

            self._write_session_line("system", "Chat session ended.")
            self.session_log = None

    def _print_welcome(self) -> None:
        self.console.print("[bold cyan]Kira[/bold cyan] lokaler Chat")
        self.console.print("Schreibe /help fuer Kommandos oder /exit zum Beenden.")

    def _show_help(self) -> None:
        self._respond(
            "Verfuegbare Kommandos: /about, /help, /memory, /projects, "
            "/reload, /stats, /ha ..., /audio ..., /media server ..., "
            "/plugins, /plugin info <name>, /plugin enable <name>, "
            "/plugin disable <name>, /plugin reload <name|all>, "
            "/plugin health, /backup, /export [path], /import <path>, "
            "/openart account|projects|models|kira info|generate <prompt>, "
            "/server start|stop|status, /speak <target> <text>, "
            "/undo last, "
            "/listen, /voice [local|ha], /voices, /say <text>, "
            "/speak_last [local|ha], /exit. "
            "Mit 'Merke: ...' speichere ich eine lokale Notiz."
        )

    def handle_message(self, message: str) -> str:
        """Handle one plain chat message and return Kira's response."""
        if self.event_bus is not None:
            self.event_bus.publish(ChatMessageReceived(message))
        started = time.perf_counter()
        response = self._chat_response(message)
        if self.telemetry is not None:
            self.telemetry.record_response_time(
                "chat.message", time.perf_counter() - started
            )
        return response

    def handle_assist_message(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Handle one Home Assistant Assist message and persist the turn."""
        if self.event_bus is not None:
            self.event_bus.publish(ChatMessageReceived(message))
        started = time.perf_counter()
        self.conversation.append(role="user", content=message)
        response = self._assist_response(message, self._assist_origin(context))
        self.conversation.append(role="assistant", content=response)
        if self.telemetry is not None:
            self.telemetry.record_response_time(
                "assist.message", time.perf_counter() - started
            )
        self.last_response = response
        return response

    def _assist_origin(self, context: dict[str, Any] | None) -> AssistOrigin | None:
        if context is None:
            return None
        metadata = context.get("metadata")
        return AssistOrigin(
            device_id=self._optional_context_string(context.get("device_id")),
            conversation_id=self._optional_context_string(
                context.get("conversation_id")
            ),
            agent_id=self._optional_context_string(context.get("agent_id")),
            area_id=self._optional_context_string(context.get("area_id")),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def _optional_context_string(self, value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    def _show_about(self) -> None:
        self._respond(
            "Ich bin Kira: ein lokaler persoenlicher KI-Assistent mit "
            "modularer Persoenlichkeit, Conversation Memory und lokalem "
            "Markdown-Wissensspeicher."
        )

    def _show_memory(self) -> None:
        notes = self.memory.list_items(kind="conversation_note")
        if not notes:
            self._respond("Ich habe noch keine gespeicherten Notizen.")
            return

        self._respond("Gespeicherte Notizen:")
        for index, item in enumerate(notes, start=1):
            self.console.print(f"  {index}. {item.content}")
            self._write_session_line("kira", f"{index}. {item.content}")

    def _remember(self, note: str) -> None:
        if not note:
            self._respond("Ich brauche noch Inhalt nach 'Merke:'.")
            return

        item = self.memory.add_conversation_note(note)
        self._respond(f"Gemerkte Notiz gespeichert: {item.content}")

    def _show_projects(self) -> None:
        categories = self.knowledge.list_categories()
        if not categories:
            self._respond("Ich habe noch keine Wissensdateien geladen.")
            return

        self._respond("Geladene Wissensbereiche:")
        for index, category in enumerate(categories, start=1):
            self.console.print(f"  {index}. {category}")
            self._write_session_line("kira", f"{index}. {category}")

    def _show_stats(self) -> None:
        notes = self.memory.list_items(kind="conversation_note")
        ha_status = (
            "aktiv" if self.homeassistant.is_configured else "nicht konfiguriert"
        )
        voice_status = "aktiv" if self.voice.is_configured else "nicht konfiguriert"
        self._respond(
            "Status: "
            f"Chats={self.conversation.count()}, "
            f"Erinnerungen={len(notes)}, "
            f"Wissensdateien={len(self.knowledge.documents)}, "
            f"Modell={self.settings.openai_model}, "
            f"HomeAssistant={ha_status}, "
            f"Voice={voice_status}, "
            f"STT={self.settings.stt_provider}:{self.settings.stt_model}, "
            f"Tokenverbrauch={self.total_tokens or 'nicht verfuegbar'}"
        )

    def _undo(self, text: str) -> None:
        if text.strip().lower() != "last":
            self._respond("Undo: Nutze /undo last.")
            return
        self._respond(self.ha_undo.undo_last().message)

    def reload_context(self) -> None:
        """Reload personality prompt and knowledge files from disk."""
        self.system_prompt = load_system_prompt(self.settings)
        self.knowledge.reload()

    def _handle_homeassistant(self, command_text: str) -> None:
        parts = command_text.split()
        if not parts:
            self._respond(
                "Home Assistant: /ha ping, /ha config, /ha states, "
                "/ha summary, /ha lights, /ha on, /ha unavailable, "
                "/ha find <suchtext>, /ha export, /ha room <raumname>, "
                "/ha media, /ha live start|stop|status|events|clear, "
                "/ha entity <entity_id>, "
                "/ha service <domain> <service> <entity_id>"
            )
            return

        command = parts[0].lower()
        try:
            self._run_homeassistant_command(command, parts)
        except RuntimeError as exc:
            self._respond(str(exc))

    def _run_homeassistant_command(self, command: str, parts: list[str]) -> None:
        """Run a parsed Home Assistant command."""
        if command == "ping":
            self._show_ha_result(self.homeassistant.ping())
            return
        if command == "config":
            self._show_ha_result(self.homeassistant.config())
            return
        if command == "states":
            self._show_ha_states(self.homeassistant.states())
            return
        if command == "media":
            if len(parts) >= 2 and parts[1].lower() == "alexa":
                self._show_ha_media_players(alexa_only=True)
                return
            self._show_ha_media_players()
            return
        if command == "live":
            self._handle_ha_live(parts[1:])
            return
        if command == "summary":
            self._show_ha_analysis_summary()
            return
        if command == "lights":
            self._show_ha_entity_list(
                "Aktive Lichter",
                self._load_ha_analysis().active_lights,
            )
            return
        if command == "on":
            self._show_ha_entity_list(
                "Eingeschaltete Geraete",
                self._load_ha_analysis().switched_on,
            )
            return
        if command == "unavailable":
            analysis = self._load_ha_analysis()
            self._show_ha_entity_list(
                "Nicht verfuegbar",
                [*analysis.unavailable, *analysis.unknown],
            )
            return
        if command == "find" and len(parts) >= 2:
            analysis = self._load_ha_analysis()
            matches = self.ha_analyzer.find(analysis, " ".join(parts[1:]))
            self._show_ha_entity_list("Suchtreffer", matches)
            return
        if command == "room" and len(parts) >= 2:
            analysis = self._load_ha_analysis()
            matches = self.ha_analyzer.by_room(analysis, " ".join(parts[1:]))
            self._show_ha_entity_list(f"Raum: {' '.join(parts[1:])}", matches)
            return
        if command == "export":
            analysis = self._load_ha_analysis()
            export = self.ha_analyzer.export(
                analysis,
                self.settings.data_dir / "homeassistant",
            )
            self._respond(
                "Home-Assistant-Export gespeichert: "
                f"{export.json_path} und {export.markdown_path}"
            )
            return
        if command == "entity" and len(parts) == 2:
            self._show_ha_result(self.homeassistant.entity(parts[1]))
            return
        if command == "service" and len(parts) == 4:
            self._show_ha_result(
                self.homeassistant.call_service(
                    domain=parts[1],
                    service=parts[2],
                    entity_id=parts[3],
                )
            )
            return

        self._respond("Home-Assistant-Befehl unvollstaendig. Nutze /ha fuer Hilfe.")

    def _handle_ha_live(self, parts: list[str]) -> None:
        if not parts:
            self._respond(
                "Home Assistant Live: /ha live start, /ha live stop, "
                "/ha live status, /ha live events, /ha live clear"
            )
            return

        command = parts[0].lower()
        if command == "start":
            status = self.homeassistant_live.start()
            self._respond(
                "Home Assistant Live gestartet: "
                f"{status.status}, Events={status.stored_events}"
            )
            return
        if command == "stop":
            status = self.homeassistant_live.stop()
            self._respond(f"Home Assistant Live gestoppt: {status.status}")
            return
        if command == "status":
            status = self.homeassistant_live.status()
            error = f", Fehler={status.last_error}" if status.last_error else ""
            self._respond(
                "Home Assistant Live Status: "
                f"{status.status}, verbunden={status.connected}, "
                f"gespeicherte Events={status.stored_events}{error}"
            )
            return
        if command == "events":
            self._show_live_events()
            return
        if command == "clear":
            self.homeassistant_live.clear_events()
            self._respond("Home Assistant Live Events geloescht.")
            return

        self._respond("Live-Befehl unvollstaendig. Nutze /ha live fuer Hilfe.")

    def _handle_audio(self, command_text: str) -> None:
        parts = command_text.split()
        if not parts:
            self._respond(
                "Audio: /audio devices, /audio input <name_or_index>, "
                "/audio output <name_or_index>, /audio current, "
                "/audio ha <media_player_entity_id>, /audio mode local|ha"
            )
            return

        command = parts[0].lower()
        try:
            if command == "devices":
                self._show_audio_devices()
                return
            if command == "current":
                self._show_audio_current()
                return
            if command == "input" and len(parts) >= 2:
                settings = self.audio_device_manager.select_input(" ".join(parts[1:]))
                self._respond(f"Audio-Eingabe gesetzt: {settings.input_device}")
                return
            if command == "output" and len(parts) >= 2:
                settings = self.audio_device_manager.select_output(" ".join(parts[1:]))
                self._respond(f"Audio-Ausgabe gesetzt: {settings.output_device}")
                return
            if command == "ha" and len(parts) == 2:
                settings = self.audio_device_manager.set_ha_media_player(parts[1])
                self._respond(
                    f"Home-Assistant-Ausgabe gesetzt: {settings.ha_media_player}"
                )
                return
            if command == "mode" and len(parts) == 2:
                settings = self.audio_device_manager.set_mode(parts[1].lower())
                self._respond(f"Audio-Modus gesetzt: {settings.mode}")
                return
        except ValueError as exc:
            self._respond(str(exc))
            return

        self._respond("Audio-Befehl unvollstaendig. Nutze /audio fuer Hilfe.")

    def _handle_media(self, command_text: str) -> None:
        parts = command_text.split()
        if len(parts) != 2 or parts[0].lower() != "server":
            self._respond("Media Server: /media server start|stop|status")
            return

        command = parts[1].lower()
        if command == "start":
            info = self.media_server.start()
            self._respond(f"Media-Server laeuft auf {info.host}:{info.port}")
            return
        if command == "stop":
            info = self.media_server.stop()
            self._respond(f"Media-Server Status: {info.status}")
            return
        if command == "status":
            info = self.media_server.status()
            self._respond(
                f"Media-Server Status: {info.status} auf {info.host}:{info.port}"
            )
            return
        self._respond("Media Server: /media server start|stop|status")

    def _handle_server(self, command_text: str) -> None:
        command = command_text.strip().lower()
        if command == "start":
            self._respond(
                "API-Server starten: `python -m kira server`. "
                "Im Chat-Prozess starte ich keinen zweiten blockierenden Server."
            )
            return
        if command == "stop":
            self._respond(
                "API-Server stoppen: beende den Prozess, der "
                "`python -m kira server` ausfuehrt."
            )
            return
        if command == "status":
            token_state = "gesetzt" if self.settings.api_token else "fehlt"
            self._respond(
                "API-Server konfiguriert: "
                f"{self.settings.api_host}:{self.settings.api_port}, "
                f"Token={token_state}"
            )
            return
        self._respond("Server: /server start, /server stop, /server status")

    def _handle_openart(self, command_text: str) -> None:
        if self.openart is None:
            self._respond("OpenArt ist nicht initialisiert.")
            return
        parts = command_text.split()
        if not parts:
            self._respond(
                "OpenArt: /openart account, /openart projects, /openart models, "
                "/openart kira info, /openart generate <prompt>"
            )
            return
        command = parts[0].lower()
        if command == "account":
            self._show_openart_result(self.openart.account())
            return
        if command == "projects":
            self._show_openart_result(self.openart.projects())
            return
        if command == "models":
            self._show_openart_result(self.openart.models())
            return
        if command == "kira" and len(parts) >= 2 and parts[1].lower() == "info":
            self._show_openart_kira_info()
            return
        if command == "generate":
            prompt = command_text.removeprefix(parts[0]).strip()
            self._openart_generate(prompt)
            return
        self._respond("OpenArt-Befehl unvollstaendig. Nutze /openart fuer Hilfe.")

    def _show_openart_kira_info(self) -> None:
        assert self.openart is not None
        data = self.openart.kira_info().data
        if not isinstance(data, dict):
            self._respond("OpenArt Kira-Konfiguration konnte nicht gelesen werden.")
            return
        missing = data.get("missing", [])
        missing_text = ", ".join(missing) if missing else "keine"
        self._respond(
            "OpenArt Kira IDs: "
            f"model={data.get('model_id') or 'fehlt'}, "
            f"style={data.get('style_id') or 'fehlt'}, "
            f"world={data.get('world_id') or 'fehlt'}, "
            f"project={data.get('default_project_id') or 'optional/fehlt'}, "
            f"fehlend={missing_text}"
        )

    def _openart_generate(self, prompt: str) -> None:
        if self.openart is None or self.openart_prompt_builder is None:
            self._respond("OpenArt ist nicht vollstaendig initialisiert.")
            return
        if not prompt:
            self._respond("OpenArt braucht einen Prompt: /openart generate <prompt>")
            return
        final_prompt = self.openart_prompt_builder.build(prompt)
        result = self.openart.generate(final_prompt)
        self._save_openart_history(prompt, final_prompt, result)
        if not result.ok:
            self._respond(self._openart_error_message(result))
            return
        if result.path is not None:
            self._respond(f"OpenArt-Bild gespeichert: {result.path}")
            return
        self._respond(
            "OpenArt hat erfolgreich geantwortet, aber keine Bilddatei geliefert. "
            f"Antwort: {self._compact_data(result.data)}"
        )

    def _save_openart_history(
        self,
        prompt: str,
        final_prompt: str,
        result: OpenArtResult,
    ) -> None:
        if self.openart is None or self.openart_history is None:
            return
        config = self.openart.kira_config
        self.openart_history.add(
            prompt=prompt,
            final_prompt=final_prompt,
            path=result.path,
            model_id=config.model_id,
            style_id=config.style_id,
            world_id=config.world_id,
            project_id=config.default_project_id,
            status=result.status,
        )

    def _show_openart_result(self, result: OpenArtResult) -> None:
        if not result.ok:
            self._respond(self._openart_error_message(result))
            return
        self._respond(f"OpenArt antwortet: {self._compact_data(result.data)}")

    def _openart_error_message(self, result: OpenArtResult) -> str:
        if result.status is OpenArtStatus.NOT_CONFIGURED:
            return "OpenArt ist nicht konfiguriert: OPENART_API_KEY fehlt."
        if result.status is OpenArtStatus.MISSING_KIRA_IDS:
            missing = ", ".join(result.data.get("missing", [])) if result.data else ""
            return f"OpenArt Kira-IDs fehlen: {missing}."
        if result.status is OpenArtStatus.AUTHENTICATION_ERROR:
            return "OpenArt hat den API-Key abgelehnt."
        if result.status is OpenArtStatus.TIMEOUT:
            return "OpenArt hat nicht rechtzeitig geantwortet."
        if result.status is OpenArtStatus.NETWORK_ERROR:
            return "OpenArt ist gerade nicht erreichbar."
        return f"OpenArt Fehler: {result.error or result.status}"

    def _show_plugins(self) -> None:
        if self.plugin_manager is None:
            self._respond("Plugin-System ist nicht initialisiert.")
            return
        records = self.plugin_manager.list_plugins()
        if not records:
            self._respond("Keine Plugins gefunden.")
            return
        self._respond(f"Plugins: {len(records)} gefunden.")
        for record in records:
            line = (
                f"{record.manifest.name} {record.manifest.version}: " f"{record.state}"
            )
            self.console.print(f"  {line}")
            self._write_session_line("kira", line)

    def _handle_plugin(self, command_text: str) -> None:
        if self.plugin_manager is None:
            self._respond("Plugin-System ist nicht initialisiert.")
            return
        parts = command_text.split()
        if not parts:
            self._respond(
                "Plugin: /plugin info <name>, /plugin enable <name>, "
                "/plugin disable <name>, /plugin reload <name|all>, /plugin health"
            )
            return
        command = parts[0].lower().rstrip(">")
        try:
            if command == "info" and len(parts) == 2:
                self._show_plugin_info(parts[1])
                return
            if command == "enable" and len(parts) == 2:
                record = self.plugin_manager.enable(parts[1])
                self._respond(
                    f"Plugin aktiviert: {record.manifest.name} ({record.state})"
                )
                return
            if command == "disable" and len(parts) == 2:
                record = self.plugin_manager.disable(parts[1])
                self._respond(f"Plugin deaktiviert: {record.manifest.name}")
                return
            if command == "reload" and len(parts) == 2:
                if parts[1].rstrip(">") == "all":
                    records = self.plugin_manager.reload_all()
                    self._respond(f"Plugins neu geladen: {len(records)}")
                    return
                record = self.plugin_manager.reload(parts[1])
                self._respond(
                    f"Plugin neu geladen: {record.manifest.name} ({record.state})"
                )
                return
            if command == "health":
                self._show_plugin_health()
                return
        except KeyError as exc:
            self._respond(str(exc))
            return
        self._respond("Plugin-Befehl unvollstaendig. Nutze /plugin fuer Hilfe.")

    def _show_plugin_info(self, name: str) -> None:
        assert self.plugin_manager is not None
        record = self.plugin_manager.get(name)
        if record is None:
            self._respond(f"Plugin nicht gefunden: {name}")
            return
        manifest = record.manifest
        dependencies = ", ".join(manifest.dependencies) or "keine"
        self._respond(
            f"{manifest.name} {manifest.version}: {manifest.description} "
            f"Autor={manifest.author}, Status={record.state}, "
            f"Abhaengigkeiten={dependencies}"
        )

    def _show_plugin_health(self) -> None:
        assert self.plugin_manager is not None
        results = self.plugin_manager.health()
        if not results:
            self._respond("Keine Plugin-Healthchecks verfuegbar.")
            return
        self._respond("Plugin Health:")
        for name, result in results.items():
            line = f"{name}: {'ok' if result.ok else 'fehler'} - {result.message}"
            self.console.print(f"  {line}")
            self._write_session_line("kira", line)

    def _backup(self) -> None:
        if self.backup_service is None:
            self._respond("Backup-Service ist nicht initialisiert.")
            return
        archive = self.backup_service.create_backup()
        self._respond(f"Backup erstellt: {archive}")

    def _export(self, path_text: str) -> None:
        if self.backup_service is None:
            self._respond("Backup-Service ist nicht initialisiert.")
            return
        archive = (
            Path(path_text)
            if path_text
            else (self.settings.data_dir / "exports" / "kira-export.zip")
        )
        exported = self.backup_service.export_archive(archive)
        self._respond(f"Export erstellt: {exported}")

    def _import(self, path_text: str) -> None:
        if self.backup_service is None:
            self._respond("Backup-Service ist nicht initialisiert.")
            return
        if not path_text:
            self._respond("Import braucht einen Pfad: /import <backup.zip>")
            return
        self.backup_service.import_archive(Path(path_text))
        self.reload_context()
        self._respond(f"Import abgeschlossen: {path_text}")

    def _show_ha_result(self, result: HomeAssistantResult) -> None:
        if not result.ok:
            self._respond(self._ha_error_message(result))
            return
        self._respond(f"Home Assistant antwortet: {self._compact_data(result.data)}")

    def _show_ha_states(self, result: HomeAssistantResult) -> None:
        if not result.ok:
            self._respond(self._ha_error_message(result))
            return
        if not isinstance(result.data, list):
            self._respond("Home Assistant lieferte keine State-Liste.")
            return
        self._respond(f"{len(result.data)} Entitaeten geladen.")
        for item in result.data[:10]:
            if isinstance(item, dict):
                entity_id = item.get("entity_id", "unknown")
                state = item.get("state", "unknown")
                self.console.print(f"  {entity_id}: {state}")
                self._write_session_line("kira", f"{entity_id}: {state}")

    def _show_ha_media_players(self, *, alexa_only: bool = False) -> None:
        result = self.homeassistant.states()
        if not result.ok:
            self._respond(self._ha_error_message(result))
            return
        if not isinstance(result.data, list):
            self._respond("Home Assistant lieferte keine State-Liste.")
            return
        states = [item for item in result.data if isinstance(item, dict)]
        media_players = self.media_player_matcher.from_states(states)
        if alexa_only:
            media_players = [player for player in media_players if player.is_alexa]
        if not media_players:
            self._respond("Keine passenden media_player-Entitaeten gefunden.")
            return
        title = "Alexa media_player" if alexa_only else "media_player"
        self._respond(f"{title}: {len(media_players)} Treffer.")
        for player in media_players[:20]:
            marker = " [Alexa]" if player.is_alexa else ""
            line = f"{player.entity_id}: {player.state} ({player.name}){marker}"
            self.console.print(f"  {line}")
            self._write_session_line("kira", line)

    def _show_audio_devices(self) -> None:
        devices = self.audio_device_manager.list_devices()
        if not devices:
            self._respond("Keine lokalen Audiogeraete gefunden oder sounddevice fehlt.")
            return
        self._respond("Lokale Audiogeraete:")
        for device in devices:
            self.console.print(f"  {self._format_audio_device(device)}")

    def _show_audio_current(self) -> None:
        settings = self.audio_device_manager.load_settings()
        self._respond(
            "Audio-Auswahl: "
            f"mode={settings.mode}, "
            f"input={settings.input_device or 'standard'}, "
            f"output={settings.output_device or 'standard'}, "
            f"ha={settings.ha_media_player or 'nicht gesetzt'}"
        )

    def _format_audio_device(self, device: AudioDevice) -> str:
        flags: list[str] = []
        if device.is_input:
            flags.append("input")
        if device.is_output:
            flags.append("output")
        if device.is_default_input:
            flags.append("default-input")
        if device.is_default_output:
            flags.append("default-output")
        return f"{device.index}: {device.name} ({', '.join(flags)})"

    def _show_ha_summary(self, result: HomeAssistantResult) -> None:
        if not result.ok:
            self._respond(self._ha_error_message(result))
            return
        if not isinstance(result.data, HomeAssistantSummary):
            self._respond("Home Assistant lieferte keine Summary.")
            return
        summary = result.data
        self._respond(
            "Home Assistant Summary: "
            f"Entitaeten={summary.total_entities}, "
            f"Lichter={summary.lights}, "
            f"Switches={summary.switches}, "
            f"Sensoren={summary.sensors}, "
            f"unavailable={summary.unavailable}, "
            f"unknown={summary.unknown}"
        )

    def _show_ha_analysis_summary(self) -> None:
        analysis = self._load_ha_analysis()
        self._respond(
            "Home Assistant Summary: "
            f"Entitaeten={len(analysis.entities)}, "
            f"Domains={len(analysis.by_domain)}, "
            f"Aktive Lichter={len(analysis.active_lights)}, "
            f"Eingeschaltete Geraete={len(analysis.switched_on)}, "
            f"Wichtige Sensoren={len(analysis.important_sensors)}, "
            f"unavailable={len(analysis.unavailable)}, "
            f"unknown={len(analysis.unknown)}"
        )
        domains = ", ".join(
            f"{domain}:{len(entities)}"
            for domain, entities in list(analysis.by_domain.items())[:12]
        )
        if domains:
            self.console.print(f"  Domains: {domains}")
            self._write_session_line("kira", f"Domains: {domains}")

    def _say(self, text: str) -> None:
        if not text:
            self._respond("Bitte gib Text an: /say <text>")
            return
        self._speak_text(text)

    def _speak_text(
        self,
        text: str,
        *,
        mode_override: str | None = None,
        target_entity_id: str | None = None,
    ) -> bool:
        result = self.voice.text_to_speech(text)
        if result.ok and result.path is not None:
            if target_entity_id is not None:
                route = self.audio_router.route_to_media_player(
                    result.path,
                    target_entity_id,
                )
            else:
                route = self.audio_router.route(
                    result.path,
                    mode_override=mode_override,
                )
            if route.ok:
                self._respond(f"Sprachausgabe: {route.message}")
                return True
            self._respond(self._route_error_message(route))
            return False
        self._respond(self._voice_error_message(result))
        return False

    def speak_to_target(self, target: str, text: str) -> bool:
        """Speak text through the best matching Home Assistant media player."""
        player = self._resolve_media_player_target(target)
        if player is None:
            self._respond(f"Kein passender media_player gefunden: {target}")
            return False
        return self._speak_text(text, target_entity_id=player.entity_id)

    def _speak_command(self, command_text: str) -> None:
        parts = command_text.split(maxsplit=1)
        if len(parts) != 2:
            self._respond(
                "Speak: /speak <media_player_entity_id|alexa|tablet> <text> "
                "oder /speak room <raumname> <text>"
            )
            return
        target, text = parts
        if target.lower() == "room":
            room_parts = text.split(maxsplit=1)
            if len(room_parts) != 2:
                self._respond("Speak room: /speak room <raumname> <text>")
                return
            room, room_text = room_parts
            self.speak_to_target(f"room:{room}", room_text)
            return
        self.speak_to_target(target, text)

    def _resolve_media_player_target(self, target: str) -> MediaPlayerView | None:
        result = self.homeassistant.states()
        if not result.ok or not isinstance(result.data, list):
            return None
        states = [item for item in result.data if isinstance(item, dict)]
        players = self.media_player_matcher.from_states(states)
        if target.startswith("room:"):
            return self.media_player_matcher.best_room_match(
                players,
                target.removeprefix("room:"),
            )
        return self.media_player_matcher.best_match(players, target)

    def _speak_last(self, command_text: str = "") -> None:
        if not self.last_response:
            self._respond("Ich habe noch keine Antwort, die ich sprechen kann.")
            return
        self._speak_text(
            self.last_response, mode_override=self._audio_mode(command_text)
        )

    def _listen(self) -> None:
        self._respond(
            f"Aufnahme laeuft fuer {self.settings.audio_record_seconds} Sekunden."
        )
        recording = self.audio_recorder.record()
        if not recording.ok or recording.path is None:
            self._respond(self._recording_error_message(recording))
            return

        self._respond(f"Aufnahme gespeichert: {recording.path}")
        transcription = self.speech_to_text.transcribe(recording.path)
        if not transcription.ok:
            self._respond(self._stt_error_message(transcription))
            return
        if not transcription.text:
            self._respond("Ich konnte keine Sprache in der Aufnahme erkennen.")
            return

        self._respond(f"Transkription: {transcription.text}")
        self._handle_plain_message(transcription.text)

    def _voice_turn(self, command_text: str = "") -> None:
        self._respond("Voice-Modus: Ich hoere einmal zu, antworte und spreche dann.")
        recording = self.audio_recorder.record()
        if not recording.ok or recording.path is None:
            self._respond(self._recording_error_message(recording))
            return

        transcription = self.speech_to_text.transcribe(recording.path)
        if not transcription.ok:
            self._respond(self._stt_error_message(transcription))
            return
        if not transcription.text:
            self._respond("Ich konnte keine Sprache in der Aufnahme erkennen.")
            return

        self._respond(f"Du sagtest: {transcription.text}")
        response = self._handle_plain_message(transcription.text)
        self._speak_text(response, mode_override=self._audio_mode(command_text))

    def _show_voices(self) -> None:
        result = self.voice.list_voices()
        if not result.ok:
            self._respond(self._voice_error_message(result))
            return

        voices = self._extract_voices(result.data)
        if not voices:
            self._respond("ElevenLabs hat keine Stimmen geliefert.")
            return

        self._respond("Verfuegbare ElevenLabs-Stimmen:")
        for voice in voices[:20]:
            name = voice.get("name", "Unbenannt")
            voice_id = voice.get("voice_id", "unknown")
            category = voice.get("category", "unknown")
            line = f"{name} ({category}) -> {voice_id}"
            self.console.print(f"  {line}")
            self._write_session_line("kira", line)

    def _ha_error_message(self, result: HomeAssistantResult) -> str:
        if result.status is HomeAssistantStatus.NOT_CONFIGURED:
            return "Home Assistant ist noch nicht konfiguriert."
        if result.status is HomeAssistantStatus.AUTHENTICATION_ERROR:
            return "Home Assistant hat den Token abgelehnt."
        if result.status is HomeAssistantStatus.NOT_FOUND:
            return "Home Assistant Ressource nicht gefunden."
        if result.status is HomeAssistantStatus.TIMEOUT:
            return "Home Assistant hat nicht rechtzeitig geantwortet."
        if result.status is HomeAssistantStatus.NETWORK_ERROR:
            return "Home Assistant ist gerade nicht erreichbar."
        return f"Home Assistant Fehler: {result.error or result.status}"

    def _voice_error_message(self, result: VoiceResult) -> str:
        if result.status is VoiceStatus.NOT_CONFIGURED:
            return "ElevenLabs ist noch nicht vollstaendig konfiguriert."
        if result.status is VoiceStatus.AUTHENTICATION_ERROR:
            return "ElevenLabs hat den API-Key abgelehnt."
        if result.status is VoiceStatus.VOICE_NOT_FOUND:
            return (
                "ElevenLabs kennt diese Voice-ID nicht. Nutze /voices und trage "
                "eine der angezeigten IDs als ELEVENLABS_VOICE_ID in .env ein."
            )
        if result.status is VoiceStatus.TIMEOUT:
            return "ElevenLabs hat nicht rechtzeitig geantwortet."
        if result.status is VoiceStatus.NETWORK_ERROR:
            return "ElevenLabs ist gerade nicht erreichbar."
        return f"ElevenLabs Fehler: {result.error or result.status}"

    def _recording_error_message(self, result: RecordingResult) -> str:
        if result.status is RecordingStatus.DEPENDENCY_MISSING:
            return (
                "Audioaufnahme ist nicht bereit. Installiere sounddevice und "
                f"soundfile. Detail: {result.error}"
            )
        return f"Audioaufnahme fehlgeschlagen: {result.error or result.status}"

    def _stt_error_message(self, result: SpeechToTextResult) -> str:
        if result.status is SpeechToTextStatus.NOT_CONFIGURED:
            return "Speech-to-Text ist nicht konfiguriert."
        if result.status is SpeechToTextStatus.UNSUPPORTED_PROVIDER:
            return "Dieser Speech-to-Text-Provider wird noch nicht unterstuetzt."
        if result.status is SpeechToTextStatus.FILE_NOT_FOUND:
            return "Die Audioaufnahme wurde nicht gefunden."
        if result.status is SpeechToTextStatus.AUTHENTICATION_ERROR:
            return "OpenAI hat den API-Key fuer Speech-to-Text abgelehnt."
        if result.status is SpeechToTextStatus.RATE_LIMITED:
            return "OpenAI meldet ein Rate-Limit fuer Speech-to-Text."
        if result.status is SpeechToTextStatus.NETWORK_ERROR:
            return "Speech-to-Text erreicht OpenAI gerade nicht."
        return f"Speech-to-Text fehlgeschlagen: {result.error or result.status}"

    def _route_error_message(self, result: AudioRouteResult) -> str:
        if result.status is AudioRouteStatus.MEDIA_BASE_URL_MISSING:
            return (
                "Home Assistant kann lokale MP3-Dateien nicht direkt abspielen. "
                "Setze KIRA_MEDIA_BASE_URL und starte /media server start."
            )
        return f"Audio-Routing fehlgeschlagen: {result.message}"

    def _audio_mode(self, command_text: str) -> str | None:
        value = command_text.strip().lower()
        if value in {"local", "ha"}:
            return value
        return None

    def _compact_data(self, data: object) -> str:
        text = str(data)
        if len(text) <= 500:
            return text
        return f"{text[:500]} ..."

    def _extract_voices(self, data: object) -> list[dict[str, object]]:
        if not isinstance(data, dict):
            return []
        voices = data.get("voices")
        if not isinstance(voices, list):
            return []
        return [voice for voice in voices if isinstance(voice, dict)]

    def _load_ha_analysis(self) -> HomeAssistantAnalysis:
        result = self.homeassistant.states()
        if not result.ok:
            raise RuntimeError(self._ha_error_message(result))
        if not isinstance(result.data, list):
            raise RuntimeError("Home Assistant lieferte keine State-Liste.")
        states = [item for item in result.data if isinstance(item, dict)]
        return self.ha_analyzer.analyze(states)

    def _show_ha_entity_list(self, title: str, entities: list[EntityView]) -> None:
        if not entities:
            self._respond(f"{title}: keine Treffer.")
            return
        self._respond(f"{title}: {len(entities)} Treffer.")
        for entity in entities[:20]:
            room = f" [{entity.room}]" if entity.room else ""
            line = f"{entity.entity_id}{room}: {entity.state} ({entity.label})"
            self.console.print(f"  {line}")
            self._write_session_line("kira", line)

    def _dummy_response(self, message: str) -> str:
        return (
            "Ich laufe gerade lokal im Fallback-Modus. "
            f"Ich habe verstanden: {message}"
        )

    def _chat_response(self, message: str) -> str:
        safety_answer = self._answer_homeassistant_safety(message)
        if safety_answer is not None:
            return safety_answer

        ha_answer = self._answer_homeassistant_question(message)
        if ha_answer is not None:
            return ha_answer

        live_answer = self._answer_homeassistant_live_question(message)
        if live_answer is not None:
            return live_answer

        memory_context = self._memory_context()
        result = self.openai_client.chat(
            system_prompt=self.system_prompt,
            memory_context=memory_context,
            knowledge_context=self.knowledge.build_context(),
            conversation=self.conversation.recent(),
        )

        if result.status is OpenAIChatStatus.SUCCESS:
            if result.total_tokens is not None:
                self.total_tokens += result.total_tokens
            return result.content

        return self._fallback_response(message=message, result=result)

    def _assist_response(self, message: str, origin: AssistOrigin | None) -> str:
        if self._asks_for_home_status(message):
            return self.home_status.status().response

        if self._asks_for_unclear_whole_house_action(message):
            return "Da bin ich mir nicht sicher. Welchen Bereich meinst du?"

        contextual_light_answer = self._handle_contextual_light_intent(message, origin)
        if contextual_light_answer is not None:
            return contextual_light_answer

        service_answer = self._handle_assist_service_intent(message)
        if service_answer is not None:
            return service_answer

        safety_answer = self._answer_homeassistant_safety(message)
        if safety_answer is not None:
            return safety_answer

        ha_answer = self._answer_homeassistant_question(message)
        if ha_answer is not None:
            return ha_answer

        live_answer = self._answer_homeassistant_live_question(message)
        if live_answer is not None:
            return live_answer

        result = self.openai_client.chat(
            system_prompt=self.system_prompt,
            memory_context=self._memory_context(),
            knowledge_context=self.knowledge.build_context(),
            conversation=self.conversation.recent(),
        )

        if result.status is OpenAIChatStatus.SUCCESS:
            if result.total_tokens is not None:
                self.total_tokens += result.total_tokens
            return result.content

        return self._assist_fallback_response(message=message, result=result)

    def _handle_contextual_light_intent(
        self,
        message: str,
        origin: AssistOrigin | None,
    ) -> str | None:
        light_intent = self._parse_contextual_light_intent(message)
        if light_intent is None:
            return None
        service, needs_room = light_intent
        try:
            analysis = self._load_ha_analysis()
        except RuntimeError as exc:
            return str(exc)

        resolved = self.homeassistant_context.resolve(
            text=message,
            origin=origin,
            entities=analysis.entities,
        )
        if resolved is None or not resolved.light_entities:
            if needs_room:
                return "Ich weiss noch nicht, welchen Raum du meinst."
            return None

        if service == "brighten":
            execution = self._execute_ha_action(
                user_text=message,
                intent="light.brighten",
                domain="light",
                service="turn_on",
                entity_ids=resolved.light_entities,
                data={"brightness_step_pct": 20},
                analysis=analysis,
                area_ids=[resolved.area_id] if resolved.area_id else [],
            )
            action = "heller gemacht"
        else:
            execution = self._execute_ha_action(
                user_text=message,
                intent=f"light.{service}",
                domain="light",
                service=service,
                entity_ids=resolved.light_entities,
                data={},
                analysis=analysis,
                area_ids=[resolved.area_id] if resolved.area_id else [],
            )
            action = "eingeschaltet" if service == "turn_on" else "ausgeschaltet"

        if execution is not None:
            return execution

        room = self._room_phrase(resolved.area_name)
        return f"Ich habe das Licht {room} {action}."

    def _parse_contextual_light_intent(self, message: str) -> tuple[str, bool] | None:
        text = self._normalize(message).strip().strip(".!?")
        if re.search(r"\b(hier heller|mach es heller|heller)\b", text):
            return "brighten", True
        turn_on_patterns = (
            r"\b(?:mach|mache|schalte)\s+(?:hier\s+)?(?:das\s+)?licht\s+(?:an|ein)\b",
            r"^licht\s+(?:an|ein)$",
            r"\bmach\s+hier\s+licht\b",
            r"\b(?:mach|mache)\s+es\s+gemuetlich\b",
            r"\b(?:mach|mache)\s+es\s+gemütlich\b",
            r"\blicht\s+an\b",
        )
        turn_off_patterns = (
            r"\b(?:mach|mache|schalte)\s+(?:hier\s+)?(?:das\s+)?licht\s+aus\b",
            r"^licht\s+aus$",
            r"^hier\s+aus$",
            r"\blicht\s+aus\b",
        )
        explicit_room_patterns = (
            r"\b(?:mach|mache|schalte)\s+in\s+.+?\s+(?:das\s+)?licht\s+(?:an|ein)\b",
            r"\b(?:mach|mache|schalte)\s+in\s+.+?\s+(?:das\s+)?licht\s+aus\b",
            r"^(?:\w+\s+){0,3}(?:licht|rgb)\s+(?:an|ein|aus)$",
            r"^(?:\w+\s+){1,4}(?:an|ein|aus)$",
        )
        if any(re.search(pattern, text) for pattern in turn_on_patterns):
            return "turn_on", True
        if any(re.search(pattern, text) for pattern in turn_off_patterns):
            return "turn_off", True
        if any(re.search(pattern, text) for pattern in explicit_room_patterns):
            service = "turn_off" if text.endswith("aus") else "turn_on"
            return service, False
        return None

    def _room_phrase(self, area_name: str | None) -> str:
        if not area_name:
            return "im Raum"
        normalized = self._normalize(area_name)
        article = "in der" if normalized in {"kueche"} else "im"
        return f"{article} {area_name}"

    def _execute_ha_action(
        self,
        *,
        user_text: str,
        intent: str,
        domain: str,
        service: str,
        entity_ids: list[str],
        data: dict[str, Any],
        analysis: HomeAssistantAnalysis,
        area_ids: list[str] | None = None,
    ) -> str | None:
        permission = self.ha_permissions.evaluate(
            domain=domain,
            service=service,
            entity_ids=entity_ids,
            area_ids=area_ids,
        )
        service_data = {"entity_id": entity_ids}
        service_data.update(data)
        service_call = {
            "domain": domain,
            "service": service,
            "data": service_data,
        }
        previous_states = self._states_for_entities(analysis, entity_ids)
        if permission.decision is PermissionDecision.BLOCK:
            self.ha_action_log.append(
                user_text=user_text,
                intent=intent,
                entities=entity_ids,
                service_call=service_call,
                risk_level=str(permission.risk_level),
                auto_executed=False,
                result="blocked",
                error=permission.reason,
                previous_states=previous_states,
            )
            return "Das darf ich aus Sicherheitsgruenden nicht ausfuehren."
        if permission.decision is PermissionDecision.REQUIRE_CONFIRM:
            self.ha_action_log.append(
                user_text=user_text,
                intent=intent,
                entities=entity_ids,
                service_call=service_call,
                risk_level=str(permission.risk_level),
                auto_executed=False,
                result="requires_confirm",
                error=permission.reason,
                previous_states=previous_states,
            )
            return "Das ist eine riskantere Aktion. Bitte bestaetige sie."

        result = self.homeassistant_services.call(domain, service, service_data)
        new_states = self._new_states_for_service(service, entity_ids, previous_states)
        self.ha_action_log.append(
            user_text=user_text,
            intent=intent,
            entities=entity_ids,
            service_call=service_call,
            risk_level=str(permission.risk_level),
            auto_executed=True,
            result="success" if result.ok else "failed",
            error=result.error,
            previous_states=previous_states,
            new_states=new_states,
        )
        if not result.ok:
            return self._ha_error_message(result)
        return None

    def _states_for_entities(
        self,
        analysis: HomeAssistantAnalysis,
        entity_ids: list[str],
    ) -> dict[str, str]:
        entity_map = {entity.entity_id: entity for entity in analysis.entities}
        return {
            entity_id: entity_map[entity_id].state
            for entity_id in entity_ids
            if entity_id in entity_map
        }

    def _new_states_for_service(
        self,
        service: str,
        entity_ids: list[str],
        previous_states: dict[str, str],
    ) -> dict[str, str]:
        if service == "turn_on":
            return dict.fromkeys(entity_ids, "on")
        if service == "turn_off":
            return dict.fromkeys(entity_ids, "off")
        if service == "toggle":
            return {
                entity_id: "off" if previous_states.get(entity_id) == "on" else "on"
                for entity_id in entity_ids
            }
        return {}

    def _handle_assist_service_intent(self, message: str) -> str | None:
        intent = self._parse_assist_service_intent(message)
        if intent is None:
            return None

        domain, service, query = intent
        try:
            analysis = self._load_ha_analysis()
        except RuntimeError as exc:
            return str(exc)

        matches = self._match_service_entities(analysis, domain, query)
        if not matches:
            return "Ich konnte kein passendes Geraet finden."
        if len(matches) > 1:
            lines = ["Ich habe mehrere passende Geraete gefunden:"]
            lines.extend(f"- {entity.entity_id}" for entity in matches[:10])
            return "\n".join(lines)

        entity = matches[0]
        execution = self._execute_ha_action(
            user_text=message,
            intent=f"{domain}.{service}",
            domain=domain,
            service=service,
            entity_ids=[entity.entity_id],
            data={},
            analysis=analysis,
            area_ids=[entity.room] if entity.room else [],
        )
        if execution is not None:
            return execution

        action = "eingeschaltet" if service == "turn_on" else "ausgeschaltet"
        return f"Ich habe {entity.label} {action}."

    def _parse_assist_service_intent(
        self,
        message: str,
    ) -> tuple[str, str, str] | None:
        text = self._normalize(message).strip().strip(".!?")
        patterns = (
            r"^(?:schalte|mache|mach)\s+(?P<target>.+?)\s+(?P<state>ein|an|aus)$",
            r"^(?P<target>.+?)\s+(?P<state>einschalten|ausschalten)$",
            r"^(?P<target>.+?)\s+(?P<state>an|aus)$",
            r"^(?P<state>einschalten|ausschalten)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match is None:
                continue
            state = match.group("state")
            target = match.groupdict().get("target") or "licht"
            service = "turn_off" if state in {"aus", "ausschalten"} else "turn_on"
            query = self._clean_service_target(target)
            return self._infer_action_domain(query), service, query
        return None

    def _infer_action_domain(self, query: str) -> str:
        normalized = self._normalize(query)
        if any(term in normalized for term in ("luefter", "lüfter", "fan")):
            return "fan"
        if any(term in normalized for term in ("drucker", "steckdose", "switch")):
            return "switch"
        return "light"

    def _clean_service_target(self, target: str) -> str:
        words = [
            word
            for word in target.split()
            if word
            not in {
                "das",
                "den",
                "die",
                "der",
                "bitte",
                "mal",
                "ein",
                "an",
                "aus",
            }
        ]
        cleaned = " ".join(words).strip()
        return cleaned or "licht"

    def _match_service_entities(
        self,
        analysis: HomeAssistantAnalysis,
        domain: str,
        query: str,
    ) -> list[EntityView]:
        query_text = self._normalize(query)
        candidates = [
            entity
            for entity in analysis.by_domain.get(domain, [])
            if entity.state not in {"unavailable", "unknown"}
        ]
        if query_text in {"licht", "lampe", "lampen", "lichter"}:
            return candidates

        query_tokens = [
            token
            for token in re.split(r"\W+", query_text.replace("_", " "))
            if token and token not in {"licht", "lampe", "lampen", "lichter"}
        ]
        if not query_tokens:
            return candidates

        matches = [
            entity
            for entity in candidates
            if all(token in self._entity_search_text(entity) for token in query_tokens)
        ]
        if matches:
            return matches

        compact_query = query_text.replace(" ", "")
        return [
            entity
            for entity in candidates
            if compact_query and compact_query in self._entity_search_text(entity)
        ]

    def _entity_search_text(self, entity: EntityView) -> str:
        return self._normalize(
            " ".join(
                item
                for item in (
                    entity.entity_id.replace(".", " ").replace("_", " "),
                    entity.friendly_name,
                    entity.room or "",
                )
                if item
            )
        )

    def _handle_plain_message(self, text: str) -> str:
        self.conversation.append(role="user", content=text)
        response = self.handle_message(text)
        self.conversation.append(role="assistant", content=response)
        self._respond(response)
        return response

    def _fallback_response(self, *, message: str, result: OpenAIChatResult) -> str:
        if result.status is OpenAIChatStatus.MISSING_API_KEY:
            return self._dummy_response(message)
        if result.status is OpenAIChatStatus.AUTHENTICATION_ERROR:
            return (
                "Der OpenAI-Key wurde abgelehnt. "
                f"Ich bleibe lokal im Fallback: {message}"
            )
        if result.status is OpenAIChatStatus.RATE_LIMITED:
            return (
                "OpenAI meldet gerade ein Rate-Limit. "
                f"Ich antworte lokal weiter: {message}"
            )
        if result.status is OpenAIChatStatus.NETWORK_ERROR:
            return (
                "Ich erreiche OpenAI gerade nicht. "
                f"Lokaler Fallback aktiv: {message}"
            )
        return (
            "Die OpenAI-Anfrage ist fehlgeschlagen. "
            f"Ich bleibe lokal handlungsfaehig: {message}"
        )

    def _assist_fallback_response(
        self, *, message: str, result: OpenAIChatResult
    ) -> str:
        lowered = self._normalize(message)
        if lowered in {"hallo", "hi", "hey", "guten tag", "servus", "moin"}:
            return "Hallo Daniel, ich bin Kira. Ich bin verbunden und bereit."
        if "wie geht" in lowered:
            return (
                "Mir geht es gut. Ich bin wach, mit Home Assistant verbunden "
                "und bereit fuer deine Fragen."
            )
        if result.status is OpenAIChatStatus.AUTHENTICATION_ERROR:
            return (
                "Ich bin mit Home Assistant verbunden, aber mein OpenAI-Zugang "
                "muss noch geprueft werden."
            )
        if result.status is OpenAIChatStatus.MISSING_API_KEY:
            return (
                "Ich bin mit Home Assistant verbunden. Fuer freie Gesprache "
                "fehlt mir noch der OpenAI-Key."
            )
        return (
            "Ich habe dich verstanden. Home Assistant-Fragen kann ich direkt "
            "beantworten, freie KI-Antworten sind gerade nicht verfuegbar."
        )

    def _memory_context(self) -> str:
        notes = self.memory.list_items(kind="conversation_note")
        if not notes:
            return ""
        return "\n".join(f"- {item.content}" for item in notes)

    def _answer_homeassistant_safety(self, message: str) -> str | None:
        lowered = self._normalize(message)
        if self._looks_like_switch_command(lowered):
            suggestion = self._suggest_explicit_service_command(lowered)
            return (
                "Ich fuehre natuerliche Schaltbefehle aus Sicherheitsgruenden "
                "nicht aus. Nutze dafuer einen expliziten CLI-Befehl."
                f"{suggestion}"
            )
        if self._looks_like_switch_confirmation(lowered):
            return (
                "Ich habe keine natuerliche Schaltaktion zur Bestaetigung offen. "
                "Schalten geht nur explizit, z. B. "
                "`/ha service light turn_off light.kinderzimmer`."
            )
        return None

    def _answer_homeassistant_question(self, message: str) -> str | None:
        lowered = self._normalize(message)
        try:
            if self._asks_for_weather(lowered):
                return self._format_weather_for_answer(self._load_ha_analysis())
            if self._asks_for_active_lights(lowered):
                entities = self._load_ha_analysis().active_lights
                return self._format_entities_for_answer("Aktive Lichter", entities)
            if self._asks_for_switched_on_devices(lowered):
                entities = self._load_ha_analysis().switched_on
                return self._format_entities_for_answer(
                    "Eingeschaltete Geraete", entities
                )
            if self._asks_for_unavailable_devices(lowered):
                analysis = self._load_ha_analysis()
                entities = [*analysis.unavailable, *analysis.unknown]
                return self._format_entities_for_answer("Nicht verfuegbar", entities)
            if lowered.startswith("suche "):
                search_text = (
                    message.split(" ", maxsplit=1)[1].strip().rstrip(".").strip("<>")
                )
                entities = self.ha_analyzer.find(self._load_ha_analysis(), search_text)
                return self._format_entities_for_answer("Suchtreffer", entities)
            if lowered.startswith("was ist im ") and " los" in lowered:
                room = lowered.removeprefix("was ist im ").split(" los", maxsplit=1)[0]
                entities = self.ha_analyzer.by_room(self._load_ha_analysis(), room)
                return self._format_entities_for_answer(f"Raum {room}", entities)
        except RuntimeError as exc:
            return str(exc)
        return None

    def _answer_homeassistant_live_question(self, message: str) -> str | None:
        lowered = self._normalize(message)
        events = self.homeassistant_live.list_events(limit=20)
        if self._asks_for_recent_events(lowered):
            return self._format_live_events_for_answer(
                "Letzte Ereignisse",
                events[-10:],
            )
        if self._asks_for_light_reason(lowered):
            light_events = [
                event
                for event in events
                if event.domain == "light" and event.new_state == "on"
            ]
            return self._format_live_events_for_answer(
                "Zuletzt eingeschaltete Lichter",
                light_events[-5:],
            )
        if self._asks_for_recent_automation(lowered):
            automation_events = [
                event
                for event in events
                if event.event_type == "automation_triggered"
                or event.domain == "automation"
            ]
            return self._format_live_events_for_answer(
                "Zuletzt ausgeloeste Automationen",
                automation_events[-5:],
            )
        if self._asks_for_offline_events(lowered):
            offline_events = [
                event
                for event in events
                if event.new_state in {"unavailable", "unknown"}
            ]
            return self._format_live_events_for_answer(
                "Offline/unknown Ereignisse",
                offline_events[-10:],
            )
        return None

    def _show_live_events(self) -> None:
        events = self.homeassistant_live.list_events(limit=20)
        if not events:
            self._respond("Noch keine Home-Assistant-Live-Events gespeichert.")
            return
        self._respond(f"Home Assistant Live Events: {len(events)} angezeigt.")
        for event in events:
            line = self._format_live_event(event)
            self.console.print(f"  {line}")
            self._write_session_line("kira", line)

    def _format_live_events_for_answer(
        self,
        title: str,
        events: list[HomeAssistantLiveEvent],
    ) -> str:
        if not events:
            return f"{title}: Ich habe dazu noch keine gespeicherten Live-Events."
        lines = [f"{title}: {len(events)} Treffer."]
        for event in events[-10:]:
            lines.append(f"- {self._format_live_event(event)}")
        return "\n".join(lines)

    def _format_live_event(self, event: HomeAssistantLiveEvent) -> str:
        marker = " wichtig" if event.important else ""
        entity = f" [{event.entity_id}]" if event.entity_id else ""
        return f"{event.timestamp} {event.event_type}{entity}: {event.summary}{marker}"

    def _looks_like_switch_command(self, text: str) -> bool:
        action_terms = (
            "schalte",
            "mach ",
            "mache ",
            "turn ",
            "setze ",
        )
        state_terms = (
            " aus",
            " an",
            " ausschalten",
            " einschalten",
            " turn_off",
            " turn_on",
        )
        device_terms = (
            "light.",
            "switch.",
            "licht",
            "lampe",
            "steckdose",
            "schalter",
        )
        return (
            any(term in text for term in action_terms)
            and any(term in text for term in state_terms)
            and any(term in text for term in device_terms)
        )

    def _looks_like_switch_confirmation(self, text: str) -> bool:
        confirmations = (
            "ja ausschalten",
            "ja, ausschalten",
            "ja einschalten",
            "ja, einschalten",
            "bestaetige ausschalten",
            "bestaetige einschalten",
        )
        return any(confirmation in text for confirmation in confirmations)

    def _suggest_explicit_service_command(self, text: str) -> str:
        entity_id = self._extract_entity_id(text)
        service = self._infer_service(text)
        if entity_id is None or service is None:
            return " Beispiel: `/ha service light turn_off light.kinderzimmer`."

        domain = entity_id.split(".", maxsplit=1)[0]
        return f" Vorschlag: `/ha service {domain} {service} {entity_id}`."

    def _extract_entity_id(self, text: str) -> str | None:
        for word in text.replace("`", " ").split():
            cleaned = word.strip(".,:;!?()[]{}<>")
            if "." in cleaned:
                domain, _ = cleaned.split(".", maxsplit=1)
                if domain in {"light", "switch", "fan", "climate", "cover"}:
                    return cleaned
        if "kinderzimmer" in text and "licht" in text:
            return "light.kinderzimmer"
        return None

    def _infer_service(self, text: str) -> str | None:
        if " aus" in text or "ausschalten" in text or "turn_off" in text:
            return "turn_off"
        if " an" in text or "einschalten" in text or "turn_on" in text:
            return "turn_on"
        return None

    def _asks_for_active_lights(self, text: str) -> bool:
        return "licht" in text and (
            " an" in text
            or "eingeschaltet" in text
            or "brennen" in text
            or "leuchten" in text
        )

    def _asks_for_switched_on_devices(self, text: str) -> bool:
        device_terms = ("geraet", "geraete", "steckdose", "switch", "schalter")
        return any(term in text for term in device_terms) and (
            " an" in text or "eingeschaltet" in text or "aktiv" in text
        )

    def _asks_for_unavailable_devices(self, text: str) -> bool:
        problem_terms = ("nicht verfuegbar", "unavailable", "unknown", "offline")
        device_terms = ("geraet", "geraete", "entity", "entities", "sensor")
        return any(term in text for term in problem_terms) and (
            any(term in text for term in device_terms) or "welche" in text
        )

    def _asks_for_home_status(self, message: str) -> bool:
        text = self._normalize(message).strip().strip(".!?")
        direct_phrases = {
            "status",
            "hausstatus",
            "ist alles okay",
            "check mal die wohnung",
        }
        if text in direct_phrases:
            return True
        phrase_markers = (
            "wie sieht es zuhause aus",
            "wie siehts zuhause aus",
            "was ist los zuhause",
            "was ist zuhause los",
            "check die wohnung",
            "check mal zuhause",
            "alles okay zuhause",
        )
        return any(marker in text for marker in phrase_markers)

    def _asks_for_unclear_whole_house_action(self, message: str) -> bool:
        text = self._normalize(message).strip().strip(".!?")
        return text in {"mach alles aus", "alles aus", "schalte alles aus"}

    def _asks_for_weather(self, text: str) -> bool:
        weather_terms = ("wetter", "forecast", "vorhersage", "regen", "temperatur")
        question_terms = ("wie", "was", "heute", "morgen", "draussen", "draußen")
        return any(term in text for term in weather_terms) and any(
            term in text for term in question_terms
        )

    def _asks_for_recent_events(self, text: str) -> bool:
        return (
            "was ist gerade" in text
            or "was ist passiert" in text
            or "ereignisse" in text
            or "zuletzt passiert" in text
        ) and ("haus" in text or "home assistant" in text or "passiert" in text)

    def _asks_for_light_reason(self, text: str) -> bool:
        return (
            "warum" in text
            and "licht" in text
            and ("ging" in text or "an" in text or "eingeschaltet" in text)
        )

    def _asks_for_recent_automation(self, text: str) -> bool:
        return "automation" in text and (
            "zuletzt" in text or "ausgeloest" in text or "ausgelöst" in text
        )

    def _asks_for_offline_events(self, text: str) -> bool:
        return (
            "offline" in text
            or "nicht verfuegbar" in text
            or "unavailable" in text
            or "unknown" in text
        ) and ("gegangen" in text or "etwas" in text or "was" in text)

    def _format_entities_for_answer(
        self,
        title: str,
        entities: list[EntityView],
    ) -> str:
        if not entities:
            return f"{title}: Ich finde gerade keine passenden Entitaeten."
        lines = [f"{title}: {len(entities)} Treffer."]
        for entity in entities[:10]:
            room = f" [{entity.room}]" if entity.room else ""
            lines.append(f"- {entity.entity_id}{room}: {entity.state} ({entity.label})")
        return "\n".join(lines)

    def _format_weather_for_answer(self, analysis: HomeAssistantAnalysis) -> str:
        weather_entities = [
            entity
            for entity in analysis.by_domain.get("weather", [])
            if entity.state not in {"unavailable", "unknown"}
        ]
        if not weather_entities:
            return (
                "Wetter: Ich finde gerade keine aktive weather-Entitaet "
                "in Home Assistant."
            )

        entity = self._preferred_weather_entity(weather_entities)
        attributes = entity.raw.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}

        condition = self._translate_weather_condition(entity.state)
        temperature = attributes.get("temperature")
        temperature_unit = attributes.get("temperature_unit") or attributes.get(
            "unit_of_measurement"
        )
        humidity = attributes.get("humidity")
        wind_speed = attributes.get("wind_speed")
        wind_unit = attributes.get("wind_speed_unit")

        details = [f"{condition}"]
        if temperature not in {None, ""}:
            unit = self._format_temperature_unit(temperature_unit)
            details.append(f"{temperature}{unit}")
        if humidity not in {None, ""}:
            details.append(f"{humidity} % Luftfeuchte")
        if wind_speed not in {None, ""}:
            unit = f" {wind_unit}" if wind_unit else ""
            details.append(f"Wind {wind_speed}{unit}")

        return f"Wetter heute: {', '.join(details)}. Quelle: {entity.label}."

    def _format_temperature_unit(self, unit: object) -> str:
        if unit is None or unit == "":
            return " Grad"
        unit_text = str(unit)
        if "c" in unit_text.lower():
            return " Grad"
        return f" {unit_text}"

    def _preferred_weather_entity(self, entities: list[EntityView]) -> EntityView:
        return sorted(
            entities,
            key=lambda entity: (
                "forecast_home" in entity.entity_id,
                "home" in self._normalize(entity.label),
                entity.entity_id,
            ),
        )[0]

    def _translate_weather_condition(self, condition: str) -> str:
        translations = {
            "clear-night": "klar",
            "cloudy": "bewoelkt",
            "fog": "neblig",
            "hail": "Hagel",
            "lightning": "Gewitter",
            "lightning-rainy": "Gewitter mit Regen",
            "partlycloudy": "teilweise bewoelkt",
            "pouring": "starker Regen",
            "rainy": "regnerisch",
            "snowy": "Schnee",
            "snowy-rainy": "Schneeregen",
            "sunny": "sonnig",
            "windy": "windig",
            "windy-variant": "windig und bewoelkt",
        }
        return translations.get(condition, condition)

    def _normalize(self, text: str) -> str:
        return (
            text.lower()
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )

    def _respond(self, message: str) -> None:
        self.console.print(f"[bold cyan]Kira:[/bold cyan] {message}")
        self.last_response = message
        self._write_session_line("kira", message)

    def _open_session_log(self) -> TextIO:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        log_dir = self.settings.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        session_log_path = log_dir / f"chat-{timestamp}.log"
        self.logger.info("Chat session log: %s", session_log_path)
        return session_log_path.open("a", encoding="utf-8")

    def _write_session_line(self, role: str, message: str) -> None:
        if self.session_log is None:
            return
        timestamp = datetime.now(UTC).isoformat()
        self.session_log.write(f"{timestamp} | {role} | {message}\n")
        self.session_log.flush()


def format_memory_item(item: MemoryItem) -> str:
    """Format a memory item for display in chat output."""
    return f"{item.title}: {item.content}"
