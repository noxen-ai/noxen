"""Test suite per TenantRepository — Step 8.2."""

import os
import pytest
import tempfile
from datetime import datetime

from core.tenants.model import (
    Tenant,
    TenantConfig,
    TenantPlan,
    TenantStatus,
)
from core.tenants.repository import TenantRepository


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tenant(**kwargs) -> Tenant:
    defaults = dict(
        id="t-001",
        name="Acme Corp",
        slug="acme",
        plan=TenantPlan.PRO,
        status=TenantStatus.ACTIVE,
        config=TenantConfig(llm_provider="claude"),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kwargs)
    return Tenant(**defaults)


@pytest.fixture
def repo(tmp_path):
    db_path = str(tmp_path / "test_tenants.db")
    return TenantRepository(db_path=db_path)


# ── Create & Get ─────────────────────────────────────────────────────

class TestCreateAndGet:
    @pytest.mark.asyncio
    async def test_create_persists(self, repo):
        tenant = _make_tenant()
        result = await repo.create(tenant)
        assert result.id == "t-001"

        retrieved = await repo.get("t-001")
        assert retrieved is not None
        assert retrieved.name == "Acme Corp"
        assert retrieved.plan == TenantPlan.PRO

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, repo):
        result = await repo.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_slug(self, repo):
        await repo.create(_make_tenant())
        result = await repo.get_by_slug("acme")
        assert result is not None
        assert result.id == "t-001"

    @pytest.mark.asyncio
    async def test_get_by_slug_nonexistent(self, repo):
        result = await repo.get_by_slug("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_config_persisted(self, repo):
        tenant = _make_tenant(
            config=TenantConfig(
                llm_provider="gemini",
                telegram_bot_token="bot123",
                smtp_to=["a@b.com"],
            )
        )
        await repo.create(tenant)
        retrieved = await repo.get("t-001")
        assert retrieved.config.llm_provider == "gemini"
        assert retrieved.config.telegram_bot_token == "bot123"
        assert retrieved.config.smtp_to == ["a@b.com"]


# ── Update ───────────────────────────────────────────────────────────

class TestUpdate:
    @pytest.mark.asyncio
    async def test_update(self, repo):
        await repo.create(_make_tenant())
        tenant = await repo.get("t-001")
        tenant.name = "Acme Corp V2"
        tenant.plan = TenantPlan.ENTERPRISE
        await repo.update(tenant)

        updated = await repo.get("t-001")
        assert updated.name == "Acme Corp V2"
        assert updated.plan == TenantPlan.ENTERPRISE


# ── Delete ───────────────────────────────────────────────────────────

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete(self, repo):
        await repo.create(_make_tenant())
        result = await repo.delete("t-001")
        assert result is True
        assert await repo.get("t-001") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repo):
        result = await repo.delete("nonexistent")
        assert result is False


# ── List ─────────────────────────────────────────────────────────────

class TestList:
    @pytest.mark.asyncio
    async def test_list_all(self, repo, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "multitenant_enabled", True)
        await repo.create(_make_tenant(id="t-1", slug="s1"))
        await repo.create(_make_tenant(id="t-2", slug="s2"))
        tenants = await repo.list_all()
        assert len(tenants) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, repo):
        tenants = await repo.list_all()
        assert tenants == []


# ── API Keys ─────────────────────────────────────────────────────────

class TestApiKeys:
    @pytest.mark.asyncio
    async def test_create_api_key_returns_plaintext(self, repo):
        await repo.create(_make_tenant())
        key = await repo.create_api_key("t-001", "production")
        assert key.startswith("nh_")
        assert len(key) > 20

    @pytest.mark.asyncio
    async def test_get_by_api_key(self, repo):
        await repo.create(_make_tenant())
        key = await repo.create_api_key("t-001", "prod")

        tenant = await repo.get_by_api_key(key)
        assert tenant is not None
        assert tenant.id == "t-001"

    @pytest.mark.asyncio
    async def test_get_by_invalid_api_key(self, repo):
        await repo.create(_make_tenant())
        await repo.create_api_key("t-001", "prod")

        tenant = await repo.get_by_api_key("nh_invalid_key")
        assert tenant is None

    @pytest.mark.asyncio
    async def test_revoked_key_rejected(self, repo):
        await repo.create(_make_tenant())
        key = await repo.create_api_key("t-001", "prod")
        key_hash = repo._hash_key(key)

        await repo.revoke_api_key(key_hash)
        tenant = await repo.get_by_api_key(key)
        assert tenant is None

    @pytest.mark.asyncio
    async def test_list_api_keys(self, repo):
        await repo.create(_make_tenant())
        await repo.create_api_key("t-001", "prod")
        await repo.create_api_key("t-001", "staging")

        keys = await repo.list_api_keys("t-001")
        assert len(keys) == 2
        assert keys[0]["name"] == "prod"
        assert keys[1]["name"] == "staging"

    @pytest.mark.asyncio
    async def test_delete_tenant_removes_keys(self, repo):
        await repo.create(_make_tenant())
        key = await repo.create_api_key("t-001", "prod")
        await repo.delete("t-001")

        tenant = await repo.get_by_api_key(key)
        assert tenant is None


# ── Session Tracking ─────────────────────────────────────────────────

class TestSessionTracking:
    @pytest.mark.asyncio
    async def test_increment_sessions(self, repo):
        await repo.create(_make_tenant())
        await repo.increment_sessions("t-001")
        await repo.increment_sessions("t-001")

        tenant = await repo.get("t-001")
        assert tenant.sessions_this_month == 2
        assert tenant.total_sessions == 2

    @pytest.mark.asyncio
    async def test_reset_monthly_sessions(self, repo):
        await repo.create(_make_tenant(sessions_this_month=50))
        # Update to set the value
        t = await repo.get("t-001")
        t.sessions_this_month = 50
        await repo.update(t)

        await repo.reset_monthly_sessions("t-001")
        tenant = await repo.get("t-001")
        assert tenant.sessions_this_month == 0


# ── Default Tenant ───────────────────────────────────────────────────

class TestDefaultTenant:
    @pytest.mark.asyncio
    async def test_ensure_default_creates(self, repo):
        tenant = await repo.ensure_default_tenant()
        assert tenant.id == "default"
        assert tenant.plan == TenantPlan.ENTERPRISE
        assert tenant.status == TenantStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_ensure_default_idempotent(self, repo):
        t1 = await repo.ensure_default_tenant()
        t2 = await repo.ensure_default_tenant()
        assert t1.id == t2.id
        assert t1.name == t2.name

        tenants = await repo.list_all()
        assert len(tenants) == 1
