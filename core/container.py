# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
"""Noxen — Dependency Injection Container.

Manages all singleton components with explicit initialization order.
Each layer depends only on layers above it.

Usage:
    container = NoxenContainer()
    container.initialize_sync()  # module-level singletons
    await container.initialize_async()  # async startup (Qdrant, etc.)
    await container.shutdown()
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger("container")


@dataclass
class NoxenContainer:
    """Container di tutti i singleton del sistema.

    L'ordine di inizializzazione e' esplicito e documentato.
    Le dipendenze sono dichiarate, non implicite.

    Layers:
        0 — Config (no deps)
        1 — Base managers (dipende da config)
        2 — Providers (dipende da config)
        3 — Research components (dipende da layer 1-2)
        4 — Notification (dipende da config)
        5 — Tenant (dipende da config)
        6 — Skill System v2 (dipende da layer 2-3)
        7 — Context & Orchestration (dipende da layer 1-6)
        8 — Bootstrap (dipende da tutto)
    """

    # Layer 0 — Config
    settings: Any = None

    # Layer 1 — Base managers
    skill_manager: Any = None
    skill_installer: Any = None
    project_manager: Any = None
    ingestor: Any = None
    plugin_composer: Any = None

    # Layer 2 — Providers
    llm_provider: Any = None
    knowledge_base: Any = None
    skill_router: Any = None
    event_router: Any = None

    # Layer 3 — Research components
    github_client: Any = None
    repo_analyzer: Any = None
    web_researcher: Any = None
    skill_builder: Any = None
    research_agent: Any = None

    # Layer 4 — Notification
    notification_engine: Any = None

    # Layer 5 — Tenant
    tenant_repository: Any = None

    # Layer 6 — Skill System v2
    skill_repository: Any = None
    skill_board_reviewer: Any = None
    skill_updater: Any = None
    skill_usage_tracker: Any = None

    # Layer 7 — Context & Orchestration
    context_gatherer: Any = None
    orchestrator: Any = None

    # Layer 8 — Bootstrap (async only)
    qdrant: Any = None
    embedding_provider: Any = None
    bootstrap: Any = None

    def initialize_sync(self) -> "NoxenContainer":
        """Initialize all module-level singletons (no async, no I/O).

        This is called at import time to create the dependency graph.
        Objects that need async init (Qdrant, embedding) get it later
        in initialize_async().
        """
        from config import settings
        from core import (
            SkillManager, SkillInstaller, ProjectManager, Ingestor,
            PluginComposer, LLMProvider, Orchestrator,
        )
        from core.knowledge_base import KnowledgeBase
        from core.context_gatherer import ContextGatherer
        from core.skill_router import SkillRouter
        from core.event_router import EventRouter
        from core.research_agent import ResearchAgent
        from core.research.github_client import GitHubClient
        from core.research.repo_analyzer import RepoAnalyzer
        from core.research.web_researcher import WebResearcher
        from core.research.skill_builder import SkillBuilder
        from core.notifications.engine import NotificationEngine
        from core.notifications.telegram_channel import TelegramChannel
        from core.notifications.slack_channel import SlackChannel
        from core.notifications.google_chat_channel import GoogleChatChannel
        from core.notifications.email_channel import EmailChannel
        from core.tenants.repository import TenantRepository
        from core.skills.repository import SkillRepository
        from core.skills.board_reviewer import SkillBoardReviewer
        from core.skills.updater import SkillUpdater
        from core.skills.usage_tracker import SkillUsageTracker

        s = settings

        # Layer 0 — Config
        self.settings = s

        # Layer 1 — Base managers (depend on settings only)
        self.skill_manager = SkillManager(s.skills_dir)
        self.skill_installer = SkillInstaller()
        self.project_manager = ProjectManager()
        self.ingestor = Ingestor(self.project_manager)
        self.plugin_composer = PluginComposer(s.skills_dir)

        # Layer 2 — Providers (depend on settings only)
        self.llm_provider = LLMProvider()
        self.knowledge_base = KnowledgeBase()
        self.skill_router = SkillRouter(self.plugin_composer)
        self.event_router = EventRouter(persist=True)

        # Layer 3 — Research (depend on layer 2)
        self.github_client = GitHubClient(token=s.github_token)
        self.repo_analyzer = RepoAnalyzer(
            sandbox_dir=s.research_sandbox_dir,
            clone_timeout_s=s.research_clone_timeout_s,
            max_file_size_kb=512,
        )
        self.web_researcher = WebResearcher(
            exa_api_key=s.exa_api_key,
            firecrawl_api_key=s.firecrawl_api_key,
        )
        self.skill_builder = SkillBuilder(llm_provider=self.llm_provider)
        self.research_agent = ResearchAgent(
            github_client=self.github_client,
            repo_analyzer=self.repo_analyzer,
            web_researcher=self.web_researcher,
            skill_builder=self.skill_builder,
            knowledge_base=self.knowledge_base,
            event_router=self.event_router,
        )

        # Layer 4 — Notification (depend on settings only)
        self.notification_engine = NotificationEngine(qdrant_persist=True)
        self.notification_engine.add_channel(TelegramChannel(
            bot_token=s.telegram_bot_token, chat_id=s.telegram_chat_id,
        ))
        self.notification_engine.add_channel(SlackChannel(
            bot_token=s.slack_bot_token, channel_id=s.slack_channel_id,
        ))
        self.notification_engine.add_channel(GoogleChatChannel(
            webhook_url=s.google_chat_webhook_url,
        ))
        self.notification_engine.add_channel(EmailChannel(
            smtp_host=s.smtp_host, smtp_port=s.smtp_port,
            smtp_user=s.smtp_user, smtp_password=s.smtp_password,
            smtp_from=s.smtp_from, smtp_to=s.smtp_to,
        ))

        # Layer 5 — Tenant (depend on settings only)
        self.tenant_repository = TenantRepository(
            db_path=str(s.data_dir / "tenants.db"),
        )

        # Layer 6 — Skill System v2 (depend on layer 2-3)
        self.skill_repository = SkillRepository()
        self.skill_board_reviewer = SkillBoardReviewer(
            llm_provider=self.llm_provider,
            skill_repository=self.skill_repository,
            event_router=self.event_router,
        )
        self.skill_updater = SkillUpdater(
            skill_repository=self.skill_repository,
            board_reviewer=self.skill_board_reviewer,
            research_agent=self.research_agent,
            llm_provider=self.llm_provider,
            event_router=self.event_router,
        )
        self.skill_usage_tracker = SkillUsageTracker(
            skill_repository=self.skill_repository,
            skill_updater=self.skill_updater,
            event_router=self.event_router,
        )

        # Layer 7 — Context & Orchestration (depend on layer 1-6)
        self.context_gatherer = ContextGatherer(
            self.knowledge_base, self.project_manager, self.skill_router,
            skill_repository=self.skill_repository,
            usage_tracker=self.skill_usage_tracker,
        )
        self.orchestrator = Orchestrator(
            self.llm_provider, self.ingestor, self.project_manager,
            self.plugin_composer, self.knowledge_base,
            context_gatherer=self.context_gatherer,
            skill_router=self.skill_router,
            event_router=self.event_router,
        )

        logger.info("container_initialized_sync", layers="0-7")
        return self

    async def initialize_async(self, app=None) -> "NoxenContainer":
        """Async initialization: Qdrant, embedding, bootstrap.

        Called during FastAPI lifespan startup.
        """
        from core.qdrant_client import NoxenQdrantClient
        from core.embedding_provider import FastEmbedProvider
        from core.bootstrap import NoxenBootstrap
        from core.tenants.auth import init_auth
        from api.routes import (
            skills, skills_v2, projects, bridge, chat,
            plugins, orchestrator, knowledge, research,
            notifications, events, admin,
        )

        s = self.settings

        # Qdrant (async)
        self.qdrant = await NoxenQdrantClient.initialize(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key or None,
        )
        health_ok = await self.qdrant.health_check()
        logger.info("qdrant_status", healthy=health_ok)

        # Configure Skill Repository with Qdrant
        self.embedding_provider = FastEmbedProvider()
        self.skill_repository._qdrant = self.qdrant
        self.skill_repository._embedding = self.embedding_provider

        # Load skills
        report = await self.skill_manager.load_all()
        for name, status in report.items():
            logger.info("skill_loaded", name=name, status=status)

        # Scan plugins
        self.plugin_composer.scan_all()

        # Inject dependencies into routes
        skills.init_router(self.skill_manager, self.skill_installer)
        projects.init_router(self.project_manager, self.ingestor)
        bridge.init_router(self.skill_manager, self.project_manager)
        chat.init_router(self.project_manager)
        plugins.init_router(self.plugin_composer)
        orchestrator.init_router(self.orchestrator, self.llm_provider)
        knowledge.init_router(self.knowledge_base)
        research.init_router(self.research_agent)
        notifications.init_router(self.notification_engine)
        skills_v2.init_router(
            skill_repository=self.skill_repository,
            board_reviewer=self.skill_board_reviewer,
            skill_updater=self.skill_updater,
            usage_tracker=self.skill_usage_tracker,
        )
        events.init_router(event_router=self.event_router)

        # Tenant auth (Phase 8)
        init_auth(
            tenant_repository=self.tenant_repository,
            multitenant_enabled=s.multitenant_enabled,
            admin_api_key=s.admin_api_key,
        )
        admin.init_router(
            tenant_repository=self.tenant_repository,
            qdrant_client=self.qdrant,
        )

        from api.routes import license as license_route
        license_route.init_router(
            tenant_repository=self.tenant_repository,
        )

        # Knowledge base status
        kb_stats = self.knowledge_base.get_stats()
        logger.info("knowledge_base_status", chunks=kb_stats.get("total_chunks", 0))

        # Bootstrap health checks
        self.bootstrap = NoxenBootstrap(
            settings=s,
            qdrant_client=self.qdrant,
            tenant_repo=self.tenant_repository,
        )
        bootstrap_result = await self.bootstrap.run()

        if app is not None:
            app.state.bootstrap_result = bootstrap_result
            app.state.container = self

        if not bootstrap_result.success:
            for error in bootstrap_result.errors:
                logger.error("startup_blocked", reason=error)

        return self

    async def shutdown(self) -> None:
        """Chiudi tutti i componenti nell'ordine inverso."""
        logger.info("container_shutdown_start")

        if self.llm_provider:
            try:
                await self.llm_provider.close()
            except Exception:
                pass

        if self.skill_manager:
            try:
                await self.skill_manager.unload_all()
            except Exception:
                pass

        qdrant_instance = None
        try:
            from core.qdrant_client import NoxenQdrantClient
            qdrant_instance = NoxenQdrantClient._instance
            if qdrant_instance:
                await qdrant_instance.close()
                NoxenQdrantClient.reset()
        except Exception:
            pass

        logger.info("container_shutdown_complete")
