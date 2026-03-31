"""BoardPanel Widget — board deliberations display.

Shows ongoing and recent board LLM decisions with outcomes.
"""

from __future__ import annotations

import httpx
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static


class BoardPanelWidget(Widget):
    """Board deliberations panel.

    Sections:
    - Active: async deliberations in progress
    - Recent: last 10 decisions with outcomes

    Columns: Type | Status | Decision | When
    """

    DEFAULT_CSS = """
    BoardPanelWidget {
        height: 100%;
    }
    """

    def __init__(self, api_base_url: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url

    def compose(self) -> ComposeResult:
        yield Label("[bold]● Board Deliberations[/bold]", classes="panel-title")
        yield Static("", id="board-summary")
        yield DataTable(id="board-table")

    async def on_mount(self) -> None:
        table = self.query_one("#board-table", DataTable)
        table.add_column("Tipo", width=20)
        table.add_column("Status", width=10)
        table.add_column("Decisione", width=15)
        table.add_column("Quando", width=12)
        await self.refresh_data()

    async def refresh_data(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/api/events/recent",
                    params={"type": "board", "limit": 20},
                    timeout=5.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    self._render_board_events(data.get("events", []))
        except Exception:
            pass

    def _render_board_events(self, events: list) -> None:
        table = self.query_one("#board-table", DataTable)
        table.clear()

        board_events = [
            e
            for e in events
            if "board" in e.get("type", "") or "skill_review" in e.get("type", "")
        ]

        summary = self.query_one("#board-summary", Static)
        if board_events:
            summary.update(f"[dim]{len(board_events)} recent deliberations[/dim]")
        else:
            summary.update("[dim]No board activity yet[/dim]")

        for event in board_events[:15]:
            event_type = event.get("type", "")
            data = event.get("data", {})
            timestamp = event.get("timestamp", "")[:16]

            decision = data.get("decision", "pending")
            decision_colors = {
                "approve": "[green]APPROVED[/green]",
                "improve": "[yellow]IMPROVE[/yellow]",
                "reject": "[red]REJECTED[/red]",
                "pending": "[dim]pending[/dim]",
            }

            table.add_row(
                event_type[:19],
                "[green]done[/green]",
                decision_colors.get(decision, decision),
                timestamp,
            )
