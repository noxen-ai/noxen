"""Test per core/llm_provider.py — pool httpx + retry con tenacity."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx

from core.llm_provider import (
    LLMProvider,
    LLMResponse,
    BoardResponse,
    _is_retryable,
    API_TIMEOUT,
    MODEL_ROUTING,
)


class TestLLMProviderInit:
    """Test creazione e configurazione LLMProvider."""

    def test_creates_persistent_client(self):
        """LLMProvider crea un httpx.AsyncClient persistente."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()

        assert provider._client is not None
        assert isinstance(provider._client, httpx.AsyncClient)
        assert not provider._client.is_closed

    def test_client_has_timeout(self):
        """Il client ha il timeout configurato."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = ""
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()

        # Verifica timeout configurato
        assert provider._client.timeout.connect is not None


class TestLLMProviderClose:
    """Test chiusura del client HTTP."""

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        """close() chiude il client HTTP."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = ""
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()

        assert not provider._client.is_closed
        await provider.close()
        assert provider._client.is_closed

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """close() puo' essere chiamato piu' volte senza errori."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = ""
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()

        await provider.close()
        await provider.close()  # Non deve sollevare eccezioni


class TestIsRetryable:
    """Test funzione _is_retryable per determinare errori ritentabili."""

    def test_429_is_retryable(self):
        """HTTP 429 (rate limit) e' ritentabile."""
        response = MagicMock()
        response.status_code = 429
        exc = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=response)
        assert _is_retryable(exc) is True

    def test_500_is_retryable(self):
        """HTTP 500 e' ritentabile."""
        response = MagicMock()
        response.status_code = 500
        exc = httpx.HTTPStatusError("server error", request=MagicMock(), response=response)
        assert _is_retryable(exc) is True

    def test_502_is_retryable(self):
        """HTTP 502 e' ritentabile."""
        response = MagicMock()
        response.status_code = 502
        exc = httpx.HTTPStatusError("bad gateway", request=MagicMock(), response=response)
        assert _is_retryable(exc) is True

    def test_503_is_retryable(self):
        """HTTP 503 e' ritentabile."""
        response = MagicMock()
        response.status_code = 503
        exc = httpx.HTTPStatusError("unavailable", request=MagicMock(), response=response)
        assert _is_retryable(exc) is True

    def test_400_not_retryable(self):
        """HTTP 400 NON e' ritentabile."""
        response = MagicMock()
        response.status_code = 400
        exc = httpx.HTTPStatusError("bad request", request=MagicMock(), response=response)
        assert _is_retryable(exc) is False

    def test_401_not_retryable(self):
        """HTTP 401 NON e' ritentabile."""
        response = MagicMock()
        response.status_code = 401
        exc = httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=response)
        assert _is_retryable(exc) is False

    def test_404_not_retryable(self):
        """HTTP 404 NON e' ritentabile."""
        response = MagicMock()
        response.status_code = 404
        exc = httpx.HTTPStatusError("not found", request=MagicMock(), response=response)
        assert _is_retryable(exc) is False

    def test_connect_error_is_retryable(self):
        """ConnectError e' ritentabile."""
        exc = httpx.ConnectError("connection refused")
        assert _is_retryable(exc) is True

    def test_read_timeout_is_retryable(self):
        """ReadTimeout e' ritentabile."""
        exc = httpx.ReadTimeout("timed out")
        assert _is_retryable(exc) is True

    def test_generic_exception_not_retryable(self):
        """Eccezione generica NON e' ritentabile."""
        assert _is_retryable(ValueError("oops")) is False


class TestLLMResponse:
    """Test dataclass LLMResponse."""

    def test_success_response(self):
        """Risposta di successo."""
        resp = LLMResponse(
            provider="gemini",
            model="gemini-2.0-flash",
            content="Hello!",
            tokens_in=10,
            tokens_out=5,
            latency_ms=150,
        )
        assert resp.success is True
        assert resp.error is None
        assert resp.provider == "gemini"

    def test_error_response(self):
        """Risposta con errore."""
        resp = LLMResponse(
            provider="ollama",
            model="llama3:8b",
            content="",
            error="Connection refused",
            success=False,
        )
        assert resp.success is False
        assert "Connection" in resp.error


class TestBoardResponse:
    """Test dataclass BoardResponse."""

    def test_default_values(self):
        """BoardResponse ha default vuoti."""
        br = BoardResponse()
        assert br.responses == []
        assert br.synthesis == ""
        assert br.chairman == ""
        assert br.consensus_level == ""

    def test_with_responses(self):
        """BoardResponse con risposte individuali."""
        r1 = LLMResponse(provider="gemini", model="m1", content="A")
        r2 = LLMResponse(provider="claude", model="m2", content="B")
        br = BoardResponse(
            responses=[r1, r2],
            synthesis="Consenso: A e B",
            chairman="gemini",
            consensus_level="high",
        )
        assert len(br.responses) == 2
        assert br.consensus_level == "high"


class TestBoardMode:
    """Test board_mode async/sync."""

    def test_board_response_default_mode(self):
        """BoardResponse default board_mode e' sync."""
        br = BoardResponse()
        assert br.board_mode == "sync"

    def test_board_response_async_mode(self):
        """BoardResponse puo' avere board_mode=async."""
        br = BoardResponse(board_mode="async")
        assert br.board_mode == "async"

    @pytest.mark.asyncio
    async def test_board_query_sync_mode(self):
        """board_query() in sync mode attende tutti i provider."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = "test"
            mock_settings.gemini_model = "gemini-2.0-flash"
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"
            mock_settings.board_chairman = "gemini"

            provider = LLMProvider()
            # Mock la query individuale
            async def mock_query(prompt, system="", provider=""):
                return LLMResponse(provider=provider, model="m", content=f"Risposta da {provider}")
            provider.query = mock_query

            result = await provider.board_query("test", board_mode="sync")

        assert result.board_mode == "sync"
        assert len(result.responses) >= 1

    @pytest.mark.asyncio
    async def test_board_query_async_mode(self):
        """board_query() in async mode ritorna il primo risultato."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = "test"
            mock_settings.gemini_model = "gemini-2.0-flash"
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"
            mock_settings.board_chairman = "gemini"

            provider = LLMProvider()
            # Mock la query individuale
            async def mock_query(prompt, system="", provider=""):
                return LLMResponse(provider=provider, model="m", content=f"Risposta da {provider}")
            provider.query = mock_query

            result = await provider.board_query("test", board_mode="async")

        assert result.board_mode == "async"
        assert len(result.responses) >= 1
        assert result.consensus_level == "async_first"

    @pytest.mark.asyncio
    async def test_board_query_no_providers(self):
        """board_query() senza provider ritorna messaggio di errore."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = ""
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()
            result = await provider.board_query("test")

        assert "Nessun provider" in result.synthesis

    @pytest.mark.asyncio
    async def test_board_query_async_single_provider_uses_sync(self):
        """board_query() async con 1 solo provider usa sync (no race condition)."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"
            mock_settings.board_chairman = "ollama"

            provider = LLMProvider()
            async def mock_query(prompt, system="", provider=""):
                return LLMResponse(provider=provider, model="m", content=f"Solo {provider}")
            provider.query = mock_query

            # async mode con 1 solo provider → fallback a sync
            result = await provider.board_query("test", board_mode="async")

        # Con un solo provider, deve usare sync
        assert result.board_mode == "sync"

    def test_last_board_result_initialized(self):
        """_last_board_result inizializzato a None."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = ""
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()
        assert provider._last_board_result is None


class TestModelRouting:
    """Test MODEL_ROUTING e route_query()."""

    def test_model_routing_has_expected_types(self):
        """MODEL_ROUTING contiene tutti i task type previsti."""
        expected = {"routing", "analysis", "architecture", "code", "security", "synthesis", "quick", "creative"}
        assert set(MODEL_ROUTING.keys()) == expected

    def test_model_routing_values_are_lists(self):
        """Ogni task type ha una lista di provider."""
        for task_type, providers in MODEL_ROUTING.items():
            assert isinstance(providers, list), f"{task_type} non e' una lista"
            assert len(providers) > 0, f"{task_type} e' vuoto"

    def test_resolve_provider_unknown_task_type(self):
        """_resolve_provider_for_task() con tipo sconosciuto usa active_provider."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"

            provider = LLMProvider()
            result = provider._resolve_provider_for_task("nonexistent")

        assert result == "ollama"

    def test_resolve_provider_empty_task_type(self):
        """_resolve_provider_for_task() con tipo vuoto usa active_provider."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"

            provider = LLMProvider()
            result = provider._resolve_provider_for_task("")

        assert result == "ollama"

    def test_resolve_provider_selects_first_available(self):
        """_resolve_provider_for_task() seleziona il primo provider disponibile."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = "test-key"
            mock_settings.gemini_model = "gemini-2.0-flash"
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"

            provider = LLMProvider()
            # "routing" preferisce ["gemini", "ollama"] — gemini è disponibile
            result = provider._resolve_provider_for_task("routing")

        assert result == "gemini"

    def test_resolve_provider_skips_unavailable(self):
        """_resolve_provider_for_task() salta provider non configurati."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"

            provider = LLMProvider()
            # "analysis" preferisce ["claude", "gemini", "openai"] — nessuno disponibile → fallback
            result = provider._resolve_provider_for_task("analysis")

        assert result == "ollama"  # fallback ad active_provider

    @pytest.mark.asyncio
    async def test_route_query_delegates_to_query(self):
        """route_query() chiama query() con il provider corretto."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = "test-key"
            mock_settings.gemini_model = "gemini-2.0-flash"
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"

            provider = LLMProvider()
            provider.query = AsyncMock(return_value=LLMResponse(
                provider="gemini", model="gemini-2.0-flash", content="OK"
            ))

            result = await provider.route_query("test prompt", task_type="routing")

        provider.query.assert_awaited_once_with("test prompt", "", provider="gemini")
        assert result.provider == "gemini"

    @pytest.mark.asyncio
    async def test_route_query_no_task_type_uses_active(self):
        """route_query() senza task_type usa active_provider."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""
            mock_settings.active_provider = "ollama"

            provider = LLMProvider()
            provider.query = AsyncMock(return_value=LLMResponse(
                provider="ollama", model="llama3:8b", content="OK"
            ))

            result = await provider.route_query("test prompt")

        provider.query.assert_awaited_once_with("test prompt", "", provider="ollama")


class TestLLMProviderAvailableProviders:
    """Test available_providers con diverse configurazioni."""

    def test_only_ollama_by_default(self):
        """Con solo Ollama configurato, solo ollama disponibile."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = ""
            mock_settings.claude_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()
            available = provider.available_providers

        assert "ollama" in available
        assert len(available) == 1

    def test_multiple_providers(self):
        """Con piu' API key, piu' provider disponibili."""
        with patch("core.llm_provider.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.default_model = "llama3:8b"
            mock_settings.gemini_api_key = "test-key"
            mock_settings.gemini_model = "gemini-2.0-flash"
            mock_settings.claude_api_key = "test-key"
            mock_settings.claude_model = "claude-sonnet-4-20250514"
            mock_settings.openai_api_key = ""
            mock_settings.grok_api_key = ""
            mock_settings.mercury_api_key = ""
            mock_settings.qwen_api_key = ""

            provider = LLMProvider()
            available = provider.available_providers

        assert "ollama" in available
        assert "gemini" in available
        assert "claude" in available
        assert len(available) == 3
