"""SkillTable Widget — skill pool with metrics.

Displays skills in a sortable table with confidence scores,
usage counts, and status filtering.
"""

from __future__ import annotations

import httpx
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label


class SkillTableWidget(Widget):
    """Skill pool table with filters.

    Columns: Name | Tech | Status | Confidence | Uses | Version

    Keyboard:
    / -> focus search bar
    Enter on row -> skill detail
    """

    COLUMNS = [
        ("Nome", 25),
        ("Tech", 15),
        ("Status", 12),
        ("Confidence", 10),
        ("Uses", 6),
        ("Versione", 8),
    ]

    DEFAULT_CSS = """
    SkillTableWidget {
        height: 100%;
    }
    """

    def __init__(self, api_base_url: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url
        self._current_filter = "approved"

    def compose(self) -> ComposeResult:
        yield Label("[bold]● Skill Pool[/bold]", classes="panel-title")
        yield Input(placeholder="Search skills...", id="skill-search")
        yield DataTable(id="skill-table")

    async def on_mount(self) -> None:
        table = self.query_one("#skill-table", DataTable)
        for col_name, col_width in self.COLUMNS:
            table.add_column(col_name, width=col_width)
        await self.refresh_data()

    async def refresh_data(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/api/skills/v2/pool",
                    params={"status": self._current_filter},
                    timeout=5.0,
                )
                if response.status_code == 200:
                    skills = response.json().get("skills", [])
                    self._render_skills(skills)
        except Exception:
            pass

    def _render_skills(self, skills: list) -> None:
        table = self.query_one("#skill-table", DataTable)
        table.clear()

        for skill in skills:
            confidence = skill.get("confidence_score", 0.0)
            conf_str = f"{confidence:.2f}"

            if confidence >= 0.7:
                conf_display = f"[green]{conf_str}[/green]"
            elif confidence >= 0.4:
                conf_display = f"[yellow]{conf_str}[/yellow]"
            else:
                conf_display = f"[red]{conf_str}[/red]"

            status = skill.get("status", "")
            status_colors = {
                "approved": "[green]approved[/green]",
                "draft": "[yellow]draft[/yellow]",
                "board_review": "[cyan]review[/cyan]",
                "rejected": "[red]rejected[/red]",
                "deprecated": "[dim]deprecated[/dim]",
                "archived": "[dim]archived[/dim]",
            }
            status_display = status_colors.get(status, status)

            table.add_row(
                skill.get("name", "")[:24],
                skill.get("technology", "")[:14],
                status_display,
                conf_display,
                str(skill.get("total_uses", 0)),
                skill.get("version", "1.0.0"),
            )
