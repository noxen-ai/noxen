"""GoalTree Widget — interactive goal graph.

Displays the current session's goal tree with status icons,
priorities, and dependencies.
"""

from __future__ import annotations

import httpx
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Tree


class GoalTreeWidget(Widget):
    """Interactive goal tree showing session progress.

    Structure:
    Session: session-id (running)
      [green]OK[/] [HIGH] Setup database connection (completed)
      [yellow]...[/] [HIGH] Add input validation (running)
      [dim]o[/] [MEDIUM] Optimize N+1 query (pending)
        depends on: Add input validation
      [red]X[/] [LOW] Add test coverage (failed, 2/3 attempts)
    """

    STATUS_ICONS = {
        "completed": "[green]OK[/green]",
        "running": "[yellow]~~[/yellow]",
        "pending": "[dim]oo[/dim]",
        "failed": "[red]XX[/red]",
        "skipped": "[dim]--[/dim]",
    }

    PRIORITY_COLORS = {
        "CRITICAL": "red",
        "HIGH": "yellow",
        "MEDIUM": "cyan",
        "LOW": "dim",
    }

    DEFAULT_CSS = """
    GoalTreeWidget {
        height: 100%;
    }
    """

    def __init__(self, api_base_url: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url

    def compose(self) -> ComposeResult:
        yield Label("[bold]● Goals[/bold]", classes="panel-title")
        yield Tree("No active session", id="goal-tree")

    async def on_mount(self) -> None:
        await self.refresh_data()

    async def refresh_data(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/api/engine/status",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    self._render_goals(data)
        except Exception:
            pass

    def _render_goals(self, data: dict) -> None:
        tree = self.query_one("#goal-tree", Tree)
        tree.clear()

        session_id = data.get("session_id", "N/A")
        status = data.get("status", "idle")
        goals = data.get("goals", [])

        root = tree.root
        root.label = f"Session: {session_id[:12]} [{status}]"
        root.expand()

        for goal in goals:
            icon = self.STATUS_ICONS.get(goal.get("status", "pending"), "oo")
            priority = goal.get("priority", "MEDIUM")
            color = self.PRIORITY_COLORS.get(priority, "white")

            label = f"{icon} [{color}][{priority}][/{color}] {goal.get('title', '')}"

            node = root.add(label, data=goal)

            if goal.get("dependencies"):
                deps_text = ", ".join(goal["dependencies"][:2])
                node.add_leaf(f"[dim]depends on: {deps_text}[/dim]")
