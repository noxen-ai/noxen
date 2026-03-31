"""Test suite per core/research/skill_builder.py — Step 3.4 Phase 3."""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone

from core.research.skill_builder import (
    SkillBuilder,
    SkillDefinition,
    SkillBuildResult,
)


# ── Fixtures ────────────────────────────────────────────────────────

def _make_mock_llm(response_text: str):
    """Crea un mock LLM provider."""
    llm = MagicMock()
    llm.query = AsyncMock(return_value={"response": response_text})
    return llm


def _make_valid_json_response(skills=None):
    """Genera una risposta JSON valida per LLM."""
    if skills is None:
        skills = [{
            "name": "fastapi-dependency-injection",
            "description": "FastAPI dependency injection patterns",
            "category": "api",
            "tags": ["fastapi", "python", "di"],
            "content": "# FastAPI DI\n\nUse Depends() for injection...",
            "confidence": 0.85,
        }]
    return json.dumps(skills)


def _make_mock_repo_analysis(repo_url="https://github.com/o/r"):
    """Crea un mock di RepoAnalysis."""
    ra = MagicMock()
    ra.repo_url = repo_url
    ra.languages = {"Python": 10, "JavaScript": 3}
    ra.frameworks = ["fastapi"]
    f1, f2 = MagicMock(), MagicMock()
    f1.name = "func1"
    f2.name = "func2"
    ra.functions = [f1, f2]
    c1 = MagicMock()
    c1.name = "Class1"
    ra.classes = [c1]
    ra.endpoints = [{"method": "GET", "path": "/users"}]
    return ra


def _make_mock_web_result():
    """Crea un mock di WebResearchResult."""
    wr = MagicMock()
    result = MagicMock()
    result.title = "FastAPI Tutorial"
    result.snippet = "Learn how to use FastAPI..."
    result.url = "https://example.com/fastapi"
    wr.results = [result]
    return wr


@pytest.fixture
def builder():
    """SkillBuilder senza LLM."""
    return SkillBuilder(llm_provider=None)


@pytest.fixture
def builder_with_llm():
    """SkillBuilder con LLM mockato."""
    llm = _make_mock_llm(_make_valid_json_response())
    return SkillBuilder(llm_provider=llm)


# ── Test Dataclasses ────────────────────────────────────────────────

def test_skill_definition_defaults():
    """SkillDefinition ha valori default corretti."""
    s = SkillDefinition(name="test", description="d", category="api")
    assert s.tags == []
    assert s.content == ""
    assert s.source_repos == []
    assert s.source_urls == []
    assert s.confidence == 0.0
    assert s.created_at is not None


def test_skill_build_result_defaults():
    """SkillBuildResult ha valori default corretti."""
    r = SkillBuildResult()
    assert r.skills == []
    assert r.errors == []
    assert r.llm_tokens_used == 0


# ── Test Constructor ────────────────────────────────────────────────

def test_init_no_llm():
    """SkillBuilder senza LLM."""
    sb = SkillBuilder()
    assert sb._llm is None


def test_init_with_llm():
    """SkillBuilder con LLM."""
    llm = MagicMock()
    sb = SkillBuilder(llm_provider=llm)
    assert sb._llm is llm


# ── Test build_skills() ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_skills_no_llm(builder):
    """build_skills() senza LLM ritorna errore."""
    result = await builder.build_skills("fastapi")
    assert len(result.errors) > 0
    assert "LLM provider not configured" in result.errors[0]


@pytest.mark.asyncio
async def test_build_skills_success(builder_with_llm):
    """build_skills() ritorna skill definitions."""
    result = await builder_with_llm.build_skills("fastapi")
    assert len(result.skills) == 1
    assert result.skills[0].name == "fastapi-dependency-injection"
    assert result.skills[0].category == "api"


@pytest.mark.asyncio
async def test_build_skills_with_repo_analysis(builder_with_llm):
    """build_skills() con RepoAnalysis include source repos."""
    ra = _make_mock_repo_analysis()
    result = await builder_with_llm.build_skills("fastapi", repo_analyses=[ra])
    assert len(result.skills) >= 1
    assert "https://github.com/o/r" in result.skills[0].source_repos


@pytest.mark.asyncio
async def test_build_skills_with_web_results(builder_with_llm):
    """build_skills() con web results include source urls."""
    wr = _make_mock_web_result()
    result = await builder_with_llm.build_skills("fastapi", web_results=[wr])
    assert len(result.skills) >= 1
    assert "https://example.com/fastapi" in result.skills[0].source_urls


@pytest.mark.asyncio
async def test_build_skills_max_limit():
    """build_skills() rispetta max_skills."""
    many_skills = [
        {"name": f"skill-{i}", "description": f"Skill {i}", "category": "api",
         "tags": [], "content": "c", "confidence": 0.8}
        for i in range(10)
    ]
    llm = _make_mock_llm(json.dumps(many_skills))
    sb = SkillBuilder(llm_provider=llm)

    result = await sb.build_skills("test", max_skills=3)
    assert len(result.skills) == 3


@pytest.mark.asyncio
async def test_build_skills_llm_error():
    """build_skills() gestisce errori LLM."""
    llm = MagicMock()
    llm.query = AsyncMock(side_effect=RuntimeError("LLM down"))
    sb = SkillBuilder(llm_provider=llm)

    result = await sb.build_skills("test")
    assert len(result.errors) > 0
    assert "LLM down" in result.errors[0]


@pytest.mark.asyncio
async def test_build_skills_empty_response():
    """build_skills() gestisce risposta LLM vuota."""
    llm = _make_mock_llm("")
    sb = SkillBuilder(llm_provider=llm)

    result = await sb.build_skills("test")
    assert len(result.errors) > 0


# ── Test _build_prompt() ───────────────────────────────────────────

def test_build_prompt_basic(builder):
    """_build_prompt() include la query."""
    prompt = builder._build_prompt("fastapi patterns")
    assert "fastapi patterns" in prompt


def test_build_prompt_with_repos(builder):
    """_build_prompt() include dati repo."""
    ra = _make_mock_repo_analysis()
    prompt = builder._build_prompt("test", repo_analyses=[ra])
    assert "Repository Analysis" in prompt
    assert "fastapi" in prompt.lower()


def test_build_prompt_with_web(builder):
    """_build_prompt() include dati web."""
    wr = _make_mock_web_result()
    prompt = builder._build_prompt("test", web_results=[wr])
    assert "Web Research" in prompt
    assert "FastAPI Tutorial" in prompt


def test_build_prompt_max_skills(builder):
    """_build_prompt() include max_skills."""
    prompt = builder._build_prompt("test", max_skills=3)
    assert "3" in prompt


# ── Test _parse_llm_response() ─────────────────────────────────────

def test_parse_valid_json(builder):
    """_parse_llm_response() parsa JSON valido."""
    response = _make_valid_json_response()
    skills = builder._parse_llm_response(response, "test")
    assert len(skills) == 1
    assert skills[0].name == "fastapi-dependency-injection"


def test_parse_json_in_code_block(builder):
    """_parse_llm_response() parsa JSON in code block."""
    response = f"Here are the skills:\n```json\n{_make_valid_json_response()}\n```"
    skills = builder._parse_llm_response(response, "test")
    assert len(skills) == 1


def test_parse_invalid_json(builder):
    """_parse_llm_response() gestisce JSON invalido."""
    skills = builder._parse_llm_response("not json at all", "test")
    assert skills == []


def test_parse_empty_name_skipped(builder):
    """_parse_llm_response() salta skill senza nome."""
    response = json.dumps([
        {"name": "", "description": "d", "category": "api"},
        {"name": "valid", "description": "d", "category": "api", "content": "c"},
    ])
    skills = builder._parse_llm_response(response, "test")
    assert len(skills) == 1
    assert skills[0].name == "valid"


def test_parse_invalid_category_defaults(builder):
    """_parse_llm_response() usa default per categorie invalide."""
    response = json.dumps([{
        "name": "test-skill",
        "description": "d",
        "category": "invalid_category",
        "content": "c",
    }])
    skills = builder._parse_llm_response(response, "test")
    assert skills[0].category == "architecture"  # default


def test_parse_confidence_clamped(builder):
    """_parse_llm_response() clampa confidence a 0-1."""
    response = json.dumps([
        {"name": "s1", "description": "d", "category": "api", "confidence": 1.5},
        {"name": "s2", "description": "d", "category": "api", "confidence": -0.5},
    ])
    skills = builder._parse_llm_response(response, "test")
    assert skills[0].confidence == 1.0
    assert skills[1].confidence == 0.0


def test_parse_includes_sources(builder):
    """_parse_llm_response() include source repos e urls."""
    ra = _make_mock_repo_analysis()
    wr = _make_mock_web_result()
    response = _make_valid_json_response()

    skills = builder._parse_llm_response(response, "test", repo_analyses=[ra], web_results=[wr])
    assert len(skills[0].source_repos) > 0
    assert len(skills[0].source_urls) > 0


def test_parse_single_object_wrapped(builder):
    """_parse_llm_response() gestisce singolo oggetto (non array)."""
    response = json.dumps({
        "name": "single-skill",
        "description": "d",
        "category": "api",
        "content": "c",
    })
    skills = builder._parse_llm_response(response, "test")
    assert len(skills) == 1


# ── Test _extract_json() ──────────────────────────────────────────

def test_extract_json_raw_array(builder):
    """_extract_json() estrae array JSON raw."""
    text = 'Some text [{"key": "value"}] more text'
    result = builder._extract_json(text)
    assert result == '[{"key": "value"}]'


def test_extract_json_code_block(builder):
    """_extract_json() estrae JSON da code block."""
    text = 'Text\n```json\n[{"k": "v"}]\n```\nMore'
    result = builder._extract_json(text)
    assert "[" in result


def test_extract_json_raw_object(builder):
    """_extract_json() estrae singolo oggetto JSON."""
    text = 'Response: {"name": "test"}'
    result = builder._extract_json(text)
    assert "test" in result


def test_extract_json_empty(builder):
    """_extract_json() ritorna '' se no JSON."""
    result = builder._extract_json("no json here")
    assert result == ""


# ── Test _call_llm() ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_llm_no_provider(builder):
    """_call_llm() senza provider ritorna ''."""
    result = await builder._call_llm("test prompt")
    assert result == ""


@pytest.mark.asyncio
async def test_call_llm_with_query_method():
    """_call_llm() usa llm.query() se disponibile."""
    llm = MagicMock()
    llm.query = AsyncMock(return_value={"response": "result text"})
    sb = SkillBuilder(llm_provider=llm)

    result = await sb._call_llm("test")
    assert result == "result text"
    llm.query.assert_called_once()


@pytest.mark.asyncio
async def test_call_llm_with_callable():
    """_call_llm() usa callable se non ha query()."""
    async def mock_llm(prompt):
        return "callable result"

    sb = SkillBuilder(llm_provider=mock_llm)
    result = await sb._call_llm("test")
    assert result == "callable result"


# ── Test SKILL_CATEGORIES ─────────────────────────────────────────

def test_skill_categories_defined():
    """SKILL_CATEGORIES ha le categorie principali."""
    cats = SkillBuilder.SKILL_CATEGORIES
    assert "api" in cats
    assert "database" in cats
    assert "security" in cats
    assert "testing" in cats


def test_system_prompt_defined():
    """SYSTEM_PROMPT e' definito e non vuoto."""
    assert len(SkillBuilder.SYSTEM_PROMPT) > 100
    assert "JSON" in SkillBuilder.SYSTEM_PROMPT
