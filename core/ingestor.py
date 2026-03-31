"""Noxen - Multi-Repo Ingestor.

Indicizza codebase di grandi dimensioni in Qdrant senza saturare i 16GB di RAM.

Fase 1 v0.3.0: migrato da ChromaDB a Qdrant collection "codebase" + FastEmbed.

Strategie di ottimizzazione:
  1. Rispetta .gitignore + pattern globali (node_modules, __pycache__, ecc.)
  2. Chunking con overlap per contesto semantico
  3. Batch insert in Qdrant (evita picchi di memoria)
  4. Stream processing: un file alla volta, mai tutto in memoria
  5. Filtro per dimensione file (skip binari e file enormi)
  6. Yield-based generator per file discovery
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

import chardet
from gitignore_parser import parse_gitignore

from config import settings
from core.logger import get_logger
from core.qdrant_client import NoxenQdrantClient

logger = get_logger("noxen.ingestor")

# Estensioni di codice sorgente che vale la pena indicizzare
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".java", ".kt", ".go", ".rs", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".cs",
    ".html", ".css", ".scss", ".sass", ".less",
    ".sql", ".graphql", ".gql",
    ".yaml", ".yml", ".toml", ".json", ".xml",
    ".md", ".rst", ".txt",
    ".sh", ".bash", ".zsh", ".fish",
    ".dockerfile", ".tf", ".hcl",
    ".env.example", ".gitignore", ".editorconfig",
}

# Nomi di file sempre utili (senza estensione)
IMPORTANT_FILENAMES = {
    "Dockerfile", "Makefile", "Procfile", "Gemfile",
    "Rakefile", "Vagrantfile", "Taskfile",
    "docker-compose.yml", "docker-compose.yaml",
}

MAX_FILE_SIZE = settings.max_file_size_mb * 1024 * 1024
COLLECTION_NAME = "codebase"


@dataclass
class ChunkInfo:
    """Un chunk di codice pronto per Qdrant."""
    content: str
    file_path: str        # Relativo alla root del progetto
    start_line: int
    end_line: int
    language: str
    file_hash: str


@dataclass
class IndexingProgress:
    """Stato dell'indicizzazione in corso."""
    project_name: str
    status: str = "idle"   # idle | scanning | indexing | done | error
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def progress_pct(self) -> float:
        if self.total_files == 0:
            return 0.0
        return round(self.processed_files / self.total_files * 100, 1)

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return round(end - self.started_at, 1) if self.started_at else 0.0


class Ingestor:
    """Indicizza codebase in Qdrant in modo asincrono e RAM-safe."""

    def __init__(self, project_manager) -> None:
        self._pm = project_manager
        self._progress: dict[str, IndexingProgress] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._embedding_provider = None  # Lazy init

    # ── Embedding & Qdrant ─────────────────────────────────────────────

    def _get_embedding_provider(self):
        """Lazy-load del FastEmbedProvider."""
        if self._embedding_provider is None:
            from core.embedding_provider import get_embedding_provider
            self._embedding_provider = get_embedding_provider("fastembed")
        return self._embedding_provider

    def _get_qdrant_client(self):
        """Ottieni il QdrantClient dal singleton."""
        from core.qdrant_client import NoxenQdrantClient
        return NoxenQdrantClient.get_instance().client

    # ── Public API ─────────────────────────────────────────────────────

    def get_progress(self, project_name: str) -> IndexingProgress | None:
        return self._progress.get(project_name)

    def get_all_progress(self) -> dict[str, IndexingProgress]:
        return dict(self._progress)

    def start_indexing(self, project_name: str) -> IndexingProgress:
        """Avvia l'indicizzazione in background. Non blocca."""
        proj = self._pm.get(project_name)
        if not proj:
            raise ValueError(f"Progetto '{project_name}' non registrato")

        # Se gia' in corso, ritorna lo stato
        existing = self._progress.get(project_name)
        if existing and existing.status in ("scanning", "indexing"):
            return existing

        progress = IndexingProgress(
            project_name=project_name,
            status="scanning",
            started_at=time.time(),
        )
        self._progress[project_name] = progress

        # Lancia il task in background
        task = asyncio.create_task(self._index_project(project_name, progress))
        self._tasks[project_name] = task
        return progress

    def cancel_indexing(self, project_name: str) -> bool:
        """Annulla l'indicizzazione in corso."""
        task = self._tasks.get(project_name)
        if task and not task.done():
            task.cancel()
            progress = self._progress.get(project_name)
            if progress:
                progress.status = "cancelled"
            return True
        return False

    async def search_code(
        self, project_name: str, query: str, n_results: int = 5
    ) -> list[dict]:
        """Cerca nel codice indicizzato di un progetto via Qdrant.

        Args:
            project_name: Nome del progetto.
            query: Testo di ricerca.
            n_results: Numero massimo di risultati.

        Returns:
            Lista di dict con content, file_path, lines, language, score.
        """
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            provider = self._get_embedding_provider()
            query_vector = await provider.embed_single(query)
            client = self._get_qdrant_client()

            results = client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
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
                    "content": hit.payload.get("document", "")[:800],
                    "file_path": hit.payload.get("file_path", ""),
                    "lines": f"{hit.payload.get('start_line', '?')}-{hit.payload.get('end_line', '?')}",
                    "language": hit.payload.get("language", ""),
                    "score": hit.score,
                }
                for hit in results.points
            ]
        except Exception as e:
            logger.warning("code_search_error", project=project_name, error=str(e))
            return []

    # ── Core Indexing Logic ────────────────────────────────────────────

    async def _index_project(
        self, project_name: str, progress: IndexingProgress
    ) -> None:
        """Pipeline completa di indicizzazione."""
        try:
            proj = self._pm.get(project_name)
            if not proj:
                progress.status = "error"
                progress.errors.append("Progetto non trovato")
                return

            root = Path(proj.path)

            # FASE 1: Scan file (rispetta .gitignore)
            progress.status = "scanning"
            files = await self._discover_files(root)
            progress.total_files = len(files)
            logger.info("ingestor_scan_complete", project=project_name, files=len(files))

            if not files:
                progress.status = "done"
                progress.finished_at = time.time()
                self._pm.mark_indexed(project_name, 0, 0)
                return

            # FASE 2: Chunk e inserisci in batch
            progress.status = "indexing"
            batch_ids: list[str] = []
            batch_texts: list[str] = []
            batch_payloads: list[dict] = []

            for filepath in files:
                try:
                    async for chunk in self._chunk_file(filepath, root):
                        # ID deterministico per upsert idempotente
                        point_id = str(uuid.uuid5(
                            uuid.NAMESPACE_DNS,
                            f"code:{project_name}:{chunk.file_path}:{chunk.start_line}"
                        ))
                        batch_ids.append(point_id)
                        batch_texts.append(chunk.content)
                        batch_payloads.append({
                            "document": chunk.content,
                            "file_path": chunk.file_path,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "language": chunk.language,
                            "file_hash": chunk.file_hash,
                            "project": project_name,
                            "tenant_id": NoxenQdrantClient.DEFAULT_TENANT,
                        })

                        # Flush batch
                        if len(batch_ids) >= settings.batch_size:
                            await self._flush_batch(
                                batch_ids, batch_texts, batch_payloads
                            )
                            progress.total_chunks += len(batch_ids)
                            batch_ids, batch_texts, batch_payloads = [], [], []

                except Exception as e:
                    progress.errors.append(f"{filepath}: {e}")
                    logger.warning("ingestor_file_error", file=str(filepath), error=str(e))

                progress.processed_files += 1

                # Yield al loop ogni 10 file per non bloccare
                if progress.processed_files % 10 == 0:
                    await asyncio.sleep(0)

            # Flush ultimo batch
            if batch_ids:
                await self._flush_batch(batch_ids, batch_texts, batch_payloads)
                progress.total_chunks += len(batch_ids)

            progress.status = "done"
            progress.finished_at = time.time()
            self._pm.mark_indexed(
                project_name, progress.processed_files, progress.total_chunks
            )
            logger.info(
                "ingestor_complete",
                project=project_name,
                files=progress.processed_files,
                chunks=progress.total_chunks,
                elapsed=progress.elapsed,
            )

        except asyncio.CancelledError:
            progress.status = "cancelled"
            logger.info("ingestor_cancelled", project=project_name)
        except Exception as e:
            progress.status = "error"
            progress.errors.append(str(e))
            logger.exception("ingestor_error", project=project_name)

    # ── File Discovery ─────────────────────────────────────────────────

    async def _discover_files(self, root: Path) -> list[Path]:
        """Trova tutti i file indicizzabili rispettando .gitignore."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._scan_dir_sync, root)

    def _scan_dir_sync(self, root: Path) -> list[Path]:
        """Scan sincrono (eseguito in thread) con supporto .gitignore."""
        gitignore_path = root / ".gitignore"
        gitignore_match = None
        if gitignore_path.exists():
            try:
                gitignore_match = parse_gitignore(gitignore_path)
            except Exception:
                pass

        result: list[Path] = []
        global_ignore = set(settings.global_ignore)

        for item in root.rglob("*"):
            if not item.is_file():
                continue

            # Skip per pattern globali
            parts = item.relative_to(root).parts
            if any(part in global_ignore for part in parts):
                continue

            # Skip per .gitignore
            if gitignore_match and gitignore_match(str(item)):
                continue

            # Skip file troppo grandi
            try:
                if item.stat().st_size > MAX_FILE_SIZE:
                    continue
                if item.stat().st_size == 0:
                    continue
            except OSError:
                continue

            # Solo file sorgente o file importanti
            if item.suffix.lower() in SOURCE_EXTENSIONS or item.name in IMPORTANT_FILENAMES:
                result.append(item)

        return sorted(result)

    # ── Chunking ───────────────────────────────────────────────────────

    async def _chunk_file(
        self, filepath: Path, root: Path
    ) -> AsyncGenerator[ChunkInfo, None]:
        """Leggi un file e producilo in chunk con overlap."""
        loop = asyncio.get_event_loop()
        content = await loop.run_in_executor(
            None, self._read_file_safe, filepath
        )
        if not content:
            return

        rel_path = str(filepath.relative_to(root))
        lang = self._detect_language(filepath)
        file_hash = hashlib.md5(content.encode()).hexdigest()[:12]

        lines = content.split("\n")
        chunk_size = settings.chunk_size
        overlap = settings.chunk_overlap

        # Chunk per righe (non per caratteri) — piu' semantico
        i = 0
        while i < len(lines):
            end = min(i + chunk_size, len(lines))
            chunk_lines = lines[i:end]
            chunk_text = "\n".join(chunk_lines).strip()

            if chunk_text:
                header = f"# File: {rel_path} (righe {i+1}-{end})\n"
                yield ChunkInfo(
                    content=header + chunk_text,
                    file_path=rel_path,
                    start_line=i + 1,
                    end_line=end,
                    language=lang,
                    file_hash=file_hash,
                )

            # Avanza con overlap
            i += chunk_size - overlap
            if i >= len(lines):
                break

    @staticmethod
    def _read_file_safe(filepath: Path) -> str | None:
        """Leggi un file gestendo encoding diversi."""
        try:
            raw = filepath.read_bytes()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                pass
            detected = chardet.detect(raw)
            enc = detected.get("encoding", "utf-8") or "utf-8"
            return raw.decode(enc, errors="replace")
        except Exception:
            return None

    @staticmethod
    def _detect_language(filepath: Path) -> str:
        """Rileva il linguaggio dal suffisso del file."""
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".tsx": "typescript", ".jsx": "javascript", ".vue": "vue",
            ".java": "java", ".kt": "kotlin", ".go": "go",
            ".rs": "rust", ".rb": "ruby", ".php": "php",
            ".c": "c", ".cpp": "cpp", ".cs": "csharp",
            ".html": "html", ".css": "css", ".scss": "scss",
            ".sql": "sql", ".sh": "shell", ".yaml": "yaml",
            ".yml": "yaml", ".json": "json", ".xml": "xml",
            ".md": "markdown", ".toml": "toml", ".tf": "terraform",
        }
        return ext_map.get(filepath.suffix.lower(), "text")

    # ── Qdrant Batch Insert ───────────────────────────────────────────

    async def _flush_batch(
        self,
        ids: list[str],
        texts: list[str],
        payloads: list[dict],
    ) -> None:
        """Embedding via FastEmbed + upsert in Qdrant."""
        from qdrant_client.models import PointStruct

        provider = self._get_embedding_provider()
        embeddings = await provider.embed(texts)
        client = self._get_qdrant_client()

        points = [
            PointStruct(id=point_id, vector=vector, payload=payload)
            for point_id, vector, payload in zip(ids, embeddings, payloads)
        ]

        client.upsert(collection_name=COLLECTION_NAME, points=points)
