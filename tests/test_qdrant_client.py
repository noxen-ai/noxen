"""Test per core/qdrant_client.py — Qdrant singleton client.

Testa il client con Qdrant reale (richiede container in esecuzione).
Per i test unitari puri, usiamo mock dove appropriato.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from core.qdrant_client import NoxenQdrantClient, COLLECTIONS


# ── Fixture ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton prima e dopo ogni test."""
    NoxenQdrantClient.reset()
    yield
    NoxenQdrantClient.reset()


# ── Singleton Pattern ────────────────────────────────────────────────────

class TestSingletonPattern:
    """Verifica il pattern singleton."""

    def test_get_instance_before_init_raises(self):
        """get_instance() senza initialize() solleva RuntimeError."""
        with pytest.raises(RuntimeError, match="non inizializzato"):
            NoxenQdrantClient.get_instance()

    @pytest.mark.asyncio
    async def test_initialize_sets_instance(self):
        """initialize() setta il singleton accessibile via get_instance()."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        assert NoxenQdrantClient.get_instance() is instance

    @pytest.mark.asyncio
    async def test_initialize_returns_same_type(self):
        """initialize() ritorna un NoxenQdrantClient."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        assert isinstance(instance, NoxenQdrantClient)

    @pytest.mark.asyncio
    async def test_second_initialize_replaces_instance(self):
        """Una seconda initialize() sostituisce l'istanza."""
        first = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        second = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        assert NoxenQdrantClient.get_instance() is second
        assert first is not second

    def test_reset_clears_instance(self):
        """reset() azzera il singleton."""
        NoxenQdrantClient._instance = MagicMock()
        NoxenQdrantClient.reset()
        assert NoxenQdrantClient._instance is None


# ── Collections ──────────────────────────────────────────────────────────

class TestCollections:
    """Verifica la creazione delle 7 collections."""

    @pytest.mark.asyncio
    async def test_ensure_collections_creates_all_seven(self):
        """_ensure_collections() crea tutte le 7 collections definite."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        existing = {
            c.name for c in instance.client.get_collections().collections
        }
        for name in COLLECTIONS:
            assert name in existing, f"Collection '{name}' non trovata"

    @pytest.mark.asyncio
    async def test_collections_count_is_seven(self):
        """Devono esserci esattamente 7 collections."""
        assert len(COLLECTIONS) == 7

    @pytest.mark.asyncio
    async def test_existing_collections_not_recreated(self):
        """Collections gia' esistenti non vengono ricreate (no errore)."""
        # Prima inizializzazione crea le collections
        await NoxenQdrantClient.initialize(url="http://localhost:6333")
        NoxenQdrantClient.reset()
        # Seconda inizializzazione non deve fallire
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        existing = {
            c.name for c in instance.client.get_collections().collections
        }
        for name in COLLECTIONS:
            assert name in existing

    @pytest.mark.asyncio
    async def test_collections_use_cosine_distance(self):
        """Le collections usano distanza cosine."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        for name in COLLECTIONS:
            info = instance.client.get_collection(name)
            # VectorParams ha distance attribute
            params = info.config.params.vectors
            assert params.distance.name == "COSINE"

    @pytest.mark.asyncio
    async def test_collections_vector_size_384(self):
        """Le collections hanno vector size 384 (fastembed default)."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        for name in COLLECTIONS:
            info = instance.client.get_collection(name)
            params = info.config.params.vectors
            assert params.size == 384


# ── Health Check ─────────────────────────────────────────────────────────

class TestHealthCheck:
    """Verifica health_check()."""

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self):
        """health_check() ritorna True con Qdrant up."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        assert await instance.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_false_on_bad_url(self):
        """health_check() ritorna False con URL sbagliato."""
        # Non usiamo initialize() perche' fallirebbe su _ensure_collections
        instance = NoxenQdrantClient(url="http://localhost:19999")
        assert await instance.health_check() is False


# ── Collection Counts ────────────────────────────────────────────────────

class TestCollectionCounts:
    """Verifica get_collection_counts()."""

    @pytest.mark.asyncio
    async def test_get_collection_counts_all_zero(self):
        """Tutte le collections partono con 0 punti."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        counts = await instance.get_collection_counts()
        assert len(counts) == 7
        for name, count in counts.items():
            assert name in COLLECTIONS
            assert count == 0


# ── Client Property ──────────────────────────────────────────────────────

class TestClientProperty:
    """Verifica accesso al client sottostante."""

    @pytest.mark.asyncio
    async def test_client_property_returns_qdrant_client(self):
        """La property client ritorna il QdrantClient."""
        from qdrant_client import QdrantClient
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        assert isinstance(instance.client, QdrantClient)


# ── Close ────────────────────────────────────────────────────────────────

class TestClose:
    """Verifica close()."""

    @pytest.mark.asyncio
    async def test_close_does_not_raise(self):
        """close() non solleva eccezioni."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        await instance.close()  # Non deve lanciare

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """close() chiamata due volte non fallisce."""
        instance = await NoxenQdrantClient.initialize(url="http://localhost:6333")
        await instance.close()
        await instance.close()
