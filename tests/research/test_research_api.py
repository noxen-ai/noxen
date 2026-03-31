"""Test suite per api/routes/research.py — Step 3.7 Phase 3."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from fastapi import FastAPI

from api.routes.research import router, init_router
from core.research_agent import ResearchResult
from core.research.github_client import RepoCandidate
from core.research.web_researcher import WebResearchResult
from core.research.skill_builder import SkillDefinition


# ── Fixtures ────────────────────────────────────────────────────────

def _make_candidate(name="o/repo", stars=100):
    return RepoCandidate(
        full_name=name, url=f"https://github.com/{name}",
        description="test desc", stars=stars, language="Python",
        topics=["test"], last_updated=datetime.now(timezone.utc),
        size_kb=1000, has_readme=True, readme_preview="# Test",
        relevance_score=0.85,
    )


def _make_skill(name="test-skill"):
    return SkillDefinition(
        name=name, description="Test skill",
        category="api", tags=["test"], content="content",
        confidence=0.8,
    )


@pytest.fixture
def mock_agent():
    """Mock ResearchAgent."""
    agent = MagicMock()
    agent._github = MagicMock()
    agent._analyzer = MagicMock()
    agent._web = MagicMock()
    agent._skill_builder = MagicMock()
    agent._kb = MagicMock()

    agent.research = AsyncMock(return_value=ResearchResult(
        query="fastapi",
        repos_found=[_make_candidate()],
        repos_analyzed=[],
        web_results=[WebResearchResult(query="fastapi", total_results=3)],
        skills_generated=[_make_skill()],
        skills_saved=1,
        duration_s=2.5,
    ))

    agent.quick_search = AsyncMock(return_value=[_make_candidate()])
    agent.detect_knowledge_gap = AsyncMock(return_value=True)

    return agent


@pytest.fixture
def client(mock_agent):
    """Test client con research router."""
    app = FastAPI()
    app.include_router(router)
    init_router(mock_agent)
    from tests.conftest import override_tenant_auth
    override_tenant_auth(app)
    return TestClient(app)


@pytest.fixture
def client_no_agent():
    """Test client senza research agent."""
    app = FastAPI()
    app.include_router(router)
    init_router(None)
    from tests.conftest import override_tenant_auth
    override_tenant_auth(app)
    return TestClient(app)


# ── Test POST /api/research ─────────────────────────────────────────

def test_research_success(client, mock_agent):
    """POST /api/research ritorna risultati."""
    resp = client.post("/api/research", json={"query": "fastapi patterns"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "fastapi"
    assert data["repos_found"] == 1
    assert data["skills_generated"] == 1
    assert data["skills_saved"] == 1
    assert data["duration_s"] == 2.5
    assert len(data["skills"]) == 1
    assert data["skills"][0]["name"] == "test-skill"


def test_research_not_configured(client_no_agent):
    """POST /api/research senza agent ritorna 503."""
    resp = client_no_agent.post("/api/research", json={"query": "test"})
    assert resp.status_code == 503


def test_research_with_params(client, mock_agent):
    """POST /api/research con parametri custom."""
    resp = client.post("/api/research", json={
        "query": "fastapi",
        "language": "Python",
        "max_repos": 3,
        "max_web_results": 5,
        "auto_save": False,
    })
    assert resp.status_code == 200
    mock_agent.research.assert_called_once()


def test_research_short_query(client):
    """POST /api/research con query troppo corta."""
    resp = client.post("/api/research", json={"query": "x"})
    assert resp.status_code == 422  # validation error


def test_research_repos_in_response(client):
    """POST /api/research include repos nel response."""
    resp = client.post("/api/research", json={"query": "fastapi"})
    data = resp.json()
    assert len(data["repos"]) == 1
    assert data["repos"][0]["full_name"] == "o/repo"
    assert data["repos"][0]["stars"] == 100


# ── Test GET /api/research/search ────────────────────────────────────

def test_quick_search_success(client, mock_agent):
    """GET /api/research/search ritorna risultati."""
    resp = client.get("/api/research/search?query=fastapi&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "fastapi"
    assert len(data["results"]) == 1
    assert data["results"][0]["full_name"] == "o/repo"


def test_quick_search_not_configured(client_no_agent):
    """GET /api/research/search senza agent ritorna 503."""
    resp = client_no_agent.get("/api/research/search?query=test")
    assert resp.status_code == 503


def test_quick_search_short_query(client):
    """GET /api/research/search con query troppo corta."""
    resp = client.get("/api/research/search?query=x")
    assert resp.status_code == 400


# ── Test POST /api/research/gap ──────────────────────────────────────

def test_gap_detect_success(client, mock_agent):
    """POST /api/research/gap ritorna gap detection."""
    resp = client.post("/api/research/gap", json={
        "query": "kubernetes deployment",
        "existing_skills": ["python-testing"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_gap"] is True
    assert data["existing_skills_checked"] == 1


def test_gap_detect_not_configured(client_no_agent):
    """POST /api/research/gap senza agent ritorna 503."""
    resp = client_no_agent.post("/api/research/gap", json={"query": "test"})
    assert resp.status_code == 503


def test_gap_detect_empty_skills(client, mock_agent):
    """POST /api/research/gap senza existing_skills."""
    resp = client.post("/api/research/gap", json={"query": "test"})
    assert resp.status_code == 200


# ── Test GET /api/research/status ────────────────────────────────────

def test_status_configured(client):
    """GET /api/research/status con agent configurato."""
    resp = client.get("/api/research/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["components"]["github_client"] is True
    assert data["components"]["repo_analyzer"] is True


def test_status_not_configured(client_no_agent):
    """GET /api/research/status senza agent."""
    resp = client_no_agent.get("/api/research/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False


# ── Test init_router() ──────────────────────────────────────────────

def test_init_router_sets_agent():
    """init_router() imposta il research agent."""
    agent = MagicMock()
    init_router(agent)
    # Reset
    init_router(None)
