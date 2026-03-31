"""Test suite per TelegramChannel — Step 5.2."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.notifications.telegram_channel import TelegramChannel
from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationResult,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def channel():
    return TelegramChannel(bot_token="123:ABC", chat_id="456")


@pytest.fixture
def unconfigured_channel():
    return TelegramChannel()


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
        assert channel.name == "telegram"

    def test_is_configured_true(self, channel):
        assert channel.is_configured() is True

    def test_is_configured_false_no_token(self):
        ch = TelegramChannel(chat_id="123")
        assert ch.is_configured() is False

    def test_is_configured_false_no_chat(self):
        ch = TelegramChannel(bot_token="tok")
        assert ch.is_configured() is False

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
    async def test_send_approval_success(self, channel, plan):
        mock_msg = MagicMock()
        mock_msg.message_id = 999
        mock_msg.to_dict.return_value = {"message_id": 999}

        mock_bot_instance = MagicMock()
        mock_bot_instance.send_message = AsyncMock(return_value=mock_msg)

        with patch("telegram.Bot", return_value=mock_bot_instance) as MockBot:
            result = await channel.send_approval_request(plan)

        assert result.success is True
        assert result.channel == "telegram"
        assert result.message_id == "999"
        MockBot.assert_called_once_with(token="123:ABC")
        mock_bot_instance.send_message.assert_called_once()

        call_kwargs = mock_bot_instance.send_message.call_args[1]
        assert call_kwargs["chat_id"] == "456"
        assert call_kwargs["parse_mode"] == "MarkdownV2"
        assert "Approval Request" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_approval_with_custom_actions(self, channel, plan):
        mock_msg = MagicMock()
        mock_msg.message_id = 100
        mock_msg.to_dict.return_value = {}

        mock_bot_instance = MagicMock()
        mock_bot_instance.send_message = AsyncMock(return_value=mock_msg)

        actions = [
            NotificationAction(label="Yes", action_type=ActionType.APPROVE, url="http://approve"),
            NotificationAction(label="No", action_type=ActionType.REJECT),
        ]

        with patch("telegram.Bot", return_value=mock_bot_instance):
            result = await channel.send_approval_request(plan, actions=actions)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_approval_api_error(self, channel, plan):
        mock_bot_instance = MagicMock()
        mock_bot_instance.send_message = AsyncMock(side_effect=Exception("API error"))

        with patch("telegram.Bot", return_value=mock_bot_instance):
            result = await channel.send_approval_request(plan)

        assert result.success is False
        assert "API error" in result.error


# ── Generic notification ─────────────────────────────────────────────

class TestNotification:
    @pytest.mark.asyncio
    async def test_send_notification_info(self, channel):
        mock_msg = MagicMock()
        mock_msg.message_id = 200
        mock_msg.to_dict.return_value = {}

        mock_bot_instance = MagicMock()
        mock_bot_instance.send_message = AsyncMock(return_value=mock_msg)

        with patch("telegram.Bot", return_value=mock_bot_instance):
            result = await channel.send_notification("Test Title", "Test body", level="info")

        assert result.success is True
        text = mock_bot_instance.send_message.call_args[1]["text"]
        assert "ℹ️" in text

    @pytest.mark.asyncio
    async def test_send_notification_levels(self, channel):
        mock_msg = MagicMock()
        mock_msg.message_id = 201
        mock_msg.to_dict.return_value = {}

        mock_bot_instance = MagicMock()
        mock_bot_instance.send_message = AsyncMock(return_value=mock_msg)

        for level, emoji in [("warning", "⚠️"), ("error", "🔴"), ("success", "✅")]:
            with patch("telegram.Bot", return_value=mock_bot_instance):
                result = await channel.send_notification("T", "M", level=level)
            assert result.success is True
            text = mock_bot_instance.send_message.call_args[1]["text"]
            assert emoji in text


# ── Reminder ─────────────────────────────────────────────────────────

class TestReminder:
    @pytest.mark.asyncio
    async def test_send_reminder(self, channel, plan):
        mock_msg = MagicMock()
        mock_msg.message_id = 300
        mock_msg.to_dict.return_value = {}

        mock_bot_instance = MagicMock()
        mock_bot_instance.send_message = AsyncMock(return_value=mock_msg)

        with patch("telegram.Bot", return_value=mock_bot_instance):
            result = await channel.send_reminder(plan, 30)

        assert result.success is True
        text = mock_bot_instance.send_message.call_args[1]["text"]
        assert "Reminder" in text
        assert "30 min" in text


# ── Helpers ──────────────────────────────────────────────────────────

class TestHelpers:
    def test_escape_md(self):
        assert TelegramChannel._escape_md("hello_world") == "hello\\_world"
        assert TelegramChannel._escape_md("a*b") == "a\\*b"
        assert TelegramChannel._escape_md("normal") == "normal"

    def test_format_approval_message(self, channel, plan):
        text = channel._format_approval_message(plan)
        assert "Approval Request" in text
        assert "run\\-42" in text or "run-42" in text
        assert "TestProject" in text or "TestProject" in text.replace("\\", "")

    def test_format_approval_message_many_goals(self, channel):
        plan = ApprovalPlan(
            run_id="r",
            project_name="P",
            goals=[{"title": f"Goal {i}", "description": "d"} for i in range(8)],
            total_goals=8,
            parallel_groups=2,
        )
        text = channel._format_approval_message(plan)
        assert "more" in text  # shows "...and 3 more"

    def test_build_inline_keyboard_with_urls(self, channel, plan):
        kb = channel._build_inline_keyboard(plan)
        assert "inline_keyboard" in kb
        row = kb["inline_keyboard"][0]
        assert len(row) == 2
        assert row[0]["text"] == "✅ Approve"
        assert row[0]["url"] == plan.approve_url

    def test_build_inline_keyboard_without_urls(self, channel):
        plan = ApprovalPlan(run_id="r", project_name="P")
        kb = channel._build_inline_keyboard(plan)
        row = kb["inline_keyboard"][0]
        assert row[0]["callback_data"] == "approve"
        assert row[1]["callback_data"] == "reject"

    def test_build_inline_keyboard_custom_actions(self, channel, plan):
        actions = [
            NotificationAction(label="Go", action_type=ActionType.APPROVE, url="http://go"),
        ]
        kb = channel._build_inline_keyboard(plan, actions=actions)
        row = kb["inline_keyboard"][0]
        assert len(row) == 1
        assert row[0]["text"] == "Go"
        assert row[0]["url"] == "http://go"
