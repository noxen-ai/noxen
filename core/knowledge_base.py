"""Noxen - Knowledge Base Manager.

Indicizza TUTTA la conoscenza interna (skills, agents, docs, comandi)
in Qdrant collection "skills", rendendola queryable semanticamente.

Fase 1 v0.3.0: migrato da ChromaDB a Qdrant + FastEmbedProvider.

Pipeline:
  1. Scansiona skills/ per file .md (SKILL.md, agents/*.md, README.md, docs/, etc.)
  2. Prepara embed_text (1500 chars) e store_text (5000 chars) per file
  3. Arricchisce con metadati (plugin, tipo, dominio, tags)
  4. Upsert incrementale (hash-based, skip se non cambiato)
  5. Query unificata cross-knowledge via Qdrant

Qdrant collection: "skills"
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import settings
from core.logger import get_logger

logger = get_logger("noxen.knowledge")

STATUS_FILE = settings.data_dir / "knowledge_status.json"

# Embedding strategy: 1 embedding per file (non per chunk)
EMBED_MAX_CHARS = 1500     # Testo usato per generare l'embedding
STORE_MAX_CHARS = 5000     # Testo salvato per retrieval (piu' contesto)
MIN_CONTENT_CHARS = 80     # File piu' corti vengono scartati
KB_BATCH_SIZE = 50         # Batch embedding — 50 docs = sweet spot


@dataclass
class KnowledgeStatus:
    """Stato dell'indicizzazione della knowledge base."""
    status: str = "idle"           # idle | scanning | indexing | done | error
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    skipped_unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    last_indexed_at: float = 0.0

    @property
    def progress_pct(self) -> float:
        if self.total_files == 0:
            return 0.0
        return round(self.processed_files / self.total_files * 100, 1)

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return round(end - self.started_at, 1) if self.started_at else 0.0


class KnowledgeBase:
    """Gestisce l'indicizzazione e la ricerca della knowledge base interna."""

    COLLECTION_NAME = "skills"

    def __init__(self, embedding_provider=None) -> None:
        self._embedding_provider = embedding_provider
        self._status = KnowledgeStatus()
        self._task: asyncio.Task | None = None
        self._hash_cache: dict[str, str] = {}  # file_path -> md5
        self._load_status()

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

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def status(self) -> KnowledgeStatus:
        return self._status

    def start_indexing(self, force: bool = False) -> KnowledgeStatus:
        """Avvia l'indicizzazione in background.

        Args:
            force: Se True, re-indicizza tutto. Se False, solo i file modificati.
        """
        if self._status.status in ("scanning", "indexing"):
            return self._status  # Gia' in corso

        self._status = KnowledgeStatus(
            status="scanning",
            started_at=time.time(),
        )

        if force:
            self._hash_cache.clear()

        self._task = asyncio.create_task(self._index_all())
        return self._status

    def cancel_indexing(self) -> bool:
        if self._task and not self._task.done():
            self._task.cancel()
            self._status.status = "cancelled"
            return True
        return False

    async def search(self, query: str, n_results: int = 10, where: dict | None = None) -> list[dict]:
        """Cerca nella knowledge base via Qdrant.

        Args:
            query: Testo da cercare
            n_results: Numero di risultati
            where: Filtro opzionale (es. {"type": "skill"})
        """
        try:
            provider = self._get_embedding_provider()
            query_vector = await provider.embed_single(query)
            client = self._get_qdrant_client()

            kwargs: dict[str, Any] = {
                "collection_name": self.COLLECTION_NAME,
                "query": query_vector,
                "limit": n_results,
            }

            # Converti filtro where in formato Qdrant
            if where:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                must_conditions = [
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in where.items()
                ]
                kwargs["query_filter"] = Filter(must=must_conditions)

            results = client.query_points(**kwargs)

            return [
                {
                    "document": hit.payload.get("document", ""),
                    "metadata": {
                        k: v for k, v in hit.payload.items()
                        if k not in ("document", "embed_text")
                    },
                    "distance": 1.0 - (hit.score or 0),
                }
                for hit in results.points
            ]
        except Exception as e:
            logger.warning("knowledge_search_error", error=str(e))
            return []

    def get_stats(self) -> dict[str, Any]:
        """Statistiche sulla knowledge base."""
        count = 0
        try:
            client = self._get_qdrant_client()
            info = client.get_collection(self.COLLECTION_NAME)
            count = info.points_count or 0
        except Exception:
            pass

        result = {
            "total_chunks": count,
            "status": self._status.status,
            "last_indexed_at": self._status.last_indexed_at,
            "total_files_indexed": self._status.total_files,
            "elapsed_seconds": self._status.elapsed if self._status.status in ("scanning", "indexing") else 0,
            "progress_pct": self._status.progress_pct if self._status.status in ("scanning", "indexing") else 100 if count > 0 else 0,
            "has_data": count > 0,
        }
        return result

    # ── Core Indexing ──────────────────────────────────────────────────

    async def _index_all(self) -> None:
        """Pipeline completa di indicizzazione knowledge base.

        Architettura:
        - FASE 1: File discovery (in executor)
        - FASE 2: File processing (read+hash+prepare) in un singolo thread
        - FASE 3: Embedding batch via FastEmbed + Qdrant upsert
        """
        try:
            skills_dir = settings.skills_dir
            if not skills_dir.exists():
                self._status.status = "error"
                self._status.errors.append("skills/ directory non trovata")
                return

            # FASE 1: Scopri file .md
            self._status.status = "scanning"
            loop = asyncio.get_event_loop()
            md_files = await loop.run_in_executor(None, self._discover_md_files, skills_dir)
            self._status.total_files = len(md_files)
            logger.info("knowledge_scan_complete", files=len(md_files))

            if not md_files:
                self._status.status = "done"
                self._status.finished_at = time.time()
                return

            # FASE 2+3: Processa file in bulk nel thread, poi flush batch
            self._status.status = "indexing"

            # Processa file: 1 embedding per file
            def process_file_batch(files: list[Path]) -> tuple[list[str], list[str], list[str], list[dict], int, int, list[str]]:
                ids: list[str] = []
                embed_texts: list[str] = []
                store_texts: list[str] = []
                metas: list[dict] = []
                skipped = 0
                processed = 0
                errors: list[str] = []

                for filepath in files:
                    try:
                        rel_path = str(filepath.relative_to(skills_dir))
                        file_hash = self._file_hash(filepath)

                        if rel_path in self._hash_cache and self._hash_cache[rel_path] == file_hash:
                            skipped += 1
                            processed += 1
                            continue

                        content = self._read_file(filepath)
                        if not content:
                            processed += 1
                            continue

                        result = self._prepare_document(content, rel_path)
                        if not result:
                            processed += 1
                            continue

                        embed_text, store_text = result
                        meta = self._extract_metadata(filepath, skills_dir, content)
                        meta["file_hash"] = file_hash

                        # ID deterministico basato sul path
                        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"kb:{rel_path}"))
                        ids.append(point_id)
                        embed_texts.append(embed_text)
                        store_texts.append(store_text)
                        metas.append(meta)

                        self._hash_cache[rel_path] = file_hash
                    except Exception as e:
                        errors.append(f"{filepath.name}: {str(e)[:100]}")

                    processed += 1

                return ids, embed_texts, store_texts, metas, skipped, processed, errors

            # Processa in mega-batch da 500 file alla volta
            PROCESS_BATCH = 500
            for start_idx in range(0, len(md_files), PROCESS_BATCH):
                file_batch = md_files[start_idx: start_idx + PROCESS_BATCH]

                # File processing in thread
                ids, embed_texts, store_texts, metas, skipped, processed, errors = await loop.run_in_executor(
                    None, process_file_batch, file_batch
                )

                self._status.skipped_unchanged += skipped
                self._status.processed_files += processed
                self._status.errors.extend(errors)

                # Embedding + upsert in sub-batch da KB_BATCH_SIZE
                for flush_start in range(0, len(ids), KB_BATCH_SIZE):
                    flush_end = flush_start + KB_BATCH_SIZE
                    b_ids = ids[flush_start:flush_end]
                    b_embed = embed_texts[flush_start:flush_end]
                    b_store = store_texts[flush_start:flush_end]
                    b_metas = metas[flush_start:flush_end]

                    await self._flush_batch(b_ids, b_embed, b_store, b_metas)
                    self._status.total_chunks += len(b_ids)

                # Log progress
                elapsed = time.time() - self._status.started_at
                rate = self._status.processed_files / elapsed if elapsed > 0 else 0
                remaining = self._status.total_files - self._status.processed_files
                eta_min = remaining / rate / 60 if rate > 0 else 0
                logger.info(
                    "knowledge_indexing_progress",
                    processed=self._status.processed_files,
                    total=self._status.total_files,
                    chunks=self._status.total_chunks,
                    rate=f"{rate:.1f}",
                    eta_min=f"{eta_min:.1f}",
                )

                await asyncio.sleep(0)
                if self._status.processed_files % 2000 == 0:
                    self._save_status()

            self._status.status = "done"
            self._status.finished_at = time.time()
            self._status.last_indexed_at = time.time()
            self._save_status()

            logger.info(
                "knowledge_indexing_complete",
                files=self._status.processed_files,
                chunks=self._status.total_chunks,
                skipped=self._status.skipped_unchanged,
                elapsed=self._status.elapsed,
            )

        except asyncio.CancelledError:
            self._status.status = "cancelled"
            logger.info("knowledge_indexing_cancelled")
        except Exception as e:
            self._status.status = "error"
            self._status.errors.append(str(e))
            logger.exception("knowledge_indexing_error")

    async def _flush_batch(
        self, ids: list[str], embed_texts: list[str],
        store_texts: list[str], metadatas: list[dict]
    ) -> None:
        """Embedding via FastEmbed + upsert in Qdrant."""
        from qdrant_client.models import PointStruct

        t0 = time.time()

        # 1. Genera embeddings
        provider = self._get_embedding_provider()
        embeddings = await provider.embed(embed_texts)
        t_embed = time.time() - t0

        # 2. Prepara punti Qdrant
        points = []
        for point_id, vector, store_text, meta in zip(ids, embeddings, store_texts, metadatas):
            from core.qdrant_client import NoxenQdrantClient
            payload = {**meta, "document": store_text, "tenant_id": NoxenQdrantClient.DEFAULT_TENANT}
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        # 3. Upsert
        t1 = time.time()
        client = self._get_qdrant_client()
        client.upsert(collection_name=self.COLLECTION_NAME, points=points)
        t_upsert = time.time() - t1

        rate = len(ids) / t_embed if t_embed > 0 else 0
        logger.info(
            "knowledge_flush",
            docs=len(ids),
            embed_s=f"{t_embed:.1f}",
            upsert_s=f"{t_upsert:.1f}",
            rate=f"{rate:.0f}",
        )

    # ── File Discovery ─────────────────────────────────────────────────

    def _discover_md_files(self, skills_dir: Path) -> list[Path]:
        """Trova file .md ad alto valore nella directory skills.

        Strategia a 2 tier:
          Tier 1 (sempre): SKILL.md, CLAUDE.md, agents/*.md, commands/*.md
          Tier 2 (se >1KB): README.md dei repo root, docs/*, guide, reference
        """
        result: list[Path] = []
        skip_dirs = {"node_modules", "__pycache__", ".git", "dist", "build",
                     ".venv", "vendor", ".next", ".nuxt"}

        for f in skills_dir.rglob("*.md"):
            if not f.is_file():
                continue

            parts = f.relative_to(skills_dir).parts

            if any(p.startswith(".") or p.lower() in skip_dirs for p in parts):
                continue

            try:
                size = f.stat().st_size
                if size > 150 * 1024 or size < 200:
                    continue
            except OSError:
                continue

            name = f.name
            name_upper = name.upper()
            parts_lower = [p.lower() for p in parts]

            # Tier 1: file di skill/agente/comando
            is_tier1 = (
                name_upper in ("SKILL.MD", "CLAUDE.MD")
                or any("agents" in p for p in parts_lower)
                or any("commands" in p for p in parts_lower)
            )

            if is_tier1:
                result.append(f)
                continue

            # Tier 2: README, docs, guide
            is_tier2 = (
                name_upper == "README.MD"
                or any(p in ("docs", "documentation", "guides", "guide") for p in parts_lower)
            )

            if is_tier2 and size >= 1000:
                if name_upper == "README.MD" and len(parts) > 3:
                    continue
                result.append(f)
                continue

            # Tier 3: altri file .md
            if size >= 2000:
                if name in ("template.md", "workflows.md", "standards.md",
                           "index.md", "one-pager.md", "guest-insights.md"):
                    continue
                result.append(f)

        return sorted(result)

    # ── Metadata Extraction ────────────────────────────────────────────

    def _extract_metadata(self, filepath: Path, skills_dir: Path, content: str) -> dict[str, str]:
        """Estrai metadati ricchi dal path e contenuto del file."""
        rel = filepath.relative_to(skills_dir)
        parts = rel.parts

        fname = filepath.name.upper()
        if fname == "SKILL.MD":
            file_type = "skill"
        elif fname == "CLAUDE.MD":
            file_type = "claude_config"
        elif fname == "README.MD":
            file_type = "readme"
        elif "agents" in str(rel).lower():
            file_type = "agent"
        elif "commands" in str(rel).lower():
            file_type = "command"
        else:
            file_type = "docs"

        plugin = parts[0] if parts else "unknown"
        sub_path = "/".join(parts[1:-1]) if len(parts) > 2 else ""

        name = filepath.stem
        description = ""
        tags_str = ""
        domain = ""

        fm = self._parse_frontmatter(content)
        if fm:
            name = fm.get("name", name)
            description = fm.get("description", "")[:300]
            tags = fm.get("tags", [])
            if isinstance(tags, list):
                tags_str = ",".join(str(t) for t in tags)
            elif isinstance(tags, str):
                tags_str = tags
            domain = fm.get("category", fm.get("domain", ""))

        meta = {
            "type": file_type,
            "plugin": plugin,
            "sub_path": sub_path,
            "file_path": str(rel),
            "name": name,
            "description": description[:300],
        }

        if tags_str:
            meta["tags"] = tags_str[:200]
        if domain:
            meta["domain"] = str(domain)[:50]

        return meta

    @staticmethod
    def _parse_frontmatter(content: str) -> dict | None:
        """Estrai frontmatter YAML dal contenuto markdown."""
        if not content.startswith("---"):
            return None

        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return None

        try:
            fm: dict[str, Any] = {}
            for line in match.group(1).split("\n"):
                line = line.strip()
                if ":" in line and not line.startswith("#"):
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if val.startswith("[") and val.endswith("]"):
                        items = val[1:-1].split(",")
                        fm[key] = [i.strip().strip('"').strip("'") for i in items if i.strip()]
                    else:
                        fm[key] = val
            return fm if fm else None
        except Exception:
            return None

    # ── Document Preparation ──────────────────────────────────────────

    def _prepare_document(self, content: str, rel_path: str) -> tuple[str, str] | None:
        """Prepara un singolo documento per l'indicizzazione.

        Returns:
            (embed_text, store_text) — testo per embedding e testo per retrieval
            None se il file e' troppo corto/vuoto
        """
        body = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", content, flags=re.DOTALL).strip()

        if not body or len(body) < MIN_CONTENT_CHARS:
            return None

        header = f"[{rel_path}]\n"
        embed_text = header + body[:EMBED_MAX_CHARS]
        store_text = header + body[:STORE_MAX_CHARS]

        return embed_text, store_text

    # ── Utilities ──────────────────────────────────────────────────────

    @staticmethod
    def _file_hash(filepath: Path) -> str:
        h = hashlib.md5()
        h.update(filepath.read_bytes())
        return h.hexdigest()[:12]

    @staticmethod
    def _read_file(filepath: Path) -> str | None:
        try:
            return filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def _load_status(self) -> None:
        if STATUS_FILE.exists():
            try:
                data = json.loads(STATUS_FILE.read_text())
                self._status.last_indexed_at = data.get("last_indexed_at", 0)
                self._status.total_files = data.get("total_files", 0)
                self._status.total_chunks = data.get("total_chunks", 0)
                self._hash_cache = data.get("hash_cache", {})
            except Exception:
                pass

    def _save_status(self) -> None:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_indexed_at": self._status.last_indexed_at,
            "total_files": self._status.total_files,
            "total_chunks": self._status.total_chunks,
            "hash_cache": self._hash_cache,
        }
        STATUS_FILE.write_text(json.dumps(data, indent=2))
