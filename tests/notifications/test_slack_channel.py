"""Test suite per SlackChannel — Step 5.3."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.notifications.slack_channel import SlackChannel
from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationResult,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def channel():
    return SlackChannel(bot_token="xoxb-test-token", channel_id="C12345")


@pytest.fixture
def unconfigured_channel():
    return SlackChannel()


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


@pytest.fixture
def mock_slack_response():
    resp = MagicMock()
    resp.get.return_value = "1234567890.123456"
    resp.__iter__ = MagicMock(return_value=iter([("ts", "1234567890.123456")]))
    resp.__bool__ = MagicMock(return_value=True)
    return resp


# ── Properties ───────────────────────────────────────────────────────

class TestProperties:
    def test_name(self, channel):
        assert channel.name == "slack"

    def test_is_configured_true(self, channel):
        assert channel.is_configured() is True

    def test_is_configured_false_no_token(self):
        assert SlackChannel(channel_id="C1").is_configured() is False

    def test_is_configured_false_no_channel(self):
        assert SlackChannel(bot_token="xoxb-x").is_configured() is False

    def test_is_configured_false_empty(self, unconfigured_channel):
        assert unconfigured_channel.is_configured() is False


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
    async def test_send_approval_success(self, channel, plan, mock_slack_response):
        mock_client = MagicMock()
        mock_client.chat_postMessage = AsyncMock(return_value=mock_slack_response)

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client):
            result = await channel.send_approval_request(plan)

        assert result.success is True
        assert result.channel == "slack"
        assert result.message_id == "1234567890.123456"
        mock_client.chat_postMessage.assert_called_once()

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "C12345"
        assert "blocks" in call_kwargs
        assert any("Approval Request" in str(b) for b in call_kwargs["blocks"])

    @pytest.mark.asyncio
    async def test_send_approval_with_custom_actions(self, channel, plan, mock_slack_response):
        mock_client = MagicMock()
        mock_client.chat_postMessage = AsyncMock(return_value=mock_slack_response)

        actions = [
            NotificationAction(label="Ship It", action_type=ActionType.APPROVE, url="http://approve"),
            NotificationAction(label="Nope", action_type=ActionType.REJECT),
        ]

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client):
            result = await channel.send_approval_request(plan, actions=actions)

        assert result.success is True
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        action_blocks = [b for b in call_kwargs["blocks"] if b.get("type") == "actions"]
        assert len(action_blocks) == 1
        elements = action_blocks[0]["elements"]
        assert elements[0]["text"]["text"] == "Ship It"

    @pytest.mark.asyncio
    async def test_send_approval_api_error(self, channel, plan):
        mock_client = MagicMock()
        mock_client.chat_postMessage = AsyncMock(side_effect=Exception("Slack API error"))

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client):
            result = await channel.send_approval_request(plan)

        assert result.success is False
        assert "Slack API error" in result.error


# ── Generic notification ─────────────────────────────────────────────

class TestNotification:
    @pytest.mark.asyncio
    async def test_send_notification_info(self, channel, mock_slack_response):
        mock_client = MagicMock()
        mock_client.chat_postMessage = AsyncMock(return_value=mock_slack_response)

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client):
            result = await channel.send_notification("Deploy", "Done!", level="info")

        assert result.success is True
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert any(":information_source:" in str(b) for b in call_kwargs["blocks"])

    @pytest.mark.asyncio
    async def test_send_notification_levels(self, channel, mock_slack_response):
        level_emojis = {
            "warning": ":warning:",
            "error": ":red_circle:",
            "success": ":white_check_mark:",
        }
        mock_client = MagicMock()
        mock_client.chat_postMessage = AsyncMock(return_value=mock_slack_response)

        for level, emoji in level_emojis.items():
            with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client):
                result = await channel.send_notification("T", "M", level=level)
            assert result.success is True
            call_kwargs = mock_client.chat_postMessage.call_args[1]
            assert any(emoji in str(b) for b in call_kwargs["blocks"])


# ── Reminder ─────────────────────────────────────────────────────────

class TestReminder:
    @pytest.mark.asyncio
    async def test_send_reminder(self, channel, plan, mock_slack_response):
        mock_client = MagicMock()
        mock_client.chat_postMessage = AsyncMock(return_value=mock_slack_response)

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client):
            result = await channel.send_reminder(plan, 45)

        assert result.success is True
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "45 min" in str(call_kwargs["blocks"])


# ── Block builders ───────────────────────────────────────────────────

class TestBlockBuilders:
    def test_build_approval_blocks(self, channel, plan):
        blocks = channel._build_approval_blocks(plan)
        types = [b["type"] for b in blocks]
        assert "header" in types
        assert "section" in types
        assert "divider" in types
        assert "actions" in types

    def test_build_approval_blocks_many_goals(self, channel):
        plan = ApprovalPlan(
            run_id="r",
            project_name="P",
            goals=[{"title": f"G{i}", "description": "d"} for i in range(8)],
            total_goals=8,
            parallel_groups=2,
        )
        blocks = channel._build_approval_blocks(plan)
        section = [b for b in blocks if b["type"] == "section"][0]
        assert "more" in section["text"]["text"]

    def test_build_action_buttons_with_urls(self, channel, plan):
        buttons = channel._build_action_buttons(plan)
        assert len(buttons) == 1
        elements = buttons[0]["elements"]
        assert len(elements) == 2
        assert elements[0]["style"] == "primary"
        assert elements[0]["url"] == plan.approve_url
        assert elements[1]["style"] == "danger"
        assert elements[1]["url"] == plan.reject_url

    def test_build_action_buttons_without_urls(self, channel):
        plan = ApprovalPlan(run_id="r", project_name="P")
        buttons = channel._build_action_buttons(plan)
        elements = buttons[0]["elements"]
        assert "url" not in elements[0]
        assert elements[0]["action_id"] == "noxen_approve"
