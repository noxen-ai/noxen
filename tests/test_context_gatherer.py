"""Test suite per core/context_gatherer.py — Step 2.1 Phase 2."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.context_gatherer import ContextGatherer


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def mock_kb():
    """KnowledgeBase mock con search async."""
    kb = MagicMock()
    kb.search = AsyncMock(return_value=[
        {"document": "Skill doc content", "metadata": {"plugin": "sec", "file_path": "scan.md", "type": "skill"}},
        {"document": "Agent doc content", "metadata": {"plugin": "dev", "file_path": "agent.md", "type": "agent"}},
    ])
    return kb


@pytest.fixture
def mock_pm():
    """ProjectManager mock."""
    pm = MagicMock()
    pm.projects = {"svc1": MagicMock(), "svc2": MagicMock()}
    pm.search = MagicMock(return_value=[
        {"document": "function login()...", "metadata": {"file_path": "auth/login.py"}, "distance": 0.3},
        {"document": "def register()...", "metadata": {"file_path": "auth/register.py"}, "distance": 0.5},
    ])
    return pm


@pytest.fixture
def mock_skill_router():
    """SkillRouter mock."""
    sr = MagicMock()
    sr.route = MagicMock(return_value=[
        {"name": "security-scan", "description": "Scansione vulnerabilità del progetto"},
    ])
    return sr


@pytest.fixture
def mock_db():
    """DBConnector mock."""
    db = MagicMock()
    db.schema_to_text = MagicMock(return_value="Table users: id INT, name VARCHAR...")
    return db


@pytest.fixture
def mock_db_schema():
    """SchemaInfo mock."""
    return MagicMock(total_tables=5)


@pytest.fixture
def gatherer(mock_kb, mock_pm, mock_skill_router):
    """ContextGatherer con tutti i mock."""
    return ContextGatherer(
        knowledge_base=mock_kb,
        project_manager=mock_pm,
        skill_router=mock_skill_router,
    )


# ── Test Constructor ────────────────────────────────────────────────

def test_init_defaults():
    """ContextGatherer senza dipendenze non crasha."""
    cg = ContextGatherer()
    assert cg.knowledge_base is None
    assert cg.project_manager is None
    assert cg.skill_router is None
    assert cg.db is None
    assert cg.db_schema is None
    assert cg.ecosystem is None
    assert cg.initialized is False


def test_init_with_deps(mock_kb, mock_pm, mock_skill_router):
    """ContextGatherer accetta dipendenze via constructor."""
    cg = ContextGatherer(mock_kb, mock_pm, mock_skill_router)
    assert cg.knowledge_base is mock_kb
    assert cg.project_manager is mock_pm
    assert cg.skill_router is mock_skill_router


# ── Test gather() — KB only ────────────────────────────────────────

@pytest.mark.asyncio
async def test_gather_kb_only(mock_kb):
    """gather() con solo KB ritorna risultati KB."""
    cg = ContextGatherer(knowledge_base=mock_kb)
    result = await cg.gather("come funziona l'autenticazione?")

    assert result["kb_results"] == 2
    assert result["rag_results"] == 0
    assert result["db_active"] is False
    assert result["skills_matched"] == 0
    assert "system_prompt" in result
    assert "CONOSCENZA INTERNA" in result["system_prompt"]
    mock_kb.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_gather_kb_empty_results():
    """gather() con KB che ritorna [] funziona."""
    kb = MagicMock()
    kb.search = AsyncMock(return_value=[])
    cg = ContextGatherer(knowledge_base=kb)
    result = await cg.gather("test")

    assert result["kb_results"] == 0
    assert "CONOSCENZA INTERNA" not in result["system_prompt"]


@pytest.mark.asyncio
async def test_gather_kb_exception_handled():
    """gather() gestisce eccezione KB gracefully."""
    kb = MagicMock()
    kb.search = AsyncMock(side_effect=Exception("Qdrant down"))
    cg = ContextGatherer(knowledge_base=kb)
    result = await cg.gather("test")

    assert result["kb_results"] == 0


# ── Test gather() — RAG (codebase) ─────────────────────────────────

@pytest.mark.asyncio
async def test_gather_rag_not_initialized(mock_kb, mock_pm):
    """RAG non viene usato se initialized=False."""
    cg = ContextGatherer(knowledge_base=mock_kb, project_manager=mock_pm)
    cg.initialized = False
    result = await cg.gather("test")

    assert result["rag_results"] == 0
    mock_pm.search.assert_not_called()


@pytest.mark.asyncio
async def test_gather_rag_initialized(mock_kb, mock_pm):
    """RAG viene usato se initialized=True."""
    cg = ContextGatherer(knowledge_base=mock_kb, project_manager=mock_pm)
    cg.initialized = True
    result = await cg.gather("login authentication")

    assert result["rag_results"] > 0
    assert "CODICE RILEVANTE" in result["system_prompt"]


@pytest.mark.asyncio
async def test_gather_rag_with_service(mock_kb, mock_pm):
    """RAG filtra su servizio specifico."""
    cg = ContextGatherer(knowledge_base=mock_kb, project_manager=mock_pm)
    cg.initialized = True
    result = await cg.gather("login", service="svc1")

    mock_pm.search.assert_called_once_with("svc1", "login", n_results=5)


@pytest.mark.asyncio
async def test_gather_rag_cross_service(mock_kb, mock_pm):
    """RAG cerca in tutti i servizi se service=''."""
    cg = ContextGatherer(knowledge_base=mock_kb, project_manager=mock_pm)
    cg.initialized = True
    result = await cg.gather("login", service="")

    # Deve cercare in ogni progetto
    assert mock_pm.search.call_count == len(mock_pm.projects)


@pytest.mark.asyncio
async def test_gather_rag_exception_handled(mock_kb):
    """RAG gestisce eccezioni gracefully."""
    pm = MagicMock()
    pm.projects = {"svc1": MagicMock()}
    pm.search = MagicMock(side_effect=Exception("search failed"))
    cg = ContextGatherer(knowledge_base=mock_kb, project_manager=pm)
    cg.initialized = True
    result = await cg.gather("test")

    assert result["rag_results"] == 0


# ── Test gather() — DB Context ──────────────────────────────────────

@pytest.mark.asyncio
async def test_gather_db_context_relevant_query(mock_kb, mock_db, mock_db_schema):
    """DB context incluso se query contiene keyword DB."""
    cg = ContextGatherer(knowledge_base=mock_kb)
    cg.db = mock_db
    cg.db_schema = mock_db_schema
    result = await cg.gather("mostrami lo schema database")

    assert result["db_active"] is True
    assert "SCHEMA DATABASE" in result["system_prompt"]
    mock_db.schema_to_text.assert_called_once_with(mock_db_schema)


@pytest.mark.asyncio
async def test_gather_db_context_irrelevant_query(mock_kb, mock_db, mock_db_schema):
    """DB context NON incluso se query non contiene keyword DB."""
    cg = ContextGatherer(knowledge_base=mock_kb)
    cg.db = mock_db
    cg.db_schema = mock_db_schema
    result = await cg.gather("come funziona il login?")

    assert result["db_active"] is False


@pytest.mark.asyncio
async def test_gather_db_context_use_db_false(mock_kb, mock_db, mock_db_schema):
    """DB context NON incluso se use_db=False."""
    cg = ContextGatherer(knowledge_base=mock_kb)
    cg.db = mock_db
    cg.db_schema = mock_db_schema
    result = await cg.gather("mostrami lo schema database", use_db=False)

    assert result["db_active"] is False


# ── Test gather() — Skill Routing ───────────────────────────────────

@pytest.mark.asyncio
async def test_gather_skills_matched(gatherer):
    """Skill router viene chiamato e i risultati inclusi."""
    result = await gatherer.gather("analizza le vulnerabilità")

    assert result["skills_matched"] == 1
    assert "COMPETENZE DISPONIBILI" in result["system_prompt"]
    gatherer.skill_router.route.assert_called_once_with("analizza le vulnerabilità")


@pytest.mark.asyncio
async def test_gather_no_skill_router(mock_kb):
    """Senza skill_router, skills_matched = 0."""
    cg = ContextGatherer(knowledge_base=mock_kb)
    result = await cg.gather("test")

    assert result["skills_matched"] == 0


# ── Test _build_system_prompt() ─────────────────────────────────────

def test_build_system_prompt_base():
    """System prompt base contiene le istruzioni core."""
    cg = ContextGatherer()
    prompt = cg._build_system_prompt("", "", "", "")

    assert "Noxen" in prompt
    assert "italiano" in prompt


def test_build_system_prompt_with_ecosystem():
    """System prompt include info ecosistema se disponibile."""
    cg = ContextGatherer()
    eco = MagicMock()
    eco.total_services = 5
    eco.languages = ["Python", "PHP"]
    eco.frameworks = ["FastAPI", "Laravel"]
    cg.ecosystem = eco
    prompt = cg._build_system_prompt("", "", "", "")

    assert "5 microservizi" in prompt
    assert "Python" in prompt
    assert "Laravel" in prompt


def test_build_system_prompt_with_all_context():
    """System prompt include tutti i blocchi di contesto."""
    cg = ContextGatherer()
    prompt = cg._build_system_prompt(
        "KB: skill data",
        "RAG: code snippet",
        "DB: table schema",
        "SKILLS: security-scan"
    )

    assert "KB: skill data" in prompt
    assert "RAG: code snippet" in prompt
    assert "DB: table schema" in prompt
    assert "SKILLS: security-scan" in prompt


# ── Test gather() — Full Integration ────────────────────────────────

@pytest.mark.asyncio
async def test_gather_full_context(gatherer, mock_db, mock_db_schema):
    """gather() con tutti i source attivi."""
    gatherer.initialized = True
    gatherer.db = mock_db
    gatherer.db_schema = mock_db_schema

    result = await gatherer.gather("mostrami lo schema database per l'autenticazione")

    assert result["kb_results"] == 2
    assert result["rag_results"] > 0
    assert result["db_active"] is True
    assert result["skills_matched"] == 1
    assert len(result["system_prompt"]) > 100


@pytest.mark.asyncio
async def test_gather_no_deps():
    """gather() senza nessuna dipendenza funziona (ritorna contesto vuoto)."""
    cg = ContextGatherer()
    result = await cg.gather("test")

    assert result["kb_results"] == 0
    assert result["rag_results"] == 0
    assert result["db_active"] is False
    assert result["skills_matched"] == 0
    assert "system_prompt" in result
