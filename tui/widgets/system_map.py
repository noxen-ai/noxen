"""SystemMap Widget — ASCII system map.

Displays the analyzed project's DNA: services, relationships,
technologies, and health scores.
"""

from __future__ import annotations

import httpx
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static


class SystemMapWidget(Widget):
    """ASCII map of the analyzed system.

    Shows project DNA: services, languages, frameworks, health.
    Uses GET /api/orchestrator/status for data.
    """

    DEFAULT_CSS = """
    SystemMapWidget {
        height: 100%;
    }
    """

    def __init__(self, api_base_url: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url

    def compose(self) -> ComposeResult:
        yield Label("[bold]● System DNA[/bold]", classes="panel-title")
        yield Static("[dim]Loading system DNA...[/dim]", id="system-map")

    async def on_mount(self) -> None:
        await self.refresh_data()

    async def refresh_data(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/api/orchestrator/status",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    map_text = self._render_map(data)
                    self.query_one("#system-map", Static).update(map_text)
        except Exception:
            self.query_one("#system-map", Static).update(
                "[dim]API not available. Start server first.[/dim]"
            )

    def _render_map(self, data: dict) -> str:
        initialized = data.get("initialized", False)

        if not initialized:
            return (
                "[dim]No project initialized.\n"
                "Use: POST /api/orchestrator/init\n"
                "Or:  noxen init <path>[/dim]"
            )

        lines = []

        project = data.get("project_path", "N/A")
        lines.append(f"[bold]Project:[/bold] {project}")

        total_services = data.get("total_services", 0)
        lines.append(f"[bold]Services:[/bold] {total_services}")

        languages = data.get("languages", [])
        if languages:
            lines.append("\n[bold]Languages:[/bold]")
            for lang in languages[:8]:
                lines.append(f"  [cyan]●[/cyan] {lang}")

        frameworks = data.get("frameworks", [])
        if frameworks:
            lines.append("\n[bold]Frameworks:[/bold]")
            for fw in frameworks[:8]:
                lines.append(f"  [green]●[/green] {fw}")

        db_connected = data.get("db_connected", False)
        db_tables = data.get("db_tables", 0)
        lines.append(
            f"\n[bold]Database:[/bold] "
            f"{'[green]Connected[/green]' if db_connected else '[dim]Not connected[/dim]'}"
            f" ({db_tables} tables)"
        )

        skills = data.get("available_skills", 0)
        lines.append(f"[bold]Skills:[/bold] {skills}")

        provider = data.get("active_provider", "N/A")
        mode = data.get("llm_mode", "N/A")
        lines.append(f"[bold]LLM:[/bold] {provider} ({mode})")

        return "\n".join(lines)
