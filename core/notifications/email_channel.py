"""Email notification channel.

Uses aiosmtplib for async SMTP delivery with HTML-formatted messages.
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationChannel,
    NotificationResult,
)

logger = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):
    """Send notifications via SMTP (async).

    Requires:
        - smtp_host, smtp_port: SMTP server address.
        - smtp_user, smtp_password: Auth credentials.
        - smtp_from: Sender email address.
        - smtp_to: Recipient email address.
    """

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        smtp_from: str = "",
        smtp_to: str = "",
    ):
        self._host = smtp_host
        self._port = smtp_port
        self._user = smtp_user
        self._password = smtp_password
        self._from = smtp_from
        self._to = smtp_to

    # ── ABC implementation ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "email"

    def is_configured(self) -> bool:
        return bool(self._host and self._from and self._to)

    async def send_approval_request(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> NotificationResult:
        """Send approval request via email with HTML body."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        subject = f"[Noxen] Approval Request — {plan.project_name} ({plan.run_id})"
        html = self._build_approval_html(plan, actions)
        return await self._send_email(subject=subject, html_body=html)

    async def send_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
    ) -> NotificationResult:
        """Send a generic notification via email."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        color = {
            "info": "#2196F3",
            "warning": "#FF9800",
            "error": "#F44336",
            "success": "#4CAF50",
        }.get(level, "#2196F3")

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px;">
            <div style="background: {color}; color: white; padding: 12px 20px; border-radius: 4px 4px 0 0;">
                <h2 style="margin: 0;">{title}</h2>
            </div>
            <div style="padding: 20px; border: 1px solid #ddd; border-top: none; border-radius: 0 0 4px 4px;">
                <p>{message}</p>
            </div>
            <p style="color: #888; font-size: 12px; margin-top: 10px;">
                Sent by Noxen Notification Engine
            </p>
        </div>
        """
        subject = f"[Noxen] {title}"
        return await self._send_email(subject=subject, html_body=html)

    async def send_reminder(
        self,
        plan: ApprovalPlan,
        elapsed_minutes: int,
    ) -> NotificationResult:
        """Send a reminder email for a pending approval."""
        if not self.is_configured():
            return NotificationResult(
                success=False, channel=self.name, error="Not configured"
            )

        subject = f"[Noxen] REMINDER: Approval pending — {plan.project_name} ({elapsed_minutes}m)"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px;">
            <div style="background: #FF9800; color: white; padding: 12px 20px; border-radius: 4px 4px 0 0;">
                <h2 style="margin: 0;">⏰ Approval Reminder</h2>
            </div>
            <div style="padding: 20px; border: 1px solid #ddd; border-top: none;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 6px 0;"><b>Project:</b></td><td>{plan.project_name}</td></tr>
                    <tr><td style="padding: 6px 0;"><b>Run:</b></td><td><code>{plan.run_id}</code></td></tr>
                    <tr><td style="padding: 6px 0;"><b>Waiting:</b></td><td>{elapsed_minutes} minutes</td></tr>
                    <tr><td style="padding: 6px 0;"><b>Goals:</b></td><td>{plan.total_goals} awaiting decision</td></tr>
                </table>
                {self._build_buttons_html(plan)}
            </div>
            <p style="color: #888; font-size: 12px; margin-top: 10px;">
                Sent by Noxen Notification Engine
            </p>
        </div>
        """
        return await self._send_email(subject=subject, html_body=html)

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_approval_html(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> str:
        """Build HTML email body for approval request."""
        goals_html = ""
        for i, g in enumerate(plan.goals[:5], 1):
            goals_html += f"<li>{g.get('title', 'Untitled')}: {g.get('description', '')}</li>\n"
        if plan.total_goals > 5:
            goals_html += f"<li><em>...and {plan.total_goals - 5} more</em></li>\n"

        buttons_html = self._build_buttons_html(plan, actions)

        return f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px;">
            <div style="background: #1976D2; color: white; padding: 12px 20px; border-radius: 4px 4px 0 0;">
                <h2 style="margin: 0;">🔔 Noxen — Approval Request</h2>
            </div>
            <div style="padding: 20px; border: 1px solid #ddd; border-top: none;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 6px 0;"><b>Project:</b></td><td>{plan.project_name}</td></tr>
                    <tr><td style="padding: 6px 0;"><b>Run:</b></td><td><code>{plan.run_id}</code></td></tr>
                    <tr><td style="padding: 6px 0;"><b>Goals:</b></td><td>{plan.total_goals} ({plan.parallel_groups} parallel groups)</td></tr>
                    <tr><td style="padding: 6px 0;"><b>Est.:</b></td><td>{plan.estimated_time or 'N/A'}</td></tr>
                </table>
                <h3>Plan:</h3>
                <ol>{goals_html}</ol>
                {buttons_html}
            </div>
            <p style="color: #888; font-size: 12px; margin-top: 10px;">
                Sent by Noxen Notification Engine
            </p>
        </div>
        """

    def _build_buttons_html(
        self,
        plan: ApprovalPlan,
        actions: list[NotificationAction] | None = None,
    ) -> str:
        """Build HTML approve/reject buttons."""
        if actions:
            btns = ""
            for action in actions:
                color = "#4CAF50" if action.action_type == ActionType.APPROVE else "#F44336"
                url = action.url or "#"
                btns += (
                    f'<a href="{url}" style="display:inline-block; padding:10px 24px; '
                    f'background:{color}; color:white; text-decoration:none; '
                    f'border-radius:4px; margin-right:10px;">{action.label}</a>\n'
                )
            return f'<div style="margin-top: 20px;">{btns}</div>'

        # Default buttons
        approve_url = plan.approve_url or "#"
        reject_url = plan.reject_url or "#"
        return f"""
        <div style="margin-top: 20px;">
            <a href="{approve_url}" style="display:inline-block; padding:10px 24px;
               background:#4CAF50; color:white; text-decoration:none;
               border-radius:4px; margin-right:10px;">✅ Approve</a>
            <a href="{reject_url}" style="display:inline-block; padding:10px 24px;
               background:#F44336; color:white; text-decoration:none;
               border-radius:4px;">❌ Reject</a>
        </div>
        """

    async def _send_email(
        self,
        subject: str,
        html_body: str,
    ) -> NotificationResult:
        """Send an email via aiosmtplib."""
        try:
            import aiosmtplib

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._from
            msg["To"] = self._to
            msg.attach(MIMEText(html_body, "html"))

            response = await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                username=self._user or None,
                password=self._password or None,
                start_tls=True,
            )

            # aiosmtplib.send returns a tuple of (dict, str) or similar
            msg_id = msg.get("Message-ID", "")
            logger.info("Email sent: %s → %s", subject, self._to)
            return NotificationResult(
                success=True,
                channel=self.name,
                message_id=str(msg_id),
                raw_response=response,
            )

        except Exception as exc:
            logger.error("Email send failed: %s", exc)
            return NotificationResult(
                success=False, channel=self.name, error=str(exc)
            )
