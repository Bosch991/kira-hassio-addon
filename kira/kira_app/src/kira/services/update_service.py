"""Local update and deployment status helpers."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kira.version import KIRA_VERSION

MAX_OUTPUT_LENGTH = 800


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Sanitized command result."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        """Return whether the command completed successfully."""
        return self.returncode == 0


CommandRunner = Callable[[list[str], Path], CommandResult]


@dataclass(frozen=True, slots=True)
class LocalUpdateStatus:
    """Local Git and version status."""

    version: str
    branch: str
    commit: str
    clean: bool
    has_uncommitted_changes: bool
    has_untracked_files: bool
    remote_status: str = "not_checked"
    message: str = ""


@dataclass(frozen=True, slots=True)
class RemoteUpdateStatus:
    """Remote comparison result."""

    success: bool
    remote_status: str
    message: str
    ahead_by: int = 0
    behind_by: int = 0


@dataclass(frozen=True, slots=True)
class PullUpdateResult:
    """Result of a fast-forward update attempt."""

    success: bool
    message: str
    old_commit: str | None = None
    new_commit: str | None = None
    version: str | None = None
    restart_required: bool = False
    health: str | None = None


@dataclass(frozen=True, slots=True)
class HealthResult:
    """Lightweight post-update health result."""

    success: bool
    message: str
    version: str


class UpdateService:
    """Inspect and update a Git-backed Kira checkout safely."""

    def __init__(
        self,
        root_dir: Path,
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        """Initialize the service."""
        self.root_dir = root_dir
        self.runner = runner or self._default_runner

    def local_status(self, *, remote_status: str = "not_checked") -> LocalUpdateStatus:
        """Return local version and Git working tree status."""
        version = self.current_version()
        branch = self._git_text(["branch", "--show-current"], fallback="unknown")
        commit = self._git_text(["rev-parse", "--short", "HEAD"], fallback="unknown")
        status = self._git(["status", "--porcelain"])
        if not status.ok:
            return LocalUpdateStatus(
                version=version,
                branch=branch,
                commit=commit,
                clean=False,
                has_uncommitted_changes=False,
                has_untracked_files=False,
                remote_status="unavailable",
                message=self._message(status, "Git status is unavailable."),
            )

        lines = [line for line in status.stdout.splitlines() if line.strip()]
        has_untracked = any(line.startswith("??") for line in lines)
        has_uncommitted = any(not line.startswith("??") for line in lines)
        return LocalUpdateStatus(
            version=version,
            branch=branch or "unknown",
            commit=commit or "unknown",
            clean=not lines,
            has_uncommitted_changes=has_uncommitted,
            has_untracked_files=has_untracked,
            remote_status=remote_status,
            message="Local status read successfully.",
        )

    def check_remote(self) -> RemoteUpdateStatus:
        """Fetch and compare local HEAD with its upstream branch."""
        fetch = self._git(["fetch", "--quiet"])
        if not fetch.ok:
            return RemoteUpdateStatus(
                success=False,
                remote_status="remote_unavailable",
                message=self._message(fetch, "Remote is unavailable."),
            )

        upstream = self._git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
        )
        if not upstream.ok:
            return RemoteUpdateStatus(
                success=False,
                remote_status="remote_unavailable",
                message=self._message(upstream, "No upstream branch is configured."),
            )

        comparison = self._git(["rev-list", "--left-right", "--count", "HEAD...@{u}"])
        if not comparison.ok:
            return RemoteUpdateStatus(
                success=False,
                remote_status="remote_unavailable",
                message=self._message(comparison, "Could not compare with remote."),
            )

        ahead, behind = self._parse_ahead_behind(comparison.stdout)
        if ahead == 0 and behind == 0:
            return RemoteUpdateStatus(
                success=True,
                remote_status="up_to_date",
                message="Kira ist aktuell.",
            )
        if ahead == 0 and behind > 0:
            return RemoteUpdateStatus(
                success=True,
                remote_status="behind",
                message=f"GitHub hat {behind} neue Commits.",
                behind_by=behind,
            )
        if ahead > 0 and behind == 0:
            return RemoteUpdateStatus(
                success=True,
                remote_status="ahead",
                message=f"Lokaler Stand ist {ahead} Commits voraus.",
                ahead_by=ahead,
            )
        return RemoteUpdateStatus(
            success=True,
            remote_status="diverged",
            message=(
                f"Branch ist auseinander gelaufen: {ahead} voraus, "
                f"{behind} zurueck."
            ),
            ahead_by=ahead,
            behind_by=behind,
        )

    def pull_updates(self) -> PullUpdateResult:
        """Pull updates with fast-forward only when the working tree is clean."""
        status = self.local_status()
        if not status.clean:
            return PullUpdateResult(
                success=False,
                message=(
                    "Update abgebrochen. Es gibt lokale Aenderungen. "
                    "Bitte erst committen, stashen oder zuruecksetzen."
                ),
                old_commit=status.commit,
                new_commit=status.commit,
                version=status.version,
            )

        old_commit = status.commit
        pull = self._git(["pull", "--ff-only"])
        if not pull.ok:
            return PullUpdateResult(
                success=False,
                message=self._message(pull, "Update konnte nicht geladen werden."),
                old_commit=old_commit,
                new_commit=old_commit,
                version=status.version,
            )

        new_status = self.local_status()
        health = self.health_after_update()
        return PullUpdateResult(
            success=True,
            message="Update geladen. Neustart empfohlen.",
            old_commit=old_commit,
            new_commit=new_status.commit,
            version=new_status.version,
            restart_required=True,
            health=health.message,
        )

    def restart_hint(self) -> str:
        """Return a safe restart hint without killing processes."""
        return (
            "Terminal: Beende Kira mit STRG+C und starte erneut mit "
            "`python -m kira chat`. Server neu starten: `python -m kira server`. "
            "Home Assistant Add-on: Add-on in Home Assistant aktualisieren oder "
            "neu starten."
        )

    def health_after_update(self) -> HealthResult:
        """Run lightweight local health checks after an update."""
        version = self.current_version()
        check = self.runner([sys.executable, "-m", "kira", "--version"], self.root_dir)
        if check.ok:
            return HealthResult(
                success=True,
                message=f"Lokaler Versionscheck ok: {check.stdout.strip() or version}.",
                version=version,
            )
        return HealthResult(
            success=False,
            message=self._message(check, "Lokaler Versionscheck nicht verfuegbar."),
            version=version,
        )

    def current_version(self) -> str:
        """Read the current Kira version from pyproject, falling back to code."""
        pyproject = self.root_dir / "pyproject.toml"
        if not pyproject.exists():
            return KIRA_VERSION
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return KIRA_VERSION
        project = data.get("project")
        if not isinstance(project, dict):
            return KIRA_VERSION
        version = project.get("version")
        return version if isinstance(version, str) and version else KIRA_VERSION

    def _git(self, args: list[str]) -> CommandResult:
        return self.runner(["git", *args], self.root_dir)

    def _git_text(self, args: list[str], *, fallback: str) -> str:
        result = self._git(args)
        if not result.ok:
            return fallback
        return result.stdout.strip() or fallback

    def _default_runner(self, command: list[str], cwd: Path) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(returncode=1, stderr=str(exc))
        return CommandResult(
            returncode=completed.returncode,
            stdout=self._sanitize(completed.stdout),
            stderr=self._sanitize(completed.stderr),
        )

    def _parse_ahead_behind(self, output: str) -> tuple[int, int]:
        parts = output.strip().split()
        if len(parts) < 2:
            return 0, 0
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return 0, 0

    def _message(self, result: CommandResult, fallback: str) -> str:
        text = (result.stderr or result.stdout).strip()
        return text if text else fallback

    def _sanitize(self, text: str) -> str:
        text = text.strip()
        if len(text) <= MAX_OUTPUT_LENGTH:
            return text
        return text[:MAX_OUTPUT_LENGTH].rstrip() + " ..."
