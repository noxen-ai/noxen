"""Test suite per core/research/github_client.py — Step 3.1 Phase 3."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock, AsyncMock
from datetime import datetime, timezone, timedelta

from core.research.github_client import GitHubClient, RepoCandidate


# ── Fixtures ────────────────────────────────────────────────────────

def _make_mock_repo(
    full_name="owner/repo",
    html_url="https://github.com/owner/repo",
    description="A test repo",
    stars=100,
    language="Python",
    topics=None,
    updated_at=None,
    size=5000,
    fork=False,
    archived=False,
    has_readme=True,
    readme_content="# Test Repo\nThis is a test.",
):
    """Crea un mock di PyGithub Repository."""
    repo = MagicMock()
    repo.full_name = full_name
    repo.html_url = html_url
    repo.description = description
    repo.stargazers_count = stars
    repo.language = language
    repo.get_topics = MagicMock(return_value=topics or ["python", "testing"])
    repo.updated_at = updated_at or datetime.now(timezone.utc)
    repo.size = size
    repo.fork = fork
    repo.archived = archived

    if has_readme:
        readme_mock = MagicMock()
        readme_mock.decoded_content = readme_content.encode("utf-8")
        repo.get_readme = MagicMock(return_value=readme_mock)
    else:
        repo.get_readme = MagicMock(side_effect=Exception("No README"))

    return repo


@pytest.fixture
def mock_github():
    """Mock PyGithub Github instance."""
    with patch("core.research.github_client.GitHubClient.__init__", return_value=None) as init:
        client = GitHubClient.__new__(GitHubClient)
        client._rest = MagicMock()
        client._token = "test-token"
        client._logger = MagicMock()
        yield client


# ── Test Constructor ────────────────────────────────────────────────

def test_init_with_token():
    """GitHubClient con token crea Github autenticato."""
    with patch("github.Github") as mock_gh:
        client = GitHubClient(token="ghp_test123")
        mock_gh.assert_called_once_with("ghp_test123")
        assert client._token == "ghp_test123"


def test_init_without_token():
    """GitHubClient senza token crea Github anonimo."""
    with patch("github.Github") as mock_gh:
        client = GitHubClient(token="")
        mock_gh.assert_called_once_with()
        assert client._token == ""


# ── Test search_repos() ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_repos_returns_list(mock_github):
    """search_repos() ritorna lista di RepoCandidate."""
    mock_repos = [
        _make_mock_repo("a/repo1", stars=200),
        _make_mock_repo("b/repo2", stars=100),
    ]
    mock_github._rest.search_repositories = MagicMock(return_value=iter(mock_repos))

    results = await mock_github.search_repos("fastapi")
    assert len(results) == 2
    assert all(isinstance(r, RepoCandidate) for r in results)
    assert results[0].full_name == "a/repo1"


@pytest.mark.asyncio
async def test_search_repos_filters_forks(mock_github):
    """search_repos() filtra i fork."""
    mock_repos = [
        _make_mock_repo("a/original", fork=False, stars=200),
        _make_mock_repo("b/forked", fork=True, stars=150),
    ]
    mock_github._rest.search_repositories = MagicMock(return_value=iter(mock_repos))

    results = await mock_github.search_repos("test")
    assert len(results) == 1
    assert results[0].full_name == "a/original"


@pytest.mark.asyncio
async def test_search_repos_filters_archived(mock_github):
    """search_repos() filtra i repo archived."""
    mock_repos = [
        _make_mock_repo("a/active", archived=False, stars=200),
        _make_mock_repo("b/old", archived=True, stars=300),
    ]
    mock_github._rest.search_repositories = MagicMock(return_value=iter(mock_repos))

    results = await mock_github.search_repos("test")
    assert len(results) == 1
    assert results[0].full_name == "a/active"


@pytest.mark.asyncio
async def test_search_repos_filters_large_repos(mock_github):
    """search_repos() filtra repo > max_size_kb."""
    mock_repos = [
        _make_mock_repo("a/small", size=5000, stars=200),
        _make_mock_repo("b/huge", size=200000, stars=300),  # 200MB
    ]
    mock_github._rest.search_repositories = MagicMock(return_value=iter(mock_repos))

    results = await mock_github.search_repos("test", max_size_kb=102400)
    assert len(results) == 1
    assert results[0].full_name == "a/small"


@pytest.mark.asyncio
async def test_search_repos_respects_limit(mock_github):
    """search_repos() rispetta il limit."""
    mock_repos = [_make_mock_repo(f"o/repo{i}", stars=100-i) for i in range(20)]
    mock_github._rest.search_repositories = MagicMock(return_value=iter(mock_repos))

    results = await mock_github.search_repos("test", limit=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_search_repos_with_language_filter(mock_github):
    """search_repos() include language nel query."""
    mock_github._rest.search_repositories = MagicMock(return_value=iter([]))

    await mock_github.search_repos("fastapi", language="Python")
    call_args = mock_github._rest.search_repositories.call_args
    assert "language:Python" in call_args[1]["query"] or "language:Python" in call_args[0][0]


@pytest.mark.asyncio
async def test_search_repos_handles_exception(mock_github):
    """search_repos() gestisce eccezioni GitHub gracefully."""
    mock_github._rest.search_repositories = MagicMock(side_effect=Exception("Rate limited"))

    results = await mock_github.search_repos("test")
    assert results == []


@pytest.mark.asyncio
async def test_search_repos_no_readme(mock_github):
    """search_repos() gestisce repo senza README."""
    mock_repos = [_make_mock_repo("a/repo", has_readme=False, stars=100)]
    mock_github._rest.search_repositories = MagicMock(return_value=iter(mock_repos))

    results = await mock_github.search_repos("test")
    assert len(results) == 1
    assert results[0].has_readme is False
    assert results[0].readme_preview == ""


# ── Test rank_candidates() ──────────────────────────────────────────

def test_rank_candidates_sorts_by_relevance(mock_github):
    """rank_candidates() ordina per relevance_score decrescente."""
    candidates = [
        RepoCandidate("a/low", "url", "unrelated", 10, "Go", [], datetime.now(timezone.utc), 100, False, ""),
        RepoCandidate("b/high", "url", "fastapi dependency injection", 5000, "Python",
                       ["fastapi", "dependency-injection"], datetime.now(timezone.utc), 200, True, ""),
    ]

    ranked = mock_github.rank_candidates(candidates, "fastapi dependency injection")
    assert ranked[0].full_name == "b/high"
    assert ranked[0].relevance_score > ranked[1].relevance_score


def test_rank_candidates_stars_matter(mock_github):
    """rank_candidates() dà peso alle stars."""
    candidates = [
        RepoCandidate("a/few", "url", "test", 10, "Python", ["test"], datetime.now(timezone.utc), 100, False, ""),
        RepoCandidate("b/many", "url", "test", 10000, "Python", ["test"], datetime.now(timezone.utc), 100, False, ""),
    ]

    ranked = mock_github.rank_candidates(candidates, "test")
    assert ranked[0].full_name == "b/many"


def test_rank_candidates_recency_matters(mock_github):
    """rank_candidates() favorisce repo recenti."""
    recent = datetime.now(timezone.utc)
    old = datetime.now(timezone.utc) - timedelta(days=1000)

    candidates = [
        RepoCandidate("a/old", "url", "test", 100, "Python", ["test"], old, 100, False, ""),
        RepoCandidate("b/recent", "url", "test", 100, "Python", ["test"], recent, 100, False, ""),
    ]

    ranked = mock_github.rank_candidates(candidates, "test")
    assert ranked[0].full_name == "b/recent"


def test_rank_candidates_empty_list(mock_github):
    """rank_candidates() con lista vuota ritorna []."""
    assert mock_github.rank_candidates([], "test") == []


def test_rank_candidates_topic_match(mock_github):
    """rank_candidates() favorisce match su topics."""
    candidates = [
        RepoCandidate("a/no-topic", "url", "generic lib", 100, "Python", [], datetime.now(timezone.utc), 100, False, ""),
        RepoCandidate("b/topic", "url", "generic lib", 100, "Python", ["fastapi", "api"], datetime.now(timezone.utc), 100, False, ""),
    ]

    ranked = mock_github.rank_candidates(candidates, "fastapi api")
    assert ranked[0].full_name == "b/topic"


# ── Test search_by_topic() ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_by_topic_no_token_fallback(mock_github):
    """search_by_topic() senza token cade su REST."""
    mock_github._token = ""
    mock_github._rest.search_repositories = MagicMock(return_value=iter([]))

    results = await mock_github.search_by_topic(["fastapi", "python"])
    assert isinstance(results, list)


# ── Test RepoCandidate dataclass ────────────────────────────────────

def test_repo_candidate_defaults():
    """RepoCandidate ha relevance_score default 0.0."""
    rc = RepoCandidate(
        full_name="o/r", url="u", description="d", stars=1,
        language="Python", topics=[], last_updated=datetime.now(timezone.utc),
        size_kb=100, has_readme=False, readme_preview="",
    )
    assert rc.relevance_score == 0.0
