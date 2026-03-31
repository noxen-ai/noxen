"""Test suite per Tenant Auth Middleware — Step 8.3."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from core.tenants.auth import (
    TenantContext,
    get_tenant_context,
    init_auth,
    require_admin,
)
from core.tenants.model import (
    Tenant,
    TenantConfig,
    TenantPlan,
    TenantStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tenant(**kwargs) -> Tenant:
    defaults = dict(
        id="t-001",
        name="Test Co",
        slug="test",
        plan=TenantPlan.PRO,
        status=TenantStatus.ACTIVE,
        config=TenantConfig(),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kwargs)
    return Tenant(**defaults)


def _make_app():
    """Create a test FastAPI app with auth dependency."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint(ctx: TenantContext = Depends(get_tenant_context)):
        return {
            "tenant_id": ctx.tenant_id,
            "is_admin": ctx.is_admin,
            "tenant_name": ctx.tenant.name,
        }

    @app.get("/admin-only")
    async def admin_endpoint(ctx: TenantContext = Depends(require_admin)):
        return {"admin": True, "tenant_id": ctx.tenant_id}

    return app


# ── On-Premise Mode (multitenant=false) ──────────────────────────────

class TestOnPremiseMode:
    def test_returns_default_tenant_no_auth(self):
        """On-premise: returns default tenant without any auth."""
        mock_repo = MagicMock()
        default_tenant = _make_tenant(id="default", name="Default")
        mock_repo.ensure_default_tenant = AsyncMock(return_value=default_tenant)

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=False,
        )

        client = TestClient(_make_app())
        resp = client.get("/test")
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "default"
        assert resp.json()["is_admin"] is True

    def test_no_auth_header_needed(self):
        """On-premise: no Authorization header needed."""
        mock_repo = MagicMock()
        mock_repo.ensure_default_tenant = AsyncMock(
            return_value=_make_tenant(id="default")
        )
        init_auth(tenant_repository=mock_repo, multitenant_enabled=False)

        client = TestClient(_make_app())
        # No headers at all
        resp = client.get("/test")
        assert resp.status_code == 200


# ── SaaS Mode (multitenant=true) ─────────────────────────────────────

class TestSaaSMode:
    def test_valid_api_key(self):
        """SaaS: valid API key returns tenant."""
        mock_repo = MagicMock()
        mock_repo.get_by_api_key = AsyncMock(return_value=_make_tenant())
        mock_repo.ensure_default_tenant = AsyncMock(
            return_value=_make_tenant(id="default")
        )

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=True,
            admin_api_key="admin-secret",
        )

        client = TestClient(_make_app())
        resp = client.get("/test", headers={"Authorization": "Bearer nh_valid_key"})
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "t-001"

    def test_invalid_api_key_returns_401(self):
        """SaaS: invalid API key returns 401."""
        mock_repo = MagicMock()
        mock_repo.get_by_api_key = AsyncMock(return_value=None)

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=True,
        )

        client = TestClient(_make_app())
        resp = client.get("/test", headers={"Authorization": "Bearer bad_key"})
        assert resp.status_code == 401

    def test_no_auth_returns_401(self):
        """SaaS: no auth header returns 401."""
        mock_repo = MagicMock()

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=True,
        )

        client = TestClient(_make_app())
        resp = client.get("/test")
        assert resp.status_code == 401

    def test_suspended_tenant_returns_403(self):
        """SaaS: suspended tenant returns 403."""
        suspended = _make_tenant(status=TenantStatus.SUSPENDED)
        mock_repo = MagicMock()
        mock_repo.get_by_api_key = AsyncMock(return_value=suspended)

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=True,
        )

        client = TestClient(_make_app())
        resp = client.get("/test", headers={"Authorization": "Bearer nh_key"})
        assert resp.status_code == 403

    def test_admin_key_grants_admin(self):
        """SaaS: admin API key grants admin access."""
        mock_repo = MagicMock()
        mock_repo.ensure_default_tenant = AsyncMock(
            return_value=_make_tenant(id="default")
        )

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=True,
            admin_api_key="admin-secret",
        )

        client = TestClient(_make_app())
        resp = client.get("/test", headers={"Authorization": "Bearer admin-secret"})
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True

    def test_x_tenant_id_header(self):
        """SaaS: X-Tenant-ID header works as fallback."""
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=_make_tenant(id="t-header"))

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=True,
        )

        client = TestClient(_make_app())
        resp = client.get("/test", headers={"X-Tenant-ID": "t-header"})
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "t-header"


# ── Admin Dependency ─────────────────────────────────────────────────

class TestRequireAdmin:
    def test_admin_allowed(self):
        """Admin dependency allows admin."""
        mock_repo = MagicMock()
        mock_repo.ensure_default_tenant = AsyncMock(
            return_value=_make_tenant(id="default")
        )
        init_auth(tenant_repository=mock_repo, multitenant_enabled=False)

        client = TestClient(_make_app())
        resp = client.get("/admin-only")
        assert resp.status_code == 200
        assert resp.json()["admin"] is True

    def test_non_admin_rejected(self):
        """Admin dependency rejects non-admin in SaaS mode."""
        mock_repo = MagicMock()
        mock_repo.get_by_api_key = AsyncMock(return_value=_make_tenant())

        init_auth(
            tenant_repository=mock_repo,
            multitenant_enabled=True,
            admin_api_key="admin-only-key",
        )

        client = TestClient(_make_app())
        # Non-admin key
        resp = client.get("/admin-only", headers={"Authorization": "Bearer nh_user_key"})
        assert resp.status_code == 403
