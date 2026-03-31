"""Noxen - Goal Graph (DAG) for Execution Engine.

Gestisce i goal come Directed Acyclic Graph:
  - GoalNode: singolo obiettivo con metadata
  - GoalGraph: DAG con dipendenze, ordinamento topologico, gruppi paralleli
  - Serializzazione JSON per Qdrant/SSE
  - Validazione cicli (no circular dependencies)

Step 4.2 della Phase 4.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import networkx as nx

from core.logger import get_logger

logger = get_logger("noxen.goal_graph")


# ── Enums ────────────────────────────────────────────────────────────

class GoalStatus(str, Enum):
    """Stato di un goal nel grafo."""
    PENDING = "pending"
    READY = "ready"          # Tutte le dipendenze completate
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class GoalCategory(str, Enum):
    """Categoria di un goal."""
    OPTIMIZATION = "optimization"
    FEATURE = "feature"
    FIX = "fix"
    REFACTOR = "refactor"
    SECURITY = "security"
    TEST = "test"
    DOCS = "docs"


# ── GoalNode ─────────────────────────────────────────────────────────

@dataclass
class GoalNode:
    """Singolo obiettivo nel Goal Graph.

    Attributes:
        id: Identificatore unico (es. "goal_001").
        title: Titolo breve del goal.
        description: Descrizione dettagliata.
        priority: 1=critico, 2=alto, 3=medio.
        category: Tipo di goal.
        status: Stato corrente.
        depends_on: Lista di goal_id da cui dipende.
        max_attempts: Numero massimo di tentativi.
        attempts: Tentativi correnti.
        result_summary: Riassunto del risultato.
        files_changed: File modificati durante l'esecuzione.
        complexity: Complessita' stimata (1-10).
    """

    id: str
    title: str
    description: str
    priority: int = 2
    category: GoalCategory = GoalCategory.OPTIMIZATION
    status: GoalStatus = GoalStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    max_attempts: int = 3
    attempts: int = 0
    result_summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    complexity: int = 5

    def to_dict(self) -> dict[str, Any]:
        """Serializza in dict per JSON/SSE."""
        d = asdict(self)
        d["status"] = self.status.value
        d["category"] = self.category.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoalNode:
        """Deserializza da dict."""
        data = dict(data)  # copy
        if "status" in data and isinstance(data["status"], str):
            data["status"] = GoalStatus(data["status"])
        if "category" in data and isinstance(data["category"], str):
            data["category"] = GoalCategory(data["category"])
        return cls(**data)

    @property
    def is_terminal(self) -> bool:
        """True se il goal e' in uno stato finale."""
        return self.status in (GoalStatus.DONE, GoalStatus.FAILED, GoalStatus.SKIPPED)


# ── GoalGraph ────────────────────────────────────────────────────────

class GoalGraph:
    """DAG di goal con dipendenze, ordinamento, e gruppi paralleli.

    Usa networkx per il grafo diretto. Ogni nodo ha un GoalNode come dato.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._goals: dict[str, GoalNode] = {}

    # ── CRUD ─────────────────────────────────────────────────────────

    def add_goal(self, goal: GoalNode) -> None:
        """Aggiunge un goal al grafo.

        Args:
            goal: GoalNode da aggiungere.

        Raises:
            ValueError: Se il goal_id esiste gia'.
            ValueError: Se aggiungere il goal creerebbe un ciclo.
        """
        if goal.id in self._goals:
            raise ValueError(f"Goal '{goal.id}' already exists")

        self._graph.add_node(goal.id)
        self._goals[goal.id] = goal

        # Add dependency edges
        for dep_id in goal.depends_on:
            if dep_id not in self._goals:
                raise ValueError(
                    f"Dependency '{dep_id}' not found. "
                    f"Add it before adding '{goal.id}'."
                )
            self._graph.add_edge(dep_id, goal.id)

        # Check for cycles
        if not nx.is_directed_acyclic_graph(self._graph):
            # Rollback
            self._graph.remove_node(goal.id)
            del self._goals[goal.id]
            raise ValueError(
                f"Adding goal '{goal.id}' would create a cycle"
            )

    def remove_goal(self, goal_id: str) -> bool:
        """Rimuove un goal dal grafo. Ritorna True se rimosso."""
        if goal_id not in self._goals:
            return False

        # Check no other goals depend on this
        dependents = list(self._graph.successors(goal_id))
        if dependents:
            raise ValueError(
                f"Cannot remove '{goal_id}': goals {dependents} depend on it"
            )

        self._graph.remove_node(goal_id)
        del self._goals[goal_id]
        return True

    def get_goal(self, goal_id: str) -> GoalNode | None:
        """Ritorna il GoalNode per ID, o None."""
        return self._goals.get(goal_id)

    def update_status(self, goal_id: str, status: GoalStatus) -> None:
        """Aggiorna lo status di un goal."""
        goal = self._goals.get(goal_id)
        if not goal:
            raise KeyError(f"Goal '{goal_id}' not found")
        goal.status = status

        # Auto-update READY status on dependent goals
        if status in (GoalStatus.DONE, GoalStatus.SKIPPED):
            self._update_ready_goals()

    # ── Query ────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """Numero totale di goal nel grafo."""
        return len(self._goals)

    @property
    def all_goals(self) -> list[GoalNode]:
        """Tutti i goal in ordine topologico."""
        order = list(nx.topological_sort(self._graph))
        return [self._goals[gid] for gid in order if gid in self._goals]

    def get_ready_goals(self) -> list[GoalNode]:
        """Ritorna goal pronti per l'esecuzione.

        Un goal e' READY se:
        1. Status e' PENDING o READY
        2. Tutte le dipendenze sono DONE o SKIPPED
        3. Non ha superato max_attempts

        Ordinati per priorita' (1 prima).
        """
        ready = []
        for goal in self._goals.values():
            if goal.status not in (GoalStatus.PENDING, GoalStatus.READY):
                continue
            if goal.attempts >= goal.max_attempts:
                continue
            # Check all dependencies
            deps = list(self._graph.predecessors(goal.id))
            all_deps_done = all(
                self._goals[d].is_terminal
                for d in deps
                if d in self._goals
            )
            if all_deps_done:
                ready.append(goal)

        ready.sort(key=lambda g: g.priority)
        return ready

    def get_parallel_groups(self) -> list[list[GoalNode]]:
        """Ritorna gruppi di goal eseguibili in parallelo.

        Ogni gruppo contiene goal senza dipendenze reciproche,
        ordinati per "livello" nel DAG (topological generations).
        """
        groups = []
        for generation in nx.topological_generations(self._graph):
            group = [
                self._goals[gid]
                for gid in generation
                if gid in self._goals
            ]
            if group:
                groups.append(group)
        return groups

    def get_dependencies(self, goal_id: str) -> list[GoalNode]:
        """Ritorna i goal da cui dipende goal_id."""
        if goal_id not in self._graph:
            return []
        return [
            self._goals[d]
            for d in self._graph.predecessors(goal_id)
            if d in self._goals
        ]

    def get_dependents(self, goal_id: str) -> list[GoalNode]:
        """Ritorna i goal che dipendono da goal_id."""
        if goal_id not in self._graph:
            return []
        return [
            self._goals[d]
            for d in self._graph.successors(goal_id)
            if d in self._goals
        ]

    @property
    def is_complete(self) -> bool:
        """True se tutti i goal sono in stato terminale."""
        return all(g.is_terminal for g in self._goals.values())

    @property
    def progress(self) -> dict[str, int]:
        """Conteggio goal per status."""
        counts: dict[str, int] = {}
        for goal in self._goals.values():
            key = goal.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    # ── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serializza il grafo completo in dict."""
        return {
            "goals": [g.to_dict() for g in self.all_goals],
            "edges": [
                {"from": u, "to": v}
                for u, v in self._graph.edges()
            ],
            "progress": self.progress,
        }

    def to_json(self) -> str:
        """Serializza in JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoalGraph:
        """Deserializza da dict."""
        graph = cls()
        # Add goals in order (they should already be topologically sorted)
        for g_data in data.get("goals", []):
            goal = GoalNode.from_dict(g_data)
            # Temporarily clear depends_on to add in order
            deps = goal.depends_on
            goal.depends_on = []
            graph._graph.add_node(goal.id)
            graph._goals[goal.id] = goal
            goal.depends_on = deps

        # Add edges from depends_on
        for goal in graph._goals.values():
            for dep_id in goal.depends_on:
                if dep_id in graph._goals:
                    graph._graph.add_edge(dep_id, goal.id)

        return graph

    @classmethod
    def from_json(cls, json_str: str) -> GoalGraph:
        """Deserializza da JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ── Internal ─────────────────────────────────────────────────────

    def _update_ready_goals(self) -> None:
        """Aggiorna status a READY per goal le cui dipendenze sono completate."""
        for goal in self._goals.values():
            if goal.status != GoalStatus.PENDING:
                continue
            deps = list(self._graph.predecessors(goal.id))
            all_deps_done = all(
                self._goals[d].is_terminal
                for d in deps
                if d in self._goals
            )
            if all_deps_done:
                goal.status = GoalStatus.READY

    def __len__(self) -> int:
        return self.size

    def __contains__(self, goal_id: str) -> bool:
        return goal_id in self._goals
