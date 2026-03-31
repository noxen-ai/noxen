"""Test suite per EmailChannel — Step 5.5."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.notifications.email_channel import EmailChannel
from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationResult,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def channel():
    return EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user@example.com",
        smtp_password="secret",
        smtp_from="noreply@neuralhub.local",
        smtp_to="admin@example.com",
    )


@pytest.fixture
def unconfigured_channel():
    return EmailChannel()


@pytest.fixture
def plan():
    return ApprovalPlan(
        run_id="run-42",
        project_name="TestProject",
        goals=[
            {"title": "Fix auth", "description": "Repair login"},
            {"title": "Add tests", "description": "Coverage"},
        ],
        total_goals=2,
        parallel_groups=1,
        estimated_time="~10 min",
        approve_url="http://localhost:8400/api/engine/approve",
        reject_url="http://localhost:8400/api/engine/reject",
    )


# ── Properties ───────────────────────────────────────────────────────

class TestProperties:
    def test_name(self, channel):
        assert channel.name == "email"

    def test_is_configured_true(self, channel):
        assert channel.is_configured() is True

    def test_is_configured_false_no_host(self):
        ch = EmailChannel(smtp_from="a@b.c", smtp_to="d@e.f")
        assert ch.is_configured() is False

    def test_is_configured_false_no_from(self):
        ch = EmailChannel(smtp_host="smtp.x.com", smtp_to="a@b.c")
        assert ch.is_configured() is False

    def test_is_configured_false_no_to(self):
        ch = EmailChannel(smtp_host="smtp.x.com", smtp_from="a@b.c")
        assert ch.is_configured() is False

    def test_is_configured_false_empty(self, unconfigured_channel):
        assert unconfigured_channel.is_configured() is False

    def test_is_configured_minimal(self):
        """Configured with just host, from, to — no auth needed."""
        ch = EmailChannel(smtp_host="mail.local", smtp_from="a@b.c", smtp_to="d@e.f")
        assert ch.is_configured() is True


# ── Unconfigured returns error ───────────────────────────────────────

class TestUnconfigured:
    @pytest.mark.asyncio
    async def test_send_approval_not_configured(self, unconfigured_channel, plan):
        result = await unconfigured_channel.send_approval_request(plan)
        assert result.success is False
        assert result.error == "Not configured"

    @pytest.mark.asyncio
    async def test_send_notification_not_configured(self, unconfigured_channel):
        result = await unconfigured_channel.send_notification("T", "M")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_send_reminder_not_configured(self, unconfigured_channel, plan):
        result = await unconfigured_channel.send_reminder(plan, 30)
        assert result.success is False


# ── Approval request ─────────────────────────────────────────────────

class TestApprovalRequest:
    @pytest.mark.asyncio
    async def test_send_approval_success(self, channel, plan):
        mock_send = AsyncMock(return_value=({}, "OK"))

        with patch("aiosmtplib.send", mock_send):
            result = await channel.send_approval_request(plan)

        assert result.success is True
        assert result.channel == "email"
        mock_send.assert_called_once()

        call_kwargs = mock_send.call_args
        msg = call_kwargs[0][0]  # first positional arg is the MIMEMultipart
        assert "Approval Request" in msg["Subject"]
        assert plan.project_name in msg["Subject"]
        assert msg["From"] == "noreply@neuralhub.local"
        assert msg["To"] == "admin@example.com"

    @pytest.mark.asyncio
    async def test_send_approval_with_custom_actions(self, channel, plan):
        mock_send = AsyncMock(return_value=({}, "OK"))
        actions = [
            NotificationAction(label="Ship It", action_type=ActionType.APPROVE, url="http://go"),
        ]
        with patch("aiosmtplib.send", mock_send):
            result = await channel.send_approval_request(plan, actions=actions)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_approval_smtp_error(self, channel, plan):
        with patch("aiosmtplib.send", AsyncMock(side_effect=Exception("SMTP error"))):
            result = await channel.send_approval_request(plan)
        assert result.success is False
        assert "SMTP error" in result.error


# ── Generic notification ─────────────────────────────────────────────

class TestNotification:
    @pytest.mark.asyncio
    async def test_send_notification_info(self, channel):
        mock_send = AsyncMock(return_value=({}, "OK"))
        with patch("aiosmtplib.send", mock_send):
            result = await channel.send_notification("Deploy Complete", "All good", level="info")
        assert result.success is True
        msg = mock_send.call_args[0][0]
        assert "[Noxen] Deploy Complete" == msg["Subject"]

    @pytest.mark.asyncio
    async def test_send_notification_smtp_params(self, channel):
        mock_send = AsyncMock(return_value=({}, "OK"))
        with patch("aiosmtplib.send", mock_send):
            await channel.send_notification("T", "M")
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["hostname"] == "smtp.example.com"
        assert call_kwargs["port"] == 587
        assert call_kwargs["username"] == "user@example.com"
        assert call_kwargs["password"] == "secret"
        assert call_kwargs["start_tls"] is True


# ── Reminder ─────────────────────────────────────────────────────────

class TestReminder:
    @pytest.mark.asyncio
    async def test_send_reminder(self, channel, plan):
        mock_send = AsyncMock(return_value=({}, "OK"))
        with patch("aiosmtplib.send", mock_send):
            result = await channel.send_reminder(plan, 45)
        assert result.success is True
        msg = mock_send.call_args[0][0]
        assert "REMINDER" in msg["Subject"]
        assert "45m" in msg["Subject"]


# ── HTML builders ────────────────────────────────────────────────────

class TestHTMLBuilders:
    def test_build_approval_html(self, channel, plan):
        html = channel._build_approval_html(plan)
        assert "Approval Request" in html
        assert plan.project_name in html
        assert plan.run_id in html
        assert "Fix auth" in html
        assert "Approve" in html
        assert "Reject" in html

    def test_build_approval_html_many_goals(self, channel):
        plan = ApprovalPlan(
            run_id="r", project_name="P",
            goals=[{"title": f"G{i}", "description": "d"} for i in range(8)],
            total_goals=8, parallel_groups=2,
        )
        html = channel._build_approval_html(plan)
        assert "more" in html

    def test_build_buttons_html_default(self, channel, plan):
        html = channel._build_buttons_html(plan)
        assert plan.approve_url in html
        assert plan.reject_url in html
        assert "Approve" in html
        assert "Reject" in html

    def test_build_buttons_html_custom(self, channel, plan):
        actions = [
            NotificationAction(label="Go", action_type=ActionType.APPROVE, url="http://go"),
            NotificationAction(label="Stop", action_type=ActionType.REJECT, url="http://stop"),
        ]
        html = channel._build_buttons_html(plan, actions=actions)
        assert "http://go" in html
        assert "http://stop" in html
        assert "Go" in html
        assert "Stop" in html

    def test_build_buttons_html_no_urls(self, channel):
        plan = ApprovalPlan(run_id="r", project_name="P")
        html = channel._build_buttons_html(plan)
        assert "#" in html  # fallback href
