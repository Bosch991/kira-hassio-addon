"""Backup service for local Kira data."""

from __future__ import annotations

import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path


class BackupService:
    """Create and restore local Kira backups."""

    def __init__(self, *, root_dir: Path, data_dir: Path, config_dir: Path) -> None:
        """Initialize the backup service."""
        self.root_dir = root_dir
        self.data_dir = data_dir
        self.config_dir = config_dir

    def create_backup(self, output_dir: Path | None = None) -> Path:
        """Create a timestamped backup ZIP."""
        target_dir = output_dir or self.data_dir / "backups"
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        archive = target_dir / f"kira-backup-{timestamp}.zip"
        self.export_archive(archive)
        return archive

    def export_archive(self, archive: Path) -> Path:
        """Export Kira memory, knowledge, prompts, plugin config, and profile."""
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in ("memory.json", "conversation.json", "profile.json"):
                self._write_if_exists(zf, self.data_dir / name, f"data/{name}")
            self._write_tree(zf, self.root_dir / "knowledge", "knowledge")
            self._write_tree(zf, self.root_dir / "prompts", "prompts")
            self._write_tree(zf, self.config_dir / "plugins", "config/plugins")
        return archive

    def import_archive(self, archive: Path) -> None:
        """Import a backup archive into the current Kira root."""
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                self._extract_member(zf, member.filename)

    def _write_tree(
        self,
        zf: zipfile.ZipFile,
        source_dir: Path,
        archive_prefix: str,
    ) -> None:
        if not source_dir.exists():
            return
        for path in source_dir.rglob("*"):
            if path.is_file():
                zf.write(path, f"{archive_prefix}/{path.relative_to(source_dir)}")

    def _write_if_exists(
        self,
        zf: zipfile.ZipFile,
        source: Path,
        archive_name: str,
    ) -> None:
        if source.exists():
            zf.write(source, archive_name)

    def _extract_member(self, zf: zipfile.ZipFile, name: str) -> None:
        if name.startswith("data/"):
            target = self.data_dir / Path(name).relative_to("data")
        elif name.startswith("knowledge/"):
            target = self.root_dir / name
        elif name.startswith("prompts/"):
            target = self.root_dir / name
        elif name.startswith("config/plugins/"):
            target = self.root_dir / name
        else:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(name) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
