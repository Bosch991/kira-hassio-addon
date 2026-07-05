"""Optional local HTTP media server for generated voice files."""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass
from enum import StrEnum
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class MediaServerStatus(StrEnum):
    """Media server state."""

    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class MediaServerInfo:
    """Current media server information."""

    status: MediaServerStatus
    host: str
    port: int
    root_dir: Path


class MediaServer:
    """Serve generated media files over HTTP when requested."""

    def __init__(self, *, root_dir: Path, host: str, port: int) -> None:
        """Initialize the media server."""
        self.root_dir = root_dir
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> MediaServerInfo:
        """Start the HTTP server if it is not already running."""
        if self._server is not None:
            return self.status()

        self.root_dir.mkdir(parents=True, exist_ok=True)
        handler = functools.partial(
            SimpleHTTPRequestHandler,
            directory=str(self.root_dir),
        )
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def stop(self) -> MediaServerInfo:
        """Stop the HTTP server if it is running."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None
        return self.status()

    def status(self) -> MediaServerInfo:
        """Return current server status."""
        status = (
            MediaServerStatus.RUNNING
            if self._server is not None
            else MediaServerStatus.STOPPED
        )
        return MediaServerInfo(
            status=status,
            host=self.host,
            port=self.port,
            root_dir=self.root_dir,
        )

    def url_for(self, path: Path, *, base_url: str) -> str:
        """Return a URL for a file under the served root directory."""
        relative = path.resolve().relative_to(self.root_dir.resolve())
        return f"{base_url.rstrip('/')}/{relative.as_posix()}"
