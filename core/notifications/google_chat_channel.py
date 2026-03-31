"""Google Chat notification channel.

Uses aiohttp to POST Card v2 messages to a Google Chat webhook URL.
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


class GoogleChatChannel(NotificationChannel):
    """Send notifications via Google Chat Incoming Webhook.

    Requires:
        - webhook_url: Google Chat space webhook URL.
    """

    def __init__(self, webhook_url: str = ""):
        self._webhook_url = webhook_url

    # ── ABC implementation ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "google_chat"

    def is_configured(self) -> bool:
        return bool(self._webhook_url)

    async def send_approval_request(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> NotificationResult:
        """Send approval request as a Google Chat Card v2."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        card = self._build_approval_card(plan, actions)
        return await self._post_webhook(card)

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
        payload = {
            "cardsV2": [
                {
                    "cardId": "notification",
                    "card": {
                        "header": {
                            "title": f"{emoji} {title}",
                            "subtitle": f"Level: {level}",
                        },
                        "sections": [
                            {
                                "widgets": [
                                    {
                                        "textParagraph": {"text": message},
                                    }
                                ]
                            }
                        ],
                    },
                }
            ]
        }
        return await self._post_webhook(payload)

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

        payload = {
            "cardsV2": [
                {
                    "cardId": "reminder",
                    "card": {
                        "header": {
                            "title": "⏰ Approval Reminder",
                            "subtitle": plan.project_name,
                        },
                        "sections": [
                            {
                                "widgets": [
                                    {
                                        "textParagraph": {
                                            "text": (
                                                f"<b>Run:</b> {plan.run_id}<br>"
                                                f"<b>Waiting:</b> {elapsed_minutes} min<br>"
                                                f"<b>Goals:</b> {plan.total_goals} awaiting decision"
                                            )
                                        }
                                    }
                                ]
                            },
                            self._build_button_section(plan),
                        ],
                    },
                }
            ]
        }
        return await self._post_webhook(payload)

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_approval_card(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> dict[str, Any]:
        """Build Google Chat Card v2 payload for approval request."""
        goals_html = ""
        for i, g in enumerate(plan.goals[:5], 1):
            goals_html += f"{i}. {g.get('title', 'Untitled')}<br>"
        if plan.total_goals > 5:
            goals_html += f"<i>...and {plan.total_goals - 5} more</i><br>"

        card: dict[str, Any] = {
            "cardsV2": [
                {
                    "cardId": "approval_request",
                    "card": {
                        "header": {
                            "title": "🔔 Noxen — Approval Request",
                            "subtitle": plan.project_name,
                        },
                        "sections": [
                            {
                                "header": "Plan Summary",
                                "widgets": [
                                    {
                                        "decoratedText": {
                                            "topLabel": "Run ID",
                                            "text": plan.run_id,
                                        }
                                    },
                                    {
                                        "decoratedText": {
                                            "topLabel": "Goals",
                                            "text": f"{plan.total_goals} ({plan.parallel_groups} parallel groups)",
                                        }
                                    },
                                    {
                                        "decoratedText": {
                                            "topLabel": "Estimated Time",
                                            "text": plan.estimated_time or "N/A",
                                        }
                                    },
                                    {
                                        "textParagraph": {"text": goals_html},
                                    },
                                ],
                            },
                            self._build_button_section(plan, actions),
                        ],
                    },
                }
            ]
        }
        return card

    def _build_button_section(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> dict[str, Any]:
        """Build a section with action buttons."""
        if actions:
            buttons = []
            for action in actions:
                btn: dict[str, Any] = {
                    "text": action.label,
                    "onClick": {},
                }
                if action.url:
                    btn["onClick"]["openLink"] = {"url": action.url}
                else:
                    btn["onClick"]["action"] = {
                        "function": f"noxen_{action.action_type.value}",
                    }
                color = (
                    {"red": 0.2, "green": 0.7, "blue": 0.3, "alpha": 1}
                    if action.action_type == ActionType.APPROVE
                    else {"red": 0.8, "green": 0.2, "blue": 0.2, "alpha": 1}
                )
                if action.action_type in (ActionType.APPROVE, ActionType.REJECT):
                    btn["color"] = color
                buttons.append(btn)
            return {"widgets": [{"buttonList": {"buttons": buttons}}]}

        # Default approve/reject buttons
        approve_click: dict[str, Any] = {}
        reject_click: dict[str, Any] = {}

        if plan.approve_url:
            approve_click["openLink"] = {"url": plan.approve_url}
        else:
            approve_click["action"] = {"function": "noxen_approve"}

        if plan.reject_url:
            reject_click["openLink"] = {"url": plan.reject_url}
        else:
            reject_click["action"] = {"function": "noxen_reject"}

        return {
            "widgets": [
                {
                    "buttonList": {
                        "buttons": [
                            {
                                "text": "✅ Approve",
                                "onClick": approve_click,
                                "color": {"red": 0.2, "green": 0.7, "blue": 0.3, "alpha": 1},
                            },
                            {
                                "text": "❌ Reject",
                                "onClick": reject_click,
                                "color": {"red": 0.8, "green": 0.2, "blue": 0.2, "alpha": 1},
                            },
                        ]
                    }
                }
            ]
        }

    async def _post_webhook(self, payload: dict[str, Any]) -> NotificationResult:
        """POST JSON payload to the Google Chat webhook."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.text()
                    if resp.status == 200:
                        import json
                        data = json.loads(body) if body else {}
                        msg_name = data.get("name", "")
                        logger.info("Google Chat message sent: %s", msg_name)
                        return NotificationResult(
                            success=True,
                            channel=self.name,
                            message_id=msg_name,
                            raw_response=data,
                        )
                    else:
                        logger.error("Google Chat webhook error %s: %s", resp.status, body)
                        return NotificationResult(
                            success=False,
                            channel=self.name,
                            error=f"HTTP {resp.status}: {body[:200]}",
                        )

        except Exception as exc:
            logger.error("Google Chat send failed: %s", exc)
            return NotificationResult(
                success=False, channel=self.name, error=str(exc)
            )
