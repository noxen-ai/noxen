"""Noxen - Web Researcher for Research Agent.

Cerca informazioni su tecnologie/concetti tramite:
  - Exa (semantic search): documentazione, tutorial, best practices
  - Firecrawl (web scraping): contenuto pagine specifiche

Produce WebResearchResult con snippet rilevanti.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger("noxen.web_researcher")


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class WebResult:
    """Singolo risultato di ricerca web."""
    title: str
    url: str
    snippet: str
    source: str  # "exa" | "firecrawl"
    score: float = 0.0
    published_date: str = ""


@dataclass
class WebResearchResult:
    """Risultato aggregato della ricerca web."""
    query: str
    results: list[WebResult] = field(default_factory=list)
    total_results: int = 0
    errors: list[str] = field(default_factory=list)
    searched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Web Researcher ───────────────────────────────────────────────────

class WebResearcher:
    """Ricerca web con Exa (semantic) e Firecrawl (scraping).

    Exa: ricerca semantica di documentazione e tutorial.
    Firecrawl: scraping di pagine specifiche per contenuto dettagliato.
    """

    def __init__(
        self,
        exa_api_key: str = "",
        firecrawl_api_key: str = "",
    ) -> None:
        self._exa_key = exa_api_key
        self._firecrawl_key = firecrawl_api_key
        self._logger = get_logger("web_researcher")

        # Lazy init dei client
        self._exa_client: Any = None
        self._firecrawl_client: Any = None

    def _get_exa_client(self) -> Any:
        """Lazy init del client Exa."""
        if not self._exa_client and self._exa_key:
            try:
                from exa_py import Exa
                self._exa_client = Exa(api_key=self._exa_key)
            except ImportError:
                self._logger.warning("exa_py not installed")
            except Exception as e:
                self._logger.error(f"Exa init failed: {e}")
        return self._exa_client

    def _get_firecrawl_client(self) -> Any:
        """Lazy init del client Firecrawl."""
        if not self._firecrawl_client and self._firecrawl_key:
            try:
                from firecrawl import FirecrawlApp
                self._firecrawl_client = FirecrawlApp(api_key=self._firecrawl_key)
            except ImportError:
                self._logger.warning("firecrawl not installed")
            except Exception as e:
                self._logger.error(f"Firecrawl init failed: {e}")
        return self._firecrawl_client

    async def search(
        self,
        query: str,
        num_results: int = 10,
        use_exa: bool = True,
        use_firecrawl: bool = False,
        firecrawl_urls: list[str] | None = None,
    ) -> WebResearchResult:
        """Esegui ricerca web combinata.

        Args:
            query: Query di ricerca.
            num_results: Numero max di risultati per fonte.
            use_exa: Usa Exa per semantic search.
            use_firecrawl: Usa Firecrawl per scraping URLs.
            firecrawl_urls: URL specifici da scrapare con Firecrawl.

        Returns:
            WebResearchResult aggregato.
        """
        result = WebResearchResult(query=query)
        tasks = []

        if use_exa and self._exa_key:
            tasks.append(self._search_exa(query, num_results))

        if use_firecrawl and self._firecrawl_key and firecrawl_urls:
            tasks.append(self._scrape_firecrawl(firecrawl_urls))

        if not tasks:
            if not self._exa_key and not self._firecrawl_key:
                result.errors.append("No API keys configured for web research")
            return result

        # Esegui in parallelo
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        for res in gathered:
            if isinstance(res, Exception):
                result.errors.append(str(res))
            elif isinstance(res, list):
                result.results.extend(res)

        result.total_results = len(result.results)
        return result

    async def search_exa(
        self,
        query: str,
        num_results: int = 10,
        category: str = "research paper",
    ) -> WebResearchResult:
        """Ricerca solo con Exa (public API)."""
        result = WebResearchResult(query=query)

        if not self._exa_key:
            result.errors.append("Exa API key not configured")
            return result

        try:
            web_results = await self._search_exa(query, num_results, category)
            result.results = web_results
            result.total_results = len(web_results)
        except Exception as e:
            result.errors.append(str(e))

        return result

    async def scrape_url(self, url: str) -> WebResult | None:
        """Scrape una singola URL con Firecrawl."""
        if not self._firecrawl_key:
            return None

        try:
            results = await self._scrape_firecrawl([url])
            return results[0] if results else None
        except Exception as e:
            self._logger.error(f"Scrape failed for {url}: {e}")
            return None

    async def _search_exa(
        self,
        query: str,
        num_results: int = 10,
        category: str = "research paper",
    ) -> list[WebResult]:
        """Ricerca semantica con Exa.

        Exa usa neural search per trovare contenuti semanticamente simili.
        """
        client = self._get_exa_client()
        if not client:
            return []

        self._logger.info(f"Exa search: {query}")

        try:
            # Exa search (sync, wrapped in executor)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.search_and_contents(
                    query,
                    num_results=num_results,
                    type="neural",
                    text=True,
                    highlights=True,
                    category=category,
                ),
            )

            results: list[WebResult] = []
            for item in response.results:
                snippet = ""
                if hasattr(item, "highlights") and item.highlights:
                    snippet = " ".join(item.highlights[:3])
                elif hasattr(item, "text") and item.text:
                    snippet = item.text[:500]

                results.append(WebResult(
                    title=getattr(item, "title", "") or "",
                    url=getattr(item, "url", "") or "",
                    snippet=snippet,
                    source="exa",
                    score=getattr(item, "score", 0.0) or 0.0,
                    published_date=getattr(item, "published_date", "") or "",
                ))

            self._logger.info(f"Exa returned {len(results)} results")
            return results

        except Exception as e:
            self._logger.error(f"Exa search failed: {e}")
            raise

    async def _scrape_firecrawl(
        self,
        urls: list[str],
    ) -> list[WebResult]:
        """Scrape pagine con Firecrawl.

        Firecrawl converte pagine web in markdown/testo pulito.
        """
        client = self._get_firecrawl_client()
        if not client:
            return []

        self._logger.info(f"Firecrawl scraping {len(urls)} URLs")

        results: list[WebResult] = []
        loop = asyncio.get_event_loop()

        for url in urls:
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda u=url: client.scrape_url(u, params={"formats": ["markdown"]}),
                )

                # Firecrawl response structure
                content = ""
                title = ""
                if isinstance(response, dict):
                    content = response.get("markdown", "") or response.get("content", "")
                    metadata = response.get("metadata", {})
                    title = metadata.get("title", "") if isinstance(metadata, dict) else ""
                elif hasattr(response, "markdown"):
                    content = response.markdown or ""
                    title = getattr(response, "metadata", {}).get("title", "") if hasattr(response, "metadata") else ""

                snippet = content[:1000] if content else ""

                results.append(WebResult(
                    title=title or url,
                    url=url,
                    snippet=snippet,
                    source="firecrawl",
                ))

            except Exception as e:
                self._logger.error(f"Firecrawl failed for {url}: {e}")
                continue

        self._logger.info(f"Firecrawl returned {len(results)} results")
        return results
