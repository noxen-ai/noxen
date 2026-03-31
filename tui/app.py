"""Noxen TUI — Terminal User Interface.

Phase 7: Keyboard-driven interface for developers who live in the terminal.
Reads from the same source of truth as the web frontend (Qdrant + SSE).

Keyboard shortcuts:
1 -> Live feed (what Noxen is doing now)
2 -> System DNA (project map)
3 -> Goals (goal tree with status)
4 -> Skills (pool with confidence scores)
5 -> Board (deliberations and outcomes)
6 -> Approval (pending plans)
7 -> Chat (contextual questions)
q -> Quit
r -> Manual refresh
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from tui.widgets.approval_widget import ApprovalWidget
from tui.widgets.board_panel import BoardPanelWidget
from tui.widgets.chat_widget import ChatWidget
from tui.widgets.goal_tree import GoalTreeWidget
from tui.widgets.live_feed import LiveFeedWidget
from tui.widgets.skill_table import SkillTableWidget
from tui.widgets.system_map import SystemMapWidget


class NoxenTUI(App):
    """Noxen Terminal UI.

    7 tabs accessible via number keys, real-time data from API.
    """

    TITLE = "Noxen"
    SUB_TITLE = "Terminal UI"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("1", "show_tab('live')", "Live", show=True),
        Binding("2", "show_tab('dna')", "DNA", show=True),
        Binding("3", "show_tab('goals')", "Goals", show=True),
        Binding("4", "show_tab('skills')", "Skills", show=True),
        Binding("5", "show_tab('board')", "Board", show=True),
        Binding("6", "show_tab('approval')", "Approval", show=True),
        Binding("7", "show_tab('chat')", "Chat", show=True),
        Binding("r", "refresh_all", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        api_base_url: str = "http://localhost:8400",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.api_base_url = api_base_url

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="live"):
            with TabPane("Live", id="live"):
                yield LiveFeedWidget(self.api_base_url)
            with TabPane("DNA", id="dna"):
                yield SystemMapWidget(self.api_base_url)
            with TabPane("Goals", id="goals"):
                yield GoalTreeWidget(self.api_base_url)
            with TabPane("Skills", id="skills"):
                yield SkillTableWidget(self.api_base_url)
            with TabPane("Board", id="board"):
                yield BoardPanelWidget(self.api_base_url)
            with TabPane("Approval", id="approval"):
                yield ApprovalWidget(self.api_base_url)
            with TabPane("Chat", id="chat"):
                yield ChatWidget(self.api_base_url)
        yield Footer()

    async def action_refresh_all(self) -> None:
        """Force refresh all widgets."""
        for widget in self.query("*"):
            if hasattr(widget, "refresh_data"):
                try:
                    await widget.refresh_data()
                except Exception:
                    pass

    async def action_show_tab(self, tab_id: str) -> None:
        """Switch to a specific tab."""
        self.query_one(TabbedContent).active = tab_id
