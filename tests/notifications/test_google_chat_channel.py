"""Test suite per GoogleChatChannel — Step 5.4."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import ClientTimeout

from core.notifications.google_chat_channel import GoogleChatChannel
from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationResult,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def channel():
    return GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/XXX/messages?key=YYY")


@pytest.fixture
def unconfigured_channel():
    return GoogleChatChannel()


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


def _mock_aiohttp_session(status=200, body='{"name":"spaces/X/messages/Y"}'):
    """Create mock aiohttp session context managers."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.text = AsyncMock(return_value=body)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


# ── Properties ───────────────────────────────────────────────────────

class TestProperties:
    def test_name(self, channel):
        assert channel.name == "google_chat"

    def test_is_configured_true(self, channel):
        assert channel.is_configured() is True

    def test_is_configured_false_empty(self, unconfigured_channel):
        assert unconfigured_channel.is_configured() is False

    def test_is_configured_false_blank(self):
        assert GoogleChatChannel(webhook_url="").is_configured() is False


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
        mock_session = _mock_aiohttp_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await channel.send_approval_request(plan)

        assert result.success is True
        assert result.channel == "google_chat"
        assert result.message_id == "spaces/X/messages/Y"
        mock_session.post.assert_called_once()

        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        assert "cardsV2" in payload

    @pytest.mark.asyncio
    async def test_send_approval_with_custom_actions(self, channel, plan):
        mock_session = _mock_aiohttp_session()
        actions = [
            NotificationAction(label="Go", action_type=ActionType.APPROVE, url="http://go"),
        ]
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await channel.send_approval_request(plan, actions=actions)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_approval_http_error(self, channel, plan):
        mock_session = _mock_aiohttp_session(status=403, body="Forbidden")
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await channel.send_approval_request(plan)
        assert result.success is False
        assert "403" in result.error

    @pytest.mark.asyncio
    async def test_send_approval_exception(self, channel, plan):
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
        mock_session.__aexit__ = AsyncMock(return_value=False)
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await channel.send_approval_request(plan)
        assert result.success is False
        assert "Network error" in result.error


# ── Generic notification ─────────────────────────────────────────────

class TestNotification:
    @pytest.mark.asyncio
    async def test_send_notification_info(self, channel):
        mock_session = _mock_aiohttp_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await channel.send_notification("Deploy", "Done!", level="info")
        assert result.success is True
        payload = mock_session.post.call_args[1]["json"]
        header = payload["cardsV2"][0]["card"]["header"]
        assert "ℹ️" in header["title"]

    @pytest.mark.asyncio
    async def test_send_notification_levels(self, channel):
        for level, emoji in [("warning", "⚠️"), ("error", "🔴"), ("success", "✅")]:
            mock_session = _mock_aiohttp_session()
            with patch("aiohttp.ClientSession", return_value=mock_session):
                result = await channel.send_notification("T", "M", level=level)
            assert result.success is True
            payload = mock_session.post.call_args[1]["json"]
            assert emoji in payload["cardsV2"][0]["card"]["header"]["title"]


# ── Reminder ─────────────────────────────────────────────────────────

class TestReminder:
    @pytest.mark.asyncio
    async def test_send_reminder(self, channel, plan):
        mock_session = _mock_aiohttp_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await channel.send_reminder(plan, 45)
        assert result.success is True
        payload = mock_session.post.call_args[1]["json"]
        card = payload["cardsV2"][0]["card"]
        assert "Reminder" in card["header"]["title"]
        # Check elapsed minutes in the text
        widgets_text = str(card["sections"][0]["widgets"])
        assert "45 min" in widgets_text


# ── Card builders ────────────────────────────────────────────────────

class TestCardBuilders:
    def test_build_approval_card(self, channel, plan):
        card = channel._build_approval_card(plan)
        assert "cardsV2" in card
        sections = card["cardsV2"][0]["card"]["sections"]
        assert len(sections) >= 2  # summary + buttons

    def test_build_approval_card_many_goals(self, channel):
        plan = ApprovalPlan(
            run_id="r",
            project_name="P",
            goals=[{"title": f"G{i}", "description": "d"} for i in range(8)],
            total_goals=8,
            parallel_groups=2,
        )
        card = channel._build_approval_card(plan)
        section_text = str(card["cardsV2"][0]["card"]["sections"][0])
        assert "more" in section_text

    def test_build_button_section_with_urls(self, channel, plan):
        section = channel._build_button_section(plan)
        buttons = section["widgets"][0]["buttonList"]["buttons"]
        assert len(buttons) == 2
        assert buttons[0]["text"] == "✅ Approve"
        assert buttons[0]["onClick"]["openLink"]["url"] == plan.approve_url

    def test_build_button_section_without_urls(self, channel):
        plan = ApprovalPlan(run_id="r", project_name="P")
        section = channel._build_button_section(plan)
        buttons = section["widgets"][0]["buttonList"]["buttons"]
        assert "action" in buttons[0]["onClick"]
        assert buttons[0]["onClick"]["action"]["function"] == "noxen_approve"

    def test_build_button_section_custom_actions(self, channel, plan):
        actions = [
            NotificationAction(label="Ship", action_type=ActionType.APPROVE, url="http://x"),
        ]
        section = channel._build_button_section(plan, actions=actions)
        buttons = section["widgets"][0]["buttonList"]["buttons"]
        assert len(buttons) == 1
        assert buttons[0]["text"] == "Ship"
