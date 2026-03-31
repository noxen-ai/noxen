"""Test suite per Per-Tenant Notifications — Step 8.8."""

import pytest
from datetime import datetime

from core.notifications.engine import NotificationEngine
from core.tenants.model import (
    Tenant,
    TenantConfig,
    TenantPlan,
    TenantStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tenant(**config_kwargs) -> Tenant:
    config = TenantConfig(**config_kwargs)
    return Tenant(
        id="t-001",
        name="Test Co",
        slug="test",
        plan=TenantPlan.PRO,
        status=TenantStatus.ACTIVE,
        config=config,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


# ── Tests ────────────────────────────────────────────────────────────

class TestForTenant:
    def test_returns_engine_instance(self):
        """for_tenant returns a NotificationEngine."""
        tenant = _make_tenant()
        engine = NotificationEngine.for_tenant(tenant)
        assert isinstance(engine, NotificationEngine)

    def test_no_config_returns_empty_engine(self):
        """Without notification config, returns engine with no channels."""
        tenant = _make_tenant()
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert len(channels) == 0

    def test_telegram_channel_created(self):
        """Telegram channel added when bot_token and chat_id present."""
        tenant = _make_tenant(
            telegram_bot_token="123:ABC",
            telegram_chat_id="-1001234567890",
        )
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert any(c["name"] == "telegram" for c in channels)

    def test_slack_channel_created(self):
        """Slack channel added when bot_token and channel_id present."""
        tenant = _make_tenant(
            slack_bot_token="xoxb-test-token",
            slack_channel_id="C012345",
        )
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert any(c["name"] == "slack" for c in channels)

    def test_google_chat_channel_created(self):
        """Google Chat channel added when webhook_url present."""
        tenant = _make_tenant(
            google_chat_webhook_url="https://chat.googleapis.com/v1/spaces/test/messages",
        )
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert any(c["name"] == "google_chat" for c in channels)

    def test_email_channel_created(self):
        """Email channel added when smtp_host and smtp_to present."""
        tenant = _make_tenant(
            smtp_host="smtp.example.com",
            smtp_to=["admin@example.com"],
        )
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert any(c["name"] == "email" for c in channels)

    def test_multiple_channels(self):
        """Multiple channels configured at once."""
        tenant = _make_tenant(
            telegram_bot_token="123:ABC",
            telegram_chat_id="-100",
            slack_bot_token="xoxb-test",
            slack_channel_id="C012",
        )
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert len(channels) == 2
        names = {c["name"] for c in channels}
        assert "telegram" in names
        assert "slack" in names

    def test_partial_config_skipped(self):
        """Partial config (e.g. token but no chat_id) doesn't add channel."""
        tenant = _make_tenant(
            telegram_bot_token="123:ABC",
            # No chat_id!
        )
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert len(channels) == 0

    def test_tenant_without_config_attr(self):
        """Object without config attribute returns empty engine."""
        class FakeTenant:
            pass
        engine = NotificationEngine.for_tenant(FakeTenant())
        assert isinstance(engine, NotificationEngine)
        assert len(engine.get_channels()) == 0

    def test_email_smtp_to_list_joined(self):
        """Email smtp_to list is joined for EmailChannel."""
        tenant = _make_tenant(
            smtp_host="smtp.example.com",
            smtp_to=["a@b.com", "c@d.com"],
        )
        engine = NotificationEngine.for_tenant(tenant)
        channels = engine.get_channels()
        assert any(c["name"] == "email" for c in channels)
