"""Test suite per core/execution/goal_graph.py — Step 4.2."""

import json
import pytest

from core.execution.goal_graph import (
    GoalGraph,
    GoalNode,
    GoalStatus,
    GoalCategory,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def graph():
    """GoalGraph vuoto."""
    return GoalGraph()


@pytest.fixture
def simple_goal():
    """Goal semplice senza dipendenze."""
    return GoalNode(
        id="goal_001",
        title="Add tests",
        description="Write unit tests for core module",
        priority=1,
        category=GoalCategory.TEST,
    )


@pytest.fixture
def chain_graph():
    """Graph con catena: A -> B -> C."""
    g = GoalGraph()
    g.add_goal(GoalNode(id="A", title="Step A", description="First step", priority=1))
    g.add_goal(GoalNode(id="B", title="Step B", description="Second step", priority=2, depends_on=["A"]))
    g.add_goal(GoalNode(id="C", title="Step C", description="Third step", priority=3, depends_on=["B"]))
    return g


@pytest.fixture
def diamond_graph():
    """Graph a diamante: A -> B, A -> C, B -> D, C -> D."""
    g = GoalGraph()
    g.add_goal(GoalNode(id="A", title="Root", description="Root goal", priority=1))
    g.add_goal(GoalNode(id="B", title="Left", description="Left branch", priority=2, depends_on=["A"]))
    g.add_goal(GoalNode(id="C", title="Right", description="Right branch", priority=2, depends_on=["A"]))
    g.add_goal(GoalNode(id="D", title="Merge", description="Merge point", priority=3, depends_on=["B", "C"]))
    return g


# ── Test GoalNode ────────────────────────────────────────────────────

def test_goal_node_creation(simple_goal):
    """GoalNode si crea con valori corretti."""
    assert simple_goal.id == "goal_001"
    assert simple_goal.title == "Add tests"
    assert simple_goal.priority == 1
    assert simple_goal.status == GoalStatus.PENDING
    assert simple_goal.category == GoalCategory.TEST
    assert simple_goal.depends_on == []
    assert simple_goal.attempts == 0


def test_goal_node_defaults():
    """GoalNode ha default sensati."""
    g = GoalNode(id="x", title="X", description="desc")
    assert g.priority == 2
    assert g.category == GoalCategory.OPTIMIZATION
    assert g.max_attempts == 3
    assert g.complexity == 5
    assert g.files_changed == []
    assert g.result_summary == ""


def test_goal_node_to_dict(simple_goal):
    """to_dict() serializza correttamente."""
    d = simple_goal.to_dict()
    assert d["id"] == "goal_001"
    assert d["status"] == "pending"
    assert d["category"] == "test"
    assert isinstance(d["depends_on"], list)


def test_goal_node_from_dict():
    """from_dict() deserializza correttamente."""
    data = {
        "id": "g1",
        "title": "Goal 1",
        "description": "desc",
        "priority": 1,
        "status": "done",
        "category": "fix",
        "depends_on": [],
    }
    goal = GoalNode.from_dict(data)
    assert goal.id == "g1"
    assert goal.status == GoalStatus.DONE
    assert goal.category == GoalCategory.FIX


def test_goal_node_is_terminal():
    """is_terminal e' True per DONE, FAILED, SKIPPED."""
    g = GoalNode(id="x", title="X", description="d")
    assert g.is_terminal is False

    g.status = GoalStatus.DONE
    assert g.is_terminal is True

    g.status = GoalStatus.FAILED
    assert g.is_terminal is True

    g.status = GoalStatus.SKIPPED
    assert g.is_terminal is True

    g.status = GoalStatus.IN_PROGRESS
    assert g.is_terminal is False

    g.status = GoalStatus.READY
    assert g.is_terminal is False


def test_goal_node_roundtrip():
    """to_dict() -> from_dict() preserva i dati."""
    original = GoalNode(
        id="g1", title="Test", description="desc",
        priority=1, category=GoalCategory.SECURITY,
        status=GoalStatus.IN_PROGRESS,
        depends_on=["g0"],
        attempts=2, max_attempts=5,
        result_summary="partial",
        files_changed=["a.py", "b.py"],
        complexity=8,
    )
    restored = GoalNode.from_dict(original.to_dict())
    assert restored.id == original.id
    assert restored.status == original.status
    assert restored.category == original.category
    assert restored.depends_on == original.depends_on
    assert restored.attempts == original.attempts
    assert restored.files_changed == original.files_changed


# ── Test GoalStatus enum ────────────────────────────────────────────

def test_goal_status_values():
    """GoalStatus ha tutti i valori attesi."""
    assert GoalStatus.PENDING.value == "pending"
    assert GoalStatus.READY.value == "ready"
    assert GoalStatus.IN_PROGRESS.value == "in_progress"
    assert GoalStatus.DONE.value == "done"
    assert GoalStatus.FAILED.value == "failed"
    assert GoalStatus.SKIPPED.value == "skipped"


def test_goal_category_values():
    """GoalCategory ha tutti i valori attesi."""
    assert GoalCategory.OPTIMIZATION.value == "optimization"
    assert GoalCategory.FEATURE.value == "feature"
    assert GoalCategory.FIX.value == "fix"
    assert GoalCategory.REFACTOR.value == "refactor"
    assert GoalCategory.SECURITY.value == "security"
    assert GoalCategory.TEST.value == "test"
    assert GoalCategory.DOCS.value == "docs"


# ── Test GoalGraph add/remove ────────────────────────────────────────

def test_add_goal(graph, simple_goal):
    """add_goal() aggiunge un goal al grafo."""
    graph.add_goal(simple_goal)
    assert graph.size == 1
    assert simple_goal.id in graph


def test_add_duplicate_goal(graph, simple_goal):
    """add_goal() lancia ValueError su duplicato."""
    graph.add_goal(simple_goal)
    with pytest.raises(ValueError, match="already exists"):
        graph.add_goal(simple_goal)


def test_add_goal_with_missing_dependency(graph):
    """add_goal() lancia ValueError se la dipendenza non esiste."""
    goal = GoalNode(id="g1", title="X", description="d", depends_on=["nonexistent"])
    with pytest.raises(ValueError, match="not found"):
        graph.add_goal(goal)


def test_add_goal_creates_cycle(graph):
    """add_goal() lancia ValueError se creerebbe un ciclo."""
    graph.add_goal(GoalNode(id="A", title="A", description="a"))
    graph.add_goal(GoalNode(id="B", title="B", description="b", depends_on=["A"]))
    graph.add_goal(GoalNode(id="C", title="C", description="c", depends_on=["B"]))
    # D depends on A but A depends on D — cycle via A -> B -> C -> D -> A
    # Actually: D depends on C, and we try to add E that depends on D and A depends on E
    # Simplest: add D depending on C, then try to add a new A-replacement depending on D
    # Since we can't modify existing nodes, test with a longer chain:
    # A -> B -> C -> D, then try to add D -> A (but D is not in graph yet, let's add it)
    # D depends_on=["C", "A"] is fine (no cycle). We need D -> ... -> A somehow.
    # Let's just build a proper cycle: X -> Y -> Z -> X
    g2 = GoalGraph()
    g2.add_goal(GoalNode(id="X", title="X", description="x"))
    g2.add_goal(GoalNode(id="Y", title="Y", description="y", depends_on=["X"]))
    # Now add Z that depends on Y AND X depends on Z — but X is already added
    # The only way to create a cycle is to have Z depend on Y and X depend on Z
    # Since X is already added without dependencies, we'd need to edit it.
    # Test a self-referencing goal instead:
    g3 = GoalGraph()
    with pytest.raises(ValueError, match="cycle"):
        # Self-dependency creates a trivial cycle
        g3.add_goal(GoalNode(id="self", title="S", description="s", depends_on=["self"]))


def test_remove_goal(graph, simple_goal):
    """remove_goal() rimuove un goal."""
    graph.add_goal(simple_goal)
    assert graph.remove_goal(simple_goal.id) is True
    assert graph.size == 0
    assert simple_goal.id not in graph


def test_remove_nonexistent_goal(graph):
    """remove_goal() ritorna False se non esiste."""
    assert graph.remove_goal("nope") is False


def test_remove_goal_with_dependents(chain_graph):
    """remove_goal() lancia ValueError se altri goal dipendono da esso."""
    with pytest.raises(ValueError, match="depend on it"):
        chain_graph.remove_goal("A")


def test_remove_leaf_goal(chain_graph):
    """remove_goal() funziona su goal foglia (senza dipendenti)."""
    assert chain_graph.remove_goal("C") is True
    assert chain_graph.size == 2


# ── Test GoalGraph query ─────────────────────────────────────────────

def test_size(graph, simple_goal):
    """size ritorna il conteggio corretto."""
    assert graph.size == 0
    graph.add_goal(simple_goal)
    assert graph.size == 1


def test_len(chain_graph):
    """__len__ funziona."""
    assert len(chain_graph) == 3


def test_contains(chain_graph):
    """__contains__ funziona."""
    assert "A" in chain_graph
    assert "Z" not in chain_graph


def test_get_goal(chain_graph):
    """get_goal() ritorna il GoalNode corretto."""
    goal = chain_graph.get_goal("B")
    assert goal is not None
    assert goal.title == "Step B"
    assert goal.depends_on == ["A"]


def test_get_goal_not_found(graph):
    """get_goal() ritorna None se non esiste."""
    assert graph.get_goal("nope") is None


def test_all_goals_topological_order(chain_graph):
    """all_goals ritorna goal in ordine topologico."""
    goals = chain_graph.all_goals
    ids = [g.id for g in goals]
    assert ids.index("A") < ids.index("B")
    assert ids.index("B") < ids.index("C")


def test_all_goals_diamond(diamond_graph):
    """all_goals su diamond: A prima di B,C; B,C prima di D."""
    goals = diamond_graph.all_goals
    ids = [g.id for g in goals]
    assert ids.index("A") < ids.index("B")
    assert ids.index("A") < ids.index("C")
    assert ids.index("B") < ids.index("D")
    assert ids.index("C") < ids.index("D")


# ── Test ready goals ────────────────────────────────────────────────

def test_get_ready_goals_initial(chain_graph):
    """Inizialmente solo A (senza dipendenze) e' ready."""
    ready = chain_graph.get_ready_goals()
    assert len(ready) == 1
    assert ready[0].id == "A"


def test_get_ready_goals_after_completion(chain_graph):
    """Dopo completare A, B diventa ready."""
    chain_graph.update_status("A", GoalStatus.DONE)
    ready = chain_graph.get_ready_goals()
    assert len(ready) == 1
    assert ready[0].id == "B"


def test_get_ready_goals_diamond(diamond_graph):
    """Diamond: dopo A, sia B che C sono ready."""
    diamond_graph.update_status("A", GoalStatus.DONE)
    ready = diamond_graph.get_ready_goals()
    ready_ids = {g.id for g in ready}
    assert ready_ids == {"B", "C"}


def test_get_ready_goals_diamond_merge(diamond_graph):
    """Diamond: D diventa ready solo dopo sia B che C."""
    diamond_graph.update_status("A", GoalStatus.DONE)
    diamond_graph.update_status("B", GoalStatus.DONE)
    # C non ancora completato — D NON e' ready
    ready = diamond_graph.get_ready_goals()
    ready_ids = {g.id for g in ready}
    assert "D" not in ready_ids
    assert "C" in ready_ids

    # Completa C — ora D e' ready
    diamond_graph.update_status("C", GoalStatus.DONE)
    ready = diamond_graph.get_ready_goals()
    ready_ids = {g.id for g in ready}
    assert "D" in ready_ids


def test_get_ready_goals_skipped_dependency(chain_graph):
    """Goal skippatp conta come "completato" per le dipendenze."""
    chain_graph.update_status("A", GoalStatus.SKIPPED)
    ready = chain_graph.get_ready_goals()
    assert len(ready) == 1
    assert ready[0].id == "B"


def test_get_ready_goals_sorted_by_priority(graph):
    """Ready goals ordinati per priorita' (1 prima)."""
    graph.add_goal(GoalNode(id="low", title="Low", description="d", priority=3))
    graph.add_goal(GoalNode(id="high", title="High", description="d", priority=1))
    graph.add_goal(GoalNode(id="mid", title="Mid", description="d", priority=2))

    ready = graph.get_ready_goals()
    priorities = [g.priority for g in ready]
    assert priorities == [1, 2, 3]


def test_ready_goals_respects_max_attempts(graph):
    """Goal con attempts >= max_attempts non e' ready."""
    goal = GoalNode(id="g1", title="X", description="d", max_attempts=2)
    goal.attempts = 2
    graph.add_goal(goal)

    ready = graph.get_ready_goals()
    assert len(ready) == 0


# ── Test parallel groups ────────────────────────────────────────────

def test_parallel_groups_chain(chain_graph):
    """Chain: 3 gruppi di 1 goal ciascuno."""
    groups = chain_graph.get_parallel_groups()
    assert len(groups) == 3
    assert groups[0][0].id == "A"
    assert groups[1][0].id == "B"
    assert groups[2][0].id == "C"


def test_parallel_groups_diamond(diamond_graph):
    """Diamond: 3 gruppi — [A], [B, C], [D]."""
    groups = diamond_graph.get_parallel_groups()
    assert len(groups) == 3
    assert len(groups[0]) == 1  # A
    assert len(groups[1]) == 2  # B, C (parallel)
    assert len(groups[2]) == 1  # D

    group1_ids = {g.id for g in groups[1]}
    assert group1_ids == {"B", "C"}


def test_parallel_groups_independent(graph):
    """Goal indipendenti sono tutti nel primo gruppo."""
    graph.add_goal(GoalNode(id="a", title="A", description="d"))
    graph.add_goal(GoalNode(id="b", title="B", description="d"))
    graph.add_goal(GoalNode(id="c", title="C", description="d"))

    groups = graph.get_parallel_groups()
    assert len(groups) == 1
    assert len(groups[0]) == 3


# ── Test dependencies ────────────────────────────────────────────────

def test_get_dependencies(chain_graph):
    """get_dependencies() ritorna le dipendenze dirette."""
    deps = chain_graph.get_dependencies("B")
    assert len(deps) == 1
    assert deps[0].id == "A"


def test_get_dependencies_multiple(diamond_graph):
    """D dipende da B e C."""
    deps = diamond_graph.get_dependencies("D")
    dep_ids = {d.id for d in deps}
    assert dep_ids == {"B", "C"}


def test_get_dependencies_none(chain_graph):
    """A non ha dipendenze."""
    assert chain_graph.get_dependencies("A") == []


def test_get_dependents(chain_graph):
    """get_dependents() ritorna i goal dipendenti."""
    dependents = chain_graph.get_dependents("A")
    assert len(dependents) == 1
    assert dependents[0].id == "B"


def test_get_dependents_diamond(diamond_graph):
    """A ha B e C come dipendenti."""
    dependents = diamond_graph.get_dependents("A")
    dep_ids = {d.id for d in dependents}
    assert dep_ids == {"B", "C"}


# ── Test update_status ───────────────────────────────────────────────

def test_update_status(chain_graph):
    """update_status() cambia lo status del goal."""
    chain_graph.update_status("A", GoalStatus.IN_PROGRESS)
    assert chain_graph.get_goal("A").status == GoalStatus.IN_PROGRESS


def test_update_status_not_found(graph):
    """update_status() lancia KeyError se non esiste."""
    with pytest.raises(KeyError, match="not found"):
        graph.update_status("nope", GoalStatus.DONE)


def test_update_status_auto_ready(chain_graph):
    """Completare A rende B automaticamente READY."""
    chain_graph.update_status("A", GoalStatus.DONE)
    assert chain_graph.get_goal("B").status == GoalStatus.READY


def test_update_status_auto_ready_diamond(diamond_graph):
    """Diamond: completare A rende B e C READY."""
    diamond_graph.update_status("A", GoalStatus.DONE)
    assert diamond_graph.get_goal("B").status == GoalStatus.READY
    assert diamond_graph.get_goal("C").status == GoalStatus.READY
    # D resta PENDING (dipende da B e C)
    assert diamond_graph.get_goal("D").status == GoalStatus.PENDING


# ── Test is_complete ─────────────────────────────────────────────────

def test_is_complete_false(chain_graph):
    """is_complete e' False quando ci sono goal non terminali."""
    assert chain_graph.is_complete is False


def test_is_complete_true(chain_graph):
    """is_complete e' True quando tutti i goal sono terminali."""
    chain_graph.update_status("A", GoalStatus.DONE)
    chain_graph.update_status("B", GoalStatus.DONE)
    chain_graph.update_status("C", GoalStatus.DONE)
    assert chain_graph.is_complete is True


def test_is_complete_with_mixed_terminal(chain_graph):
    """is_complete con mix di DONE, FAILED, SKIPPED."""
    chain_graph.update_status("A", GoalStatus.DONE)
    chain_graph.update_status("B", GoalStatus.FAILED)
    chain_graph.update_status("C", GoalStatus.SKIPPED)
    assert chain_graph.is_complete is True


def test_is_complete_empty(graph):
    """Grafo vuoto e' completo."""
    assert graph.is_complete is True


# ── Test progress ────────────────────────────────────────────────────

def test_progress_initial(chain_graph):
    """progress() conta correttamente all'inizio."""
    p = chain_graph.progress
    assert p.get("pending", 0) == 3


def test_progress_mixed(chain_graph):
    """progress() conta correttamente con status misti."""
    chain_graph.update_status("A", GoalStatus.DONE)
    chain_graph.update_status("B", GoalStatus.IN_PROGRESS)
    p = chain_graph.progress
    assert p["done"] == 1
    assert p["in_progress"] == 1
    # C became PENDING (A done, but B not done yet)
    # B was set to READY when A completed, then to IN_PROGRESS
    assert p.get("pending", 0) + p.get("ready", 0) >= 1


# ── Test serialization ──────────────────────────────────────────────

def test_to_dict(chain_graph):
    """to_dict() produce struttura corretta."""
    d = chain_graph.to_dict()
    assert "goals" in d
    assert "edges" in d
    assert "progress" in d
    assert len(d["goals"]) == 3
    assert len(d["edges"]) == 2  # A->B, B->C


def test_to_json(chain_graph):
    """to_json() produce JSON valido."""
    j = chain_graph.to_json()
    data = json.loads(j)
    assert len(data["goals"]) == 3


def test_from_dict_roundtrip(diamond_graph):
    """to_dict() -> from_dict() preserva il grafo."""
    d = diamond_graph.to_dict()
    restored = GoalGraph.from_dict(d)

    assert restored.size == 4
    assert "A" in restored
    assert "D" in restored

    # Check dependencies preserved
    d_deps = restored.get_dependencies("D")
    dep_ids = {d.id for d in d_deps}
    assert dep_ids == {"B", "C"}


def test_from_json_roundtrip(chain_graph):
    """to_json() -> from_json() preserva il grafo."""
    j = chain_graph.to_json()
    restored = GoalGraph.from_json(j)

    assert restored.size == 3
    goals = restored.all_goals
    ids = [g.id for g in goals]
    assert ids.index("A") < ids.index("B") < ids.index("C")


def test_serialization_preserves_status(chain_graph):
    """Serializzazione preserva lo status dei goal."""
    chain_graph.update_status("A", GoalStatus.DONE)
    chain_graph.update_status("B", GoalStatus.IN_PROGRESS)

    d = chain_graph.to_dict()
    restored = GoalGraph.from_dict(d)

    assert restored.get_goal("A").status == GoalStatus.DONE
    assert restored.get_goal("B").status == GoalStatus.IN_PROGRESS


# ── Test empty graph ─────────────────────────────────────────────────

def test_empty_graph(graph):
    """Grafo vuoto ha dimensione 0."""
    assert graph.size == 0
    assert graph.all_goals == []
    assert graph.get_ready_goals() == []
    assert graph.get_parallel_groups() == []
    assert graph.is_complete is True
    assert graph.progress == {}
