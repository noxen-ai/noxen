"""API Routes: Claude Code Plugin Management."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.plugin_composer import PluginComposer

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_composer: PluginComposer | None = None


def init_router(composer: PluginComposer) -> None:
    global _composer
    _composer = composer


def _get_composer() -> PluginComposer:
    if not _composer:
        raise HTTPException(503, "PluginComposer non inizializzato")
    return _composer


class ComposeRequest(BaseModel):
    name: str
    description: str
    selected_skills: list[dict]  # [{"plugin": ..., "skill": ..., "priority": ...}]
    owner_name: str = "Noxen"
    version: str = "1.0.0"


# ── Plugin Discovery ─────────────────────────────────────────────────

@router.get("/")
async def list_plugins():
    """Elenca tutti i plugin Claude Code trovati."""
    composer = _get_composer()
    return {
        "count": len(composer.plugins),
        "plugins": composer.get_plugin_summary(),
    }


@router.get("/stats")
async def plugin_stats():
    """Statistiche aggregate: totale skills, commands, agents."""
    composer = _get_composer()
    total_skills = 0
    total_commands = 0
    total_agents = 0
    for plugin in composer.plugins.values():
        total_skills += len(plugin.skills)
        total_commands += len(plugin.commands)
        total_agents += len(plugin.agents)
    return {
        "total_plugins": len(composer.plugins),
        "total_skills": total_skills,
        "total_commands": total_commands,
        "total_agents": total_agents,
    }


@router.post("/scan")
async def scan_plugins():
    """Riscansiona la directory skills per plugin Claude Code."""
    composer = _get_composer()
    plugins = composer.scan_all()
    return {
        "scanned": len(plugins),
        "plugins": composer.get_plugin_summary(),
    }


@router.get("/skills")
async def list_all_skills():
    """Lista piatta di tutte le skill da tutti i plugin."""
    composer = _get_composer()
    skills = composer.get_all_skills()
    return {"count": len(skills), "skills": skills}


@router.get("/agents")
async def list_all_agents():
    """Lista piatta di tutti gli agenti da tutti i plugin, con contenuto."""
    composer = _get_composer()
    agents = []
    for pname, plugin in composer.plugins.items():
        for a in plugin.agents:
            # Leggi contenuto del file agente se disponibile
            content = ""
            if a.content_file:
                from pathlib import Path
                fp = Path(a.content_file)
                if fp.exists():
                    try:
                        raw = fp.read_text(encoding="utf-8", errors="replace")
                        # Rimuovi frontmatter YAML
                        import re
                        raw = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", raw, flags=re.DOTALL)
                        content = raw.strip()
                    except Exception:
                        pass

            agents.append({
                "name": a.name,
                "description": a.description,
                "plugin": pname,
                "plugin_owner": plugin.owner,
                "path": a.path,
                "content": content,
            })
    return {"count": len(agents), "agents": agents}


@router.get("/{plugin_name}")
async def get_plugin_detail(plugin_name: str):
    """Dettaglio di un plugin specifico."""
    composer = _get_composer()
    plugin = composer.plugins.get(plugin_name)
    if not plugin:
        raise HTTPException(404, f"Plugin '{plugin_name}' non trovato")

    return {
        "name": plugin.name,
        "description": plugin.description,
        "version": plugin.version,
        "owner": plugin.owner,
        "source_repo": plugin.source_repo,
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "tags": s.tags,
                "group": s.plugin_group,
                "path": s.path,
                "type": s.skill_type,
            }
            for s in plugin.skills
        ],
        "commands": [
            {"name": c.name, "description": c.description, "path": c.path}
            for c in plugin.commands
        ],
        "agents": [
            {"name": a.name, "description": a.description, "path": a.path}
            for a in plugin.agents
        ],
    }


# ── Plugin Composition ───────────────────────────────────────────────

@router.post("/compose")
async def compose_plugin(req: ComposeRequest):
    """Componi un nuovo plugin Claude Code da skill selezionate."""
    composer = _get_composer()

    if not req.selected_skills:
        raise HTTPException(400, "Nessuna skill selezionata")

    try:
        output_path = composer.compose_plugin(
            name=req.name,
            description=req.description,
            selected_skills=req.selected_skills,
            owner_name=req.owner_name,
            version=req.version,
        )
    except Exception as e:
        raise HTTPException(500, f"Errore composizione: {e}")

    return {
        "status": "composed",
        "plugin_name": req.name,
        "output_path": str(output_path),
        "skills_count": len(req.selected_skills),
    }


@router.get("/composed")
async def list_composed():
    """Lista i plugin composti."""
    from config import settings
    output_dir = settings.data_dir / "composed_plugins"
    if not output_dir.exists():
        return {"count": 0, "plugins": []}

    composed = []
    for d in sorted(output_dir.iterdir()):
        if d.is_dir():
            pjson = d / ".claude-plugin" / "plugin.json"
            if pjson.exists():
                import json
                manifest = json.loads(pjson.read_text())
                composed.append({
                    "name": manifest.get("name", d.name),
                    "description": manifest.get("metadata", {}).get("description", ""),
                    "version": manifest.get("metadata", {}).get("version", ""),
                    "path": str(d),
                })

    return {"count": len(composed), "plugins": composed}
