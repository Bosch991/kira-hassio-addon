"""Parser for Kira's local chat commands and memory notes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChatCommand(StrEnum):
    """Supported local chat commands."""

    EXIT = "exit"
    ABOUT = "about"
    AUDIO = "audio"
    BACKUP = "backup"
    BRIEFING = "briefing"
    EXPORT = "export"
    HA = "ha"
    HELP = "help"
    IMPORT = "import"
    LISTEN = "listen"
    MEMORY = "memory"
    MEDIA = "media"
    MESSAGE = "message"
    OPENART = "openart"
    PLUGIN = "plugin"
    PLUGINS = "plugins"
    PROJECTS = "projects"
    RELOAD = "reload"
    REMEMBER = "remember"
    STATS = "stats"
    SAY = "say"
    SERVER = "server"
    SPEAK = "speak"
    SPEAK_LAST = "speak_last"
    UNDO = "undo"
    VOICES = "voices"
    VOICE = "voice"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ParsedInput:
    """Normalized user input for the chat session."""

    command: ChatCommand
    text: str = ""


def parse_input(raw_input: str) -> ParsedInput:
    """Parse terminal input into a command or plain message."""
    value = raw_input.strip()
    if not value:
        return ParsedInput(ChatCommand.MESSAGE)

    lowered = value.lower()
    if lowered == "/exit":
        return ParsedInput(ChatCommand.EXIT)
    if lowered == "/about":
        return ParsedInput(ChatCommand.ABOUT)
    if lowered.startswith("/audio"):
        return ParsedInput(ChatCommand.AUDIO, value.removeprefix("/audio").strip())
    if lowered == "/backup":
        return ParsedInput(ChatCommand.BACKUP)
    if lowered.startswith("/briefing"):
        return ParsedInput(
            ChatCommand.BRIEFING,
            value.removeprefix("/briefing").strip(),
        )
    if lowered.startswith("/export"):
        return ParsedInput(ChatCommand.EXPORT, value.removeprefix("/export").strip())
    if lowered == "/help":
        return ParsedInput(ChatCommand.HELP)
    if lowered == "/listen":
        return ParsedInput(ChatCommand.LISTEN)
    if lowered.startswith("/import"):
        return ParsedInput(ChatCommand.IMPORT, value.removeprefix("/import").strip())
    if lowered.startswith("/ha"):
        return ParsedInput(ChatCommand.HA, value.removeprefix("/ha").strip())
    if lowered == "/memory":
        return ParsedInput(ChatCommand.MEMORY)
    if lowered.startswith("/media"):
        return ParsedInput(ChatCommand.MEDIA, value.removeprefix("/media").strip())
    if lowered.startswith("/openart"):
        return ParsedInput(
            ChatCommand.OPENART,
            value.removeprefix("/openart").strip(),
        )
    if lowered == "/plugins":
        return ParsedInput(ChatCommand.PLUGINS)
    if lowered.startswith("/plugin"):
        return ParsedInput(ChatCommand.PLUGIN, value.removeprefix("/plugin").strip())
    if lowered == "/projects":
        return ParsedInput(ChatCommand.PROJECTS)
    if lowered == "/reload":
        return ParsedInput(ChatCommand.RELOAD)
    if lowered == "/stats":
        return ParsedInput(ChatCommand.STATS)
    if lowered.startswith("/say"):
        return ParsedInput(ChatCommand.SAY, value.removeprefix("/say").strip())
    if lowered.startswith("/server"):
        return ParsedInput(ChatCommand.SERVER, value.removeprefix("/server").strip())
    if lowered == "/speak" or lowered.startswith("/speak "):
        return ParsedInput(ChatCommand.SPEAK, value.removeprefix("/speak").strip())
    if lowered.startswith("/speak_last"):
        return ParsedInput(
            ChatCommand.SPEAK_LAST,
            value.removeprefix("/speak_last").strip(),
        )
    if lowered.startswith("/undo"):
        return ParsedInput(ChatCommand.UNDO, value.removeprefix("/undo").strip())
    if lowered == "/voices":
        return ParsedInput(ChatCommand.VOICES)
    if lowered.startswith("/voice"):
        return ParsedInput(ChatCommand.VOICE, value.removeprefix("/voice").strip())
    if value.startswith("/"):
        return ParsedInput(ChatCommand.UNKNOWN, value)

    if lowered.startswith("merke:"):
        note = value.split(":", maxsplit=1)[1].strip()
        return ParsedInput(ChatCommand.REMEMBER, note)

    return ParsedInput(ChatCommand.MESSAGE, value)
