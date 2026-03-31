"""Abstract base for notification channels.

Defines NotificationChannel ABC and shared dataclasses used by all
channel implementations (Telegram, Slack, Google Chat, Email).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ── Enums ────────────────────────────────────────────────────────────

class ActionType(str, enum.Enum):
    """Type of action associated with a notification."""
    APPROVE = "approve"
    REJECT = "reject"
    INFO = "info"
    REMINDER = "reminder"


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class NotificationAction:
    """A clickable action (button / link) in a notification.

    Attributes:
        label: Button text displayed to the user.
        action_type: Semantic action type (approve, reject, info, reminder).
        url: Optional callback URL for the action.
        payload: Arbitrary data attached to the action.
    """
    label: str
    action_type: ActionType
    url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalPlan:
    """Summary of the plan awaiting approval.

    Attributes:
        run_id: Unique execution run identifier.
        project_name: Human-readable project name.
        goals: List of goal summaries (title + description).
        total_goals: Number of goals in the plan.
        parallel_groups: Number of parallel execution groups.
        estimated_time: Human-readable time estimate.
        approve_url: URL to approve the plan.
        reject_url: URL to reject the plan.
    """
    run_id: str
    project_name: str
    goals: list[dict[str, str]] = field(default_factory=list)
    total_goals: int = 0
    parallel_groups: int = 0
    estimated_time: str = ""
    approve_url: str = ""
    reject_url: str = ""


@dataclass
class NotificationResult:
    """Result of sending a notification through a channel.

    Attributes:
        success: Whether the notification was sent successfully.
        channel: Channel name (telegram, slack, google_chat, email).
        message_id: Platform-specific message identifier.
        error: Error message if sending failed.
        timestamp: When the notification was sent.
        raw_response: Raw response from the platform API.
    """
    success: bool
    channel: str
    message_id: str = ""
    error: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    raw_response: Any = None


# ── Abstract Base ────────────────────────────────────────────────────

class NotificationChannel(ABC):
    """Abstract base class for notification channels.

    Each channel implementation must provide:
    - name: Human-readable channel name.
    - is_configured(): Whether the channel has all required settings.
    - send_approval_request(): Send an approval request notification.
    - send_notification(): Send a generic text notification.
    - send_reminder(): Send a reminder for a pending approval.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable channel name (e.g. 'telegram', 'slack')."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the channel has all required configuration."""
        ...

    @abstractmethod
    async def send_approval_request(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> NotificationResult:
        """Send an approval request with optional action buttons.

        Args:
            plan: The approval plan summary.
            actions: Optional list of actions (approve/reject buttons).

        Returns:
            NotificationResult with success status and platform details.
        """
        ...

    @abstractmethod
    async def send_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
    ) -> NotificationResult:
        """Send a generic notification message.

        Args:
            title: Notification title / subject.
            message: Notification body text.
            level: Severity level (info, warning, error, success).

        Returns:
            NotificationResult with success status.
        """
        ...

    @abstractmethod
    async def send_reminder(
        self,
        plan: ApprovalPlan,
        elapsed_minutes: int,
    ) -> NotificationResult:
        """Send a reminder for a pending approval request.

        Args:
            plan: The approval plan still awaiting action.
            elapsed_minutes: Minutes since the original request was sent.

        Returns:
            NotificationResult with success status.
        """
        ...
