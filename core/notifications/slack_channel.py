"""Slack notification channel.

Uses slack-sdk (WebClient async) to send approval requests,
notifications, and reminders via Slack Block Kit.
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


class SlackChannel(NotificationChannel):
    """Send notifications via Slack Bot API (Block Kit).

    Requires:
        - bot_token: Slack Bot User OAuth Token (xoxb-...).
        - channel_id: Target Slack channel ID (C...).
    """

    def __init__(self, bot_token: str = "", channel_id: str = ""):
        self._bot_token = bot_token
        self._channel_id = channel_id

    # ── ABC implementation ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "slack"

    def is_configured(self) -> bool:
        return bool(self._bot_token and self._channel_id)

    async def send_approval_request(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> NotificationResult:
        """Send approval request with Block Kit buttons."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        blocks = self._build_approval_blocks(plan, actions)
        text = f"Noxen — Approval Request: {plan.project_name}"
        return await self._send_blocks(text=text, blocks=blocks)

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

        emoji = {"info": ":information_source:", "warning": ":warning:",
                 "error": ":red_circle:", "success": ":white_check_mark:"}.get(
            level, ":information_source:"
        )
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{title}", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{emoji} {message}"},
            },
        ]
        return await self._send_blocks(text=f"{title}: {message}", blocks=blocks)

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

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":alarm_clock: Approval Reminder", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Project:* {plan.project_name}\n"
                        f"*Run:* `{plan.run_id}`\n"
                        f"*Waiting:* {elapsed_minutes} min\n"
                        f"*Goals:* {plan.total_goals} awaiting your decision"
                    ),
                },
            },
            *self._build_action_buttons(plan),
        ]
        return await self._send_blocks(
            text=f"Reminder: Approval pending for {plan.project_name} ({elapsed_minutes}m)",
            blocks=blocks,
        )

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_approval_blocks(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks for approval request."""
        # Header
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":bell: Noxen — Approval Request",
                    "emoji": True,
                },
            },
        ]

        # Plan summary section
        goals_text = ""
        for i, g in enumerate(plan.goals[:5], 1):
            goals_text += f"  {i}. {g.get('title', 'Untitled')}\n"
        if plan.total_goals > 5:
            goals_text += f"  ...and {plan.total_goals - 5} more\n"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Project:* {plan.project_name}\n"
                    f"*Run:* `{plan.run_id}`\n"
                    f"*Goals:* {plan.total_goals} ({plan.parallel_groups} parallel groups)\n"
                    f"*Est.:* {plan.estimated_time or 'N/A'}\n\n"
                    f"*Plan:*\n{goals_text}"
                ),
            },
        })

        # Divider
        blocks.append({"type": "divider"})

        # Action buttons
        if actions:
            elements = []
            for action in actions:
                btn: dict[str, Any] = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": action.label, "emoji": True},
                    "action_id": f"noxen_{action.action_type.value}",
                }
                if action.url:
                    btn["url"] = action.url
                style = "primary" if action.action_type == ActionType.APPROVE else "danger"
                if action.action_type in (ActionType.APPROVE, ActionType.REJECT):
                    btn["style"] = style
                elements.append(btn)
            blocks.append({"type": "actions", "elements": elements})
        else:
            blocks.extend(self._build_action_buttons(plan))

        return blocks

    def _build_action_buttons(self, plan: ApprovalPlan) -> list[dict[str, Any]]:
        """Build default approve/reject action buttons."""
        elements: list[dict[str, Any]] = []

        approve_btn: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
            "style": "primary",
            "action_id": "noxen_approve",
        }
        if plan.approve_url:
            approve_btn["url"] = plan.approve_url
        elements.append(approve_btn)

        reject_btn: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
            "style": "danger",
            "action_id": "noxen_reject",
        }
        if plan.reject_url:
            reject_btn["url"] = plan.reject_url
        elements.append(reject_btn)

        return [{"type": "actions", "elements": elements}]

    async def _send_blocks(
        self,
        text: str,
        blocks: list[dict[str, Any]],
    ) -> NotificationResult:
        """Send blocks via Slack WebClient."""
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self._bot_token)
            response = await client.chat_postMessage(
                channel=self._channel_id,
                text=text,
                blocks=blocks,
            )

            msg_ts = response.get("ts", "") if response else ""
            logger.info("Slack message sent: %s", msg_ts)
            return NotificationResult(
                success=True,
                channel=self.name,
                message_id=str(msg_ts),
                raw_response=dict(response) if response else None,
            )

        except Exception as exc:
            logger.error("Slack send failed: %s", exc)
            return NotificationResult(
                success=False, channel=self.name, error=str(exc)
            )
