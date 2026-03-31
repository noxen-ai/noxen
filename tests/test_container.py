"""Tests for core/container.py — Dependency Injection Container."""

import pytest

from core.container import NoxenContainer


class TestContainerInitSync:
    """Test synchronous initialization."""

    def test_initialize_sync_returns_self(self):
        c = NoxenContainer()
        result = c.initialize_sync()
        assert result is c

    def test_settings_not_none(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.settings is not None

    def test_layer1_managers_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.skill_manager is not None
        assert c.skill_installer is not None
        assert c.project_manager is not None
        assert c.ingestor is not None
        assert c.plugin_composer is not None

    def test_layer2_providers_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.llm_provider is not None
        assert c.knowledge_base is not None
        assert c.skill_router is not None
        assert c.event_router is not None

    def test_layer3_research_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.github_client is not None
        assert c.repo_analyzer is not None
        assert c.web_researcher is not None
        assert c.skill_builder is not None
        assert c.research_agent is not None

    def test_layer4_notification_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.notification_engine is not None

    def test_layer5_tenant_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.tenant_repository is not None

    def test_layer6_skills_v2_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.skill_repository is not None
        assert c.skill_board_reviewer is not None
        assert c.skill_updater is not None
        assert c.skill_usage_tracker is not None

    def test_layer7_orchestration_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.context_gatherer is not None
        assert c.orchestrator is not None

    def test_async_components_not_yet_initialized(self):
        c = NoxenContainer()
        c.initialize_sync()
        # Qdrant and embedding need async init
        assert c.qdrant is None
        assert c.embedding_provider is None
        assert c.bootstrap is None


class TestContainerDependencyOrder:
    """Verify correct dependency wiring."""

    def test_ingestor_has_project_manager(self):
        c = NoxenContainer()
        c.initialize_sync()
        # Ingestor(project_manager) — verify it got the right one
        assert c.ingestor._pm is c.project_manager

    def test_skill_builder_has_llm(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.skill_builder._llm is c.llm_provider

    def test_skill_board_reviewer_has_deps(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.skill_board_reviewer._llm == c.llm_provider
        assert c.skill_board_reviewer._repo == c.skill_repository
        assert c.skill_board_reviewer._event_router == c.event_router

    def test_context_gatherer_has_deps(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.context_gatherer.knowledge_base is c.knowledge_base
        assert c.context_gatherer.project_manager is c.project_manager
        assert c.context_gatherer.skill_router is c.skill_router

    def test_orchestrator_has_llm(self):
        c = NoxenContainer()
        c.initialize_sync()
        assert c.orchestrator.llm is c.llm_provider

    def test_no_circular_references(self):
        """All dependencies resolve without circular refs."""
        c = NoxenContainer()
        c.initialize_sync()
        # If we got here, no circular reference
        assert True


class TestContainerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_no_error(self):
        """shutdown() runs without errors even when async wasn't called."""
        c = NoxenContainer()
        c.initialize_sync()
        await c.shutdown()  # Should not raise


class TestMainModuleUsesContainer:
    """Verify main.py uses the container."""

    def test_main_has_container(self):
        from main import container
        assert isinstance(container, NoxenContainer)

    def test_main_aliases_match_container(self):
        from main import container, skill_manager, llm_provider, event_router
        assert skill_manager is container.skill_manager
        assert llm_provider is container.llm_provider
        assert event_router is container.event_router
