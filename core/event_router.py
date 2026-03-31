"""Noxen - Event Router.

Creato in Phase 2 Step 2.3.
Router leggero per eventi del sistema:
  - Logga ogni evento su Qdrant collection "events"
  - Routing basato su tipo evento (query, init, spider, engine, db, error)
  - Nessun LLM coinvolto — solo logging e routing

Preparazione per il bus eventi completo (Phase 3+).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from core.logger import get_logger
from core.qdrant_client import NoxenQdrantClient

logger = get_logger("noxen.event_router")

# Tipi di evento supportati
EVENT_TYPES = {
    "query",       # Query utente (chat, query non-streaming)
    "init",        # Init progetto
    "spider",      # Spider analysis
    "engine",      # Neural Engine ciclo
    "db",          # Query database
    "skill",       # Skill routing
    "error",       # Errore sistema
    "system",      # Eventi di sistema (startup, shutdown)
}


class EventRouter:
    """Router e logger di eventi del sistema."""

    def __init__(self, persist: bool = True) -> None:
        """
        Args:
            persist: Se True, logga eventi su Qdrant collection "events".
                     Se False, solo in-memory (utile per test).
        """
        self._persist = persist
        self._recent: list[dict[str, Any]] = []
        self._max_recent = 100  # Buffer circolare ultimi N eventi

    async def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        source: str = "",
    ) -> str:
        """Emetti un evento nel sistema.

        Args:
            event_type: Tipo di evento (query, init, spider, engine, db, skill, error, system)
            data: Payload dell'evento
            source: Modulo sorgente (es. "orchestrator", "spider", "engine")

        Returns:
            event_id: UUID dell'evento creato.
        """
        event_id = str(uuid.uuid4())
        timestamp = time.time()

        event = {
            "event_id": event_id,
            "type": event_type if event_type in EVENT_TYPES else "system",
            "source": source,
            "timestamp": timestamp,
            "data": data or {},
        }

        # Buffer circolare in-memory
        self._recent.append(event)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]

        # Persist su Qdrant (best-effort)
        if self._persist:
            await self._persist_event(event)

        logger.debug(f"Event [{event_type}] from {source}: {event_id}")
        return event_id

    async def _persist_event(self, event: dict[str, Any]) -> None:
        """Salva l'evento su Qdrant collection 'events'."""
        try:
            from core.qdrant_client import NoxenQdrantClient
            from core.embedding_provider import FastEmbedProvider
            from qdrant_client.models import PointStruct

            instance = NoxenQdrantClient.get_instance()
            client = instance.client

            # Testo per embedding: tipo + source + dati principali
            text = f"{event['type']} {event['source']} {str(event['data'])[:500]}"
            provider = FastEmbedProvider.get_instance()
            vectors = provider.embed([text])
            if not vectors:
                return

            point = PointStruct(
                id=str(uuid.UUID(event["event_id"])),
                vector=vectors[0],
                payload={
                    "event_id": event["event_id"],
                    "type": event["type"],
                    "source": event["source"],
                    "timestamp": event["timestamp"],
                    "data": str(event["data"])[:2000],
                    "tenant_id": NoxenQdrantClient.DEFAULT_TENANT,
                },
            )

            client.upsert(collection_name="events", points=[point])

        except (RuntimeError, ImportError) as e:
            # Qdrant non inizializzato o FastEmbed non disponibile — skip silenzioso
            logger.debug(f"Event persist skipped: {e}")
        except Exception as e:
            logger.warning(f"Event persist failed: {e}")

    def get_recent(self, event_type: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Ritorna gli eventi recenti dal buffer in-memory.

        Args:
            event_type: Filtra per tipo (vuoto = tutti)
            limit: Numero massimo di eventi

        Returns:
            Lista di eventi, più recenti prima.
        """
        events = self._recent
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        return list(reversed(events[-limit:]))

    def get_stats(self) -> dict[str, Any]:
        """Statistiche degli eventi in-memory."""
        type_counts: dict[str, int] = {}
        for event in self._recent:
            t = event["type"]
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "total_events": len(self._recent),
            "by_type": type_counts,
            "buffer_size": self._max_recent,
        }
