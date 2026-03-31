# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
"""Noxen - Execution Engine (Phase 4 replacement for neural_engine.py).

Two-Loop Architecture con sandbox isolation, Goal Graph DAG,
Claude Code Executor, Approval Gate, e EventRouter integration.

  BOOTSTRAP  — Spider DNA + KB research + LLM ideation + Goal Graph
  INNER LOOP — Per ogni ready goal: genera istruzioni -> Claude Code -> registra
  OUTER LOOP — Verifica risultato, aggiorna goal status, decide CONTINUE/DONE
  APPROVAL   — Pausa per approvazione umana prima di eseguire

Step 4.4 della Phase 4.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from core.execution.claude_executor import (
    ClaudeExecutor,
    ExecutionResult,
    InstructionContext,
)
from core.execution.goal_graph import GoalCategory, GoalGraph, GoalNode, GoalStatus
from core.execution.sandbox_manager import SandboxInfo, SandboxManager
from core.logger import get_logger

logger = get_logger("noxen.engine")


# ── Constants ────────────────────────────────────────────────────────

MAX_TOTAL_CYCLES = 30
DEFAULT_TIMEOUT_S = 600


# ── Dataclass ────────────────────────────────────────────────────────

@dataclass
class EngineConfig:
    """Configurazione dell'Execution Engine."""

    max_cycles: int = MAX_TOTAL_CYCLES
    claude_timeout_s: int = DEFAULT_TIMEOUT_S
    require_approval: bool = True
    sandbox_base_dir: str = "./data/execution_sandbox"
    qdrant_persist: bool = True


@dataclass
class EngineState:
    """Stato corrente dell'Execution Engine."""

    run_id: str
    project_path: str
    project_name: str = ""
    phase: str = "idle"  # idle, bootstrap, awaiting_approval, running, done, error, stopped
    current_cycle: int = 0
    total_cycles: int = 0
    started_at: str = ""
    is_running: bool = False
    stop_requested: bool = False
    approval_pending: bool = False
    sandbox_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── ExecutionEngine ──────────────────────────────────────────────────

class ExecutionEngine:
    """Motore di esecuzione autonomo con sandbox, DAG, e approval gate.

    Lifecycle:
        1. run() avvia il loop
        2. Bootstrap: Spider analysis + LLM goal generation -> GoalGraph
        3. Approval gate: se require_approval, attende approvazione
        4. Inner loop: per ogni ready goal, genera istruzioni + Claude Code
        5. Outer loop: verifica risultato, aggiorna grafo
        6. Ripete 4-5 fino a completamento o max_cycles
    """

    def __init__(
        self,
        llm_query_fn=None,
        knowledge_base=None,
        event_router=None,
        config: EngineConfig | None = None,
        notification_engine=None,
    ) -> None:
        """
        Args:
            llm_query_fn: Async callable(system, user_msg) -> str.
            knowledge_base: KnowledgeBase per ricerca.
            event_router: EventRouter per emettere eventi.
            config: Configurazione engine.
            notification_engine: NotificationEngine per notifiche multi-canale.
        """
        self._config = config or EngineConfig()
        self._llm_query = llm_query_fn
        self._kb = knowledge_base
        self._event_router = event_router
        self._notification_engine = notification_engine

        self._sandbox_mgr = SandboxManager(
            sandbox_base_dir=self._config.sandbox_base_dir,
            qdrant_persist=self._config.qdrant_persist,
        )
        self._executor = ClaudeExecutor(
            llm_query_fn=llm_query_fn,
            timeout_s=self._config.claude_timeout_s,
        )

        self.state: EngineState | None = None
        self.goal_graph: GoalGraph | None = None
        self._sandbox_info: SandboxInfo | None = None
        self._approval_event: asyncio.Event | None = None

    # ── Public API ───────────────────────────────────────────────────

    async def run(
        self,
        project_path: str,
        project_name: str = "",
        goals: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Loop autonomo completo. Genera eventi SSE.

        Args:
            project_path: Path del progetto da analizzare/migliorare.
            project_name: Nome del progetto (opzionale, derivato dal path).
            goals: Lista di goal pre-definiti (opzionale, se None usa bootstrap).

        Yields:
            Dict con eventi SSE per il frontend.
        """
        run_id = uuid.uuid4().hex[:12]
        if not project_name:
            project_name = project_path.rstrip("/").split("/")[-1]

        # ── License enforcement ──
        try:
            from core.tenants.repository import TenantRepository
            from core.qdrant_client import DEFAULT_TENANT
            _repo = TenantRepository()
            _tenant_id = DEFAULT_TENANT
            _can, _reason = await _repo.activate_project(
                tenant_id=_tenant_id,
                project_name=project_name,
                project_path=project_path,
            )
            if not _can:
                yield {"phase": "license_error", "run_id": run_id,
                       "message": _reason, "upgrade_url": "https://noxen.ai/upgrade",
                       "done": True}
                return
            await _repo.increment_execution_session(_tenant_id)
        except Exception as _le:
            logger.warning("engine.license_check_failed", error=str(_le))

        self.state = EngineState(
            run_id=run_id,
            project_path=project_path,
            project_name=project_name,
            started_at=datetime.now(timezone.utc).isoformat(),
            is_running=True,
        )

        yield self._event("start", progress=0, detail="Execution Engine avviato")
        await self._emit_event("engine", {"action": "start", "run_id": run_id})

        try:
            # ── SANDBOX ──
            self.state.phase = "sandbox"
            yield self._event("sandbox", progress=5, detail="Creazione sandbox...")

            self._sandbox_info = await self._sandbox_mgr.create(
                project_path, run_id=run_id
            )
            self.state.sandbox_id = self._sandbox_info.sandbox_id

            yield self._event(
                "sandbox", progress=10,
                detail=f"Sandbox creata: {self._sandbox_info.branch_name}",
                sandbox_id=self._sandbox_info.sandbox_id,
            )

            # ── BOOTSTRAP ──
            if goals:
                # Use pre-defined goals
                self.goal_graph = self._build_graph_from_dicts(goals)
                yield self._event(
                    "bootstrap", progress=30,
                    detail=f"{self.goal_graph.size} goal caricati",
                )
            else:
                async for event in self._bootstrap():
                    yield event

            if not self.goal_graph or self.goal_graph.size == 0:
                yield self._event(
                    "error", progress=100,
                    detail="Nessun goal generato", done=True,
                )
                return

            # ── APPROVAL GATE ──
            if self._config.require_approval:
                self.state.phase = "awaiting_approval"
                self.state.approval_pending = True

                yield self._event(
                    "approval_required", progress=40,
                    detail=f"Piano con {self.goal_graph.size} goal pronto. In attesa di approvazione.",
                    goals=self.goal_graph.to_dict(),
                )

                # Send approval notification to all channels
                await self._notify_approval_request()

                # Wait for approval
                self._approval_event = asyncio.Event()
                await self._approval_event.wait()
                self.state.approval_pending = False

                if self.state.stop_requested:
                    # Notify rejection
                    await self._notify_completion("rejected")
                    yield self._event(
                        "stopped", progress=100,
                        detail="Esecuzione annullata", done=True,
                    )
                    return

                yield self._event(
                    "approved", progress=45,
                    detail="Piano approvato, inizio esecuzione",
                )

            # ── EXECUTION LOOP ──
            self.state.phase = "running"
            cycle_id = 0

            yield self._event(
                "loop_start", progress=50,
                detail=f"Inizio loop: {self.goal_graph.size} goal",
                goals=self.goal_graph.to_dict(),
            )

            while cycle_id < self._config.max_cycles:
                if self.state.stop_requested:
                    yield self._event(
                        "stopped", progress=100,
                        detail="Stop richiesto", done=True,
                    )
                    break

                # Get next ready goals
                ready = self.goal_graph.get_ready_goals()
                if not ready:
                    break

                goal = ready[0]  # Execute one at a time
                cycle_id += 1
                self.state.current_cycle = cycle_id
                self.state.total_cycles = cycle_id
                goal.attempts += 1

                self.goal_graph.update_status(goal.id, GoalStatus.IN_PROGRESS)

                yield self._event(
                    "cycle_start", progress=self._calc_progress(50, 95),
                    cycle=cycle_id, goal=goal.to_dict(),
                    detail=f"Ciclo {cycle_id}: {goal.title}",
                )

                # ── INNER LOOP ──
                async for event in self._inner_loop(goal, cycle_id):
                    yield event

                # ── OUTER LOOP ──
                async for event in self._outer_loop(goal, cycle_id):
                    yield event

            # ── DONE ──
            self.state.phase = "done"
            self.state.is_running = False
            progress = self.goal_graph.progress

            # Notify completion
            await self._notify_completion("done")

            yield self._event(
                "done", progress=100,
                detail=(
                    f"Completato: {progress.get('done', 0)}/{self.goal_graph.size} goal, "
                    f"{cycle_id} cicli"
                ),
                goals=self.goal_graph.to_dict(),
                done=True,
            )

        except Exception as e:
            self.state.phase = "error"
            self.state.error = str(e)
            self.state.is_running = False
            logger.error("engine.error", error=str(e))
            yield self._event(
                "error", progress=100,
                detail=f"Errore: {e}", done=True,
            )

        finally:
            # Cleanup sandbox
            if self._sandbox_info:
                await self._sandbox_mgr.cleanup(self._sandbox_info.sandbox_id)
            await self._emit_event("engine", {"action": "done", "run_id": run_id})

    def approve(self) -> bool:
        """Approva il piano e riprendi l'esecuzione.

        Returns:
            True se c'era un'approvazione pending, False altrimenti.
        """
        if self._approval_event and not self._approval_event.is_set():
            self._approval_event.set()
            return True
        return False

    def reject(self) -> bool:
        """Rifiuta il piano e ferma l'esecuzione.

        Returns:
            True se c'era un'approvazione pending, False altrimenti.
        """
        if self._approval_event and not self._approval_event.is_set():
            self.state.stop_requested = True
            self._approval_event.set()
            return True
        return False

    def request_stop(self) -> None:
        """Richiedi stop graceful del loop."""
        if self.state:
            self.state.stop_requested = True
            # If waiting for approval, unblock
            if self._approval_event:
                self._approval_event.set()

    def get_status(self) -> dict[str, Any]:
        """Ritorna stato corrente."""
        result = {"running": False, "state": None, "goals": None}
        if self.state:
            result["running"] = self.state.is_running
            result["state"] = self.state.to_dict()
        if self.goal_graph:
            result["goals"] = self.goal_graph.to_dict()
        return result

    # ── Bootstrap ────────────────────────────────────────────────────

    async def _bootstrap(self) -> AsyncGenerator[dict[str, Any], None]:
        """Bootstrap: analizza progetto e genera GoalGraph."""
        self.state.phase = "bootstrap"

        yield self._event(
            "bootstrap", progress=15,
            detail="Analisi progetto in corso...",
        )

        # Spider Discovery
        project_profile = await self._get_project_profile()

        yield self._event(
            "bootstrap", progress=20,
            detail="Progetto analizzato, ricerca best practice...",
        )

        # KB Research
        kb_context = await self._kb_search_context()

        yield self._event(
            "bootstrap", progress=30,
            detail="Generazione obiettivi...",
        )

        # LLM Goal Generation
        if self._llm_query:
            goals_data = await self._generate_goals_via_llm(
                project_profile, kb_context
            )
        else:
            goals_data = self._generate_default_goals()

        # Build GoalGraph
        self.goal_graph = self._build_graph_from_dicts(goals_data)

        yield self._event(
            "bootstrap", progress=40,
            detail=f"Bootstrap completato: {self.goal_graph.size} obiettivi",
            goals=self.goal_graph.to_dict(),
        )

    async def _get_project_profile(self) -> str:
        """Ottieni profilo del progetto (Spider discovery)."""
        try:
            from core.spider import SpiderAnalysis

            # SpiderAnalysis needs orchestrator, but we can use discovery directly
            # For now, just scan basic info from the sandbox path
            sandbox_path = self._sandbox_info.sandbox_path if self._sandbox_info else self.state.project_path
            return f"Project: {self.state.project_name}\nPath: {sandbox_path}"
        except Exception as e:
            return f"Project: {self.state.project_name} (profile unavailable: {e})"

    async def _kb_search_context(self) -> str:
        """Cerca nella KB per contesto."""
        if not self._kb:
            return ""
        try:
            results = await self._kb.search(
                f"best practices {self.state.project_name}", n_results=5
            )
            if results:
                docs = [r.get("document", "") for r in results]
                return "\n\n---\n\n".join(docs[:5])
        except Exception:
            pass
        return ""

    async def _generate_goals_via_llm(
        self, profile: str, kb_context: str
    ) -> list[dict[str, Any]]:
        """Genera goals via LLM."""
        import json as json_module

        system = (
            "Sei il Neural Development Engine.\n"
            "Genera una lista di 5-10 obiettivi di sviluppo per il progetto.\n\n"
            f"PROFILO:\n{profile}\n\n"
            f"BEST PRACTICE:\n{kb_context[:3000]}\n\n"
            "Rispondi SOLO con un JSON array valido, senza testo prima o dopo.\n"
            "Ogni obiettivo ha: id, title, description, priority (1-3), "
            "category (optimization/feature/fix/refactor/security/test/docs), "
            "depends_on (lista di id, vuota se nessuna dipendenza).\n"
        )

        prompt = "Genera gli obiettivi in formato JSON array."

        try:
            response = await self._llm_query(system, prompt)
            # Try to parse JSON from response
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            goals = json_module.loads(text)
            if isinstance(goals, dict) and "goals" in goals:
                goals = goals["goals"]
            return goals if isinstance(goals, list) else []
        except Exception as e:
            logger.warning("engine.goal_generation_failed", error=str(e))
            return self._generate_default_goals()

    def _generate_default_goals(self) -> list[dict[str, Any]]:
        """Goals di fallback."""
        return [
            {
                "id": "goal_001",
                "title": "Code Quality Audit",
                "description": "Analizza e migliora la qualita del codice.",
                "priority": 1,
                "category": "refactor",
                "depends_on": [],
            },
            {
                "id": "goal_002",
                "title": "Error Handling",
                "description": "Implementa error handling consistente.",
                "priority": 1,
                "category": "fix",
                "depends_on": [],
            },
            {
                "id": "goal_003",
                "title": "Add Tests",
                "description": "Aggiungi test per i moduli principali.",
                "priority": 2,
                "category": "test",
                "depends_on": ["goal_001"],
            },
        ]

    def _build_graph_from_dicts(
        self, goals_data: list[dict[str, Any]]
    ) -> GoalGraph:
        """Costruisci GoalGraph da lista di dict."""
        graph = GoalGraph()

        # First pass: add goals without dependencies
        for g in goals_data:
            node = GoalNode(
                id=g.get("id", f"goal_{uuid.uuid4().hex[:6]}"),
                title=g.get("title", "Untitled"),
                description=g.get("description", ""),
                priority=int(g.get("priority", 2)),
                category=GoalCategory(g.get("category", "optimization")),
                depends_on=[],  # Add deps in second pass
            )
            try:
                graph.add_goal(node)
            except ValueError:
                pass  # Skip duplicates

        # Second pass: add dependency edges
        for g in goals_data:
            goal_id = g.get("id", "")
            deps = g.get("depends_on", [])
            node = graph.get_goal(goal_id)
            if node and deps:
                for dep_id in deps:
                    if dep_id in graph and dep_id != goal_id:
                        node.depends_on.append(dep_id)
                        graph._graph.add_edge(dep_id, goal_id)

        return graph

    # ── Inner Loop ───────────────────────────────────────────────────

    async def _inner_loop(
        self,
        goal: GoalNode,
        cycle_id: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Esegui un goal: genera istruzioni + Claude Code."""
        sandbox_path = (
            self._sandbox_info.sandbox_path
            if self._sandbox_info
            else self.state.project_path
        )

        yield self._event(
            "inner_loop", progress=self._calc_progress(55, 75),
            step="planning", goal_id=goal.id, cycle=cycle_id,
            detail=f"Generazione istruzioni per: {goal.title}",
        )

        # Generate instructions
        context = InstructionContext(
            project_name=self.state.project_name,
            project_path=sandbox_path,
            goal_title=goal.title,
            goal_description=goal.description,
            goal_category=goal.category.value,
        )

        instructions = await self._executor.generate_instructions(context)

        yield self._event(
            "inner_loop", progress=self._calc_progress(60, 80),
            step="executing", goal_id=goal.id, cycle=cycle_id,
            detail=f"Esecuzione Claude Code ({len(instructions)} chars)...",
        )

        # Execute
        result = await self._executor.execute(
            instructions=instructions,
            working_dir=sandbox_path,
            goal_id=goal.id,
        )

        # Store result on goal
        goal.files_changed = result.files_changed

        yield self._event(
            "inner_loop", progress=self._calc_progress(70, 85),
            step="done", goal_id=goal.id, cycle=cycle_id,
            detail=(
                f"Completato in {result.duration_s:.0f}s — "
                f"exit={result.exit_code}, "
                f"{len(result.files_changed)} file"
            ),
            result=result.to_dict(),
        )

        # Save the result for outer loop
        self._last_result = result

    # ── Outer Loop ───────────────────────────────────────────────────

    async def _outer_loop(
        self,
        goal: GoalNode,
        cycle_id: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Verifica risultato e aggiorna goal status."""

        result = getattr(self, "_last_result", None)
        if not result:
            self.goal_graph.update_status(goal.id, GoalStatus.FAILED)
            yield self._event(
                "outer_loop", step="failed", goal_id=goal.id,
                detail="Nessun risultato dall'inner loop",
            )
            return

        yield self._event(
            "outer_loop", progress=self._calc_progress(75, 90),
            step="verifying", goal_id=goal.id, cycle=cycle_id,
            detail="Verifica risultato...",
        )

        # Verify via LLM
        verification = await self._executor.verify(
            result, goal.title, goal.description,
        )

        # Determine success
        goal_completed = self._evaluate_completion(result, verification)

        if goal_completed:
            self.goal_graph.update_status(goal.id, GoalStatus.DONE)
            goal.result_summary = verification[:500] if verification else "Completed"
        elif goal.attempts >= goal.max_attempts:
            self.goal_graph.update_status(goal.id, GoalStatus.FAILED)
            goal.result_summary = f"Failed after {goal.attempts} attempts"
        else:
            self.goal_graph.update_status(goal.id, GoalStatus.PENDING)

        yield self._event(
            "outer_loop", progress=self._calc_progress(80, 95),
            step="evaluated", goal_id=goal.id, cycle=cycle_id,
            goal_completed=goal_completed,
            detail=(
                f"Goal {'COMPLETATO' if goal_completed else 'da ritentare'}: "
                f"{goal.title}"
            ),
            progress_summary=self.goal_graph.progress,
        )

    def _evaluate_completion(
        self, result: ExecutionResult, verification: str
    ) -> bool:
        """Determina se il goal e' completato."""
        if result.exit_code != 0:
            return False
        if not result.success:
            return False
        if verification:
            v_lower = verification.lower()[:200]
            if "no" in v_lower[:20] and "si" not in v_lower[:20]:
                return False
        return True

    # ── Notification helpers ─────────────────────────────────────────

    async def _notify_approval_request(self) -> None:
        """Send approval request via NotificationEngine (if configured)."""
        if not self._notification_engine or not self.goal_graph or not self.state:
            return
        try:
            from core.notifications.base import ApprovalPlan

            goals_summary = []
            for node in list(self.goal_graph._goals.values())[:10]:
                goals_summary.append({
                    "title": node.title,
                    "description": node.description,
                })

            groups = self.goal_graph.get_parallel_groups()
            plan = ApprovalPlan(
                run_id=self.state.run_id,
                project_name=self.state.project_name,
                goals=goals_summary,
                total_goals=self.goal_graph.size,
                parallel_groups=len(groups),
            )
            await self._notification_engine.send_approval_request(plan)
        except Exception as e:
            logger.warning("engine.notification_failed", error=str(e))

    async def _notify_completion(self, status: str) -> None:
        """Send completion/rejection notification."""
        if not self._notification_engine or not self.state:
            return
        try:
            title = f"Noxen — Execution {status.title()}"
            if self.goal_graph:
                progress = self.goal_graph.progress
                message = (
                    f"Project: {self.state.project_name}\n"
                    f"Run: {self.state.run_id}\n"
                    f"Goals: {progress.get('done', 0)}/{self.goal_graph.size} completed\n"
                    f"Cycles: {self.state.total_cycles}"
                )
            else:
                message = f"Project: {self.state.project_name}\nRun: {self.state.run_id}"

            level = "success" if status == "done" else "warning"
            await self._notification_engine.send_notification(title, message, level)
        except Exception as e:
            logger.warning("engine.notification_failed", error=str(e))

    # ── Helpers ──────────────────────────────────────────────────────

    def _event(self, phase: str, **kwargs) -> dict[str, Any]:
        """Crea un evento SSE."""
        event = {"phase": phase, "run_id": self.state.run_id if self.state else ""}
        event.update(kwargs)
        return event

    def _calc_progress(self, min_pct: int, max_pct: int) -> int:
        """Calcola progresso basato su goal completati."""
        if not self.goal_graph or self.goal_graph.size == 0:
            return min_pct
        progress = self.goal_graph.progress
        done = progress.get("done", 0) + progress.get("skipped", 0) + progress.get("failed", 0)
        total = self.goal_graph.size
        ratio = done / total
        return min_pct + int((max_pct - min_pct) * ratio)

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emetti evento via EventRouter."""
        if self._event_router:
            try:
                await self._event_router.emit(
                    event_type=event_type,
                    data=data,
                    source="execution_engine",
                )
            except Exception:
                pass  # Non-fatal
