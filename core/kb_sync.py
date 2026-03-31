"""KB Sync — sincronizza la KB globale da api.noxen.ai al Qdrant locale.

Modalita':
- Full: scarica snapshot completo (primo avvio)
- Delta: scarica solo nuovi documenti (sync periodico)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from core.logger import get_logger

logger = get_logger("kb_sync")


class KBSync:

    def __init__(
        self,
        license_server_url: str,
        license_key: str,
        qdrant_client=None,
        data_dir: str = "data",
    ):
        self._server = license_server_url
        self._key = license_key
        self._qdrant = qdrant_client
        self._data_dir = Path(data_dir)
        self._sync_state_file = self._data_dir / ".kb_sync_state.json"

    def _load_sync_state(self) -> dict:
        if self._sync_state_file.exists():
            return json.loads(self._sync_state_file.read_text())
        return {"last_sync": None, "count": 0}

    def _save_sync_state(self, state: dict):
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._sync_state_file.write_text(json.dumps(state))

    async def needs_sync(self) -> bool:
        """Ritorna True se la KB locale e' vuota o non sincronizzata da piu' di 7 giorni."""
        state = self._load_sync_state()
        if not state["last_sync"]:
            return True
        last = datetime.fromisoformat(state["last_sync"])
        days_since = (datetime.now() - last).days
        return days_since >= 7

    async def sync(
        self,
        technologies: list[str] | None = None,
        force_full: bool = False,
    ) -> dict:
        """Sincronizza KB globale nel Qdrant locale."""
        state = self._load_sync_state()
        is_first_sync = state["last_sync"] is None

        if is_first_sync or force_full:
            return await self._full_sync(technologies)
        else:
            return await self._delta_sync(
                since=state["last_sync"],
                technologies=technologies,
            )

    async def _full_sync(self, technologies: list[str] | None = None) -> dict:
        """Scarica e importa snapshot completo."""
        logger.info("kb_sync_full_start", technologies=technologies)

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                params: dict = {"key": self._key}
                if technologies:
                    params["tech"] = ",".join(technologies)

                r = await client.get(
                    f"{self._server}/v1/kb/snapshot",
                    params=params,
                )

                if r.status_code == 404:
                    logger.warning("kb_sync_snapshot_not_available")
                    return {"synced": 0, "status": "unavailable"}

                r.raise_for_status()
                data = r.json()
                points = data.get("points", [])

        except Exception as e:
            logger.warning("kb_sync_failed", error=str(e))
            return {"synced": 0, "status": "error"}

        # Importa in Qdrant
        imported = await self._import_points(points)

        # Aggiorna stato
        self._save_sync_state({
            "last_sync": datetime.now().isoformat(),
            "count": imported,
        })

        logger.info("kb_sync_complete", imported=imported)
        return {"synced": imported, "status": "ok"}

    async def _delta_sync(
        self, since: str, technologies: list[str] | None = None
    ) -> dict:
        """Scarica solo i nuovi documenti."""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                params: dict = {"key": self._key, "since": since}
                if technologies:
                    params["tech"] = ",".join(technologies)

                r = await client.get(
                    f"{self._server}/v1/kb/delta",
                    params=params,
                )
                r.raise_for_status()
                data = r.json()
                points = data.get("points", [])

        except Exception as e:
            logger.warning("kb_delta_sync_failed", error=str(e))
            return {"synced": 0, "status": "error"}

        imported = await self._import_points(points)

        state = self._load_sync_state()
        state["last_sync"] = datetime.now().isoformat()
        state["count"] = state.get("count", 0) + imported
        self._save_sync_state(state)

        return {"synced": imported, "status": "ok"}

    async def _import_points(self, points: list[dict]) -> int:
        """Importa punti nel Qdrant locale."""
        if not points or not self._qdrant:
            return 0

        try:
            from qdrant_client.models import PointStruct, VectorParams, Distance

            collection = "global_knowledge"

            # Crea collection se non esiste
            existing = [
                c.name for c in self._qdrant.client.get_collections().collections
            ]
            if collection not in existing:
                self._qdrant.client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )

            # Importa a batch
            batch_size = 100
            imported = 0

            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                qdrant_points = [
                    PointStruct(
                        id=p.get("id", str(uuid.uuid4())),
                        vector=p["vector"],
                        payload=p.get("payload", {}),
                    )
                    for p in batch
                    if "vector" in p
                ]

                if qdrant_points:
                    self._qdrant.client.upsert(
                        collection_name=collection,
                        points=qdrant_points,
                    )
                    imported += len(qdrant_points)

            return imported

        except Exception as e:
            logger.warning("kb_import_failed", error=str(e))
            return 0

    async def contribute_skill(
        self,
        skill_id: str,
        skill_content: dict,
        license_key: str,
        plan: str,
    ) -> bool:
        """Contribuisce una skill alla KB globale. Solo piano Team puo' contribuire."""
        if plan != "team":
            logger.info(
                "kb_contribute_skipped",
                reason="developer plan cannot contribute",
            )
            return False

        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self._server}/v1/kb/contribute",
                    json={"license_key": license_key, "skill": skill_content},
                    timeout=30.0,
                )
                return r.status_code == 200
        except Exception as e:
            logger.warning("kb_contribute_failed", error=str(e))
            return False
