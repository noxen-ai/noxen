"""Noxen - Project Manager.

Gestisce la registrazione dei progetti (microservizi, frontend, ecc.)
con persistenza in Qdrant (collection "projects") + JSON locale di backup.

Fase 1 v0.3.0: migrato da ChromaDB a Qdrant.
Ogni progetto ha un vettore embedding del nome+descrizione per semantic search.

Design:
  - Metadati salvati in JSON locale (data/projects.json) per boot veloce
  - Vettori in Qdrant collection "projects" per ricerca semantica
  - FastEmbedProvider per gli embedding (no Ollama dependency)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import settings
from core.logger import get_logger
from core.qdrant_client import NoxenQdrantClient

logger = get_logger("noxen.projects")

PROJECTS_FILE = settings.data_dir / "projects.json"


@dataclass
class ProjectInfo:
    """Metadati di un progetto registrato."""
    name: str
    path: str
    slug: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    indexed: bool = False
    indexed_at: float = 0.0
    file_count: int = 0
    chunk_count: int = 0

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = self.name.lower().replace(" ", "_").replace("-", "_")


class ProjectManager:
    """Registra progetti e gestisce il registry con Qdrant + JSON."""

    def __init__(self) -> None:
        self._projects: dict[str, ProjectInfo] = {}
        self._embedding_provider = None  # Lazy init
        self._load_projects()

    # ── Embedding Provider ─────────────────────────────────────────────

    def _get_embedding_provider(self):
        """Lazy-load del FastEmbedProvider."""
        if self._embedding_provider is None:
            from core.embedding_provider import get_embedding_provider
            self._embedding_provider = get_embedding_provider("fastembed")
        return self._embedding_provider

    # ── Qdrant Access ──────────────────────────────────────────────────

    def _get_qdrant_client(self):
        """Ottieni il QdrantClient dal singleton."""
        from core.qdrant_client import NoxenQdrantClient
        return NoxenQdrantClient.get_instance().client

    # ── CRUD Progetti ──────────────────────────────────────────────────

    @property
    def projects(self) -> dict[str, ProjectInfo]:
        return dict(self._projects)

    def register(
        self,
        name: str,
        path: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> ProjectInfo:
        """Registra un nuovo progetto o aggiorna uno esistente."""
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Il percorso non esiste: {resolved}")

        proj = ProjectInfo(
            name=name,
            path=str(resolved),
            description=description,
            tags=tags or [],
        )
        self._projects[name] = proj
        self._save_projects()

        logger.info("project_registered", project=name, path=str(resolved))
        return proj

    def unregister(self, name: str) -> bool:
        """Rimuovi un progetto dal registry e da Qdrant."""
        if name not in self._projects:
            return False
        self._projects.pop(name)
        self._save_projects()

        # Rimuovi da Qdrant (best-effort)
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            client = self._get_qdrant_client()
            client.delete(
                collection_name="projects",
                points_selector=Filter(
                    must=[FieldCondition(key="name", match=MatchValue(value=name))]
                ),
            )
        except Exception:
            pass  # Qdrant potrebbe non essere up

        logger.info("project_unregistered", project=name)
        return True

    def get(self, name: str) -> ProjectInfo | None:
        return self._projects.get(name)

    async def search_projects(self, query: str, n_results: int = 5) -> list[dict]:
        """Ricerca semantica tra i progetti registrati via Qdrant.

        Args:
            query: Testo di ricerca.
            n_results: Numero massimo di risultati.

        Returns:
            Lista di dict con name, path, description, score.
        """
        if not self._projects:
            return []

        try:
            provider = self._get_embedding_provider()
            query_vector = await provider.embed_single(query)
            client = self._get_qdrant_client()

            results = client.query_points(
                collection_name="projects",
                query=query_vector,
                limit=n_results,
            )

            return [
                {
                    "name": hit.payload.get("name", ""),
                    "path": hit.payload.get("path", ""),
                    "description": hit.payload.get("description", ""),
                    "score": hit.score,
                }
                for hit in results.points
            ]
        except Exception as e:
            logger.warning("project_search_error", error=str(e))
            return []

    def search(
        self, project_name: str, query: str, n_results: int = 5
    ) -> list[dict]:
        """Cerca nel codebase di un progetto (collection 'codebase' in Qdrant).

        Nota: questa e' una ricerca sincrona nei metadati locali.
        La ricerca semantica nel codice indicizzato e' gestita dall'Ingestor.
        Per compatibilita' con l'orchestrator, ritorna risultati dal JSON locale.
        """
        proj = self._projects.get(project_name)
        if not proj:
            return []

        # Ricerca locale semplice nei metadati (placeholder fino a migrazione Ingestor)
        # L'orchestrator usa questo per context gathering
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            client = self._get_qdrant_client()

            results = client.query_points(
                collection_name="codebase",
                query=[0.0] * 384,  # Dummy vector — filter-only search
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="project",
                            match=MatchValue(value=project_name),
                        )
                    ]
                ),
                limit=n_results,
            )

            return [
                {
                    "document": hit.payload.get("document", ""),
                    "metadata": {
                        k: v for k, v in hit.payload.items() if k != "document"
                    },
                    "distance": 1.0 - (hit.score or 0),
                }
                for hit in results.points
            ]
        except Exception:
            # Fallback: nessun risultato se Qdrant non e' pronto
            return []

    def mark_indexed(
        self, name: str, file_count: int, chunk_count: int
    ) -> None:
        """Segna un progetto come indicizzato."""
        proj = self._projects.get(name)
        if proj:
            proj.indexed = True
            proj.indexed_at = time.time()
            proj.file_count = file_count
            proj.chunk_count = chunk_count
            self._save_projects()

    async def sync_to_qdrant(self) -> int:
        """Sincronizza tutti i progetti nel registry JSON verso Qdrant.

        Ritorna il numero di progetti sincronizzati.
        """
        if not self._projects:
            return 0

        try:
            from qdrant_client.models import PointStruct
            provider = self._get_embedding_provider()
            client = self._get_qdrant_client()

            # Prepara testi per embedding batch
            texts = []
            projects_list = list(self._projects.values())
            for proj in projects_list:
                text = f"{proj.name} {proj.description} {' '.join(proj.tags)}"
                texts.append(text.strip())

            vectors = await provider.embed(texts)

            points = []
            for proj, vector in zip(projects_list, vectors):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"project:{proj.name}"))
                points.append(
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "name": proj.name,
                            "path": proj.path,
                            "slug": proj.slug,
                            "description": proj.description,
                            "tags": proj.tags,
                            "indexed": proj.indexed,
                            "indexed_at": proj.indexed_at,
                            "file_count": proj.file_count,
                            "chunk_count": proj.chunk_count,
                            "tenant_id": NoxenQdrantClient.DEFAULT_TENANT,
                            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    )
                )

            if points:
                client.upsert(collection_name="projects", points=points)

            logger.info("projects_synced_to_qdrant", count=len(points))
            return len(points)

        except Exception as e:
            logger.warning("projects_sync_error", error=str(e))
            return 0

    # ── Persistenza locale ─────────────────────────────────────────────

    def _load_projects(self) -> None:
        if PROJECTS_FILE.exists():
            try:
                data = json.loads(PROJECTS_FILE.read_text())
                for name, info in data.items():
                    self._projects[name] = ProjectInfo(**info)
                logger.info("projects_loaded", count=len(self._projects))
            except Exception as e:
                logger.warning("projects_load_error", error=str(e))

    def _save_projects(self) -> None:
        PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {name: asdict(proj) for name, proj in self._projects.items()}
        PROJECTS_FILE.write_text(json.dumps(data, indent=2))

    def to_dict(self) -> dict[str, Any]:
        """Esporta tutti i progetti come dizionario."""
        return {
            name: {
                "name": p.name,
                "path": p.path,
                "description": p.description,
                "tags": p.tags,
                "indexed": p.indexed,
                "indexed_at": p.indexed_at,
                "file_count": p.file_count,
                "chunk_count": p.chunk_count,
            }
            for name, p in self._projects.items()
        }
