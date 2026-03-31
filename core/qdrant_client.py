"""Noxen - Qdrant Client Singleton.

Fase 1 della migrazione v0.3.0: sostituisce ChromaDB con Qdrant
come memoria vettoriale unica del sistema.

7 collections:
  - projects: Registry progetti con DNA
  - skills: Skill pool globale con metriche
  - findings: Findings per progetto
  - cycles: Storia cicli di esecuzione
  - events: Bus eventi del sistema
  - approvals: Approval gate — piani e decisioni
  - codebase: Codice indicizzato dei progetti

Uso:
    from core.qdrant_client import NoxenQdrantClient

    client = await NoxenQdrantClient.initialize(url="http://localhost:6333")
    ok = await client.health_check()
"""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from core.logger import get_logger

logger = get_logger("noxen.qdrant")

COLLECTIONS = {
    "projects": {
        "description": "Registry progetti con DNA",
        "vector_size": 384,  # fastembed default (BAAI/bge-small-en-v1.5)
    },
    "skills": {
        "description": "Skill pool globale con metriche",
        "vector_size": 384,
    },
    "findings": {
        "description": "Findings per progetto",
        "vector_size": 384,
    },
    "cycles": {
        "description": "Storia cicli di esecuzione",
        "vector_size": 384,
    },
    "events": {
        "description": "Bus eventi del sistema",
        "vector_size": 384,
    },
    "approvals": {
        "description": "Approval gate - piani e decisioni",
        "vector_size": 384,
    },
    "codebase": {
        "description": "Codice indicizzato dei progetti",
        "vector_size": 384,
    },
}


class NoxenQdrantClient:
    """Singleton Qdrant client per Noxen."""

    _instance: NoxenQdrantClient | None = None

    def __init__(self, url: str, api_key: str | None = None):
        self._client = QdrantClient(url=url, api_key=api_key)
        self._url = url
        self._logger = get_logger("noxen.qdrant")

    @classmethod
    def get_instance(cls) -> NoxenQdrantClient:
        """Ottieni l'istanza singleton. Richiede initialize() prima."""
        if cls._instance is None:
            raise RuntimeError(
                "NoxenQdrantClient non inizializzato. "
                "Chiamare initialize() prima."
            )
        return cls._instance

    @classmethod
    async def initialize(
        cls, url: str, api_key: str | None = None
    ) -> NoxenQdrantClient:
        """Inizializza il singleton e crea le collections mancanti."""
        instance = cls(url, api_key)
        await instance._ensure_collections()
        cls._instance = instance
        logger.info("qdrant_initialized", url=url, collections=len(COLLECTIONS))
        return instance

    @classmethod
    def reset(cls) -> None:
        """Reset del singleton (per test)."""
        cls._instance = None

    async def _ensure_collections(self) -> None:
        """Crea le collections se non esistono."""
        existing = {
            c.name for c in self._client.get_collections().collections
        }
        for name, config in COLLECTIONS.items():
            if name not in existing:
                self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=config["vector_size"],
                        distance=Distance.COSINE,
                    ),
                )
                self._logger.info("collection_created", collection=name)

    @property
    def client(self) -> QdrantClient:
        """Accesso diretto al QdrantClient sottostante."""
        return self._client

    async def health_check(self) -> bool:
        """Verifica che Qdrant sia raggiungibile e funzionante."""
        try:
            self._client.get_collections()
            return True
        except Exception:
            return False

    async def get_collection_counts(self) -> dict[str, int]:
        """Ritorna il conteggio punti per ogni collection."""
        counts: dict[str, int] = {}
        for name in COLLECTIONS:
            try:
                info = self._client.get_collection(name)
                counts[name] = info.points_count or 0
            except Exception:
                counts[name] = 0
        return counts

    # ── Tenant-Aware Operations (Phase 8) ────────────────────────────

    # Tenant constants — use these instead of hardcoding strings.
    # DEFAULT_TENANT: private data for on-premise tenant (projects, findings, events)
    # GLOBAL_TENANT: shared data across all tenants (skills, public knowledge)
    DEFAULT_TENANT = "default"
    GLOBAL_TENANT = "global"

    async def search_with_tenant(
        self,
        collection: str,
        query_vector: list[float],
        tenant_id: str,
        include_global: bool = True,
        limit: int = 5,
        extra_conditions: list | None = None,
    ) -> list[dict]:
        """Search with tenant isolation.

        If include_global=True: search tenant OR global pool.
        If include_global=False: search ONLY the specified tenant.
        """
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchValue,
        )

        tenant_conditions = []
        if include_global and tenant_id != self.GLOBAL_TENANT:
            # Should match either tenant-specific or global
            from qdrant_client.models import Filter as QFilter
            tenant_filter = Filter(
                should=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="tenant_id", match=MatchValue(value=self.GLOBAL_TENANT)),
                ]
            )
        else:
            tenant_filter = Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                ]
            )

        # Add extra conditions to must
        if extra_conditions:
            if not hasattr(tenant_filter, "must") or tenant_filter.must is None:
                tenant_filter.must = []
            tenant_filter.must = list(tenant_filter.must or []) + extra_conditions

        try:
            result = self._client.query_points(
                collection_name=collection,
                query=query_vector,
                query_filter=tenant_filter,
                limit=limit,
            )
            return [
                {"id": p.id, "payload": p.payload, "score": p.score}
                for p in result.points
            ]
        except Exception as e:
            self._logger.warning("search_with_tenant failed: %s", e)
            return []

    async def upsert_with_tenant(
        self,
        collection: str,
        point_id: str,
        vector: list[float],
        payload: dict,
        tenant_id: str,
    ) -> None:
        """Insert/update point with tenant_id in payload."""
        from qdrant_client.models import PointStruct

        payload["tenant_id"] = tenant_id
        self._client.upsert(
            collection_name=collection,
            points=[
                PointStruct(id=point_id, vector=vector, payload=payload)
            ],
        )

    async def delete_tenant_data(
        self,
        tenant_id: str,
        collections: list[str] | None = None,
    ) -> dict[str, int]:
        """Delete all data for a tenant from Qdrant.

        Does NOT delete global skills (tenant_id="global").
        Returns count of deleted points per collection.
        """
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchValue,
        )

        if tenant_id == self.GLOBAL_TENANT:
            raise ValueError("Cannot delete global tenant data")

        target_collections = collections or list(COLLECTIONS.keys())
        deleted: dict[str, int] = {}

        for col_name in target_collections:
            try:
                # Count before delete
                scroll_result = self._client.scroll(
                    collection_name=col_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="tenant_id",
                                match=MatchValue(value=tenant_id),
                            )
                        ]
                    ),
                    limit=10000,
                )
                points, _ = scroll_result
                count = len(points)

                if count > 0:
                    from qdrant_client.models import PointIdsList

                    point_ids = [p.id for p in points]
                    self._client.delete(
                        collection_name=col_name,
                        points_selector=PointIdsList(points=point_ids),
                    )

                deleted[col_name] = count
            except Exception as e:
                self._logger.warning(
                    "delete_tenant_data failed for %s: %s", col_name, e
                )
                deleted[col_name] = 0

        return deleted

    async def close(self) -> None:
        """Chiudi la connessione al client Qdrant."""
        try:
            self._client.close()
        except Exception:
            pass
