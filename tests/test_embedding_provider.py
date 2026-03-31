"""Test per core/embedding_provider.py — interfaccia embedding provider."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from core.embedding_provider import (
    EmbeddingProvider,
    EmbeddingError,
    OllamaEmbedding,
    FastEmbedProvider,
    get_embedding_provider,
)


class TestEmbeddingProviderInterface:
    """Test interfaccia astratta EmbeddingProvider."""

    def test_cannot_instantiate_abstract(self):
        """Non si puo' istanziare direttamente EmbeddingProvider."""
        with pytest.raises(TypeError):
            EmbeddingProvider()

    def test_concrete_must_implement_all(self):
        """Una subclass senza embed() non puo' essere istanziata."""

        class Incomplete(EmbeddingProvider):
            @property
            def name(self):
                return "x"

            @property
            def model_name(self):
                return "y"

            @property
            def dimension(self):
                return 128
            # manca embed()

        with pytest.raises(TypeError):
            Incomplete()


class TestOllamaEmbedding:
    """Test OllamaEmbedding provider."""

    def test_default_values(self):
        """Valori default corretti."""
        provider = OllamaEmbedding()
        assert provider.name == "ollama"
        assert provider.model_name == "nomic-embed-text"
        assert provider.dimension == 768

    def test_custom_values(self):
        """Valori custom accettati."""
        provider = OllamaEmbedding(
            base_url="http://gpu-server:11434",
            model="mxbai-embed-large",
            dimension=1024,
        )
        assert provider.model_name == "mxbai-embed-large"
        assert provider.dimension == 1024

    @pytest.mark.asyncio
    async def test_embed_empty_returns_empty(self):
        """Embed di lista vuota ritorna lista vuota."""
        provider = OllamaEmbedding()
        result = await provider.embed([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_calls_ollama_api(self):
        """embed() chiama l'API Ollama correttamente."""
        provider = OllamaEmbedding()
        fake_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": fake_embeddings}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.embedding_provider.httpx.AsyncClient", return_value=mock_client):
            result = await provider.embed(["testo 1", "testo 2"])

        assert result == fake_embeddings
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/api/embed" in call_args[0][0]
        assert call_args[1]["json"]["model"] == "nomic-embed-text"
        assert len(call_args[1]["json"]["input"]) == 2

    @pytest.mark.asyncio
    async def test_embed_sanitizes_empty_strings(self):
        """Stringhe vuote vengono sostituite con spazio."""
        provider = OllamaEmbedding()
        fake_embeddings = [[0.1]]

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": fake_embeddings}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.embedding_provider.httpx.AsyncClient", return_value=mock_client):
            result = await provider.embed([""])

        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["input"] == [" "]

    @pytest.mark.asyncio
    async def test_embed_truncates_long_text(self):
        """Testi lunghi vengono troncati a max_chars."""
        provider = OllamaEmbedding(max_chars=10)
        fake_embeddings = [[0.1]]

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": fake_embeddings}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.embedding_provider.httpx.AsyncClient", return_value=mock_client):
            await provider.embed(["x" * 100])

        call_args = mock_client.post.call_args
        assert len(call_args[1]["json"]["input"][0]) == 10

    @pytest.mark.asyncio
    async def test_embed_connection_error(self):
        """Errore di connessione produce EmbeddingError."""
        import httpx
        provider = OllamaEmbedding(base_url="http://nonexistent:11434")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.embedding_provider.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(EmbeddingError, match="connettersi a Ollama"):
                await provider.embed(["test"])

    @pytest.mark.asyncio
    async def test_embed_count_mismatch_raises(self):
        """Mismatch nel numero di embeddings produce errore."""
        provider = OllamaEmbedding()

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1]]}  # 1 embedding per 2 testi
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.embedding_provider.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(EmbeddingError, match="embeddings"):
                await provider.embed(["a", "b"])


class TestFastEmbedProvider:
    """Test FastEmbedProvider."""

    def test_default_values(self):
        """Valori default corretti."""
        provider = FastEmbedProvider()
        assert provider.name == "fastembed"
        assert provider.model_name == "BAAI/bge-small-en-v1.5"
        assert provider.dimension == 384

    def test_custom_values(self):
        """Valori custom accettati."""
        provider = FastEmbedProvider(
            model="BAAI/bge-base-en-v1.5",
            dimension=768,
        )
        assert provider.model_name == "BAAI/bge-base-en-v1.5"
        assert provider.dimension == 768

    @pytest.mark.asyncio
    async def test_embed_empty_returns_empty(self):
        """Embed di lista vuota ritorna lista vuota."""
        provider = FastEmbedProvider()
        result = await provider.embed([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_uses_fastembed_model(self):
        """embed() usa il modello FastEmbed."""
        import numpy as np

        provider = FastEmbedProvider()
        fake_vectors = [np.array([0.1, 0.2, 0.3]), np.array([0.4, 0.5, 0.6])]

        mock_model = MagicMock()
        mock_model.embed.return_value = iter(fake_vectors)

        mock_text_embedding = MagicMock(return_value=mock_model)

        with patch.dict("sys.modules", {"fastembed": MagicMock(TextEmbedding=mock_text_embedding)}):
            provider._embedding_model = mock_model
            result = await provider.embed(["testo 1", "testo 2"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        mock_model.embed.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_sanitizes_empty_strings(self):
        """Stringhe vuote vengono sostituite con spazio."""
        import numpy as np

        provider = FastEmbedProvider()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1])])
        provider._embedding_model = mock_model

        await provider.embed([""])

        call_args = mock_model.embed.call_args[0][0]
        assert call_args == [" "]

    def test_fastembed_import_error(self):
        """Se fastembed non e' installato, errore chiaro."""
        provider = FastEmbedProvider()
        provider._embedding_model = None

        with patch.dict("sys.modules", {"fastembed": None}):
            with pytest.raises(EmbeddingError, match="fastembed non installato"):
                provider._get_model()

    @pytest.mark.asyncio
    async def test_embed_single_convenience(self):
        """embed_single() funziona come convenience method."""
        import numpy as np

        provider = FastEmbedProvider()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2])])
        provider._embedding_model = mock_model

        result = await provider.embed_single("testo singolo")
        assert result == [0.1, 0.2]


class TestGetEmbeddingProvider:
    """Test factory get_embedding_provider."""

    def test_get_ollama(self):
        """Factory ritorna OllamaEmbedding per 'ollama'."""
        provider = get_embedding_provider("ollama")
        assert isinstance(provider, OllamaEmbedding)

    def test_get_fastembed(self):
        """Factory ritorna FastEmbedProvider per 'fastembed'."""
        provider = get_embedding_provider("fastembed")
        assert isinstance(provider, FastEmbedProvider)

    def test_case_insensitive(self):
        """Il nome provider e' case-insensitive."""
        provider = get_embedding_provider("Ollama")
        assert isinstance(provider, OllamaEmbedding)

    def test_unknown_provider_raises(self):
        """Provider sconosciuto solleva ValueError."""
        with pytest.raises(ValueError, match="non supportato"):
            get_embedding_provider("openai")

    def test_passes_kwargs(self):
        """I kwargs vengono passati al costruttore."""
        provider = get_embedding_provider(
            "ollama",
            base_url="http://custom:11434",
            model="custom-model",
        )
        assert provider.model_name == "custom-model"

    def test_default_is_ollama(self):
        """Default provider e' ollama."""
        provider = get_embedding_provider()
        assert isinstance(provider, OllamaEmbedding)


class TestEmbeddingError:
    """Test EmbeddingError exception."""

    def test_is_exception(self):
        """EmbeddingError e' una Exception."""
        err = EmbeddingError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"
