# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
"""Noxen - Main Entry Point.

Start with:  python main.py
Or:          uvicorn main:app --host 0.0.0.0 --port 8400 --reload
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Ensure project root is on sys.path for skill imports
sys.path.insert(0, str(Path(__file__).parent))

from api.routes import health, skills, skills_v2, projects, bridge, chat, terminal, plugins, orchestrator, knowledge, research, notifications, events, admin, license as license_route
from config import settings
from core.container import NoxenContainer

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-24s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("noxen")

# ── DI Container ─────────────────────────────────────────────────────
# All singletons are created in explicit layer order.
# No forward references possible — each layer depends only on layers above it.
container = NoxenContainer()
container.initialize_sync()

# Module-level aliases for backward compatibility with existing code/tests
skill_manager = container.skill_manager
skill_installer = container.skill_installer
project_manager = container.project_manager
ingestor = container.ingestor
plugin_composer = container.plugin_composer
llm_provider = container.llm_provider
knowledge_base = container.knowledge_base
skill_router = container.skill_router
event_router = container.event_router
research_agent = container.research_agent
notification_engine = container.notification_engine
tenant_repository = container.tenant_repository
skill_repository = container.skill_repository
skill_board_reviewer = container.skill_board_reviewer
skill_updater = container.skill_updater
skill_usage_tracker = container.skill_usage_tracker
context_gatherer = container.context_gatherer
orch = container.orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: async init (Qdrant, embedding, routes). Shutdown: cleanup."""
    logger.info("=" * 60)
    logger.info("  Noxen starting up...")
    logger.info(f"  Skills dir : {settings.skills_dir}")
    logger.info(f"  Qdrant     : {settings.qdrant_url}")
    logger.info(f"  Progetti   : {len(container.project_manager.projects)}")
    logger.info("=" * 60)

    # Async initialization: Qdrant, embedding, route injection, bootstrap
    await container.initialize_async(app=app)

    yield

    # Shutdown (reverse order)
    logger.info("Noxen shutting down...")
    await container.shutdown()


# ── FastAPI App ───────────────────────────────────────────────────────
app = FastAPI(
    title="Noxen",
    description="Local AI Orchestrator for Multi-Repo Development",
    version="0.3.0",
    lifespan=lifespan,
)

# Static files & templates
app.mount("/static", StaticFiles(directory=str(settings.hub_root / "ui" / "static")), name="static")
templates = Jinja2Templates(directory=str(settings.hub_root / "ui" / "templates"))

# Routes
app.include_router(health.router)
app.include_router(skills.router)
app.include_router(projects.router)
app.include_router(bridge.router)
app.include_router(chat.router)
app.include_router(terminal.router)
app.include_router(plugins.router)
app.include_router(orchestrator.router)
app.include_router(knowledge.router)
app.include_router(research.router)
app.include_router(notifications.router)
app.include_router(skills_v2.router)
app.include_router(events.router)
app.include_router(admin.router)
app.include_router(admin.license_router)
app.include_router(license_route.router)


# ── Dashboard (served at root) ────────────────────────────────────────
@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "skills": container.skill_manager.skills,
        "installer": container.skill_installer,
        "projects": container.project_manager.projects,
        "ingestor": container.ingestor,
        "settings": container.settings,
        "plugin_composer": container.plugin_composer,
    })


# ── Run directly ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,  # Disabilitato: il Neural Engine scrive file che triggerano reload
    )
