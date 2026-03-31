"""Telegram notification channel.

Uses python-telegram-bot to send approval requests, notifications,
and reminders to a configured Telegram chat.
"""

from __future__ import annotations

import logging
from typing import Any

from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationChannel,
    NotificationResult,
)

logger = logging.getLogger(__name__)


class TelegramChannel(NotificationChannel):
    """Send notifications via Telegram Bot API.

    Requires:
        - bot_token: Telegram Bot API token (from @BotFather).
        - chat_id: Target chat/group/channel ID.
    """

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self._bot_token = bot_token
        self._chat_id = chat_id

    # ── ABC implementation ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "telegram"

    def is_configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    async def send_approval_request(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> NotificationResult:
        """Send approval request with inline keyboard buttons."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        text = self._format_approval_message(plan)
        reply_markup = self._build_inline_keyboard(plan, actions)
        return await self._send_message(text, reply_markup=reply_markup)

    async def send_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
    ) -> NotificationResult:
        """Send a generic notification."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        emoji = {"info": "ℹ️", "warning": "⚠️", "error": "🔴", "success": "✅"}.get(
            level, "ℹ️"
        )
        text = f"{emoji} *{self._escape_md(title)}*\n\n{self._escape_md(message)}"
        return await self._send_message(text)

    async def send_reminder(
        self,
        plan: ApprovalPlan,
        elapsed_minutes: int,
    ) -> NotificationResult:
        """Send a reminder for a pending approval."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        text = (
            f"⏰ *Reminder: Approval Pending*\n\n"
            f"Project: *{self._escape_md(plan.project_name)}*\n"
            f"Run: `{plan.run_id}`\n"
            f"Waiting: *{elapsed_minutes} min*\n\n"
            f"_{self._escape_md(f'{plan.total_goals} goals awaiting your decision')}_"
        )
        reply_markup = self._build_inline_keyboard(plan)
        return await self._send_message(text, reply_markup=reply_markup)

    # ── Internal helpers ─────────────────────────────────────────────

    def _format_approval_message(self, plan: ApprovalPlan) -> str:
        """Format the approval request message in Markdown."""
        goals_text = ""
        for i, g in enumerate(plan.goals[:5], 1):
            title = self._escape_md(g.get("title", "Untitled"))
            goals_text += f"  {i}\\. {title}\n"
        if plan.total_goals > 5:
            goals_text += f"  _\\.\\.\\.and {plan.total_goals - 5} more_\n"

        return (
            f"🔔 *Noxen — Approval Request*\n\n"
            f"📁 Project: *{self._escape_md(plan.project_name)}*\n"
            f"🆔 Run: `{plan.run_id}`\n"
            f"🎯 Goals: *{plan.total_goals}* "
            f"\\({plan.parallel_groups} parallel groups\\)\n"
            f"⏱️ Est\\.: {self._escape_md(plan.estimated_time or 'N/A')}\n\n"
            f"*Plan:*\n{goals_text}"
        )

    def _build_inline_keyboard(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> dict[str, Any] | None:
        """Build Telegram InlineKeyboardMarkup dict.

        If approve_url / reject_url are set, uses URL buttons.
        Otherwise, uses callback_data buttons.
        """
        if actions:
            buttons = []
            for action in actions:
                btn: dict[str, str] = {"text": action.label}
                if action.url:
                    btn["url"] = action.url
                else:
                    btn["callback_data"] = action.action_type.value
                buttons.append(btn)
            return {"inline_keyboard": [buttons]}

        # Default: approve/reject buttons
        row = []
        if plan.approve_url:
            row.append({"text": "✅ Approve", "url": plan.approve_url})
        else:
            row.append({"text": "✅ Approve", "callback_data": "approve"})

        if plan.reject_url:
            row.append({"text": "❌ Reject", "url": plan.reject_url})
        else:
            row.append({"text": "❌ Reject", "callback_data": "reject"})

        return {"inline_keyboard": [row]}

    async def _send_message(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> NotificationResult:
        """Send a message via Telegram Bot API."""
        try:
            from telegram import Bot

            bot = Bot(token=self._bot_token)
            kwargs: dict[str, Any] = {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "MarkdownV2",
            }
            if reply_markup:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                rows = []
                for row_data in reply_markup.get("inline_keyboard", []):
                    row = []
                    for btn_data in row_data:
                        btn_kwargs: dict[str, str] = {"text": btn_data["text"]}
                        if "url" in btn_data:
                            btn_kwargs["url"] = btn_data["url"]
                        if "callback_data" in btn_data:
                            btn_kwargs["callback_data"] = btn_data["callback_data"]
                        row.append(InlineKeyboardButton(**btn_kwargs))
                    rows.append(row)
                kwargs["reply_markup"] = InlineKeyboardMarkup(rows)

            msg = await bot.send_message(**kwargs)
            logger.info("Telegram message sent: %s", msg.message_id)
            return NotificationResult(
                success=True,
                channel=self.name,
                message_id=str(msg.message_id),
                raw_response=msg.to_dict() if hasattr(msg, "to_dict") else None,
            )

        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            return NotificationResult(
                success=False, channel=self.name, error=str(exc)
            )

    @staticmethod
    def _escape_md(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2."""
        special = r"_*[]()~`>#+-=|{}.!"
        result = ""
        for ch in text:
            if ch in special:
                result += f"\\{ch}"
            else:
                result += ch
        return result
