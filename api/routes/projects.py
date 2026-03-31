"""API Routes: Gestione Progetti e Indicizzazione."""

from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.project_manager import ProjectManager
from core.ingestor import Ingestor
from core.tenants.auth import TenantContext, get_tenant_context

router = APIRouter(prefix="/api/projects", tags=["projects"])

_pm: ProjectManager | None = None
_ingestor: Ingestor | None = None


def init_router(pm: ProjectManager, ingestor: Ingestor) -> None:
    global _pm, _ingestor
    _pm = pm
    _ingestor = ingestor


def _get_pm() -> ProjectManager:
    if not _pm:
        raise HTTPException(503, "ProjectManager non inizializzato")
    return _pm


def _get_ingestor() -> Ingestor:
    if not _ingestor:
        raise HTTPException(503, "Ingestor non inizializzato")
    return _ingestor


class RegisterRequest(BaseModel):
    name: str
    path: str
    description: str = ""
    tags: list[str] = []


# ── CRUD ──────────────────────────────────────────────────────────────

@router.get("/")
async def list_projects(ctx: TenantContext = Depends(get_tenant_context)):
    """Elenca tutti i progetti registrati."""
    pm = _get_pm()
    return {"count": len(pm.projects), "projects": pm.to_dict()}


@router.post("/register")
async def register_project(
    req: RegisterRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Registra un nuovo progetto (microservizio, frontend, ecc.)."""
    pm = _get_pm()
    try:
        proj = pm.register(
            name=req.name,
            path=req.path,
            description=req.description,
            tags=req.tags,
        )
        return {"status": "registered", "project": asdict(proj)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{name}")
async def unregister_project(name: str):
    """Rimuovi un progetto e la sua collection."""
    pm = _get_pm()
    if pm.unregister(name):
        return {"status": "removed", "name": name}
    raise HTTPException(404, f"Progetto '{name}' non trovato")


@router.get("/{name}")
async def get_project(name: str):
    """Dettagli di un singolo progetto."""
    proj = _get_pm().get(name)
    if not proj:
        raise HTTPException(404, f"Progetto '{name}' non trovato")
    return asdict(proj)


# ── Indicizzazione ────────────────────────────────────────────────────

@router.post("/{name}/index")
async def start_indexing(name: str, ctx: TenantContext = Depends(get_tenant_context)):
    """Avvia l'indicizzazione in background per un progetto."""
    ing = _get_ingestor()
    try:
        progress = ing.start_indexing(name)
        return {
            "status": progress.status,
            "project": name,
            "message": "Indicizzazione avviata in background",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{name}/index/status")
async def get_indexing_status(name: str):
    """Stato dell'indicizzazione di un progetto."""
    ing = _get_ingestor()
    progress = ing.get_progress(name)
    if not progress:
        return {"project": name, "status": "never_indexed"}
    return {
        "project": name,
        "status": progress.status,
        "progress_pct": progress.progress_pct,
        "total_files": progress.total_files,
        "processed_files": progress.processed_files,
        "total_chunks": progress.total_chunks,
        "elapsed_seconds": progress.elapsed,
        "errors": progress.errors[:10],  # Limita errori in risposta
    }


@router.post("/{name}/index/cancel")
async def cancel_indexing(name: str):
    """Annulla l'indicizzazione in corso."""
    if _get_ingestor().cancel_indexing(name):
        return {"status": "cancelled", "project": name}
    return {"status": "not_running", "project": name}


@router.get("/index/status-all")
async def get_all_indexing_status():
    """Stato di tutte le indicizzazioni in corso."""
    ing = _get_ingestor()
    all_progress = ing.get_all_progress()
    return {
        name: {
            "status": p.status,
            "progress_pct": p.progress_pct,
            "total_chunks": p.total_chunks,
            "elapsed": p.elapsed,
        }
        for name, p in all_progress.items()
    }


# ── Query sulla Collection ────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    n_results: int = 5


@router.post("/{name}/search")
async def search_project(name: str, req: SearchRequest):
    """Cerca nel codebase indicizzato di un progetto."""
    pm = _get_pm()
    collection = pm.get_collection(name)
    if not collection:
        raise HTTPException(404, f"Progetto '{name}' non trovato o non indicizzato")

    try:
        results = collection.query(
            query_texts=[req.query],
            n_results=req.n_results,
        )
        return {
            "project": name,
            "query": req.query,
            "results": [
                {
                    "content": doc,
                    "metadata": meta,
                    "distance": dist,
                }
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                )
            ],
        }
    except Exception as e:
        raise HTTPException(500, f"Errore ricerca: {e}")
