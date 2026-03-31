"""Approval Widget — plan approval gate.

Keyboard-driven approval interface for execution plans.
Approve or reject plans directly from the TUI.
"""

from __future__ import annotations

import httpx
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, Static


class ApprovalWidget(Widget):
    """Plan approval interface.

    Shows pending plans with goals, priorities, complexity.
    Keyboard: a -> approve all, r -> reject, d -> details.
    """

    DEFAULT_CSS = """
    ApprovalWidget {
        height: 100%;
    }

    ApprovalWidget Horizontal {
        height: 3;
        padding: 0 1;
    }
    """

    def __init__(self, api_base_url: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url
        self._current_approval: dict | None = None

    def compose(self) -> ComposeResult:
        yield Label("[bold]● Approval Gate[/bold]", classes="panel-title")
        yield Static("No pending plans", id="approval-status")
        yield DataTable(id="goals-preview")
        with Horizontal():
            yield Button(
                "Approve all [a]",
                id="btn-approve",
                variant="success",
                disabled=True,
            )
            yield Button(
                "Reject [r]",
                id="btn-reject",
                variant="error",
                disabled=True,
            )

    async def on_mount(self) -> None:
        table = self.query_one("#goals-preview", DataTable)
        table.add_column("Priority", width=10)
        table.add_column("Goal", width=40)
        table.add_column("Complexity", width=12)
        await self.refresh_data()

    async def refresh_data(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/api/notifications/approvals",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    approvals = response.json().get("approvals", [])
                    pending = [a for a in approvals if a.get("status") == "pending"]
                    if pending:
                        self._render_approval(pending[0])
                    else:
                        self._show_no_approval()
        except Exception:
            self._show_no_approval()

    def _render_approval(self, approval: dict) -> None:
        self._current_approval = approval

        status = self.query_one("#approval-status", Static)
        status.update(
            f"[yellow]Pending plan:[/yellow] "
            f"{approval.get('project_name', '')} — "
            f"{approval.get('goals_count', 0)} goals"
        )

        table = self.query_one("#goals-preview", DataTable)
        table.clear()

        for goal in approval.get("goals", [])[:10]:
            priority = goal.get("priority", "MEDIUM")
            priority_colors = {
                "CRITICAL": "[red]CRITICAL[/red]",
                "HIGH": "[yellow]HIGH[/yellow]",
                "MEDIUM": "[cyan]MEDIUM[/cyan]",
                "LOW": "[dim]LOW[/dim]",
            }

            table.add_row(
                priority_colors.get(priority, priority),
                goal.get("title", "")[:39],
                goal.get("complexity", "M"),
            )

        self.query_one("#btn-approve").disabled = False
        self.query_one("#btn-reject").disabled = False

    def _show_no_approval(self) -> None:
        self._current_approval = None
        status = self.query_one("#approval-status", Static)
        status.update("[dim]No pending plans[/dim]")
        table = self.query_one("#goals-preview", DataTable)
        table.clear()
        self.query_one("#btn-approve").disabled = True
        self.query_one("#btn-reject").disabled = True

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            await self._do_approve()
        elif event.button.id == "btn-reject":
            await self._do_reject()

    async def _do_approve(self) -> None:
        if not self._current_approval:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.api_base_url}/api/notifications/approve",
                    json={
                        "approval_id": self._current_approval.get("id", ""),
                        "action": "approve_all",
                        "source": "tui",
                    },
                    timeout=5.0,
                )
            self.notify("Plan approved")
            await self.refresh_data()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    async def _do_reject(self) -> None:
        if not self._current_approval:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.api_base_url}/api/notifications/reject",
                    json={
                        "approval_id": self._current_approval.get("id", ""),
                        "source": "tui",
                    },
                    timeout=5.0,
                )
            self.notify("Plan rejected")
            await self.refresh_data()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
