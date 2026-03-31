"""Test suite per core/execution/engine.py — Step 4.4."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from core.execution.engine import (
    ExecutionEngine,
    EngineConfig,
    EngineState,
    MAX_TOTAL_CYCLES,
)
from core.execution.goal_graph import GoalGraph, GoalNode, GoalStatus, GoalCategory
from core.execution.claude_executor import ExecutionResult


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_project(tmp_path):
    """Crea un progetto di esempio."""
    proj = tmp_path / "test_project"
    proj.mkdir()
    (proj / "main.py").write_text("print('hello')\n")
    (proj / "README.md").write_text("# Test\n")
    return proj


@pytest.fixture
def config(tmp_path):
    """Engine config per test (no Qdrant, no approval)."""
    return EngineConfig(
        max_cycles=5,
        claude_timeout_s=30,
        require_approval=False,
        sandbox_base_dir=str(tmp_path / "sandboxes"),
        qdrant_persist=False,
    )


@pytest.fixture
def config_with_approval(tmp_path):
    """Engine config con approval gate."""
    return EngineConfig(
        max_cycles=5,
        claude_timeout_s=30,
        require_approval=True,
        sandbox_base_dir=str(tmp_path / "sandboxes"),
        qdrant_persist=False,
    )


@pytest.fixture
def mock_llm():
    """Mock LLM che ritorna risposte sensate."""
    return AsyncMock(return_value="SI, il goal e' stato completato correttamente.")


@pytest.fixture
def mock_event_router():
    """Mock EventRouter."""
    router = MagicMock()
    router.emit = AsyncMock()
    return router


@pytest.fixture
def sample_goals():
    """Lista di goal pre-definiti."""
    return [
        {
            "id": "g1",
            "title": "Add error handling",
            "description": "Implementa try/except in tutti gli endpoint.",
            "priority": 1,
            "category": "fix",
            "depends_on": [],
        },
        {
            "id": "g2",
            "title": "Add tests",
            "description": "Scrivi test per gli endpoint.",
            "priority": 2,
            "category": "test",
            "depends_on": ["g1"],
        },
    ]


@pytest.fixture
def engine(config, mock_llm, mock_event_router):
    """Engine completo con mock."""
    return ExecutionEngine(
        llm_query_fn=mock_llm,
        knowledge_base=None,
        event_router=mock_event_router,
        config=config,
    )


# ── Test EngineConfig ────────────────────────────────────────────────

def test_engine_config_defaults():
    """EngineConfig ha default sensati."""
    cfg = EngineConfig()
    assert cfg.max_cycles == MAX_TOTAL_CYCLES
    assert cfg.require_approval is True
    assert cfg.qdrant_persist is True


def test_engine_config_custom():
    """EngineConfig con valori custom."""
    cfg = EngineConfig(max_cycles=10, require_approval=False)
    assert cfg.max_cycles == 10
    assert cfg.require_approval is False


# ── Test EngineState ─────────────────────────────────────────────────

def test_engine_state_creation():
    """EngineState si crea correttamente."""
    state = EngineState(run_id="abc", project_path="/tmp/proj")
    assert state.run_id == "abc"
    assert state.phase == "idle"
    assert state.is_running is False
    assert state.stop_requested is False
    assert state.approval_pending is False


def test_engine_state_to_dict():
    """to_dict() produce dizionario."""
    state = EngineState(run_id="x", project_path="/tmp")
    d = state.to_dict()
    assert d["run_id"] == "x"
    assert d["phase"] == "idle"


# ── Test ExecutionEngine constructor ─────────────────────────────────

def test_engine_init(engine):
    """Engine si inizializza correttamente."""
    assert engine.state is None
    assert engine.goal_graph is None


def test_engine_init_no_args():
    """Engine funziona senza argomenti."""
    e = ExecutionEngine()
    assert e._llm_query is None
    assert e._kb is None
    assert e._event_router is None


# ── Test run() with pre-defined goals ────────────────────────────────

@pytest.mark.asyncio
async def test_run_with_goals(engine, sample_project, sample_goals):
    """run() con goal pre-definiti esegue il loop."""
    # Mock the executor to return success
    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="Task completed successfully with changes applied to the codebase.",
        exit_code=0, duration_s=5.0, success=True,
        files_changed=["main.py"],
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        events = []
        async for event in engine.run(
            str(sample_project), goals=sample_goals
        ):
            events.append(event)

    # Check we got events
    assert len(events) > 0

    # Check we have start and done events
    phases = [e["phase"] for e in events]
    assert "start" in phases
    assert "done" in phases

    # Check state
    assert engine.state.phase == "done"
    assert engine.state.is_running is False


@pytest.mark.asyncio
async def test_run_creates_sandbox(engine, sample_project, sample_goals):
    """run() crea una sandbox."""
    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="Done with the changes, everything works fine now correctly.",
        exit_code=0, duration_s=1.0, success=True,
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        events = []
        async for event in engine.run(str(sample_project), goals=sample_goals):
            events.append(event)

    # Check sandbox was created
    sandbox_events = [e for e in events if e.get("phase") == "sandbox"]
    assert len(sandbox_events) >= 1


@pytest.mark.asyncio
async def test_run_project_name_from_path(engine, sample_project, sample_goals):
    """run() deriva project_name dal path se non fornito."""
    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="Completed all tasks successfully with the required modifications.",
        exit_code=0, duration_s=1.0, success=True,
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        async for _ in engine.run(str(sample_project), goals=sample_goals):
            pass

    assert engine.state.project_name == "test_project"


@pytest.mark.asyncio
async def test_run_custom_project_name(engine, sample_project, sample_goals):
    """run() usa project_name custom se fornito."""
    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="All changes completed successfully for the entire codebase update.",
        exit_code=0, duration_s=1.0, success=True,
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        async for _ in engine.run(
            str(sample_project), project_name="CustomName", goals=sample_goals
        ):
            pass

    assert engine.state.project_name == "CustomName"


# ── Test approval gate ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_with_approval(sample_project, sample_goals, config_with_approval, mock_llm, mock_event_router):
    """run() con approval gate attende e poi procede."""
    engine = ExecutionEngine(
        llm_query_fn=mock_llm,
        event_router=mock_event_router,
        config=config_with_approval,
    )

    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="Changes applied successfully to the codebase with proper formatting.",
        exit_code=0, duration_s=1.0, success=True,
    )

    # Approve after a short delay
    async def auto_approve():
        await asyncio.sleep(0.1)
        engine.approve()

    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        approve_task = asyncio.create_task(auto_approve())
        events = []
        async for event in engine.run(str(sample_project), goals=sample_goals):
            events.append(event)
        await approve_task

    phases = [e["phase"] for e in events]
    assert "approval_required" in phases
    assert "approved" in phases
    assert "done" in phases


@pytest.mark.asyncio
async def test_reject_stops_execution(sample_project, sample_goals, config_with_approval, mock_llm, mock_event_router):
    """reject() ferma l'esecuzione."""
    engine = ExecutionEngine(
        llm_query_fn=mock_llm,
        event_router=mock_event_router,
        config=config_with_approval,
    )

    async def auto_reject():
        await asyncio.sleep(0.1)
        engine.reject()

    with patch.object(engine._executor, "execute", new_callable=AsyncMock):
        reject_task = asyncio.create_task(auto_reject())
        events = []
        async for event in engine.run(str(sample_project), goals=sample_goals):
            events.append(event)
        await reject_task

    phases = [e["phase"] for e in events]
    assert "approval_required" in phases
    assert "stopped" in phases
    assert "done" not in phases


def test_approve_no_pending():
    """approve() ritorna False senza approvazione pending."""
    engine = ExecutionEngine()
    assert engine.approve() is False


def test_reject_no_pending():
    """reject() ritorna False senza approvazione pending."""
    engine = ExecutionEngine()
    assert engine.reject() is False


# ── Test stop ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_stop(engine, sample_project, sample_goals):
    """request_stop() ferma il loop."""
    call_count = 0

    async def slow_execute(instructions, working_dir, goal_id=""):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            engine.request_stop()
        return ExecutionResult(
            goal_id=goal_id, instructions=instructions,
            output="Done with first goal implementation successfully, all tests pass.",
            exit_code=0, duration_s=1.0, success=True,
        )

    with patch.object(engine._executor, "execute", side_effect=slow_execute):
        events = []
        async for event in engine.run(str(sample_project), goals=sample_goals):
            events.append(event)

    phases = [e["phase"] for e in events]
    assert "stopped" in phases


# ── Test get_status ──────────────────────────────────────────────────

def test_get_status_initial():
    """get_status() su engine non avviato."""
    engine = ExecutionEngine()
    status = engine.get_status()
    assert status["running"] is False
    assert status["state"] is None
    assert status["goals"] is None


@pytest.mark.asyncio
async def test_get_status_after_run(engine, sample_project, sample_goals):
    """get_status() dopo esecuzione."""
    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="Completed the task with all required changes applied correctly.",
        exit_code=0, duration_s=1.0, success=True,
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        async for _ in engine.run(str(sample_project), goals=sample_goals):
            pass

    status = engine.get_status()
    assert status["state"] is not None
    assert status["goals"] is not None


# ── Test _build_graph_from_dicts ─────────────────────────────────────

def test_build_graph_from_dicts(engine, sample_goals):
    """_build_graph_from_dicts() crea GoalGraph corretto."""
    graph = engine._build_graph_from_dicts(sample_goals)
    assert graph.size == 2
    assert "g1" in graph
    assert "g2" in graph

    # Check dependency
    deps = graph.get_dependencies("g2")
    assert len(deps) == 1
    assert deps[0].id == "g1"


def test_build_graph_no_deps(engine):
    """Graph senza dipendenze."""
    goals = [
        {"id": "a", "title": "A", "description": "d"},
        {"id": "b", "title": "B", "description": "d"},
    ]
    graph = engine._build_graph_from_dicts(goals)
    assert graph.size == 2
    assert graph.get_dependencies("a") == []


def test_build_graph_invalid_dep(engine):
    """Dipendenza inesistente viene ignorata."""
    goals = [
        {"id": "a", "title": "A", "description": "d", "depends_on": ["nonexistent"]},
    ]
    graph = engine._build_graph_from_dicts(goals)
    assert graph.size == 1
    assert graph.get_dependencies("a") == []


# ── Test _generate_default_goals ─────────────────────────────────────

def test_generate_default_goals(engine):
    """_generate_default_goals() ritorna goal sensati."""
    goals = engine._generate_default_goals()
    assert len(goals) >= 2
    assert all("id" in g for g in goals)
    assert all("title" in g for g in goals)


# ── Test _evaluate_completion ────────────────────────────────────────

def test_evaluate_completion_success(engine):
    """Completamento con exit 0 e output lungo."""
    result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="x" * 100, exit_code=0, duration_s=1.0, success=True,
    )
    assert engine._evaluate_completion(result, "SI completato") is True


def test_evaluate_completion_failure_exit_code(engine):
    """Non completato se exit code != 0."""
    result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="x" * 100, exit_code=1, duration_s=1.0, success=True,
    )
    assert engine._evaluate_completion(result, "SI completato") is False


def test_evaluate_completion_failure_not_success(engine):
    """Non completato se success=False."""
    result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="x" * 100, exit_code=0, duration_s=1.0, success=False,
    )
    assert engine._evaluate_completion(result, "SI completato") is False


def test_evaluate_completion_no_verification(engine):
    """Completato senza verifica (no LLM)."""
    result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="x" * 100, exit_code=0, duration_s=1.0, success=True,
    )
    assert engine._evaluate_completion(result, "") is True


def test_evaluate_completion_negative_verification(engine):
    """Non completato se verifica dice NO."""
    result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="x" * 100, exit_code=0, duration_s=1.0, success=True,
    )
    assert engine._evaluate_completion(result, "NO, il goal non e' stato completato") is False


# ── Test _calc_progress ──────────────────────────────────────────────

def test_calc_progress_no_graph(engine):
    """progress senza graph ritorna min."""
    assert engine._calc_progress(50, 95) == 50


def test_calc_progress_with_graph(engine, sample_goals):
    """progress con graph calcola correttamente."""
    engine.goal_graph = engine._build_graph_from_dicts(sample_goals)
    # No goals done
    assert engine._calc_progress(50, 95) == 50

    # Complete one goal
    engine.goal_graph.update_status("g1", GoalStatus.DONE)
    progress = engine._calc_progress(50, 95)
    assert 50 < progress < 95


# ── Test event_router integration ────────────────────────────────────

@pytest.mark.asyncio
async def test_event_router_called(engine, sample_project, sample_goals, mock_event_router):
    """EventRouter.emit() viene chiamata durante run()."""
    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="Completed successfully with all the required code changes applied.",
        exit_code=0, duration_s=1.0, success=True,
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        async for _ in engine.run(str(sample_project), goals=sample_goals):
            pass

    # EventRouter should have been called
    assert mock_event_router.emit.call_count >= 2  # start + done


# ── Test empty goals ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_no_bootstrap_no_goals(sample_project, mock_event_router, tmp_path):
    """run() senza LLM e senza goal pre-definiti usa default goals."""
    config = EngineConfig(
        max_cycles=1,
        require_approval=False,
        sandbox_base_dir=str(tmp_path / "sb"),
        qdrant_persist=False,
    )
    engine = ExecutionEngine(
        llm_query_fn=None,  # No LLM
        event_router=mock_event_router,
        config=config,
    )

    mock_result = ExecutionResult(
        goal_id="g1", instructions="x",
        output="Done with the task, all changes applied successfully to the code.",
        exit_code=0, duration_s=1.0, success=True,
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        events = []
        async for event in engine.run(str(sample_project)):
            events.append(event)

    # Should use default goals from bootstrap
    assert engine.goal_graph.size >= 2


# ── Test max_cycles limit ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_max_cycles_respected(sample_project, mock_llm, mock_event_router, tmp_path):
    """Engine rispetta max_cycles."""
    config = EngineConfig(
        max_cycles=2,
        require_approval=False,
        sandbox_base_dir=str(tmp_path / "sb"),
        qdrant_persist=False,
    )
    engine = ExecutionEngine(
        llm_query_fn=mock_llm,
        event_router=mock_event_router,
        config=config,
    )

    # Goals that always "fail" (need retry)
    goals = [
        {"id": "g1", "title": "Hard task", "description": "d", "priority": 1,
         "category": "fix", "depends_on": [], "max_attempts": 5},
    ]

    mock_result = ExecutionResult(
        goal_id="g1", instructions="x", output="short",
        exit_code=0, duration_s=1.0, success=False,  # Not successful
    )
    with patch.object(engine._executor, "execute", new_callable=AsyncMock, return_value=mock_result):
        events = []
        async for event in engine.run(str(sample_project), goals=goals):
            events.append(event)

    # Should have stopped at max_cycles
    assert engine.state.total_cycles <= 2
