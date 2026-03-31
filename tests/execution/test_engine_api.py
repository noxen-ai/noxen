"""Test suite per API routes dell'Execution Engine — Step 4.5."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.orchestrator import router, init_router


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_orchestrator():
    """Mock Orchestrator con attributi necessari."""
    orch = MagicMock()
    orch.llm = MagicMock()
    orch.llm.stream_query = AsyncMock(return_value=iter(["test response"]))
    orch.knowledge_base = MagicMock()
    orch.knowledge_base.search = AsyncMock(return_value=[])
    orch.event_router = MagicMock()
    orch.event_router.emit = AsyncMock()
    return orch


@pytest.fixture
def mock_llm():
    """Mock LLMProvider."""
    llm = MagicMock()
    llm.available_providers = ["ollama", "gemini"]
    return llm


@pytest.fixture
def app(mock_orchestrator, mock_llm):
    """FastAPI app con routes configurate."""
    app = FastAPI()
    app.include_router(router)
    init_router(mock_orchestrator, mock_llm)
    from tests.conftest import override_tenant_auth
    override_tenant_auth(app)
    return app


@pytest.fixture
def client(app):
    """TestClient per l'app."""
    return TestClient(app)


# ── Test POST /api/engine/status (initial) ───────────────────────────

def test_engine_status_initial(client):
    """GET /api/engine/status ritorna not running inizialmente."""
    # Reset engine
    import api.routes.orchestrator as orch_module
    orch_module._execution_engine = None

    response = client.get("/api/engine/status")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["state"] is None


# ── Test POST /api/engine/approve (no pending) ──────────────────────

def test_engine_approve_no_pending(client):
    """POST /api/engine/approve senza engine attivo."""
    import api.routes.orchestrator as orch_module
    orch_module._execution_engine = None

    response = client.post("/api/engine/approve")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "no_approval_pending"


# ── Test POST /api/engine/reject (no pending) ───────────────────────

def test_engine_reject_no_pending(client):
    """POST /api/engine/reject senza engine attivo."""
    import api.routes.orchestrator as orch_module
    orch_module._execution_engine = None

    response = client.post("/api/engine/reject")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "no_approval_pending"


# ── Test POST /api/engine/stop (not running) ────────────────────────

def test_engine_stop_not_running(client):
    """POST /api/engine/stop senza engine attivo."""
    import api.routes.orchestrator as orch_module
    orch_module._execution_engine = None

    response = client.post("/api/engine/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_running"


# ── Test POST /api/engine/stop (with engine) ────────────────────────

def test_engine_stop_with_engine(client):
    """POST /api/engine/stop con engine attivo."""
    import api.routes.orchestrator as orch_module
    from core.execution.engine import ExecutionEngine, EngineConfig, EngineState

    engine = ExecutionEngine(config=EngineConfig(qdrant_persist=False))
    engine.state = EngineState(run_id="test", project_path="/tmp")
    orch_module._execution_engine = engine

    response = client.post("/api/engine/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "stop_requested"
    assert engine.state.stop_requested is True


# ── Test POST /api/engine/start (SSE streaming) ─────────────────────

def test_engine_start_returns_sse(client, tmp_path):
    """POST /api/engine/start ritorna SSE stream."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text("x = 1\n")

    from core.execution.engine import ExecutionEngine
    from core.execution.claude_executor import ExecutionResult

    # Patch ExecutionEngine.run to yield simple events
    async def mock_run(self, project_path, project_name="", goals=None):
        yield {"phase": "start", "progress": 0, "detail": "test"}
        yield {"phase": "done", "progress": 100, "detail": "done", "done": True}

    with patch.object(ExecutionEngine, "run", mock_run):
        response = client.post(
            "/api/engine/start",
            json={"project_path": str(proj), "require_approval": False},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    # Parse SSE events
    lines = response.text.strip().split("\n")
    data_lines = [l for l in lines if l.startswith("data: ")]
    assert len(data_lines) >= 2

    first_event = json.loads(data_lines[0].replace("data: ", ""))
    assert first_event["phase"] == "start"

    last_event = json.loads(data_lines[-1].replace("data: ", ""))
    assert last_event["phase"] == "done"


# ── Test POST /api/engine/status (with engine) ──────────────────────

def test_engine_status_with_engine(client):
    """GET /api/engine/status con engine attivo."""
    import api.routes.orchestrator as orch_module
    from core.execution.engine import ExecutionEngine, EngineConfig, EngineState
    from core.execution.goal_graph import GoalGraph, GoalNode

    engine = ExecutionEngine(config=EngineConfig(qdrant_persist=False))
    engine.state = EngineState(
        run_id="test123",
        project_path="/tmp/proj",
        project_name="TestProj",
        phase="running",
        is_running=True,
    )
    engine.goal_graph = GoalGraph()
    engine.goal_graph.add_goal(GoalNode(id="g1", title="Test", description="d"))

    orch_module._execution_engine = engine

    response = client.get("/api/engine/status")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is True
    assert data["state"]["run_id"] == "test123"
    assert data["state"]["project_name"] == "TestProj"
    assert data["goals"] is not None
    assert len(data["goals"]["goals"]) == 1


# ── Test backward compat: old engine endpoints still work ────────────

def test_old_engine_status_still_works(client):
    """GET /api/orchestrator/engine/status funziona ancora."""
    import api.routes.orchestrator as orch_module
    orch_module._engine = None

    response = client.get("/api/orchestrator/engine/status")
    assert response.status_code == 200
    data = response.json()
    assert "running" in data


def test_old_engine_stop_still_works(client):
    """POST /api/orchestrator/engine/stop funziona ancora."""
    import api.routes.orchestrator as orch_module
    orch_module._engine = None

    response = client.post("/api/orchestrator/engine/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_running"


# ── Test ExecutionEngineRequest validation ───────────────────────────

def test_start_requires_project_path(client):
    """POST /api/engine/start richiede project_path."""
    response = client.post("/api/engine/start", json={})
    assert response.status_code == 422  # Validation error


def test_start_with_goals(client, tmp_path):
    """POST /api/engine/start accetta goals pre-definiti."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "x.py").write_text("pass\n")

    from core.execution.engine import ExecutionEngine

    async def mock_run(self, project_path, project_name="", goals=None):
        yield {"phase": "done", "detail": "done", "done": True}

    with patch.object(ExecutionEngine, "run", mock_run):
        response = client.post(
            "/api/engine/start",
            json={
                "project_path": str(proj),
                "require_approval": False,
                "goals": [
                    {"id": "g1", "title": "Test", "description": "d",
                     "priority": 1, "category": "fix"},
                ],
            },
        )

    assert response.status_code == 200


# ── Test approve/reject with mock engine ─────────────────────────────

def test_approve_with_mock_engine(client):
    """POST /api/engine/approve con engine che ha approval pending."""
    import api.routes.orchestrator as orch_module

    mock_engine = MagicMock()
    mock_engine.approve.return_value = True
    orch_module._execution_engine = mock_engine

    response = client.post("/api/engine/approve")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    mock_engine.approve.assert_called_once()


def test_reject_with_mock_engine(client):
    """POST /api/engine/reject con engine che ha approval pending."""
    import api.routes.orchestrator as orch_module

    mock_engine = MagicMock()
    mock_engine.reject.return_value = True
    orch_module._execution_engine = mock_engine

    response = client.post("/api/engine/reject")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    mock_engine.reject.assert_called_once()
