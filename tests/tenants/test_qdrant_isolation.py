"""Test suite per Qdrant Tenant Isolation — Step 8.4."""

import pytest
from unittest.mock import MagicMock, patch

from core.qdrant_client import NoxenQdrantClient


# ── Mock Qdrant Client ───────────────────────────────────────────────

class MockPoint:
    def __init__(self, id, payload, score=0.9):
        self.id = id
        self.payload = payload
        self.score = score


class MockQueryResult:
    def __init__(self, points):
        self.points = points


class MockQdrant:
    """In-memory mock of QdrantClient for isolation tests."""

    def __init__(self):
        self._points: dict[str, dict] = {}  # point_id -> {vector, payload, collection}

    def upsert(self, collection_name, points):
        for p in points:
            self._points[f"{collection_name}:{p.id}"] = {
                "vector": p.vector,
                "payload": p.payload,
                "collection": collection_name,
            }

    def query_points(self, collection_name, query, query_filter=None, limit=5):
        results = []
        for key, data in self._points.items():
            if not key.startswith(f"{collection_name}:"):
                continue
            payload = data["payload"]

            if query_filter:
                if not self._matches_filter(payload, query_filter):
                    continue

            point_id = key.split(":", 1)[1]
            results.append(MockPoint(point_id, payload))

        return MockQueryResult(results[:limit])

    def scroll(self, collection_name, scroll_filter=None, limit=100, with_payload=True):
        results = []
        for key, data in self._points.items():
            if not key.startswith(f"{collection_name}:"):
                continue
            payload = data["payload"]

            if scroll_filter:
                if not self._matches_filter(payload, scroll_filter):
                    continue

            point_id = key.split(":", 1)[1]
            results.append(MockPoint(point_id, payload))

        return results[:limit], None

    def delete(self, collection_name, points_selector):
        for pid in points_selector.points:
            self._points.pop(f"{collection_name}:{pid}", None)

    def _matches_filter(self, payload, qfilter):
        # Handle 'must' conditions
        if qfilter.must:
            for cond in qfilter.must:
                key = cond.key
                if hasattr(cond, "match") and cond.match:
                    if payload.get(key) != cond.match.value:
                        return False

        # Handle 'should' conditions (OR logic)
        if hasattr(qfilter, "should") and qfilter.should:
            matched_any = False
            for cond in qfilter.should:
                key = cond.key
                if hasattr(cond, "match") and cond.match:
                    if payload.get(key) == cond.match.value:
                        matched_any = True
                        break
            if not matched_any:
                return False

        return True


@pytest.fixture
def qdrant():
    """NoxenQdrantClient with mock backend."""
    client = NoxenQdrantClient.__new__(NoxenQdrantClient)
    client._client = MockQdrant()
    client._logger = MagicMock()
    return client


# ── Helper to insert points ──────────────────────────────────────────

async def _insert(qdrant, collection, pid, tenant_id, name="test"):
    await qdrant.upsert_with_tenant(
        collection=collection,
        point_id=pid,
        vector=[0.1] * 384,
        payload={"name": name},
        tenant_id=tenant_id,
    )


# ── search_with_tenant ───────────────────────────────────────────────

class TestSearchWithTenant:
    @pytest.mark.asyncio
    async def test_finds_tenant_data(self, qdrant):
        """search_with_tenant finds data for the specific tenant."""
        await _insert(qdrant, "skills", "s1", "team-a", "Skill A")
        await _insert(qdrant, "skills", "s2", "team-b", "Skill B")

        results = await qdrant.search_with_tenant(
            collection="skills",
            query_vector=[0.1] * 384,
            tenant_id="team-a",
            include_global=False,
        )
        assert len(results) == 1
        assert results[0]["payload"]["name"] == "Skill A"

    @pytest.mark.asyncio
    async def test_include_global(self, qdrant):
        """search_with_tenant with include_global finds tenant + global."""
        await _insert(qdrant, "skills", "s1", "team-a", "Team A Skill")
        await _insert(qdrant, "skills", "s2", "global", "Global Skill")
        await _insert(qdrant, "skills", "s3", "team-b", "Team B Skill")

        results = await qdrant.search_with_tenant(
            collection="skills",
            query_vector=[0.1] * 384,
            tenant_id="team-a",
            include_global=True,
        )
        names = [r["payload"]["name"] for r in results]
        assert "Team A Skill" in names
        assert "Global Skill" in names
        assert "Team B Skill" not in names

    @pytest.mark.asyncio
    async def test_does_not_find_other_tenant(self, qdrant):
        """search_with_tenant does NOT find data from other tenants."""
        await _insert(qdrant, "skills", "s1", "team-a", "A")
        await _insert(qdrant, "skills", "s2", "team-b", "B")

        results = await qdrant.search_with_tenant(
            collection="skills",
            query_vector=[0.1] * 384,
            tenant_id="team-a",
            include_global=False,
        )
        names = [r["payload"]["name"] for r in results]
        assert "B" not in names

    @pytest.mark.asyncio
    async def test_empty_results(self, qdrant):
        """search_with_tenant returns empty for nonexistent tenant."""
        results = await qdrant.search_with_tenant(
            collection="skills",
            query_vector=[0.1] * 384,
            tenant_id="nonexistent",
        )
        assert results == []


# ── upsert_with_tenant ───────────────────────────────────────────────

class TestUpsertWithTenant:
    @pytest.mark.asyncio
    async def test_adds_tenant_id_to_payload(self, qdrant):
        """upsert_with_tenant adds tenant_id to payload."""
        await qdrant.upsert_with_tenant(
            collection="skills",
            point_id="s1",
            vector=[0.1] * 384,
            payload={"name": "Test"},
            tenant_id="team-x",
        )

        results = await qdrant.search_with_tenant(
            collection="skills",
            query_vector=[0.1] * 384,
            tenant_id="team-x",
            include_global=False,
        )
        assert len(results) == 1
        assert results[0]["payload"]["tenant_id"] == "team-x"


# ── delete_tenant_data ───────────────────────────────────────────────

class TestDeleteTenantData:
    @pytest.mark.asyncio
    async def test_deletes_tenant_data(self, qdrant):
        """delete_tenant_data removes only the specified tenant's data."""
        await _insert(qdrant, "skills", "s1", "team-a")
        await _insert(qdrant, "skills", "s2", "team-b")

        deleted = await qdrant.delete_tenant_data("team-a")
        assert deleted["skills"] == 1

        # team-b data still exists
        results = await qdrant.search_with_tenant(
            collection="skills",
            query_vector=[0.1] * 384,
            tenant_id="team-b",
            include_global=False,
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_does_not_delete_global(self, qdrant):
        """delete_tenant_data does NOT delete global skills."""
        await _insert(qdrant, "skills", "s1", "global", "Global")
        await _insert(qdrant, "skills", "s2", "team-a", "Team A")

        await qdrant.delete_tenant_data("team-a")

        # Global still exists
        results = await qdrant.search_with_tenant(
            collection="skills",
            query_vector=[0.1] * 384,
            tenant_id="global",
            include_global=False,
        )
        assert len(results) == 1
        assert results[0]["payload"]["name"] == "Global"

    @pytest.mark.asyncio
    async def test_cannot_delete_global_tenant(self, qdrant):
        """delete_tenant_data raises ValueError for global tenant."""
        with pytest.raises(ValueError, match="Cannot delete global"):
            await qdrant.delete_tenant_data("global")

    @pytest.mark.asyncio
    async def test_deletes_across_collections(self, qdrant):
        """delete_tenant_data works across multiple collections."""
        await _insert(qdrant, "skills", "s1", "team-a")
        await _insert(qdrant, "events", "e1", "team-a")
        await _insert(qdrant, "findings", "f1", "team-a")

        deleted = await qdrant.delete_tenant_data(
            "team-a", collections=["skills", "events", "findings"]
        )
        assert deleted["skills"] == 1
        assert deleted["events"] == 1
        assert deleted["findings"] == 1
