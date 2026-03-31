"""API Routes: Events — real-time event feed for TUI and dashboards.

Phase 7: Provides recent events from the EventRouter for
the TUI LiveFeed widget and web dashboard.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/events", tags=["events"])

_event_router = None


def init_router(event_router=None) -> None:
    """Inject EventRouter at startup."""
    global _event_router
    _event_router = event_router


@router.get("/recent")
async def get_recent_events(
    after_id: Optional[str] = Query(None, description="Return events after this ID"),
    type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=200, description="Max events to return"),
) -> dict[str, Any]:
    """Get recent events, optionally filtered.

    Used by TUI LiveFeed widget (polls every 2s).
    """
    if not _event_router:
        return {"events": [], "count": 0}

    try:
        # Get events from EventRouter (sync method)
        all_events = _event_router.get_recent(
            event_type=type or "",
            limit=limit,
        )

        # Filter by after_id if specified
        if after_id:
            found = False
            filtered = []
            for e in all_events:
                if found:
                    filtered.append(e)
                if e.get("id") == after_id:
                    found = True
            all_events = filtered

        events = all_events[:limit]

        return {
            "events": events,
            "count": len(events),
        }

    except Exception:
        return {"events": [], "count": 0}
