"""Test suite per Noxen TUI — Phase 7."""

import pytest
from textual.widgets import TabbedContent, DataTable, Input, RichLog, Tree

from tui.app import NoxenTUI


@pytest.mark.asyncio
async def test_app_starts():
    """TUI starts without errors."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        assert app.title == "Noxen"


@pytest.mark.asyncio
async def test_tab_navigation_to_dna():
    """Navigate to DNA tab with key 2."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("2")
        tabbed = app.query_one(TabbedContent)
        assert tabbed.active == "dna"


@pytest.mark.asyncio
async def test_tab_navigation_to_goals():
    """Navigate to Goals tab with key 3."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("3")
        tabbed = app.query_one(TabbedContent)
        assert tabbed.active == "goals"


@pytest.mark.asyncio
async def test_tab_navigation_to_skills():
    """Navigate to Skills tab with key 4."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("4")
        tabbed = app.query_one(TabbedContent)
        assert tabbed.active == "skills"


@pytest.mark.asyncio
async def test_tab_navigation_to_board():
    """Navigate to Board tab with key 5."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("5")
        tabbed = app.query_one(TabbedContent)
        assert tabbed.active == "board"


@pytest.mark.asyncio
async def test_tab_navigation_to_approval():
    """Navigate to Approval tab with key 6."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("6")
        tabbed = app.query_one(TabbedContent)
        assert tabbed.active == "approval"


@pytest.mark.asyncio
async def test_tab_navigation_to_chat():
    """Navigate to Chat tab with key 7."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("7")
        tabbed = app.query_one(TabbedContent)
        assert tabbed.active == "chat"


@pytest.mark.asyncio
async def test_initial_tab_is_live():
    """App starts on the Live tab."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        tabbed = app.query_one(TabbedContent)
        assert tabbed.active == "live"


@pytest.mark.asyncio
async def test_skill_table_has_columns():
    """SkillTable has the correct 6 columns."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("4")
        table = app.query_one("#skill-table", DataTable)
        assert len(table.columns) == 6


@pytest.mark.asyncio
async def test_board_table_has_columns():
    """BoardPanel table has 4 columns."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("5")
        table = app.query_one("#board-table", DataTable)
        assert len(table.columns) == 4


@pytest.mark.asyncio
async def test_approval_buttons_disabled():
    """Approval buttons are disabled when no pending plans."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("6")
        btn_approve = app.query_one("#btn-approve")
        btn_reject = app.query_one("#btn-reject")
        assert btn_approve.disabled is True
        assert btn_reject.disabled is True


@pytest.mark.asyncio
async def test_chat_input_exists():
    """Chat tab has an input field."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("7")
        chat_input = app.query_one("#chat-input", Input)
        assert chat_input is not None


@pytest.mark.asyncio
async def test_event_log_exists():
    """Live tab has an event log."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        log = app.query_one("#event-log", RichLog)
        assert log is not None


@pytest.mark.asyncio
async def test_goal_tree_exists():
    """Goals tab has a tree widget."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("3")
        tree = app.query_one("#goal-tree", Tree)
        assert tree is not None


@pytest.mark.asyncio
async def test_approval_status_exists():
    """Approval tab has a status display."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("6")
        status = app.query_one("#approval-status")
        assert status is not None


@pytest.mark.asyncio
async def test_system_map_exists():
    """DNA tab has a system map display."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("2")
        smap = app.query_one("#system-map")
        assert smap is not None


@pytest.mark.asyncio
async def test_keyboard_quit():
    """q closes the TUI."""
    app = NoxenTUI(api_base_url="http://localhost:9999")
    async with app.run_test(headless=True) as pilot:
        await pilot.press("q")
        assert not app.is_running
