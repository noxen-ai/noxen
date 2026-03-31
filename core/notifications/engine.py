"""Notification Engine — orchestrates multi-channel notifications.

Manages all configured notification channels, broadcasts approval requests,
generic notifications, and reminders. Tracks pending approvals with
optional Qdrant persistence.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.notifications.base import (
    ApprovalPlan,
    NotificationAction,
    NotificationChannel,
    NotificationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    """Tracks a pending approval request.

    Attributes:
        approval_id: Unique ID for this approval request.
        plan: The approval plan sent.
        results: Per-channel send results.
        created_at: When the request was sent.
        reminder_count: Number of reminders sent.
        resolved: Whether the approval has been resolved.
        resolution: "approved", "rejected", or "" if pending.
    """
    approval_id: str
    plan: ApprovalPlan
    results: list[NotificationResult] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    reminder_count: int = 0
    resolved: bool = False
    resolution: str = ""


class NotificationEngine:
    """Orchestrates multi-channel notifications.

    Usage:
        engine = NotificationEngine()
        engine.add_channel(TelegramChannel(...))
        engine.add_channel(SlackChannel(...))
        await engine.send_approval_request(plan)
    """

    def __init__(self, qdrant_persist: bool = False):
        self._channels: list[NotificationChannel] = []
        self._pending: dict[str, PendingApproval] = {}
        self._qdrant_persist = qdrant_persist

    @classmethod
    def for_tenant(cls, tenant) -> NotificationEngine:
        """Create a NotificationEngine configured for a specific tenant.

        Reads the tenant's config to set up notification channels
        (Telegram, Slack, Google Chat, Email). Returns an engine
        with only the channels that are configured.
        """
        engine = cls()
        config = getattr(tenant, "config", None)
        if not config:
            return engine

        # Telegram
        if config.telegram_bot_token and config.telegram_chat_id:
            from core.notifications.telegram_channel import TelegramChannel
            engine.add_channel(TelegramChannel(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
            ))

        # Slack
        if config.slack_bot_token and config.slack_channel_id:
            from core.notifications.slack_channel import SlackChannel
            engine.add_channel(SlackChannel(
                bot_token=config.slack_bot_token,
                channel_id=config.slack_channel_id,
            ))

        # Google Chat
        if config.google_chat_webhook_url:
            from core.notifications.google_chat_channel import GoogleChatChannel
            engine.add_channel(GoogleChatChannel(
                webhook_url=config.google_chat_webhook_url,
            ))

        # Email
        if config.smtp_host and config.smtp_to:
            from core.notifications.email_channel import EmailChannel
            # TenantConfig.smtp_to is list[str], EmailChannel wants str
            to_addr = config.smtp_to if isinstance(config.smtp_to, str) else ", ".join(config.smtp_to)
            engine.add_channel(EmailChannel(
                smtp_host=config.smtp_host,
                smtp_to=to_addr,
            ))

        return engine

    # ── Channel management ───────────────────────────────────────────

    def add_channel(self, channel: NotificationChannel) -> None:
        """Register a notification channel."""
        self._channels.append(channel)
        logger.info("Notification channel added: %s (configured=%s)", channel.name, channel.is_configured())

    def remove_channel(self, channel_name: str) -> bool:
        """Remove a channel by name. Returns True if found and removed."""
        before = len(self._channels)
        self._channels = [c for c in self._channels if c.name != channel_name]
        removed = len(self._channels) < before
        if removed:
            logger.info("Notification channel removed: %s", channel_name)
        return removed

    def get_channels(self) -> list[dict[str, Any]]:
        """Return list of channels with their configuration status."""
        return [
            {"name": c.name, "configured": c.is_configured()}
            for c in self._channels
        ]

    def get_configured_channels(self) -> list[NotificationChannel]:
        """Return only channels that are properly configured."""
        return [c for c in self._channels if c.is_configured()]

    # ── Broadcast methods ────────────────────────────────────────────

    async def send_approval_request(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> PendingApproval:
        """Broadcast approval request to all configured channels.

        Returns a PendingApproval tracking the request.
        """
        approval_id = str(uuid.uuid4())[:8]
        pending = PendingApproval(
            approval_id=approval_id,
            plan=plan,
        )

        configured = self.get_configured_channels()
        if not configured:
            logger.warning("No configured notification channels — approval request not sent")
            pending.results.append(
                NotificationResult(success=False, channel="none", error="No configured channels")
            )
            self._pending[approval_id] = pending
            return pending

        # Send to all channels concurrently
        tasks = [ch.send_approval_request(plan, actions) for ch in configured]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                pending.results.append(
                    NotificationResult(
                        success=False,
                        channel=configured[i].name,
                        error=str(result),
                    )
                )
            else:
                pending.results.append(result)

        self._pending[approval_id] = pending

        # Optional Qdrant persistence
        if self._qdrant_persist:
            await self._persist_to_qdrant(pending)

        success_count = sum(1 for r in pending.results if r.success)
        logger.info(
            "Approval request %s sent to %d/%d channels",
            approval_id, success_count, len(configured),
        )
        return pending

    async def send_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
    ) -> list[NotificationResult]:
        """Broadcast a generic notification to all configured channels."""
        configured = self.get_configured_channels()
        if not configured:
            return [NotificationResult(success=False, channel="none", error="No configured channels")]

        tasks = [ch.send_notification(title, message, level) for ch in configured]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[NotificationResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final.append(
                    NotificationResult(
                        success=False,
                        channel=configured[i].name,
                        error=str(result),
                    )
                )
            else:
                final.append(result)
        return final

    async def send_reminder(
        self,
        approval_id: str,
    ) -> list[NotificationResult]:
        """Send a reminder for a pending approval.

        Args:
            approval_id: ID of the pending approval.

        Returns:
            List of NotificationResult for each channel.
        """
        pending = self._pending.get(approval_id)
        if not pending:
            return [NotificationResult(success=False, channel="none", error=f"Approval {approval_id} not found")]

        if pending.resolved:
            return [NotificationResult(success=False, channel="none", error="Approval already resolved")]

        elapsed = int((datetime.now() - pending.created_at).total_seconds() / 60)
        configured = self.get_configured_channels()
        if not configured:
            return [NotificationResult(success=False, channel="none", error="No configured channels")]

        tasks = [ch.send_reminder(pending.plan, elapsed) for ch in configured]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[NotificationResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final.append(
                    NotificationResult(
                        success=False,
                        channel=configured[i].name,
                        error=str(result),
                    )
                )
            else:
                final.append(result)

        pending.reminder_count += 1
        return final

    # ── Approval resolution ──────────────────────────────────────────

    def resolve_approval(self, approval_id: str, resolution: str) -> bool:
        """Mark an approval as resolved.

        Args:
            approval_id: ID of the pending approval.
            resolution: "approved" or "rejected".

        Returns:
            True if resolved, False if not found or already resolved.
        """
        pending = self._pending.get(approval_id)
        if not pending or pending.resolved:
            return False

        pending.resolved = True
        pending.resolution = resolution
        logger.info("Approval %s resolved: %s", approval_id, resolution)
        return True

    # ── Status queries ───────────────────────────────────────────────

    def get_pending_approvals(self) -> list[PendingApproval]:
        """Return all unresolved pending approvals."""
        return [p for p in self._pending.values() if not p.resolved]

    def get_approval(self, approval_id: str) -> PendingApproval | None:
        """Get a specific approval by ID."""
        return self._pending.get(approval_id)

    def get_status(self) -> dict[str, Any]:
        """Return engine status summary."""
        return {
            "channels": self.get_channels(),
            "configured_count": len(self.get_configured_channels()),
            "pending_approvals": len(self.get_pending_approvals()),
            "total_approvals": len(self._pending),
        }

    # ── Persistence ──────────────────────────────────────────────────

    async def _persist_to_qdrant(self, pending: PendingApproval) -> None:
        """Persist approval to Qdrant 'approvals' collection."""
        try:
            from core.qdrant_client import qdrant_client

            data = {
                "approval_id": pending.approval_id,
                "run_id": pending.plan.run_id,
                "project_name": pending.plan.project_name,
                "total_goals": pending.plan.total_goals,
                "created_at": pending.created_at.isoformat(),
                "channels_sent": [r.channel for r in pending.results if r.success],
                "channels_failed": [r.channel for r in pending.results if not r.success],
            }

            text = f"Approval request for {pending.plan.project_name} run {pending.plan.run_id}"
            await qdrant_client.add_to_collection(
                collection_name="approvals",
                texts=[text],
                metadatas=[data],
            )
            logger.info("Approval %s persisted to Qdrant", pending.approval_id)
        except Exception as exc:
            logger.warning("Failed to persist approval to Qdrant: %s", exc)
