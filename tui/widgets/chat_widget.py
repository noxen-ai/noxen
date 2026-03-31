"""Chat Widget — contextual chat with Noxen.

Full access to project context: DNA, findings, skills, session history.
Uses POST /api/orchestrator/chat with SSE streaming.
"""

from __future__ import annotations

import json

import httpx
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Input, Label, RichLog


class ChatWidget(Widget):
    """Contextual chat interface.

    Keyboard:
    Enter -> send message
    Ctrl+L -> clear chat
    """

    DEFAULT_CSS = """
    ChatWidget {
        height: 100%;
    }

    ChatWidget #chat-log {
        height: 1fr;
    }
    """

    def __init__(self, api_base_url: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url

    def compose(self) -> ComposeResult:
        yield Label("[bold]● Contextual Chat[/bold]", classes="panel-title")
        yield RichLog(
            id="chat-log",
            highlight=True,
            markup=True,
            wrap=True,
            max_lines=500,
        )
        yield Input(
            placeholder="Ask about your project...",
            id="chat-input",
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return

        event.input.clear()

        log = self.query_one("#chat-log", RichLog)
        log.write(f"\n[bold cyan]You:[/bold cyan] {message}")

        await self._stream_response(message, log)

    async def _stream_response(self, message: str, log: RichLog) -> None:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.api_base_url}/api/orchestrator/chat",
                    json={"message": message},
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    buffer = ""
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                if buffer:
                                    log.write(f"[dim]Noxen:[/dim] {buffer}")
                                break
                            try:
                                parsed = json.loads(data)
                                token = parsed.get("token", "")
                                if token:
                                    buffer += token
                            except json.JSONDecodeError:
                                buffer += data

                    if buffer:
                        log.write(f"[dim]Noxen:[/dim] {buffer}")

        except httpx.ConnectError:
            log.write("[red]Server not reachable. Start Noxen first.[/red]")
        except Exception as e:
            log.write(f"[red]Error: {e}[/red]")

    async def refresh_data(self) -> None:
        pass  # Chat doesn't auto-refresh
