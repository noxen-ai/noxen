"""Noxen - Notification Engine package.

Phase 5: Multi-channel notifications (Telegram, Slack, Google Chat, Email).
"""

from core.notifications.base import (
    NotificationChannel,
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationResult,
)
from core.notifications.telegram_channel import TelegramChannel
from core.notifications.slack_channel import SlackChannel
from core.notifications.google_chat_channel import GoogleChatChannel
from core.notifications.email_channel import EmailChannel
from core.notifications.engine import NotificationEngine, PendingApproval

__all__ = [
    "NotificationChannel",
    "ActionType",
    "ApprovalPlan",
    "NotificationAction",
    "NotificationResult",
    "TelegramChannel",
    "SlackChannel",
    "GoogleChatChannel",
    "EmailChannel",
    "NotificationEngine",
    "PendingApproval",
]
