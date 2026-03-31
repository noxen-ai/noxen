"""API Routes: Skill Management + Installer."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.skill_manager import SkillManager
from core.skill_installer import SkillInstaller

router = APIRouter(prefix="/api/skills", tags=["skills"])

_manager: SkillManager | None = None
_installer: SkillInstaller | None = None


def init_router(manager: SkillManager, installer: SkillInstaller) -> None:
    global _manager, _installer
    _manager = manager
    _installer = installer


def _get_manager() -> SkillManager:
    if not _manager:
        raise HTTPException(503, "SkillManager non inizializzato")
    return _manager


def _get_installer() -> SkillInstaller:
    if not _installer:
        raise HTTPException(503, "SkillInstaller non inizializzato")
    return _installer


class ExecuteRequest(BaseModel):
    skill_name: str
    params: dict = {}


class AnalyzeRequest(BaseModel):
    url: str              # GitHub URL o user/repo


class InstallRequest(BaseModel):
    url: str              # GitHub URL, user/repo, o raw URL
    group: str = ""       # Gruppo/categoria (opzionale)
    priority: int = 3     # Execution priority (1=orchestrator, 5=background)


# ── CRUD Skills ───────────────────────────────────────────────────────

@router.get("/")
async def list_skills():
    """Elenca tutte le skill caricate con metadati."""
    mgr = _get_manager()
    return {
        "count": mgr.active_count,
        "skills": [
            {
                "name": s.metadata.name,
                "description": s.metadata.description,
                "version": s.metadata.version,
                "category": s.metadata.category.value,
                "tags": s.metadata.tags,
                "author": s.metadata.author,
                "auto_approve": s.metadata.auto_approve,
                "priority": s.metadata.priority,
                "depends_on": s.metadata.depends_on,
            }
            for s in mgr.skills.values()
        ],
    }


@router.get("/tools")
async def get_tool_schemas():
    """Esporta tutte le skill come tool OpenAI-compatible."""
    return _get_manager().get_tool_schemas()


@router.post("/execute")
async def execute_skill(req: ExecuteRequest):
    """Esegui una skill per nome con i parametri dati."""
    result = await _get_manager().execute_skill(skill_name=req.skill_name, **req.params)
    if not result.success:
        raise HTTPException(400, detail=result.error)
    return {"success": True, "data": result.data, "metadata": result.metadata}


@router.post("/reload/{skill_name}")
async def reload_skill(skill_name: str):
    """Hot-reload di una skill specifica."""
    status = await _get_manager().reload_skill(skill_name)
    return {"skill": skill_name, "status": status}


@router.post("/reload-all")
async def reload_all_skills():
    """Scarica tutte le skill e riscansiona la directory."""
    mgr = _get_manager()
    await mgr.unload_all()
    report = await mgr.load_all()
    return {"reloaded": report, "active_count": mgr.active_count}


# ── Analisi Pre-Installazione ────────────────────────────────────────

@router.post("/analyze")
async def analyze_repo(req: AnalyzeRequest):
    """Analizza un repo GitHub prima dell'installazione.

    Restituisce un report con: indicatori skill, confidenza, raccomandazione.
    L'utente puo' poi decidere se procedere con l'installazione.
    """
    installer = _get_installer()
    from dataclasses import asdict
    analysis = await installer.analyze_repo(req.url)
    return asdict(analysis)


# ── Installazione da GitHub ───────────────────────────────────────────

@router.post("/install")
async def install_skill(req: InstallRequest):
    """Installa una skill da GitHub URL o shorthand."""
    installer = _get_installer()
    url = req.url.strip()

    try:
        # Detecta se e' un URL raw (file singolo .py)
        if url.endswith(".py") or "raw.githubusercontent.com" in url or "gist.github" in url:
            info = await installer.install_from_raw_url(url, group=req.group, priority=req.priority)
        else:
            info = await installer.install_from_github(url, group=req.group, priority=req.priority)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(500, detail=str(e))

    # Ricarica le skill dopo l'installazione
    mgr = _get_manager()
    await mgr.unload_all()
    report = await mgr.load_all()

    return {
        "status": "installed",
        "skill": {
            "name": info.name,
            "source": info.source,
            "group": info.group,
            "priority": info.priority,
            "path": info.install_path,
        },
        "loaded_skills": report,
        "active_count": mgr.active_count,
    }


@router.post("/update/{skill_name}")
async def update_skill(skill_name: str):
    """Aggiorna una skill installata (git pull)."""
    installer = _get_installer()
    result = await installer.update(skill_name)

    # Ricarica dopo update
    mgr = _get_manager()
    await mgr.unload_all()
    await mgr.load_all()

    return {"skill": skill_name, "result": result, "active_count": mgr.active_count}


@router.delete("/uninstall/{skill_name}")
async def uninstall_skill(skill_name: str):
    """Disinstalla una skill."""
    installer = _get_installer()
    if not installer.uninstall(skill_name):
        raise HTTPException(404, detail=f"Skill '{skill_name}' non trovata")

    # Ricarica dopo rimozione
    mgr = _get_manager()
    await mgr.unload_all()
    await mgr.load_all()

    return {"status": "uninstalled", "skill": skill_name, "active_count": mgr.active_count}


# ── Gerarchia e Registro ──────────────────────────────────────────────

@router.get("/hierarchy")
async def get_hierarchy():
    """Ritorna la gerarchia skill organizzata per gruppi."""
    return _get_installer().get_hierarchy()


@router.get("/installed")
async def list_installed():
    """Elenca le skill installate da GitHub."""
    installer = _get_installer()
    return {
        "count": len(installer.installed),
        "skills": [
            {
                "name": info.name,
                "source": info.source,
                "group": info.group,
                "priority": info.priority,
                "path": info.install_path,
                "installed_at": info.installed_at,
            }
            for info in installer.installed.values()
        ],
    }


@router.get("/install-log")
async def get_install_log():
    """Log delle installazioni (ultime 100)."""
    installer = _get_installer()
    return {"log": installer.install_log}


@router.get("/priority-order")
async def get_priority_order():
    """Ritorna le skill ordinate per priorita' di esecuzione."""
    return _get_manager().get_by_priority()


@router.post("/pipeline")
async def run_pipeline(params: dict = {}):
    """Esegui tutte le skill in ordine di priorita' (orchestrator first)."""
    results = await _get_manager().run_pipeline(**params)
    return {
        "pipeline": [
            {"skill": name, "success": r.success, "data": r.data, "error": r.error}
            for name, r in results.items()
        ]
    }
