"""Safety review, activation, and runtime execution for conditional tasks."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from kira.agent.context import ConversationContextStore
from kira.agent.entities import EntityCatalog
from kira.agent.execution import ActionExecutor
from kira.agent.models import (
    ActionPlan,
    AgentRequestContext,
    ConversationContext,
    utc_now,
)
from kira.agent.planning import HomeAssistantPlanner
from kira.agent.safety import PlanSafetyManager
from kira.agent.tasks import (
    AgentTask,
    TaskActionKind,
    TaskManager,
    TaskParser,
    TaskStatus,
)
from kira.homeassistant.events import HomeAssistantLiveEvent
from kira.homeassistant.permissions import PermissionDecision, RiskLevel
from kira.homeassistant.world_model import HomeAssistantWorldModel


@dataclass(frozen=True, slots=True)
class TaskCreationResult:
    """Result returned when a conditional request is registered."""

    handled: bool
    message: str
    task: AgentTask | None = None
    needs_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class TaskRunResult:
    """Outcome from evaluating and possibly executing one matched task."""

    task_id: str
    status: TaskStatus
    message: str


class TaskService:
    """Create safe durable tasks from parsed conditional user requests."""

    def __init__(
        self,
        *,
        parser: TaskParser,
        manager: TaskManager,
        planner: HomeAssistantPlanner,
        safety: PlanSafetyManager,
        activation_hook: Callable[[], object] | None = None,
        confirmation_seconds: int = 120,
    ) -> None:
        """Initialize creation dependencies and optional live-mode hook."""
        self.parser = parser
        self.manager = manager
        self.planner = planner
        self.safety = safety
        self.activation_hook = activation_hook
        self.confirmation_seconds = max(10, confirmation_seconds)
        self.logger = logging.getLogger(__name__)

    def is_task_request(self, message: str) -> bool:
        """Return whether this service owns the request."""
        return self.parser.is_task_request(message)

    def create(
        self,
        message: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> TaskCreationResult:
        """Parse, preview-plan, safety-review, and persist a task."""
        parsed = self.parser.parse(message, context, catalog)
        draft = parsed.draft
        if draft is None:
            return TaskCreationResult(True, parsed.message)
        if not draft.trigger.entity_ids:
            return TaskCreationResult(
                True,
                (
                    "Ich finde fuer den Ausloeser keine eindeutige Home-Assistant-"
                    "Entity. Die Aufgabe wurde deshalb nicht aktiviert."
                ),
            )
        unresolved_conditions = [
            condition.description
            for condition in draft.conditions
            if not condition.entity_ids
        ]
        if unresolved_conditions:
            return TaskCreationResult(
                True,
                (
                    "Ich finde fuer diese Zusatzbedingung keine eindeutige "
                    "Home-Assistant-Entity: "
                    f"{', '.join(unresolved_conditions)}. Der Task wurde nicht "
                    "aktiviert."
                ),
            )

        delegated = self.manager.find_existing_automation(draft, catalog)
        if delegated is not None:
            task = self.manager.create(
                draft,
                context,
                decision=PermissionDecision.AUTO_EXECUTE,
                risk=RiskLevel.LOW,
                delegated_automation_id=delegated,
            )
            return TaskCreationResult(
                True,
                (
                    "Dafuer existiert bereits eine passende Home-Assistant-"
                    f"Automation ({delegated}). Ich lasse den Ablauf dort."
                ),
                task,
            )

        action = draft.actions[0]
        if action.kind is TaskActionKind.NOTIFY:
            task = self.manager.create(
                draft,
                context,
                decision=PermissionDecision.AUTO_EXECUTE,
                risk=RiskLevel.LOW,
            )
            self._ensure_live_mode()
            return TaskCreationResult(
                True,
                (
                    f"Aufgabe {task.id[:8]} ist gespeichert. Ich reagiere erst, "
                    "wenn der Ausloeser eintritt."
                ),
                task,
            )

        if action.intent is None:
            return TaskCreationResult(True, "Die spaetere Aktion ist unvollstaendig.")
        planning = self.planner.plan(action.intent, context, catalog)
        if planning.plan is None:
            return TaskCreationResult(True, planning.message)
        plan = planning.plan.model_copy(
            update={"confidence": min(planning.plan.confidence, draft.confidence)}
        )
        review = self.safety.review(plan, catalog)
        authorized_ids = list(
            dict.fromkeys(
                entity_id for step in plan.steps for entity_id in step.entity_ids
            )
        )
        safe_draft = draft.model_copy(
            update={
                "actions": [
                    action.model_copy(update={"authorized_entity_ids": authorized_ids})
                ]
            }
        )
        task = self.manager.create(
            safe_draft,
            context,
            decision=review.decision,
            risk=review.risk_level,
            preview_plan=plan,
            confirmation_expires_at=(
                utc_now() + timedelta(seconds=self.confirmation_seconds)
                if review.decision is PermissionDecision.REQUIRE_CONFIRM
                else None
            ),
        )
        if task.status is TaskStatus.BLOCKED:
            reason = review.reasons[0] if review.reasons else "safety_blocked"
            return TaskCreationResult(
                True,
                (
                    "Diese bedingte Aufgabe wurde von der Sicherheitspruefung "
                    f"blockiert ({reason})."
                ),
                task,
            )
        if task.status is TaskStatus.PENDING_CONFIRMATION:
            return TaskCreationResult(
                True,
                (
                    f"Aufgabe {task.id[:8]} ist vorbereitet, aber wegen "
                    f"Risikostufe {task.safety_classification} noch nicht aktiv. "
                    "Mit 'Bestaetigen' aktivierst du nur die Aufgabe; sie wird "
                    "jetzt noch nicht ausgefuehrt."
                ),
                task,
                True,
            )
        self._ensure_live_mode()
        return TaskCreationResult(
            True,
            (
                f"Aufgabe {task.id[:8]} ist gespeichert. Die Aktion wird erst "
                "beim passenden Home-Assistant-Ereignis ausgefuehrt."
            ),
            task,
        )

    def confirm(self, task_id: str) -> AgentTask | None:
        """Activate one previously reviewed task after explicit confirmation."""
        task = self.manager.get(task_id)
        if task is None or task.status is not TaskStatus.PENDING_CONFIRMATION:
            return None
        activated = self.manager.activate(task_id)
        if activated is not None:
            self._ensure_live_mode()
        return activated

    def cancel(self, task_id: str) -> AgentTask | None:
        """Cancel a pending task."""
        return self.manager.cancel(task_id)

    def _ensure_live_mode(self) -> None:
        if self.activation_hook is None:
            return
        try:
            self.activation_hook()
        except Exception:
            self.logger.exception("Task activation could not start HA live mode")


class TaskRunner:
    """Evaluate live events and execute only pre-authorized task actions."""

    def __init__(
        self,
        *,
        manager: TaskManager,
        world: HomeAssistantWorldModel,
        contexts: ConversationContextStore,
        planner: HomeAssistantPlanner,
        safety: PlanSafetyManager,
        executor: ActionExecutor,
        notifier: Callable[[AgentTask, str], None] | None = None,
    ) -> None:
        """Initialize runtime dependencies."""
        self.manager = manager
        self.world = world
        self.contexts = contexts
        self.planner = planner
        self.safety = safety
        self.executor = executor
        self.notifier = notifier
        self.logger = logging.getLogger(__name__)
        self._queue: Queue[HomeAssistantLiveEvent | None] = Queue(maxsize=500)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._thread_lock = Lock()
        self._accepting = True

    def start(self) -> None:
        """Start the bounded background consumer once."""
        with self._thread_lock:
            self._accepting = True
            self._start_worker_locked()

    def stop(self) -> None:
        """Stop the background consumer without delaying shutdown indefinitely."""
        with self._thread_lock:
            self._accepting = False
            self._stop_event.set()
            thread = self._thread
        try:
            self._queue.put_nowait(None)
        except Full:
            pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        with self._thread_lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def submit(self, event: HomeAssistantLiveEvent) -> None:
        """Queue one event without blocking Home Assistant's websocket loop."""
        with self._thread_lock:
            if not self._accepting:
                self.logger.debug("Task event ignored during shutdown")
                return
            self._start_worker_locked()
        try:
            self._queue.put_nowait(event)
        except Full:
            self.logger.warning("Task event queue is full; event was dropped")

    def _start_worker_locked(self) -> None:
        """Start the worker while the lifecycle lock is held."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._queue = Queue(maxsize=500)
        self._thread = Thread(
            target=self._worker,
            name="kira-task-runner",
            daemon=True,
        )
        self._thread.start()

    def handle_event(self, event: HomeAssistantLiveEvent) -> list[TaskRunResult]:
        """Handle one normalized live event; websocket access stays read-only."""
        snapshot = self.world.refresh()
        if snapshot is None or not self.world.last_refresh_ok:
            return []
        catalog = EntityCatalog.from_snapshot(snapshot)
        results: list[TaskRunResult] = []
        for task in self.manager.match_event(event, catalog):
            claimed = self.manager.mark_running(task.id)
            if claimed is None:
                continue
            results.append(self._run(claimed, catalog))
        return results

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                if event is None:
                    return
                self.handle_event(event)
            except Exception:
                self.logger.exception("Conditional task event failed")
            finally:
                self._queue.task_done()

    def _run(self, task: AgentTask, catalog: EntityCatalog) -> TaskRunResult:
        action = task.actions[0]
        if action.kind is TaskActionKind.NOTIFY:
            message = f"Task ausgeloest: {task.trigger.description}"
            if self.notifier is not None:
                try:
                    self.notifier(task, message)
                except Exception:
                    self.logger.exception("Task notifier failed: %s", task.id)
                    self.manager.fail(task.id, "notification_failed")
                    return TaskRunResult(
                        task.id,
                        TaskStatus.FAILED,
                        "Benachrichtigung fehlgeschlagen.",
                    )
            self.manager.complete(task.id, "notification_emitted")
            return TaskRunResult(task.id, TaskStatus.COMPLETED, message)

        if action.intent is None:
            self.manager.fail(task.id, "missing_action_intent")
            return TaskRunResult(task.id, TaskStatus.FAILED, "Aktion fehlt.")
        context = self.contexts.get(
            AgentRequestContext(
                conversation_id=task.conversation_id,
                user=task.user,
                source=task.source,
                source_room=task.source_room,
            )
        )
        planning = self.planner.plan(action.intent, context, catalog)
        if planning.plan is None:
            self.manager.fail(task.id, f"planning_failed:{planning.message}")
            return TaskRunResult(task.id, TaskStatus.FAILED, planning.message)
        plan = planning.plan.model_copy(
            update={"confidence": min(planning.plan.confidence, task.confidence)}
        )
        review = self.safety.review(plan, catalog)
        if review.decision is PermissionDecision.BLOCK:
            self.manager.fail(task.id, "runtime_safety_blocked")
            return TaskRunResult(
                task.id,
                TaskStatus.FAILED,
                "Die Laufzeit-Sicherheitspruefung hat die Aktion blockiert.",
            )
        if not self._within_authorization(task, plan):
            self.manager.defer_confirmation(task.id, "runtime_plan_changed")
            return TaskRunResult(
                task.id,
                TaskStatus.PENDING_CONFIRMATION,
                "Der Laufzeitplan hat sich geaendert und braucht neue Bestaetigung.",
            )
        if (
            review.decision is PermissionDecision.REQUIRE_CONFIRM
            and task.confirmed_at is None
        ):
            self.manager.defer_confirmation(task.id, "runtime_confirmation_required")
            return TaskRunResult(
                task.id,
                TaskStatus.PENDING_CONFIRMATION,
                "Die Aktion braucht vor der Ausfuehrung eine Bestaetigung.",
            )
        execution = self.executor.execute(plan, catalog, user_text=task.request_text)
        if execution.ok:
            self.manager.complete(task.id, "executed_and_verified")
            return TaskRunResult(
                task.id,
                TaskStatus.COMPLETED,
                "Bedingte Aufgabe ausgefuehrt und verifiziert.",
            )
        self.manager.fail(task.id, "execution_failed")
        return TaskRunResult(
            task.id,
            TaskStatus.FAILED,
            "Die bedingte Aktion konnte nicht sicher abgeschlossen werden.",
        )

    def _within_authorization(self, task: AgentTask, plan: ActionPlan) -> bool:
        if task.preview_plan is None:
            return False
        preview_signatures = {
            (
                step.domain,
                step.service,
                tuple(sorted(step.entity_ids)),
                json.dumps(step.data, sort_keys=True, separators=(",", ":")),
            )
            for step in task.preview_plan.steps
        }
        runtime_signatures = {
            (
                step.domain,
                step.service,
                tuple(sorted(step.entity_ids)),
                json.dumps(step.data, sort_keys=True, separators=(",", ":")),
            )
            for step in plan.steps
        }
        return runtime_signatures <= preview_signatures
