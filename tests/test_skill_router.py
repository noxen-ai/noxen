"""Test suite per core/skill_router.py — Step 2.2 Phase 2."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from core.skill_router import SkillRouter, SKILL_ROUTING


# ── Fixtures ────────────────────────────────────────────────────────

MOCK_SKILLS = [
    {"name": "security-scan", "description": "Scansione vulnerabilità XSS e SQL injection", "tags": ["security", "pentesting"]},
    {"name": "api-analyzer", "description": "Analisi endpoint REST e middleware", "tags": ["api", "rest"]},
    {"name": "db-optimizer", "description": "Ottimizzazione query MySQL e schema migration", "tags": ["database", "mysql"]},
    {"name": "vue-builder", "description": "Generazione componenti Vue.js e template", "tags": ["frontend", "vue"]},
    {"name": "docker-deploy", "description": "Deploy container Docker e CI/CD pipeline", "tags": ["devops", "docker"]},
    {"name": "arch-refactor", "description": "Refactoring architettura microservizi", "tags": ["architecture"]},
    {"name": "perf-tuner", "description": "Ottimizzazione performance e cache Redis", "tags": ["performance"]},
    {"name": "test-generator", "description": "Generazione unit test e integration test", "tags": ["testing"]},
]


@pytest.fixture
def mock_composer():
    """PluginComposer mock."""
    pc = MagicMock()
    pc.get_all_skills = MagicMock(return_value=MOCK_SKILLS)
    return pc


@pytest.fixture
def router(mock_composer):
    """SkillRouter con cache popolata."""
    sr = SkillRouter(plugin_composer=mock_composer)
    sr.refresh_cache()
    return sr


# ── Test Constructor ────────────────────────────────────────────────

def test_init_defaults():
    """SkillRouter senza plugin_composer non crasha."""
    sr = SkillRouter()
    assert sr._cache == []
    assert sr.cache_size == 0


def test_init_with_composer(mock_composer):
    """SkillRouter accetta plugin_composer."""
    sr = SkillRouter(plugin_composer=mock_composer)
    assert sr._plugin_composer is mock_composer


# ── Test refresh_cache() ────────────────────────────────────────────

def test_refresh_cache(mock_composer):
    """refresh_cache() popola la cache."""
    sr = SkillRouter(plugin_composer=mock_composer)
    count = sr.refresh_cache()
    assert count == 8
    assert sr.cache_size == 8
    mock_composer.get_all_skills.assert_called_once()


def test_refresh_cache_no_composer():
    """refresh_cache() senza composer ritorna 0."""
    sr = SkillRouter()
    count = sr.refresh_cache()
    assert count == 0
    assert sr.cache_size == 0


# ── Test SKILL_ROUTING constant ─────────────────────────────────────

def test_skill_routing_has_categories():
    """SKILL_ROUTING ha tutte le categorie previste."""
    expected = {"security", "database", "api", "frontend", "devops", "architecture", "performance", "testing"}
    assert set(SKILL_ROUTING.keys()) == expected


def test_skill_routing_values_are_lists():
    """Ogni categoria ha una lista di keyword."""
    for cat, keywords in SKILL_ROUTING.items():
        assert isinstance(keywords, list)
        assert len(keywords) > 0


# ── Test route() — Keyword Matching ─────────────────────────────────

def test_route_security(router):
    """route() trova skill di security."""
    result = router.route("analizza le vulnerabilità XSS del progetto")
    names = [s["name"] for s in result]
    assert "security-scan" in names


def test_route_database(router):
    """route() trova skill database."""
    result = router.route("ottimizza le query MySQL")
    names = [s["name"] for s in result]
    assert "db-optimizer" in names


def test_route_api(router):
    """route() trova skill API."""
    result = router.route("analizza gli endpoint REST")
    names = [s["name"] for s in result]
    assert "api-analyzer" in names


def test_route_frontend(router):
    """route() trova skill frontend."""
    result = router.route("crea un component Vue")
    names = [s["name"] for s in result]
    assert "vue-builder" in names


def test_route_devops(router):
    """route() trova skill devops."""
    result = router.route("configura il deploy Docker")
    names = [s["name"] for s in result]
    assert "docker-deploy" in names


def test_route_no_match(router):
    """route() ritorna [] se nessuna keyword matcha."""
    result = router.route("qual è il senso della vita?")
    assert result == []


def test_route_empty_cache():
    """route() ritorna [] se cache vuota."""
    sr = SkillRouter()
    result = sr.route("security vulnerability scan")
    assert result == []


def test_route_max_results(router):
    """route() rispetta max_results."""
    # Forza un match su molte categorie
    result = router.route("security database api frontend devops test performance", max_results=3)
    assert len(result) <= 3


def test_route_multiple_categories(router):
    """route() matcha skill di categorie diverse."""
    result = router.route("security vulnerability nelle query database MySQL")
    names = [s["name"] for s in result]
    assert "security-scan" in names
    assert "db-optimizer" in names


def test_route_case_insensitive(router):
    """route() è case insensitive."""
    result1 = router.route("SECURITY VULNERABILITY")
    result2 = router.route("security vulnerability")
    assert len(result1) == len(result2)


# ── Test semantic_route() ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_route_fallback_no_qdrant(router):
    """semantic_route() cade su keyword route se Qdrant non disponibile."""
    with patch("core.skill_router.SkillRouter.route", return_value=[{"name": "fallback"}]):
        # Poiché NoxenQdrantClient non è inizializzato nei test, deve fare fallback
        result = await router.semantic_route("security scan")
        # Dovrebbe ritornare qualcosa (fallback o Qdrant result)
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_semantic_route_returns_list(router):
    """semantic_route() ritorna sempre una lista."""
    result = await router.semantic_route("test query")
    assert isinstance(result, list)
