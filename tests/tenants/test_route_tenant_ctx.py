"""Test suite per Route Tenant Context Integration — Step 8.5.

Verifies that all updated API routes correctly use tenant context
from the auth middleware, including tenant_id propagation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.tenants.auth import TenantContext, get_tenant_context
from core.tenants.model import Tenant, TenantConfig, TenantPlan, TenantStatus


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tenant(tenant_id="t-001", name="Test Co", plan=TenantPlan.PRO) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug="test",
        plan=plan,
        status=TenantStatus.ACTIVE,
        config=TenantConfig(),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


def _make_ctx(tenant_id="t-001", is_admin=False) -> TenantContext:
    return TenantContext(
        tenant=_make_tenant(tenant_id=tenant_id),
        tenant_id=tenant_id,
        is_admin=is_admin,
    )


# ── Skills v2 Routes ────────────────────────────────────────────────

class TestSkillsV2TenantContext:
    """Skills v2 routes pass tenant_id from context, not query param."""

    @pytest.fixture
    def client(self):
        from api.routes.skills_v2 import router, init_router
        from core.skills.lifecycle import Skill, SkillStatus, SkillSource

        mock_repo = MagicMock()
        mock_repo.get_pool_stats = AsyncMock(return_value={"total": 3})
        mock_repo.search = AsyncMock(return_value=[])
        mock_repo.list_by_status = AsyncMock(return_value=[])

        mock_tracker = MagicMock()
        mock_tracker.get_usage_analytics = AsyncMock(return_value={"events": 0})

        mock_updater = MagicMock()
        mock_updater.check_degraded_skills = AsyncMock(return_value=[])
        mock_updater.MIN_CONFIDENCE_THRESHOLD = 0.4

        init_router(
            skill_repository=mock_repo,
            board_reviewer=MagicMock(),
            skill_updater=mock_updater,
            usage_tracker=mock_tracker,
        )

        app = FastAPI()
        app.include_router(router)

        ctx = _make_ctx(tenant_id="team-alpha")
        app.dependency_overrides[get_tenant_context] = lambda: ctx

        self._mock_repo = mock_repo
        self._mock_tracker = mock_tracker
        self._mock_updater = mock_updater
        return TestClient(app)

    def test_pool_uses_tenant_from_ctx(self, client):
        """GET /pool uses tenant_id from context."""
        resp = client.get("/api/skills/v2/pool")
        assert resp.status_code == 200
        self._mock_repo.get_pool_stats.assert_called_with(tenant_id="team-alpha")

    def test_pool_status_filter_uses_tenant_from_ctx(self, client):
        """GET /pool?status=approved uses tenant_id from context."""
        resp = client.get("/api/skills/v2/pool?status=approved")
        assert resp.status_code == 200
        self._mock_repo.list_by_status.assert_called_once()
        call_kwargs = self._mock_repo.list_by_status.call_args
        assert call_kwargs.kwargs.get("tenant_id") == "team-alpha"

    def test_stats_uses_tenant_from_ctx(self, client):
        """GET /stats uses tenant_id from context."""
        resp = client.get("/api/skills/v2/stats")
        assert resp.status_code == 200
        self._mock_repo.get_pool_stats.assert_called_with(tenant_id="team-alpha")

    def test_search_uses_tenant_from_ctx(self, client):
        """POST /search uses tenant_id from context."""
        resp = client.post(
            "/api/skills/v2/search",
            json={"query": "redis"},
        )
        assert resp.status_code == 200
        call_kwargs = self._mock_repo.search.call_args
        assert call_kwargs.kwargs.get("tenant_id") == "team-alpha"

    def test_analytics_uses_tenant_from_ctx(self, client):
        """GET /analytics uses tenant_id from context."""
        resp = client.get("/api/skills/v2/analytics")
        assert resp.status_code == 200
        self._mock_tracker.get_usage_analytics.assert_called_with(tenant_id="team-alpha")

    def test_check_degraded_uses_tenant_from_ctx(self, client):
        """POST /check-degraded uses tenant_id from context."""
        resp = client.post("/api/skills/v2/check-degraded")
        assert resp.status_code == 200
        self._mock_updater.check_degraded_skills.assert_called_with(tenant_id="team-alpha")

    def test_no_tenant_id_query_param_accepted(self, client):
        """tenant_id query param is no longer accepted (removed from schema)."""
        resp = client.get("/api/skills/v2/pool?tenant_id=hacker")
        assert resp.status_code == 200
        # Should still use "team-alpha" from context, ignoring query param
        self._mock_repo.get_pool_stats.assert_called_with(tenant_id="team-alpha")


# ── Cross-Route Dependency Injection ─────────────────────────────────

class TestRoutesDependencyPresent:
    """Verify that all updated route files import and use tenant auth."""

    def test_orchestrator_has_tenant_import(self):
        import api.routes.orchestrator as mod
        source = open(mod.__file__).read()
        assert "get_tenant_context" in source
        assert "TenantContext" in source

    def test_research_has_tenant_import(self):
        import api.routes.research as mod
        source = open(mod.__file__).read()
        assert "get_tenant_context" in source
        assert "TenantContext" in source

    def test_projects_has_tenant_import(self):
        import api.routes.projects as mod
        source = open(mod.__file__).read()
        assert "get_tenant_context" in source
        assert "TenantContext" in source

    def test_knowledge_has_tenant_import(self):
        import api.routes.knowledge as mod
        source = open(mod.__file__).read()
        assert "get_tenant_context" in source
        assert "TenantContext" in source

    def test_notifications_has_tenant_import(self):
        import api.routes.notifications as mod
        source = open(mod.__file__).read()
        assert "get_tenant_context" in source
        assert "TenantContext" in source

    def test_skills_v2_has_tenant_import(self):
        import api.routes.skills_v2 as mod
        source = open(mod.__file__).read()
        assert "get_tenant_context" in source
        assert "TenantContext" in source
