"""Local audio playback."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PlaybackStatus(StrEnum):
    """Possible playback outcomes."""

    SUCCESS = "success"
    FILE_NOT_FOUND = "file_not_found"
    DEPENDENCY_MISSING = "dependency_missing"
    PLAYBACK_ERROR = "playback_error"


@dataclass(frozen=True, slots=True)
class PlaybackResult:
    """Result of local audio playback."""

    status: PlaybackStatus
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether playback succeeded."""
        return self.status is PlaybackStatus.SUCCESS


class AudioPlayer:
    """Play audio files through the default system output."""

    def __init__(self, play_fn: Callable[[str], object] | None = None) -> None:
        """Initialize the player with an optional playback function."""
        self.play_fn = play_fn

    def play(
        self,
        path: Path,
        *,
        output_device: str | None = None,
    ) -> PlaybackResult:
        """Play an audio file."""
        if not path.exists():
            return PlaybackResult(
                status=PlaybackStatus.FILE_NOT_FOUND,
                error=f"Audio file not found: {path}",
            )

        try:
            if self.play_fn is not None:
                self.play_fn(str(path))
            else:
                _ = output_device
                os.startfile(path)
        except ModuleNotFoundError as exc:
            return PlaybackResult(
                status=PlaybackStatus.DEPENDENCY_MISSING,
                error=f"Audio playback dependency missing: {exc.name}",
            )
        except Exception as exc:
            return PlaybackResult(status=PlaybackStatus.PLAYBACK_ERROR, error=str(exc))

        return PlaybackResult(status=PlaybackStatus.SUCCESS)
