"""Test suite per Tenant Model — Step 8.1."""

import pytest
from datetime import datetime

from core.tenants.model import (
    PLAN_LIMITS,
    Tenant,
    TenantConfig,
    TenantLimits,
    TenantPlan,
    TenantStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tenant(**kwargs) -> Tenant:
    defaults = dict(
        id="t-123",
        name="Test Company",
        slug="test-co",
        plan=TenantPlan.PRO,
        status=TenantStatus.ACTIVE,
        config=TenantConfig(),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kwargs)
    return Tenant(**defaults)


# ── TenantPlan & TenantLimits ───────────────────────────────────────

class TestPlanLimits:
    def test_free_plan_limits(self):
        limits = PLAN_LIMITS[TenantPlan.FREE]
        assert limits.max_projects == 1
        assert limits.max_sessions_per_month == 10
        assert limits.notifications_enabled is False

    def test_pro_plan_limits(self):
        limits = PLAN_LIMITS[TenantPlan.PRO]
        assert limits.max_projects == 5
        assert limits.max_sessions_per_month == 100
        assert limits.notifications_enabled is True

    def test_enterprise_plan_limits(self):
        limits = PLAN_LIMITS[TenantPlan.ENTERPRISE]
        assert limits.max_projects == 999
        assert limits.max_sessions_per_month == 9999
        assert "claude" in limits.board_providers
        assert "grok" in limits.board_providers

    def test_all_plans_have_limits(self):
        for plan in TenantPlan:
            assert plan in PLAN_LIMITS

    def test_plan_enum_values(self):
        assert TenantPlan.FREE.value == "free"
        assert TenantPlan.PRO.value == "pro"
        assert TenantPlan.ENTERPRISE.value == "enterprise"


# ── TenantConfig ─────────────────────────────────────────────────────

class TestTenantConfig:
    def test_default_config(self):
        config = TenantConfig()
        assert config.llm_provider == "claude"
        assert config.llm_api_key == ""
        assert config.board_enabled is True

    def test_to_dict_from_dict_roundtrip(self):
        config = TenantConfig(
            llm_provider="gemini",
            telegram_bot_token="tok123",
            smtp_to=["a@b.com"],
        )
        d = config.to_dict()
        restored = TenantConfig.from_dict(d)
        assert restored.llm_provider == "gemini"
        assert restored.telegram_bot_token == "tok123"
        assert restored.smtp_to == ["a@b.com"]

    def test_from_dict_ignores_unknown_fields(self):
        config = TenantConfig.from_dict({"llm_provider": "openai", "unknown_field": 42})
        assert config.llm_provider == "openai"


# ── Tenant ───────────────────────────────────────────────────────────

class TestTenant:
    def test_limits_property(self):
        tenant = _make_tenant(plan=TenantPlan.FREE)
        assert tenant.limits.max_projects == 1

    def test_can_start_session_active_under_limit(self):
        tenant = _make_tenant(sessions_this_month=5)
        assert tenant.can_start_session() is True

    def test_can_start_session_suspended(self):
        tenant = _make_tenant(status=TenantStatus.SUSPENDED)
        assert tenant.can_start_session() is False

    def test_can_start_session_trial(self):
        tenant = _make_tenant(status=TenantStatus.TRIAL)
        assert tenant.can_start_session() is False

    def test_can_start_session_limit_reached(self):
        tenant = _make_tenant(
            plan=TenantPlan.FREE,
            sessions_this_month=10,  # FREE limit is 10
        )
        assert tenant.can_start_session() is False

    def test_can_start_session_one_below_limit(self):
        tenant = _make_tenant(
            plan=TenantPlan.FREE,
            sessions_this_month=9,
        )
        assert tenant.can_start_session() is True

    def test_to_dict(self):
        tenant = _make_tenant()
        d = tenant.to_dict()
        assert d["id"] == "t-123"
        assert d["plan"] == "pro"
        assert d["status"] == "active"
        assert isinstance(d["config"], dict)
        assert isinstance(d["created_at"], str)

    def test_from_dict(self):
        tenant = _make_tenant(total_sessions=42)
        d = tenant.to_dict()
        restored = Tenant.from_dict(d)
        assert restored.id == "t-123"
        assert restored.name == "Test Company"
        assert restored.plan == TenantPlan.PRO
        assert restored.status == TenantStatus.ACTIVE
        assert restored.total_sessions == 42

    def test_to_dict_from_dict_roundtrip(self):
        original = _make_tenant(
            sessions_this_month=7,
            total_skills_created=15,
            config=TenantConfig(llm_provider="gemini", smtp_to=["x@y.com"]),
        )
        restored = Tenant.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.slug == original.slug
        assert restored.plan == original.plan
        assert restored.sessions_this_month == 7
        assert restored.total_skills_created == 15
        assert restored.config.llm_provider == "gemini"
        assert restored.config.smtp_to == ["x@y.com"]

    def test_from_dict_with_string_config(self):
        """from_dict handles config as JSON string."""
        import json
        d = _make_tenant().to_dict()
        d["config"] = json.dumps(d["config"])
        restored = Tenant.from_dict(d)
        assert isinstance(restored.config, TenantConfig)


# ── TenantStatus ─────────────────────────────────────────────────────

class TestTenantStatus:
    def test_status_values(self):
        assert TenantStatus.ACTIVE.value == "active"
        assert TenantStatus.SUSPENDED.value == "suspended"
        assert TenantStatus.TRIAL.value == "trial"
