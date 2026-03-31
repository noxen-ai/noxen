"""API Routes: Knowledge Base (Contesto Interno RAG)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.knowledge_base import KnowledgeBase
from core.tenants.auth import TenantContext, get_tenant_context

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_kb: KnowledgeBase | None = None


def init_router(knowledge_base: KnowledgeBase) -> None:
    global _kb
    _kb = knowledge_base


def _get_kb() -> KnowledgeBase:
    if not _kb:
        raise HTTPException(503, "KnowledgeBase non inizializzata")
    return _kb


class SearchRequest(BaseModel):
    query: str
    n_results: int = 10
    type: str = ""       # Filtro: skill, agent, command, docs, readme, claude_config
    plugin: str = ""     # Filtro per plugin/repo
    domain: str = ""     # Filtro per dominio


# ── Indicizzazione ───────────────────────────────────────────────────

@router.post("/ingest")
async def start_ingestion(
    force: bool = False,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Avvia l'indicizzazione della knowledge base.

    Con force=True re-indicizza tutto, altrimenti solo i file modificati.
    """
    kb = _get_kb()
    status = kb.start_indexing(force=force)
    return {
        "status": status.status,
        "total_files": status.total_files,
        "message": "Indicizzazione avviata in background",
    }


@router.get("/status")
async def get_status():
    """Stato corrente della knowledge base e dell'indicizzazione."""
    kb = _get_kb()
    stats = kb.get_stats()
    s = kb.status

    return {
        **stats,
        "indexing": {
            "status": s.status,
            "progress_pct": s.progress_pct,
            "processed_files": s.processed_files,
            "total_files": s.total_files,
            "total_chunks": s.total_chunks,
            "skipped_unchanged": s.skipped_unchanged,
            "elapsed": s.elapsed,
            "errors": s.errors[:10],  # Ultimi 10 errori
        },
    }


@router.post("/cancel")
async def cancel_ingestion():
    """Annulla l'indicizzazione in corso."""
    kb = _get_kb()
    cancelled = kb.cancel_indexing()
    return {"cancelled": cancelled}


# ── Ricerca ──────────────────────────────────────────────────────────

@router.post("/search")
async def search_knowledge(
    req: SearchRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Cerca nella knowledge base.

    Filtri opzionali:
    - type: skill, agent, command, docs, readme
    - plugin: nome del plugin/repo
    - domain: dominio di conoscenza
    """
    kb = _get_kb()

    where = {}
    if req.type:
        where["type"] = req.type
    if req.plugin:
        where["plugin"] = req.plugin
    if req.domain:
        where["domain"] = req.domain

    results = await kb.search(
        query=req.query,
        n_results=req.n_results,
        where=where if where else None,
    )

    return {
        "query": req.query,
        "count": len(results),
        "results": [
            {
                "content": r["document"][:500],
                "full_content": r["document"],
                "metadata": r["metadata"],
                "distance": round(r["distance"], 4),
            }
            for r in results
        ],
    }
