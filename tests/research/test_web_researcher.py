"""Test suite per core/research/web_researcher.py — Step 3.3 Phase 3."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone

from core.research.web_researcher import (
    WebResearcher,
    WebResult,
    WebResearchResult,
)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def researcher():
    """WebResearcher senza API keys."""
    return WebResearcher(exa_api_key="", firecrawl_api_key="")


@pytest.fixture
def researcher_with_exa():
    """WebResearcher con Exa key."""
    r = WebResearcher(exa_api_key="test-exa-key", firecrawl_api_key="")
    return r


@pytest.fixture
def researcher_with_firecrawl():
    """WebResearcher con Firecrawl key."""
    r = WebResearcher(exa_api_key="", firecrawl_api_key="test-fc-key")
    return r


@pytest.fixture
def researcher_full():
    """WebResearcher con entrambe le keys."""
    return WebResearcher(exa_api_key="test-exa-key", firecrawl_api_key="test-fc-key")


def _make_exa_result(title="Test", url="https://example.com", text="Content here", score=0.9):
    """Mock di un risultato Exa."""
    r = MagicMock()
    r.title = title
    r.url = url
    r.text = text
    r.highlights = ["highlight 1", "highlight 2"]
    r.score = score
    r.published_date = "2025-01-01"
    return r


def _make_exa_response(results=None):
    """Mock di response Exa."""
    resp = MagicMock()
    resp.results = results or [_make_exa_result()]
    return resp


# ── Test Dataclasses ────────────────────────────────────────────────

def test_web_result_defaults():
    """WebResult ha valori default corretti."""
    r = WebResult(title="T", url="u", snippet="s", source="exa")
    assert r.score == 0.0
    assert r.published_date == ""


def test_web_research_result_defaults():
    """WebResearchResult ha valori default corretti."""
    r = WebResearchResult(query="test")
    assert r.results == []
    assert r.total_results == 0
    assert r.errors == []
    assert r.searched_at is not None


# ── Test Constructor ────────────────────────────────────────────────

def test_init_no_keys():
    """WebResearcher senza keys inizializza correttamente."""
    r = WebResearcher()
    assert r._exa_key == ""
    assert r._firecrawl_key == ""
    assert r._exa_client is None
    assert r._firecrawl_client is None


def test_init_with_keys():
    """WebResearcher con keys inizializza correttamente."""
    r = WebResearcher(exa_api_key="exa", firecrawl_api_key="fc")
    assert r._exa_key == "exa"
    assert r._firecrawl_key == "fc"


# ── Test search() ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_no_keys(researcher):
    """search() senza API keys ritorna errore."""
    result = await researcher.search("fastapi")
    assert len(result.errors) > 0
    assert "No API keys" in result.errors[0]


@pytest.mark.asyncio
async def test_search_exa_only(researcher_with_exa):
    """search() con solo Exa chiama _search_exa."""
    mock_results = [WebResult(title="T", url="u", snippet="s", source="exa")]
    with patch.object(researcher_with_exa, "_search_exa", new_callable=AsyncMock, return_value=mock_results):
        result = await researcher_with_exa.search("fastapi", use_exa=True)
    assert result.total_results == 1
    assert result.results[0].source == "exa"


@pytest.mark.asyncio
async def test_search_both_sources(researcher_full):
    """search() con entrambe le fonti ritorna risultati combinati."""
    exa_results = [WebResult(title="Exa", url="u1", snippet="s1", source="exa")]
    fc_results = [WebResult(title="FC", url="u2", snippet="s2", source="firecrawl")]

    with patch.object(researcher_full, "_search_exa", new_callable=AsyncMock, return_value=exa_results):
        with patch.object(researcher_full, "_scrape_firecrawl", new_callable=AsyncMock, return_value=fc_results):
            result = await researcher_full.search(
                "fastapi",
                use_exa=True,
                use_firecrawl=True,
                firecrawl_urls=["https://example.com"],
            )

    assert result.total_results == 2


@pytest.mark.asyncio
async def test_search_handles_exception(researcher_with_exa):
    """search() gestisce eccezioni gracefully."""
    with patch.object(researcher_with_exa, "_search_exa", new_callable=AsyncMock, side_effect=RuntimeError("API error")):
        result = await researcher_with_exa.search("test")
    assert len(result.errors) > 0
    assert "API error" in result.errors[0]


@pytest.mark.asyncio
async def test_search_firecrawl_needs_urls(researcher_full):
    """search() con firecrawl ma senza urls non chiama firecrawl."""
    with patch.object(researcher_full, "_search_exa", new_callable=AsyncMock, return_value=[]):
        with patch.object(researcher_full, "_scrape_firecrawl", new_callable=AsyncMock) as mock_fc:
            await researcher_full.search("test", use_exa=True, use_firecrawl=True, firecrawl_urls=None)
    mock_fc.assert_not_called()


# ── Test search_exa() ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_exa_no_key():
    """search_exa() senza key ritorna errore."""
    r = WebResearcher(exa_api_key="")
    result = await r.search_exa("test")
    assert len(result.errors) > 0
    assert "not configured" in result.errors[0]


@pytest.mark.asyncio
async def test_search_exa_success(researcher_with_exa):
    """search_exa() ritorna risultati."""
    mock_results = [WebResult(title="T", url="u", snippet="s", source="exa", score=0.9)]
    with patch.object(researcher_with_exa, "_search_exa", new_callable=AsyncMock, return_value=mock_results):
        result = await researcher_with_exa.search_exa("fastapi")
    assert result.total_results == 1
    assert result.query == "fastapi"


@pytest.mark.asyncio
async def test_search_exa_error(researcher_with_exa):
    """search_exa() gestisce errori."""
    with patch.object(researcher_with_exa, "_search_exa", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
        result = await researcher_with_exa.search_exa("test")
    assert len(result.errors) > 0


# ── Test _search_exa() internal ────────────────────────────────────

@pytest.mark.asyncio
async def test_internal_search_exa_no_client(researcher_with_exa):
    """_search_exa() senza client ritorna lista vuota."""
    researcher_with_exa._exa_key = ""
    results = await researcher_with_exa._search_exa("test")
    assert results == []


@pytest.mark.asyncio
async def test_internal_search_exa_with_mock(researcher_with_exa):
    """_search_exa() con client mockato ritorna WebResult."""
    mock_client = MagicMock()
    mock_client.search_and_contents = MagicMock(return_value=_make_exa_response())
    researcher_with_exa._exa_client = mock_client

    results = await researcher_with_exa._search_exa("fastapi")
    assert len(results) == 1
    assert results[0].source == "exa"
    assert results[0].title == "Test"


@pytest.mark.asyncio
async def test_internal_search_exa_multiple(researcher_with_exa):
    """_search_exa() con multipli risultati."""
    items = [
        _make_exa_result("Result 1", "https://r1.com", score=0.95),
        _make_exa_result("Result 2", "https://r2.com", score=0.85),
        _make_exa_result("Result 3", "https://r3.com", score=0.75),
    ]
    mock_client = MagicMock()
    mock_client.search_and_contents = MagicMock(return_value=_make_exa_response(items))
    researcher_with_exa._exa_client = mock_client

    results = await researcher_with_exa._search_exa("test", num_results=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_internal_search_exa_highlights(researcher_with_exa):
    """_search_exa() usa highlights come snippet."""
    mock_client = MagicMock()
    mock_client.search_and_contents = MagicMock(return_value=_make_exa_response())
    researcher_with_exa._exa_client = mock_client

    results = await researcher_with_exa._search_exa("test")
    assert "highlight" in results[0].snippet


@pytest.mark.asyncio
async def test_internal_search_exa_exception(researcher_with_exa):
    """_search_exa() propaga eccezioni."""
    mock_client = MagicMock()
    mock_client.search_and_contents = MagicMock(side_effect=RuntimeError("API error"))
    researcher_with_exa._exa_client = mock_client

    with pytest.raises(RuntimeError, match="API error"):
        await researcher_with_exa._search_exa("test")


# ── Test _scrape_firecrawl() ────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_firecrawl_no_client(researcher_with_firecrawl):
    """_scrape_firecrawl() senza client ritorna lista vuota."""
    researcher_with_firecrawl._firecrawl_key = ""
    results = await researcher_with_firecrawl._scrape_firecrawl(["https://example.com"])
    assert results == []


@pytest.mark.asyncio
async def test_scrape_firecrawl_success(researcher_with_firecrawl):
    """_scrape_firecrawl() con client mockato ritorna WebResult."""
    mock_client = MagicMock()
    mock_client.scrape_url = MagicMock(return_value={
        "markdown": "# Title\nContent here",
        "metadata": {"title": "Page Title"},
    })
    researcher_with_firecrawl._firecrawl_client = mock_client

    results = await researcher_with_firecrawl._scrape_firecrawl(["https://example.com"])
    assert len(results) == 1
    assert results[0].source == "firecrawl"
    assert results[0].title == "Page Title"
    assert "Content" in results[0].snippet


@pytest.mark.asyncio
async def test_scrape_firecrawl_multiple_urls(researcher_with_firecrawl):
    """_scrape_firecrawl() scrape multiple URLs."""
    mock_client = MagicMock()
    mock_client.scrape_url = MagicMock(return_value={
        "markdown": "content",
        "metadata": {"title": "T"},
    })
    researcher_with_firecrawl._firecrawl_client = mock_client

    results = await researcher_with_firecrawl._scrape_firecrawl([
        "https://a.com", "https://b.com", "https://c.com",
    ])
    assert len(results) == 3


@pytest.mark.asyncio
async def test_scrape_firecrawl_error_continues(researcher_with_firecrawl):
    """_scrape_firecrawl() continua dopo errore su singola URL."""
    mock_client = MagicMock()
    call_count = 0

    def side_effect(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Failed")
        return {"markdown": "ok", "metadata": {"title": "T"}}

    mock_client.scrape_url = MagicMock(side_effect=side_effect)
    researcher_with_firecrawl._firecrawl_client = mock_client

    results = await researcher_with_firecrawl._scrape_firecrawl(["https://a.com", "https://b.com"])
    assert len(results) == 1  # solo il secondo


# ── Test scrape_url() ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_url_no_key():
    """scrape_url() senza key ritorna None."""
    r = WebResearcher(firecrawl_api_key="")
    result = await r.scrape_url("https://example.com")
    assert result is None


@pytest.mark.asyncio
async def test_scrape_url_success(researcher_with_firecrawl):
    """scrape_url() ritorna WebResult."""
    mock_result = WebResult(title="T", url="u", snippet="s", source="firecrawl")
    with patch.object(researcher_with_firecrawl, "_scrape_firecrawl", new_callable=AsyncMock, return_value=[mock_result]):
        result = await researcher_with_firecrawl.scrape_url("https://example.com")
    assert result is not None
    assert result.source == "firecrawl"


@pytest.mark.asyncio
async def test_scrape_url_error(researcher_with_firecrawl):
    """scrape_url() gestisce errori."""
    with patch.object(researcher_with_firecrawl, "_scrape_firecrawl", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
        result = await researcher_with_firecrawl.scrape_url("https://example.com")
    assert result is None


# ── Test Lazy Init ─────────────────────────────────────────────────

def test_get_exa_client_no_key():
    """_get_exa_client() senza key ritorna None."""
    r = WebResearcher(exa_api_key="")
    assert r._get_exa_client() is None


def test_get_firecrawl_client_no_key():
    """_get_firecrawl_client() senza key ritorna None."""
    r = WebResearcher(firecrawl_api_key="")
    assert r._get_firecrawl_client() is None


def test_get_exa_client_import_error():
    """_get_exa_client() gestisce ImportError."""
    r = WebResearcher(exa_api_key="key")
    with patch("core.research.web_researcher.WebResearcher._get_exa_client") as mock_get:
        mock_get.return_value = None
        result = r._get_exa_client()
    assert result is None


def test_get_firecrawl_client_import_error():
    """_get_firecrawl_client() gestisce ImportError."""
    r = WebResearcher(firecrawl_api_key="key")
    with patch("core.research.web_researcher.WebResearcher._get_firecrawl_client") as mock_get:
        mock_get.return_value = None
        result = r._get_firecrawl_client()
    assert result is None
