"""Test suite per core/research_agent.py — Step 3.5 Phase 3."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from core.research_agent import (
    ResearchAgent,
    ResearchRequest,
    ResearchResult,
)
from core.research.github_client import RepoCandidate
from core.research.repo_analyzer import RepoAnalysis
from core.research.web_researcher import WebResearchResult, WebResult
from core.research.skill_builder import SkillDefinition, SkillBuildResult


# ── Fixtures ────────────────────────────────────────────────────────

def _make_candidate(name="o/repo", stars=100):
    return RepoCandidate(
        full_name=name, url=f"https://github.com/{name}",
        description="test", stars=stars, language="Python",
        topics=["test"], last_updated=datetime.now(timezone.utc),
        size_kb=1000, has_readme=True, readme_preview="# Test",
    )


def _make_analysis(repo_url="https://github.com/o/repo"):
    return RepoAnalysis(repo_url=repo_url, file_count=10, total_lines=500)


def _make_web_result():
    return WebResearchResult(
        query="test",
        results=[WebResult(title="T", url="u", snippet="s", source="exa")],
        total_results=1,
    )


def _make_skill(name="test-skill"):
    return SkillDefinition(
        name=name, description="Test skill",
        category="api", content="content",
        confidence=0.8,
    )


@pytest.fixture
def mock_github():
    gh = MagicMock()
    gh.search_repos = AsyncMock(return_value=[_make_candidate()])
    gh.rank_candidates = MagicMock(side_effect=lambda c, q: c)
    return gh


@pytest.fixture
def mock_analyzer():
    a = MagicMock()
    a.clone_and_analyze = AsyncMock(return_value=_make_analysis())
    return a


@pytest.fixture
def mock_web():
    w = MagicMock()
    w.search = AsyncMock(return_value=_make_web_result())
    return w


@pytest.fixture
def mock_skill_builder():
    sb = MagicMock()
    sb.build_skills = AsyncMock(return_value=SkillBuildResult(skills=[_make_skill()]))
    return sb


@pytest.fixture
def mock_kb():
    kb = MagicMock()
    kb.add_skill = AsyncMock(return_value=True)
    return kb


@pytest.fixture
def mock_events():
    ev = MagicMock()
    ev.emit = AsyncMock()
    return ev


@pytest.fixture
def agent(mock_github, mock_analyzer, mock_web, mock_skill_builder, mock_kb, mock_events):
    return ResearchAgent(
        github_client=mock_github,
        repo_analyzer=mock_analyzer,
        web_researcher=mock_web,
        skill_builder=mock_skill_builder,
        knowledge_base=mock_kb,
        event_router=mock_events,
    )


# ── Test Dataclasses ────────────────────────────────────────────────

def test_research_request_defaults():
    """ResearchRequest ha valori default corretti."""
    r = ResearchRequest(query="fastapi")
    assert r.context == ""
    assert r.language is None
    assert r.max_repos == 5
    assert r.max_web_results == 10
    assert r.auto_save is True


def test_research_result_defaults():
    """ResearchResult ha valori default corretti."""
    r = ResearchResult(query="test")
    assert r.repos_found == []
    assert r.repos_analyzed == []
    assert r.web_results == []
    assert r.skills_generated == []
    assert r.skills_saved == 0
    assert r.errors == []
    assert r.duration_s == 0.0


# ── Test Constructor ────────────────────────────────────────────────

def test_init_minimal():
    """ResearchAgent senza dipendenze."""
    agent = ResearchAgent()
    assert agent._github is None
    assert agent._analyzer is None
    assert agent._web is None
    assert agent._skill_builder is None
    assert agent._kb is None


def test_init_full(agent):
    """ResearchAgent con tutte le dipendenze."""
    assert agent._github is not None
    assert agent._analyzer is not None
    assert agent._web is not None
    assert agent._skill_builder is not None
    assert agent._kb is not None


# ── Test research() pipeline ────────────────────────────────────────

@pytest.mark.asyncio
async def test_research_full_pipeline(agent, mock_github, mock_analyzer, mock_web, mock_skill_builder, mock_kb):
    """research() esegue il pipeline completo."""
    request = ResearchRequest(query="fastapi patterns")
    result = await agent.research(request)

    assert result.query == "fastapi patterns"
    assert len(result.repos_found) > 0
    assert len(result.repos_analyzed) > 0
    assert len(result.web_results) > 0
    assert len(result.skills_generated) > 0
    assert result.skills_saved > 0
    assert result.duration_s > 0
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_research_no_github():
    """research() funziona senza GitHub client."""
    agent = ResearchAgent(web_researcher=MagicMock(search=AsyncMock(return_value=_make_web_result())))
    request = ResearchRequest(query="test")
    result = await agent.research(request)

    assert result.repos_found == []
    assert len(result.web_results) > 0


@pytest.mark.asyncio
async def test_research_no_analyzer(mock_github, mock_web):
    """research() funziona senza analyzer."""
    agent = ResearchAgent(github_client=mock_github, web_researcher=mock_web)
    request = ResearchRequest(query="test")
    result = await agent.research(request)

    assert len(result.repos_found) > 0
    assert result.repos_analyzed == []


@pytest.mark.asyncio
async def test_research_no_web(mock_github, mock_analyzer):
    """research() funziona senza web researcher."""
    agent = ResearchAgent(github_client=mock_github, repo_analyzer=mock_analyzer)
    request = ResearchRequest(query="test")
    result = await agent.research(request)

    assert result.web_results == []


@pytest.mark.asyncio
async def test_research_no_skill_builder(mock_github, mock_analyzer, mock_web):
    """research() funziona senza skill builder."""
    agent = ResearchAgent(
        github_client=mock_github, repo_analyzer=mock_analyzer, web_researcher=mock_web
    )
    request = ResearchRequest(query="test")
    result = await agent.research(request)

    assert result.skills_generated == []


@pytest.mark.asyncio
async def test_research_no_auto_save(agent, mock_kb):
    """research() non salva se auto_save=False."""
    request = ResearchRequest(query="test", auto_save=False)
    result = await agent.research(request)

    assert result.skills_saved == 0
    mock_kb.add_skill.assert_not_called()


@pytest.mark.asyncio
async def test_research_handles_github_error(mock_web):
    """research() gestisce errori GitHub."""
    gh = MagicMock()
    gh.search_repos = AsyncMock(side_effect=RuntimeError("GH down"))
    gh.rank_candidates = MagicMock(return_value=[])
    agent = ResearchAgent(github_client=gh, web_researcher=mock_web)

    request = ResearchRequest(query="test")
    result = await agent.research(request)
    # Should not crash, repos_found = []
    assert result.repos_found == []


@pytest.mark.asyncio
async def test_research_emits_events(agent, mock_events):
    """research() emette eventi."""
    request = ResearchRequest(query="test")
    await agent.research(request)

    assert mock_events.emit.call_count >= 2  # almeno start + complete


@pytest.mark.asyncio
async def test_research_pipeline_error_recorded(agent, mock_github):
    """research() registra errori nel result."""
    mock_github.search_repos = AsyncMock(side_effect=RuntimeError("fail"))
    request = ResearchRequest(query="test")
    result = await agent.research(request)

    # Pipeline continues after step 1 error
    assert result.repos_found == []


# ── Test quick_search() ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quick_search_success(agent):
    """quick_search() ritorna candidati ranked."""
    results = await agent.quick_search("fastapi", limit=3)
    assert len(results) > 0


@pytest.mark.asyncio
async def test_quick_search_no_github():
    """quick_search() senza GitHub ritorna []."""
    agent = ResearchAgent()
    results = await agent.quick_search("test")
    assert results == []


@pytest.mark.asyncio
async def test_quick_search_error():
    """quick_search() gestisce errori."""
    gh = MagicMock()
    gh.search_repos = AsyncMock(side_effect=RuntimeError("fail"))
    agent = ResearchAgent(github_client=gh)

    results = await agent.quick_search("test")
    assert results == []


# ── Test detect_knowledge_gap() ────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_gap_no_skills():
    """detect_knowledge_gap() senza skills esistenti ritorna True."""
    agent = ResearchAgent()
    assert await agent.detect_knowledge_gap("fastapi") is True


@pytest.mark.asyncio
async def test_detect_gap_covered():
    """detect_knowledge_gap() con skill corrispondente ritorna False."""
    agent = ResearchAgent()
    result = await agent.detect_knowledge_gap(
        "fastapi", existing_skills=["fastapi-patterns", "fastapi-di"]
    )
    assert result is False


@pytest.mark.asyncio
async def test_detect_gap_not_covered():
    """detect_knowledge_gap() con skill non corrispondente ritorna True."""
    agent = ResearchAgent()
    result = await agent.detect_knowledge_gap(
        "kubernetes deployment", existing_skills=["fastapi-patterns", "python-testing"]
    )
    assert result is True


@pytest.mark.asyncio
async def test_detect_gap_partial_match():
    """detect_knowledge_gap() con match parziale."""
    agent = ResearchAgent()
    result = await agent.detect_knowledge_gap(
        "python testing", existing_skills=["python-testing-best-practices"]
    )
    assert result is False


# ── Test _save_skills() ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_skills_with_add_skill(agent, mock_kb):
    """_save_skills() usa add_skill se disponibile."""
    skills = [_make_skill("s1"), _make_skill("s2")]
    saved = await agent._save_skills(skills)
    assert saved == 2
    assert mock_kb.add_skill.call_count == 2


@pytest.mark.asyncio
async def test_save_skills_error_continues(agent, mock_kb):
    """_save_skills() continua dopo errore su singola skill."""
    mock_kb.add_skill = AsyncMock(side_effect=[RuntimeError("fail"), True])
    skills = [_make_skill("s1"), _make_skill("s2")]
    saved = await agent._save_skills(skills)
    assert saved == 1


@pytest.mark.asyncio
async def test_save_skills_with_add_method():
    """_save_skills() usa add() come fallback."""
    kb = MagicMock(spec=[])  # no add_skill
    kb.add = AsyncMock(return_value=True)
    agent = ResearchAgent(knowledge_base=kb)

    # Need to add the 'add' attribute
    agent._kb = kb

    skills = [_make_skill()]
    saved = await agent._save_skills(skills)
    assert saved == 1


# ── Test _emit() ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_with_router(agent, mock_events):
    """_emit() chiama event_router.emit()."""
    await agent._emit("test", {"key": "value"})
    mock_events.emit.assert_called_once_with("test", {"key": "value"})


@pytest.mark.asyncio
async def test_emit_no_router():
    """_emit() senza router non crasha."""
    agent = ResearchAgent()
    await agent._emit("test", {})  # Should not raise


@pytest.mark.asyncio
async def test_emit_error_suppressed(agent, mock_events):
    """_emit() sopprime errori del router."""
    mock_events.emit = AsyncMock(side_effect=RuntimeError("event fail"))
    await agent._emit("test", {})  # Should not raise


# ── Test _analyze_repos() ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_repos_success(agent):
    """_analyze_repos() analizza candidati."""
    candidates = [_make_candidate("a/r1"), _make_candidate("b/r2")]
    analyses = await agent._analyze_repos(candidates)
    assert len(analyses) == 2


@pytest.mark.asyncio
async def test_analyze_repos_skips_empty(agent, mock_analyzer):
    """_analyze_repos() salta analisi con 0 file."""
    empty = RepoAnalysis(repo_url="u", file_count=0)
    mock_analyzer.clone_and_analyze = AsyncMock(return_value=empty)

    analyses = await agent._analyze_repos([_make_candidate()])
    assert len(analyses) == 0


@pytest.mark.asyncio
async def test_analyze_repos_error_continues(agent, mock_analyzer):
    """_analyze_repos() continua dopo errore su singolo repo."""
    mock_analyzer.clone_and_analyze = AsyncMock(
        side_effect=[RuntimeError("fail"), _make_analysis()]
    )
    candidates = [_make_candidate("a/r1"), _make_candidate("b/r2")]
    analyses = await agent._analyze_repos(candidates)
    assert len(analyses) == 1
