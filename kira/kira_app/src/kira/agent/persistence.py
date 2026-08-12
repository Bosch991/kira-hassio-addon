"""Small atomic persistence primitive for typed agent documents."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ValidationError

from kira.agent.models import utc_now


class AtomicDocumentStore[DocumentT: BaseModel]:
    """Read and replace one Pydantic JSON document under a process lock."""

    def __init__(
        self,
        path: Path,
        *,
        document_type: type[DocumentT],
        empty_factory: Callable[[], DocumentT],
    ) -> None:
        """Initialize the file contract and recovery factory."""
        self.path = path
        self.document_type = document_type
        self.empty_factory = empty_factory
        self._lock = RLock()
        self.logger = logging.getLogger(__name__)

    def initialize(self) -> None:
        """Create the parent and an empty document when missing."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self._write_unlocked(self.empty_factory())

    def read(self) -> DocumentT:
        """Return a defensive copy of the current document."""
        with self._lock:
            return self._read_unlocked().model_copy(deep=True)

    def update(self, mutate: Callable[[DocumentT], None]) -> DocumentT:
        """Mutate and atomically persist one document under the same lock."""
        with self._lock:
            document = self._read_unlocked()
            mutate(document)
            self._write_unlocked(document)
            return document.model_copy(deep=True)

    def _read_unlocked(self) -> DocumentT:
        self.initialize()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return self.document_type.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            self.logger.warning("Agent document could not be loaded: %s", exc)
            document = self.empty_factory()
            backup = self.path.with_name(
                f"{self.path.name}.corrupt-{utc_now().strftime('%Y%m%d%H%M%S%f')}"
            )
            try:
                self.path.replace(backup)
                self._write_unlocked(document)
            except OSError as backup_error:
                self.logger.error("Agent document recovery failed: %s", backup_error)
            return document

    def _write_unlocked(self, document: DocumentT) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                document.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
