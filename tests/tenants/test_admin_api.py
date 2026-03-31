"""Test suite per Tenant Admin API — Step 8.6."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.admin import router, init_router
from core.tenants.auth import TenantContext, require_admin
from core.tenants.model import (
    Tenant,
    TenantConfig,
    TenantPlan,
    TenantStatus,
    PLAN_LIMITS,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tenant(**kwargs) -> Tenant:
    defaults = dict(
        id="t-001",
        name="Test Co",
        slug="test-co",
        plan=TenantPlan.PRO,
        status=TenantStatus.ACTIVE,
        config=TenantConfig(),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kwargs)
    return Tenant(**defaults)


def _admin_ctx() -> TenantContext:
    return TenantContext(
        tenant=_make_tenant(id="default", name="Admin"),
        tenant_id="default",
        is_admin=True,
    )


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.create = AsyncMock(return_value=_make_tenant())
    repo.get = AsyncMock(return_value=_make_tenant())
    repo.get_by_slug = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[_make_tenant(), _make_tenant(id="t-002")])
    repo.update = AsyncMock(return_value=_make_tenant())
    repo.delete = AsyncMock(return_value=True)
    repo.create_api_key = AsyncMock(return_value="nh_test_api_key_abc123")
    repo.revoke_api_key = AsyncMock(return_value=True)
    repo.reset_monthly_sessions = AsyncMock()
    return repo


@pytest.fixture
def mock_qdrant():
    qdrant = MagicMock()
    qdrant.delete_tenant_data = AsyncMock(return_value={"skills": 5, "events": 2})
    return qdrant


@pytest.fixture
def client(mock_repo, mock_qdrant):
    app = FastAPI()
    app.include_router(router)
    init_router(tenant_repository=mock_repo, qdrant_client=mock_qdrant)
    app.dependency_overrides[require_admin] = lambda: _admin_ctx()
    return TestClient(app)


# ── POST / (create tenant) ──────────────────────────────────────────

class TestCreateTenant:
    def test_create_tenant(self, client, mock_repo):
        resp = client.post(
            "/api/admin/tenants/",
            json={"name": "New Co", "slug": "new-co", "plan": "pro"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "created"
        mock_repo.create.assert_called_once()

    def test_create_duplicate_slug(self, client, mock_repo):
        mock_repo.get_by_slug = AsyncMock(return_value=_make_tenant())
        resp = client.post(
            "/api/admin/tenants/",
            json={"name": "Dup", "slug": "test-co"},
        )
        assert resp.status_code == 409

    def test_create_invalid_slug(self, client):
        resp = client.post(
            "/api/admin/tenants/",
            json={"name": "Bad", "slug": "UPPER CASE!"},
        )
        assert resp.status_code == 422

    def test_create_invalid_plan(self, client):
        resp = client.post(
            "/api/admin/tenants/",
            json={"name": "Bad", "slug": "ok", "plan": "mega"},
        )
        assert resp.status_code == 422


# ── GET / (list tenants) ────────────────────────────────────────────

class TestListTenants:
    def test_list_tenants(self, client):
        resp = client.get("/api/admin/tenants/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["tenants"]) == 2


# ── GET /{tenant_id} ────────────────────────────────────────────────

class TestGetTenant:
    def test_get_tenant(self, client):
        resp = client.get("/api/admin/tenants/t-001")
        assert resp.status_code == 200
        assert resp.json()["tenant"]["id"] == "t-001"

    def test_get_tenant_not_found(self, client, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)
        resp = client.get("/api/admin/tenants/nonexistent")
        assert resp.status_code == 404


# ── PATCH /{tenant_id} ──────────────────────────────────────────────

class TestUpdateTenant:
    def test_update_name(self, client, mock_repo):
        resp = client.patch(
            "/api/admin/tenants/t-001",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"
        mock_repo.update.assert_called_once()

    def test_update_plan(self, client, mock_repo):
        resp = client.patch(
            "/api/admin/tenants/t-001",
            json={"plan": "enterprise"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_repo.update.call_args
        assert call_kwargs.kwargs.get("plan") == TenantPlan.ENTERPRISE

    def test_update_status_suspended(self, client, mock_repo):
        resp = client.patch(
            "/api/admin/tenants/t-001",
            json={"status": "suspended"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_repo.update.call_args
        assert call_kwargs.kwargs.get("status") == TenantStatus.SUSPENDED

    def test_update_no_changes(self, client):
        resp = client.patch(
            "/api/admin/tenants/t-001",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_changes"

    def test_update_not_found(self, client, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)
        resp = client.patch(
            "/api/admin/tenants/nope",
            json={"name": "X"},
        )
        assert resp.status_code == 404


# ── DELETE /{tenant_id} ─────────────────────────────────────────────

class TestDeleteTenant:
    def test_delete_tenant(self, client, mock_repo):
        resp = client.delete("/api/admin/tenants/t-001")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        mock_repo.delete.assert_called_once_with("t-001")

    def test_delete_with_data(self, client, mock_repo, mock_qdrant):
        resp = client.delete("/api/admin/tenants/t-001?delete_data=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["qdrant_deleted"]["skills"] == 5
        mock_qdrant.delete_tenant_data.assert_called_once_with("t-001")

    def test_delete_default_forbidden(self, client):
        resp = client.delete("/api/admin/tenants/default")
        assert resp.status_code == 400

    def test_delete_not_found(self, client, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)
        resp = client.delete("/api/admin/tenants/nope")
        assert resp.status_code == 404


# ── POST /{tenant_id}/api-keys ──────────────────────────────────────

class TestApiKeyManagement:
    def test_create_api_key(self, client, mock_repo):
        resp = client.post(
            "/api/admin/tenants/t-001/api-keys",
            json={"key_name": "prod-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"].startswith("nh_")
        assert "warning" in data

    def test_create_api_key_tenant_not_found(self, client, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)
        resp = client.post(
            "/api/admin/tenants/nope/api-keys",
            json={"key_name": "test-key"},
        )
        assert resp.status_code == 404

    def test_revoke_api_key(self, client, mock_repo):
        resp = client.delete("/api/admin/tenants/t-001/api-keys/abc123hash")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    def test_revoke_api_key_not_found(self, client, mock_repo):
        mock_repo.revoke_api_key = AsyncMock(return_value=False)
        resp = client.delete("/api/admin/tenants/t-001/api-keys/nope")
        assert resp.status_code == 404


# ── GET /{tenant_id}/usage ──────────────────────────────────────────

class TestTenantUsage:
    def test_get_usage(self, client):
        resp = client.get("/api/admin/tenants/t-001/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"] == "pro"
        assert "limits" in data
        assert "usage_pct" in data
        assert data["limits"]["max_projects"] == PLAN_LIMITS[TenantPlan.PRO].max_projects

    def test_get_usage_not_found(self, client, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)
        resp = client.get("/api/admin/tenants/nope/usage")
        assert resp.status_code == 404

    def test_reset_sessions(self, client, mock_repo):
        resp = client.post("/api/admin/tenants/t-001/reset-sessions")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"
        mock_repo.reset_monthly_sessions.assert_called_once_with("t-001")
