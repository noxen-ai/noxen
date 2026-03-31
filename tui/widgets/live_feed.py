"""LiveFeed Widget — real-time event feed.

Shows what Noxen is doing right now.
Polls GET /api/events/recent every 2 seconds.
"""

from __future__ import annotations

import asyncio

import httpx
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog


class LiveFeedWidget(Widget):
    """Real-time event feed from Noxen API.

    Format:
    12:34:56 [research_agent ] Analyzing repo: fastapi/fastapi
    12:34:58 [skill_builder  ] Building skill: FastAPI DI
    12:35:02 [board_reviewer ] Review skill: FastAPI (APPROVED)
    """

    DEFAULT_CSS = """
    LiveFeedWidget {
        height: 100%;
    }
    """

    def __init__(self, api_base_url: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url
        self._polling_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Label("[bold]● Live Feed[/bold]", classes="panel-title")
        yield RichLog(
            id="event-log",
            highlight=True,
            markup=True,
            wrap=True,
            max_lines=200,
        )

    async def on_mount(self) -> None:
        self._polling_task = asyncio.create_task(self._poll_events())

    async def on_unmount(self) -> None:
        if self._polling_task:
            self._polling_task.cancel()

    async def _poll_events(self) -> None:
        last_event_id: str | None = None

        while True:
            try:
                async with httpx.AsyncClient() as client:
                    params: dict = {}
                    if last_event_id:
                        params["after_id"] = last_event_id

                    response = await client.get(
                        f"{self.api_base_url}/api/events/recent",
                        params=params,
                        timeout=5.0,
                    )

                    if response.status_code == 200:
                        events = response.json().get("events", [])
                        log = self.query_one("#event-log", RichLog)

                        for event in events:
                            log.write(self._format_event(event))
                            last_event_id = event.get("id")

            except Exception:
                pass  # Silent if API unavailable

            await asyncio.sleep(2.0)

    def _format_event(self, event: dict) -> str:
        timestamp = event.get("timestamp", "")[:8]
        source = event.get("source", "unknown").ljust(16)
        event_type = event.get("type", "")
        data = event.get("data", {})

        color_map = {
            "research_agent": "cyan",
            "skill_builder": "blue",
            "board_reviewer": "magenta",
            "execution_engine": "green",
            "usage_tracker": "yellow",
            "error": "red",
        }
        color = color_map.get(event.get("source", ""), "white")

        description = self._extract_description(event_type, data)

        return (
            f"[dim]{timestamp}[/dim] "
            f"[{color}][{source}][/{color}] "
            f"{description}"
        )

    def _extract_description(self, event_type: str, data: dict) -> str:
        descriptions = {
            "skill_review_requested": f"Review: {data.get('skill_name', '')}",
            "skill_review_completed": (
                f"Skill [{data.get('decision', '')}]: {data.get('skill_id', '')[:8]}"
            ),
            "skill_used": (
                f"Skill used: {data.get('skill_id', '')[:8]} "
                f"({data.get('outcome', '')})"
            ),
            "skill_degraded": (
                f"[red]Skill degraded:[/red] {data.get('skill_id', '')[:8]} "
                f"conf={data.get('confidence_score', 0):.2f}"
            ),
            "goal_result": (
                f"Goal '{data.get('goal_title', '')}': "
                f"{'[green]OK[/green]' if data.get('success') else '[red]FAIL[/red]'}"
            ),
            "bootstrap_complete": f"Bootstrap: {data.get('goals_count', 0)} goals",
            "awaiting_approval": "[yellow]Awaiting approval[/yellow]",
            "session_complete": "[green]Session complete[/green]",
        }
        return descriptions.get(event_type, f"{event_type}: {str(data)[:60]}")

    async def refresh_data(self) -> None:
        log = self.query_one("#event-log", RichLog)
        log.clear()
