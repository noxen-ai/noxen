"""Test suite per integrazione Research Agent in Spider — Step 3.6 Phase 3."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from core.spider import SpiderAnalysis


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator per Spider."""
    orch = MagicMock()
    orch.llm = MagicMock()
    return orch


@pytest.fixture
def mock_research_agent():
    """Mock ResearchAgent."""
    from core.research_agent import ResearchResult
    from core.research.skill_builder import SkillDefinition

    agent = MagicMock()
    agent.research = AsyncMock(return_value=ResearchResult(
        query="test",
        repos_found=[MagicMock()],
        skills_generated=[SkillDefinition(name="s1", description="d", category="api")],
        skills_saved=1,
    ))
    return agent


@pytest.fixture
def mock_dna():
    """Mock ProjectDNA."""
    dna = MagicMock()
    dna.frameworks = ["FastAPI", "React"]
    dna.languages = ["Python", "JavaScript"]
    dna.total_files = 50
    dna.total_loc = 5000
    dna.total_dirs = 10
    dna.code_files = 30
    dna.has_db = False
    dna.has_tests = True
    dna.has_docker = False
    dna.has_ci = False
    dna.has_api = True
    dna.to_profile_text = MagicMock(return_value="test profile")
    dna.name = "test-project"
    dna.path = "/tmp/test"
    return dna


# ── Test Constructor ────────────────────────────────────────────────

def test_spider_init_with_research_agent(mock_orchestrator, mock_research_agent):
    """SpiderAnalysis accetta research_agent."""
    spider = SpiderAnalysis(mock_orchestrator, research_agent=mock_research_agent)
    assert spider.research_agent is mock_research_agent


def test_spider_init_without_research_agent(mock_orchestrator):
    """SpiderAnalysis funziona senza research_agent."""
    spider = SpiderAnalysis(mock_orchestrator)
    assert spider.research_agent is None


# ── Test _run_research_phase() ──────────────────────────────────────

@pytest.mark.asyncio
async def test_research_phase_no_agent(mock_orchestrator, mock_dna):
    """_run_research_phase() senza agent ritorna skipped."""
    spider = SpiderAnalysis(mock_orchestrator)
    result = await spider._run_research_phase(mock_dna)
    assert result["skipped"] is True


@pytest.mark.asyncio
async def test_research_phase_success(mock_orchestrator, mock_research_agent, mock_dna):
    """_run_research_phase() esegue ricerca con successo."""
    spider = SpiderAnalysis(mock_orchestrator, research_agent=mock_research_agent)
    result = await spider._run_research_phase(mock_dna)

    assert result["skipped"] is False
    assert result["repos_found"] >= 1
    assert result["skills_generated"] >= 1
    mock_research_agent.research.assert_called_once()


@pytest.mark.asyncio
async def test_research_phase_builds_query(mock_orchestrator, mock_research_agent, mock_dna):
    """_run_research_phase() costruisce query dai framework/linguaggi."""
    spider = SpiderAnalysis(mock_orchestrator, research_agent=mock_research_agent)
    await spider._run_research_phase(mock_dna)

    call_args = mock_research_agent.research.call_args[0][0]
    assert "FastAPI" in call_args.query
    assert call_args.language == "Python"


@pytest.mark.asyncio
async def test_research_phase_no_topics(mock_orchestrator, mock_research_agent):
    """_run_research_phase() salta se no framework/linguaggi."""
    dna = MagicMock()
    dna.frameworks = []
    dna.languages = []

    spider = SpiderAnalysis(mock_orchestrator, research_agent=mock_research_agent)
    result = await spider._run_research_phase(dna)

    assert result["skipped"] is True
    assert "no frameworks" in result["reason"]


@pytest.mark.asyncio
async def test_research_phase_error_handled(mock_orchestrator, mock_dna):
    """_run_research_phase() gestisce errori gracefully."""
    agent = MagicMock()
    agent.research = AsyncMock(side_effect=RuntimeError("research failed"))

    spider = SpiderAnalysis(mock_orchestrator, research_agent=agent)
    result = await spider._run_research_phase(mock_dna)

    assert result["skipped"] is True
    assert "research failed" in result["reason"]


@pytest.mark.asyncio
async def test_research_phase_auto_save(mock_orchestrator, mock_research_agent, mock_dna):
    """_run_research_phase() imposta auto_save=True."""
    spider = SpiderAnalysis(mock_orchestrator, research_agent=mock_research_agent)
    await spider._run_research_phase(mock_dna)

    call_args = mock_research_agent.research.call_args[0][0]
    assert call_args.auto_save is True


@pytest.mark.asyncio
async def test_research_phase_limits_repos(mock_orchestrator, mock_research_agent, mock_dna):
    """_run_research_phase() limita max_repos a 3."""
    spider = SpiderAnalysis(mock_orchestrator, research_agent=mock_research_agent)
    await spider._run_research_phase(mock_dna)

    call_args = mock_research_agent.research.call_args[0][0]
    assert call_args.max_repos == 3
    assert call_args.max_web_results == 5
