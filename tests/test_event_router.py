"""Test suite per core/event_router.py — Step 2.3 Phase 2."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from core.event_router import EventRouter, EVENT_TYPES


# ── Test Constructor ────────────────────────────────────────────────

def test_init_defaults():
    """EventRouter defaults: persist=True, buffer vuoto."""
    er = EventRouter()
    assert er._persist is True
    assert er._recent == []
    assert er._max_recent == 100


def test_init_no_persist():
    """EventRouter con persist=False."""
    er = EventRouter(persist=False)
    assert er._persist is False


# ── Test EVENT_TYPES ────────────────────────────────────────────────

def test_event_types_set():
    """EVENT_TYPES contiene i tipi previsti."""
    expected = {"query", "init", "spider", "engine", "db", "skill", "error", "system"}
    assert EVENT_TYPES == expected


# ── Test emit() ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_returns_uuid():
    """emit() ritorna un UUID valido."""
    er = EventRouter(persist=False)
    event_id = await er.emit("query", {"question": "test"}, source="orchestrator")

    assert isinstance(event_id, str)
    assert len(event_id) == 36  # UUID format


@pytest.mark.asyncio
async def test_emit_adds_to_buffer():
    """emit() aggiunge l'evento al buffer in-memory."""
    er = EventRouter(persist=False)
    await er.emit("query", {"q": "test"}, source="orch")

    assert len(er._recent) == 1
    assert er._recent[0]["type"] == "query"
    assert er._recent[0]["source"] == "orch"
    assert er._recent[0]["data"] == {"q": "test"}


@pytest.mark.asyncio
async def test_emit_unknown_type_becomes_system():
    """emit() con tipo sconosciuto diventa 'system'."""
    er = EventRouter(persist=False)
    await er.emit("unknown_type", source="test")

    assert er._recent[0]["type"] == "system"


@pytest.mark.asyncio
async def test_emit_all_valid_types():
    """emit() accetta tutti i tipi in EVENT_TYPES."""
    er = EventRouter(persist=False)
    for event_type in EVENT_TYPES:
        await er.emit(event_type, source="test")

    assert len(er._recent) == len(EVENT_TYPES)
    types = {e["type"] for e in er._recent}
    assert types == EVENT_TYPES


@pytest.mark.asyncio
async def test_emit_timestamp():
    """emit() include un timestamp numerico."""
    er = EventRouter(persist=False)
    await er.emit("query", source="test")

    ts = er._recent[0]["timestamp"]
    assert isinstance(ts, float)
    assert ts > 0


@pytest.mark.asyncio
async def test_emit_default_data():
    """emit() con data=None usa dict vuoto."""
    er = EventRouter(persist=False)
    await er.emit("system", source="test")

    assert er._recent[0]["data"] == {}


# ── Test Buffer Circolare ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_buffer_circular():
    """Il buffer circolare mantiene solo gli ultimi _max_recent eventi."""
    er = EventRouter(persist=False)
    er._max_recent = 5

    for i in range(10):
        await er.emit("query", {"i": i}, source="test")

    assert len(er._recent) == 5
    # Gli ultimi 5 eventi (indici 5-9)
    assert er._recent[0]["data"]["i"] == 5
    assert er._recent[4]["data"]["i"] == 9


# ── Test get_recent() ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_recent_all():
    """get_recent() ritorna tutti gli eventi (più recenti prima)."""
    er = EventRouter(persist=False)
    await er.emit("query", {"q": "first"}, source="test")
    await er.emit("init", {"p": "/path"}, source="test")
    await er.emit("query", {"q": "last"}, source="test")

    recent = er.get_recent()
    assert len(recent) == 3
    # Più recente prima
    assert recent[0]["data"]["q"] == "last"
    assert recent[2]["data"]["q"] == "first"


@pytest.mark.asyncio
async def test_get_recent_filter_type():
    """get_recent() filtra per tipo."""
    er = EventRouter(persist=False)
    await er.emit("query", {"q": "q1"}, source="test")
    await er.emit("init", {"p": "/path"}, source="test")
    await er.emit("query", {"q": "q2"}, source="test")

    recent = er.get_recent(event_type="query")
    assert len(recent) == 2
    assert all(e["type"] == "query" for e in recent)


@pytest.mark.asyncio
async def test_get_recent_limit():
    """get_recent() rispetta il limit."""
    er = EventRouter(persist=False)
    for i in range(10):
        await er.emit("query", {"i": i}, source="test")

    recent = er.get_recent(limit=3)
    assert len(recent) == 3


@pytest.mark.asyncio
async def test_get_recent_empty():
    """get_recent() su buffer vuoto ritorna []."""
    er = EventRouter(persist=False)
    assert er.get_recent() == []


# ── Test get_stats() ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_stats():
    """get_stats() ritorna conteggi corretti."""
    er = EventRouter(persist=False)
    await er.emit("query", source="test")
    await er.emit("query", source="test")
    await er.emit("init", source="test")
    await er.emit("error", source="test")

    stats = er.get_stats()
    assert stats["total_events"] == 4
    assert stats["by_type"]["query"] == 2
    assert stats["by_type"]["init"] == 1
    assert stats["by_type"]["error"] == 1
    assert stats["buffer_size"] == 100


def test_get_stats_empty():
    """get_stats() su router vuoto."""
    er = EventRouter(persist=False)
    stats = er.get_stats()
    assert stats["total_events"] == 0
    assert stats["by_type"] == {}


# ── Test persist (mocked) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_called_when_enabled():
    """_persist_event() è chiamato quando persist=True."""
    er = EventRouter(persist=True)
    er._persist_event = AsyncMock()

    await er.emit("query", {"q": "test"}, source="orch")
    er._persist_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_not_called_when_disabled():
    """_persist_event() NON è chiamato quando persist=False."""
    er = EventRouter(persist=False)
    er._persist_event = AsyncMock()

    await er.emit("query", {"q": "test"}, source="orch")
    er._persist_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_graceful_on_qdrant_missing():
    """_persist_event() non crasha se Qdrant non è inizializzato."""
    er = EventRouter(persist=True)
    # _persist_event() importa NoxenQdrantClient che non è inizializzato → RuntimeError
    # Deve gestire gracefully
    event_id = await er.emit("query", {"q": "test"}, source="test")
    assert isinstance(event_id, str)
    assert len(er._recent) == 1
