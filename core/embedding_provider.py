"""Embedding provider — interfaccia astratta + implementazioni concrete.

Step 0.3 della migrazione v0.3.0: disaccoppia l'embedding dalla dipendenza
hard su Ollama, permettendo FastEmbed come alternativa locale senza GPU.

Uso:
    from core.embedding_provider import get_embedding_provider

    provider = get_embedding_provider("fastembed")  # oppure "ollama"
    vectors = await provider.embed(["testo 1", "testo 2"])
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Interfaccia astratta per generare embeddings."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificativo del provider."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nome del modello di embedding usato."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensione dei vettori generati."""
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings per una lista di testi.

        Args:
            texts: Lista di stringhe da embeddare.

        Returns:
            Lista di vettori float, uno per ogni testo in input.
            Ogni vettore ha lunghezza == self.dimension.

        Raises:
            EmbeddingError: Se l'embedding fallisce.
        """
        ...

    async def embed_single(self, text: str) -> list[float]:
        """Genera embedding per un singolo testo. Convenience method."""
        results = await self.embed([text])
        return results[0]


class EmbeddingError(Exception):
    """Errore durante la generazione degli embedding."""
    pass


# ── OllamaEmbedding ────────────────────────────────────────────────────

class OllamaEmbedding(EmbeddingProvider):
    """Embedding via Ollama API (/api/embed endpoint batch).

    Richiede un server Ollama in esecuzione con il modello scaricato.
    Performance: ~50 docs/s su M1 GPU con nomic-embed-text.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        max_chars: int = 1500,
        dimension: int = 768,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_chars = max_chars
        self._dimension = dimension

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding via Ollama /api/embed."""
        if not texts:
            return []

        # Sanitizza e tronca
        sanitized = []
        for t in texts:
            t = t.strip()
            if not t:
                t = " "  # Ollama richiede testo non vuoto
            if len(t) > self._max_chars:
                t = t[:self._max_chars]
            sanitized.append(t)

        url = f"{self._base_url}/api/embed"
        payload = {"model": self._model, "input": sanitized}

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

            embeddings = data.get("embeddings", [])
            if len(embeddings) != len(sanitized):
                raise EmbeddingError(
                    f"Ollama ha ritornato {len(embeddings)} embeddings per {len(sanitized)} testi"
                )
            return embeddings

        except httpx.ConnectError:
            raise EmbeddingError(
                f"Impossibile connettersi a Ollama ({self._base_url}). "
                "Verifica che il server sia in esecuzione."
            )
        except httpx.HTTPStatusError as e:
            raise EmbeddingError(f"Ollama errore HTTP {e.response.status_code}: {e.response.text}")
        except Exception as e:
            if isinstance(e, EmbeddingError):
                raise
            raise EmbeddingError(f"Errore Ollama embedding: {e}") from e


# ── FastEmbedProvider ───────────────────────────────────────────────────

class FastEmbedProvider(EmbeddingProvider):
    """Embedding locale via FastEmbed (ONNX, no GPU required).

    Non richiede server esterno. Il modello viene scaricato e cachato
    automaticamente al primo uso (~100MB).
    Performance: ~20-30 docs/s su M1 CPU.
    """

    # Modello default: BAAI/bge-small-en-v1.5, piccolo e veloce
    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
    DEFAULT_DIMENSION = 384

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        dimension: int = DEFAULT_DIMENSION,
        max_length: int = 512,
        cache_dir: Optional[str] = None,
    ):
        self._model_name = model
        self._dimension = dimension
        self._max_length = max_length
        self._cache_dir = cache_dir
        self._embedding_model = None  # Lazy init

    @property
    def name(self) -> str:
        return "fastembed"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_model(self):
        """Lazy-load del modello FastEmbed."""
        if self._embedding_model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError:
                raise EmbeddingError(
                    "fastembed non installato. Installa con: pip install fastembed"
                )
            kwargs = {"model_name": self._model_name}
            if self._cache_dir:
                kwargs["cache_dir"] = self._cache_dir
            self._embedding_model = TextEmbedding(**kwargs)
            logger.info("FastEmbed model loaded: %s", self._model_name)
        return self._embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings con FastEmbed (eseguito in executor per non bloccare)."""
        if not texts:
            return []

        loop = asyncio.get_event_loop()
        try:
            embeddings = await loop.run_in_executor(None, self._embed_sync, texts)
            return embeddings
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(f"FastEmbed errore: {e}") from e

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        """Embedding sincrono (chiamato dall'executor)."""
        model = self._get_model()

        # Sanitizza
        sanitized = []
        for t in texts:
            t = t.strip() if t else " "
            if not t:
                t = " "
            sanitized.append(t)

        # FastEmbed ritorna un generator, convertiamo in lista
        result = list(model.embed(sanitized))
        # Ogni elemento e' un numpy array, convertiamo in lista float
        return [vec.tolist() for vec in result]


# ── Factory ─────────────────────────────────────────────────────────────

_PROVIDERS = {
    "ollama": OllamaEmbedding,
    "fastembed": FastEmbedProvider,
}


def get_embedding_provider(
    provider_name: str = "ollama",
    **kwargs,
) -> EmbeddingProvider:
    """Factory per ottenere un embedding provider.

    Args:
        provider_name: "ollama" o "fastembed"
        **kwargs: Parametri specifici del provider.

    Returns:
        Istanza del provider richiesto.

    Raises:
        ValueError: Se il provider non e' supportato.
    """
    provider_class = _PROVIDERS.get(provider_name.lower())
    if provider_class is None:
        supported = ", ".join(_PROVIDERS.keys())
        raise ValueError(
            f"Provider '{provider_name}' non supportato. Supportati: {supported}"
        )
    return provider_class(**kwargs)
