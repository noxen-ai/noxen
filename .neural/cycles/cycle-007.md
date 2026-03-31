# Cycle 7 — Goal: goal_007

## Istruzioni inviate a Claude Code

```
Sei nel progetto Neural-Hub.

**LLM Provider Refactoring**

Objective: Refactor the `llm_provider.py` file to use a more efficient and scalable architecture for handling large amounts of data.

Step-by-Step Instructions:

1. Open the `llm_provider.py` file located at `/Users/luigi/Neural-Hub/core/llm_provider.py`.

2. Identify the current implementation's bottlenecks, such as inefficient data retrieval or processing methods. Consider factors like memory usage, CPU load, and database queries.

3. Introduce a new class `LLMDataFetcher` that encapsulates the logic for retrieving and processing large amounts of data. This class should:
   - Define a constructor that takes required parameters (e.g., API key, endpoint URL)
   - Implement methods for data retrieval, parsing, and caching
   - Utilize async/await syntax to improve performance and handle concurrent requests

4. Update the `llm_provider.py` file to use the new `LLMDataFetcher` class:
    ```python
    from . import LLMDataFetcher

    # ...

    def get_llm_data(self, query):
        fetcher = LLMDataFetcher(api_key='YOUR_API_KEY', endpoint_url='https://example.com/api')
        result = await fetcher.get_data(query)
        return result
    ```

5. Refactor the `get_llm_data` method to use the new `LLMDataFetcher` class and async/await syntax:
    ```python
    async def get_llm_data(self, query):
        fetcher = LLMDataFetcher(api_key='YOUR_API_KEY', endpoint_url='https://example.com/api')
        result = await fetcher.get_data(query)
        return result
    ```

6. Test the refactored code by calling the `get_llm_data` method and verifying the output:
    ```python
    async def test_get_llm_data():
        llm_provider = LLMProvider()
        query = 'test_query'
        result = await llm_provider.get_llm_data(query)
        assert result is not None

    if __name__ == '__main__':
        asyncio.run(test_get_llm_data())
    ```

7. Integrate the refactored code into the existing project structure and update any dependent components.

When you have finished, run a test to verify that it functions as expected.
```

## Output Claude Code

```
It seems file-write permission needs to be granted. Please approve the edit to `/Users/luigi/Neural-Hub/core/llm_provider.py` and I'll proceed.

Once you allow it, here's a summary of all changes I'll make:

1. **Add `import hashlib`** — needed for cache key hashing
2. **New `LLMDataFetcher` class** (inserted before `LLMProvider`) with:
   - Persistent `httpx.AsyncClient` (reused across requests, created lazily)
   - TTL-based in-memory response cache (5 min, keyed by SHA-256 of provider+model+system+prompt)
   - `get_data(prompt, system)` — public method with cache check → fetch → store
   - `_fetch_ollama/gemini/claude/openai` — the provider-specific HTTP logic moved from `LLMProvider`
   - `close()` — releases the underlying client
3. **`LLMProvider._refresh_config()`** — also rebuilds `self._fetchers` dict
4. **`LLMProvider.query()`** — replaces the `_call_*` dispatch with `await self._fetchers[provider].get_data(prompt, system)`
5. **Remove `_call_ollama/gemini/claude/openai`** — replaced by fetcher methods
6. **Add `LLMProvider.close()`** — closes all fetcher clients
7. Streaming methods (`_stream_*`) are unchanged — they manage their own connections by design

```

## Risultato

- Exit code: 0
- Durata: 106s
- Successo: Si
