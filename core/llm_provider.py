"""Noxen - Multi-LLM Provider.

Supporta 4 backend LLM con interfaccia unificata:
  - Ollama (locale, gratis)
  - Google Gemini (API, economico)
  - Anthropic Claude (API)
  - OpenAI GPT (API)

Modalita':
  - single: usa un solo provider
  - board: tutti i provider in parallelo + sintesi (CDA)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)

from config import settings

logger = logging.getLogger("noxen.llm")

# Timeout per le chiamate API
API_TIMEOUT = 120.0


def _is_retryable(exc: BaseException) -> bool:
    """Determina se un errore HTTP e' ritentabile (429 o 5xx)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True
    return False


# Decorator condiviso per retry con backoff esponenziale
_llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)


@dataclass
class LLMResponse:
    """Risposta da un singolo provider LLM."""
    provider: str
    model: str
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    error: str | None = None
    success: bool = True


@dataclass
class BoardResponse:
    """Risposta del CDA: tutte le risposte individuali + sintesi."""
    responses: list[LLMResponse] = field(default_factory=list)
    synthesis: str = ""
    chairman: str = ""
    consensus_level: str = ""  # high, medium, low
    latency_ms: int = 0
    board_mode: str = "sync"  # "sync" (blocking) or "async" (fire-and-forget)


# Model routing per tipo di task — Phase 2 Step 2.6
# Mappa task_type → lista di provider preferiti (in ordine di preferenza)
# Il primo provider disponibile viene usato.
MODEL_ROUTING: dict[str, list[str]] = {
    "routing":      ["gemini", "ollama"],       # Routing veloce, modelli piccoli
    "analysis":     ["claude", "gemini", "openai"],  # Analisi approfondita
    "architecture": ["claude", "openai", "gemini"],  # Design architetturale
    "code":         ["claude", "openai", "qwen"],    # Generazione codice
    "security":     ["claude", "openai", "gemini"],  # Analisi sicurezza
    "synthesis":    ["gemini", "claude", "openai"],   # Sintesi board
    "quick":        ["gemini", "ollama", "grok"],     # Risposte rapide
    "creative":     ["claude", "openai", "gemini"],   # Task creativi
}


class LLMProvider:
    """Provider LLM unificato con supporto multi-backend e modalita' board."""

    def __init__(self) -> None:
        self._providers: dict[str, dict[str, Any]] = {}
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=API_TIMEOUT,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._last_board_result: BoardResponse | None = None
        self._refresh_config()

    async def close(self) -> None:
        """Chiudi il client HTTP persistente. Chiamare in shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("LLMProvider HTTP client closed")

    def _refresh_config(self) -> None:
        """Ricarica la configurazione dei provider dalle settings."""
        self._providers = {}

        # Ollama (sempre disponibile se url configurato)
        if settings.ollama_base_url:
            self._providers["ollama"] = {
                "type": "ollama",
                "url": settings.ollama_base_url,
                "model": settings.default_model,
                "name": "Ollama",
            }

        # Gemini
        if settings.gemini_api_key:
            self._providers["gemini"] = {
                "type": "gemini",
                "api_key": settings.gemini_api_key,
                "model": settings.gemini_model,
                "name": "Gemini",
            }

        # Claude
        if settings.claude_api_key:
            self._providers["claude"] = {
                "type": "claude",
                "api_key": settings.claude_api_key,
                "model": settings.claude_model,
                "name": "Claude",
            }

        # OpenAI
        if settings.openai_api_key:
            self._providers["openai"] = {
                "type": "openai",
                "api_key": settings.openai_api_key,
                "model": settings.openai_model,
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
            }

        # Grok (xAI) — OpenAI-compatible
        if settings.grok_api_key:
            self._providers["grok"] = {
                "type": "openai_compat",
                "api_key": settings.grok_api_key,
                "model": settings.grok_model,
                "name": "Grok",
                "base_url": settings.grok_base_url,
            }

        # Mercury (Inception Labs) — OpenAI-compatible
        if settings.mercury_api_key:
            self._providers["mercury"] = {
                "type": "openai_compat",
                "api_key": settings.mercury_api_key,
                "model": settings.mercury_model,
                "name": "Mercury",
                "base_url": settings.mercury_base_url,
            }

        # Qwen3 (Alibaba DashScope) — OpenAI-compatible
        if settings.qwen_api_key:
            self._providers["qwen"] = {
                "type": "openai_compat",
                "api_key": settings.qwen_api_key,
                "model": settings.qwen_model,
                "name": "Qwen3",
                "base_url": settings.qwen_base_url,
            }

    @classmethod
    def for_tenant(cls, tenant) -> LLMProvider:
        """Create an LLMProvider configured for a specific tenant.

        Uses the tenant's LLM config (provider, API key) while falling
        back to global settings for non-configured providers.
        If no tenant-specific config, returns a default instance.
        """
        instance = cls()

        config = getattr(tenant, "config", None)
        if config and config.llm_api_key:
            # Override the active provider with tenant's preference
            provider_name = config.llm_provider or "claude"
            instance._providers[provider_name] = {
                "type": cls._provider_type(provider_name),
                "api_key": config.llm_api_key,
                "model": cls._default_model(provider_name),
                "name": provider_name.capitalize(),
                "base_url": cls._default_base_url(provider_name),
            }
        return instance

    @staticmethod
    def _provider_type(name: str) -> str:
        """Map provider name to type."""
        if name in ("ollama",):
            return "ollama"
        if name in ("gemini",):
            return "gemini"
        if name in ("claude",):
            return "claude"
        if name in ("openai",):
            return "openai"
        return "openai_compat"

    @staticmethod
    def _default_model(name: str) -> str:
        """Default model for a provider."""
        models = {
            "ollama": settings.default_model,
            "gemini": settings.gemini_model,
            "claude": settings.claude_model,
            "openai": settings.openai_model,
            "grok": settings.grok_model,
            "mercury": settings.mercury_model,
            "qwen": settings.qwen_model,
        }
        return models.get(name, "")

    @staticmethod
    def _default_base_url(name: str) -> str:
        """Default base URL for a provider."""
        urls = {
            "ollama": settings.ollama_base_url,
            "openai": "https://api.openai.com/v1",
            "grok": settings.grok_base_url,
            "mercury": settings.mercury_base_url,
            "qwen": settings.qwen_base_url,
        }
        return urls.get(name, "")

    @property
    def available_providers(self) -> list[str]:
        self._refresh_config()
        return list(self._providers.keys())

    def update_provider(self, provider: str, api_key: str = "", model: str = "") -> None:
        """Aggiorna la configurazione di un provider a runtime."""
        if provider == "ollama":
            if model:
                settings.default_model = model
        elif provider == "gemini":
            if api_key:
                settings.gemini_api_key = api_key
            if model:
                settings.gemini_model = model
        elif provider == "claude":
            if api_key:
                settings.claude_api_key = api_key
            if model:
                settings.claude_model = model
        elif provider == "openai":
            if api_key:
                settings.openai_api_key = api_key
            if model:
                settings.openai_model = model
        elif provider == "grok":
            if api_key:
                settings.grok_api_key = api_key
            if model:
                settings.grok_model = model
        elif provider == "mercury":
            if api_key:
                settings.mercury_api_key = api_key
            if model:
                settings.mercury_model = model
        elif provider == "qwen":
            if api_key:
                settings.qwen_api_key = api_key
            if model:
                settings.qwen_model = model
        self._refresh_config()

    # ── Single Query ─────────────────────────────────────────────────

    async def query(
        self,
        prompt: str,
        system: str = "",
        provider: str = "",
    ) -> LLMResponse:
        """Esegui una query su un singolo provider."""
        self._refresh_config()
        provider = provider or settings.active_provider

        if provider not in self._providers:
            return LLMResponse(
                provider=provider, model="", content="",
                error=f"Provider '{provider}' non configurato",
                success=False,
            )

        cfg = self._providers[provider]
        start = time.monotonic()

        try:
            if cfg["type"] == "ollama":
                result = await self._call_ollama(prompt, system, cfg)
            elif cfg["type"] == "gemini":
                result = await self._call_gemini(prompt, system, cfg)
            elif cfg["type"] == "claude":
                result = await self._call_claude(prompt, system, cfg)
            elif cfg["type"] in ("openai", "openai_compat"):
                result = await self._call_openai(prompt, system, cfg)
            else:
                result = LLMResponse(
                    provider=provider, model=cfg["model"], content="",
                    error=f"Tipo provider sconosciuto: {cfg['type']}",
                    success=False,
                )
        except Exception as e:
            result = LLMResponse(
                provider=provider, model=cfg.get("model", ""),
                content="", error=str(e), success=False,
            )

        result.latency_ms = int((time.monotonic() - start) * 1000)
        return result

    # ── Routed Query (task-type aware) ──────────────────────────────

    async def route_query(
        self,
        prompt: str,
        system: str = "",
        task_type: str = "",
    ) -> LLMResponse:
        """Query con routing automatico basato sul tipo di task.

        Seleziona il provider migliore per il task_type dalla MODEL_ROUTING map.
        Se nessun provider nella lista è disponibile, fallback ad active_provider.

        Args:
            prompt: La domanda
            system: System prompt
            task_type: Tipo di task (routing, analysis, architecture, code, security,
                       synthesis, quick, creative). Vuoto = usa active_provider.

        Returns:
            LLMResponse dal provider selezionato.
        """
        provider = self._resolve_provider_for_task(task_type)
        logger.debug(f"Route query: task_type={task_type!r} → provider={provider}")
        return await self.query(prompt, system, provider=provider)

    def _resolve_provider_for_task(self, task_type: str) -> str:
        """Risolvi il provider migliore per un task_type.

        Scorre la lista di provider preferiti per il task_type e ritorna
        il primo che è configurato. Se nessuno è disponibile, usa active_provider.
        """
        if not task_type or task_type not in MODEL_ROUTING:
            return settings.active_provider

        self._refresh_config()
        for preferred in MODEL_ROUTING[task_type]:
            if preferred in self._providers:
                return preferred

        # Nessun provider preferito disponibile → fallback
        return settings.active_provider

    # ── Board Query (CDA) ────────────────────────────────────────────

    async def board_query(
        self,
        prompt: str,
        system: str = "",
        providers: list[str] | None = None,
        board_mode: str = "sync",
    ) -> BoardResponse:
        """Esegui la query su tutti i provider in parallelo + sintesi.

        Args:
            prompt: La domanda
            system: System prompt
            providers: Lista provider da usare (default: tutti)
            board_mode: "sync" (blocking, aspetta tutti) o "async" (fire-and-forget,
                        ritorna il primo risultato e lancia sintesi in background)
        """
        self._refresh_config()
        start = time.monotonic()

        target_providers = providers or list(self._providers.keys())
        if not target_providers:
            return BoardResponse(
                synthesis="Nessun provider LLM configurato. Aggiungi almeno una API key nelle Settings.",
                board_mode=board_mode,
            )

        if board_mode == "async" and len(target_providers) > 1:
            return await self._board_query_async(prompt, system, target_providers, start)

        return await self._board_query_sync(prompt, system, target_providers, start)

    async def _board_query_sync(
        self,
        prompt: str,
        system: str,
        target_providers: list[str],
        start: float,
    ) -> BoardResponse:
        """Board query SYNC: aspetta tutti i provider, poi sintetizza."""
        # Chiama tutti in parallelo
        tasks = [
            self.query(prompt, system, p)
            for p in target_providers
            if p in self._providers
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        board = BoardResponse(board_mode="sync")
        for r in responses:
            if isinstance(r, Exception):
                board.responses.append(LLMResponse(
                    provider="unknown", model="", content="",
                    error=str(r), success=False,
                ))
            else:
                board.responses.append(r)

        # Sintesi da parte del chairman
        successful = [r for r in board.responses if r.success and r.content]
        if len(successful) >= 2:
            board.synthesis = await self._synthesize(prompt, successful)
            board.chairman = settings.board_chairman
            board.consensus_level = self._assess_consensus(successful)
        elif len(successful) == 1:
            board.synthesis = successful[0].content
            board.chairman = successful[0].provider
            board.consensus_level = "single"
        else:
            board.synthesis = "Nessun provider ha risposto con successo."
            board.consensus_level = "none"

        board.latency_ms = int((time.monotonic() - start) * 1000)
        return board

    async def _board_query_async(
        self,
        prompt: str,
        system: str,
        target_providers: list[str],
        start: float,
    ) -> BoardResponse:
        """Board query ASYNC: ritorna il primo provider, lancia gli altri in background.

        Il risultato contiene la risposta del primo provider che completa.
        Gli altri provider e la sintesi vengono lanciati come background task
        e il risultato completo sarà disponibile nel _last_board_result.
        """
        # Crea le task per tutti i provider
        tasks = [
            asyncio.create_task(self.query(prompt, system, p))
            for p in target_providers
            if p in self._providers
        ]

        if not tasks:
            return BoardResponse(
                synthesis="Nessun provider disponibile.",
                board_mode="async",
            )

        # Aspetta il primo risultato
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        first_result: LLMResponse | None = None
        for task in done:
            try:
                result = task.result()
                if result.success:
                    first_result = result
                    break
            except Exception:
                continue

        if not first_result and done:
            # Prendi anche un risultato con errore se necessario
            for task in done:
                try:
                    first_result = task.result()
                    break
                except Exception:
                    pass

        # Costruisci la risposta immediata
        board = BoardResponse(board_mode="async")
        if first_result:
            board.responses.append(first_result)
            board.synthesis = first_result.content
            board.chairman = first_result.provider
            board.consensus_level = "async_first"

        board.latency_ms = int((time.monotonic() - start) * 1000)

        # Lancia la raccolta degli altri risultati + sintesi in background
        if pending:
            asyncio.create_task(
                self._complete_board_async(prompt, board, list(pending))
            )

        # Salva per accesso futuro
        self._last_board_result = board
        return board

    async def _complete_board_async(
        self,
        prompt: str,
        board: BoardResponse,
        pending_tasks: list[asyncio.Task],
    ) -> None:
        """Completa la board query in background: raccoglie i risultati rimanenti e sintetizza."""
        try:
            done, _ = await asyncio.wait(pending_tasks, timeout=API_TIMEOUT)
            for task in done:
                try:
                    result = task.result()
                    board.responses.append(result)
                except Exception as e:
                    board.responses.append(LLMResponse(
                        provider="unknown", model="", content="",
                        error=str(e), success=False,
                    ))

            # Sintetizza se abbiamo abbastanza risposte
            successful = [r for r in board.responses if r.success and r.content]
            if len(successful) >= 2:
                board.synthesis = await self._synthesize(prompt, successful)
                board.chairman = settings.board_chairman
                board.consensus_level = self._assess_consensus(successful)

            logger.info(f"Board async completed: {len(board.responses)} responses, consensus={board.consensus_level}")
        except Exception as e:
            logger.warning(f"Board async completion failed: {e}")

    async def _synthesize(self, original_prompt: str, responses: list[LLMResponse]) -> str:
        """Il chairman sintetizza le risposte del board."""
        synthesis_prompt = "Sei il chairman di un consiglio di amministrazione AI.\n"
        synthesis_prompt += "Hai ricevuto le analisi di piu' esperti sulla stessa domanda.\n"
        synthesis_prompt += "Sintetizza le risposte trovando consenso e divergenze.\n"
        synthesis_prompt += "Dai la risposta finale migliore, motivando le scelte.\n\n"
        synthesis_prompt += f"DOMANDA ORIGINALE:\n{original_prompt}\n\n"

        for r in responses:
            synthesis_prompt += f"--- {r.provider.upper()} ({r.model}) ---\n"
            synthesis_prompt += r.content + "\n\n"

        synthesis_prompt += "--- SINTESI DEL CHAIRMAN ---\n"
        synthesis_prompt += "Analizza i punti in comune, le divergenze, e dai la risposta finale."

        chairman = settings.board_chairman
        if chairman not in self._providers:
            # Fallback: usa il primo provider disponibile
            chairman = next(iter(self._providers), "ollama")

        result = await self.query(synthesis_prompt, provider=chairman)
        return result.content if result.success else f"Errore sintesi: {result.error}"

    @staticmethod
    def _assess_consensus(responses: list[LLMResponse]) -> str:
        """Valuta il livello di consenso (euristico semplice)."""
        if len(responses) < 2:
            return "single"
        # Euristico: se le risposte sono lunghe e simili in lunghezza = probabile consenso
        lengths = [len(r.content) for r in responses]
        avg = sum(lengths) / len(lengths)
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        # Bassa varianza relativa = alto consenso
        cv = (variance ** 0.5) / avg if avg > 0 else 1
        if cv < 0.3:
            return "high"
        elif cv < 0.6:
            return "medium"
        return "low"

    # ── Test Connection ──────────────────────────────────────────────

    async def test_provider(self, provider: str) -> dict[str, Any]:
        """Testa la connessione a un provider."""
        result = await self.query("Rispondi solo: OK", provider=provider)
        return {
            "provider": provider,
            "success": result.success,
            "latency_ms": result.latency_ms,
            "model": result.model,
            "error": result.error,
        }

    # ── Provider Implementations ─────────────────────────────────────

    @_llm_retry
    async def _call_ollama(self, prompt: str, system: str, cfg: dict) -> LLMResponse:
        """Chiamata a Ollama (locale)."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await self._client.post(
            f"{cfg['url']}/api/chat",
            json={"model": cfg["model"], "messages": messages, "stream": False},
        )
        resp.raise_for_status()
        data = resp.json()

        return LLMResponse(
            provider="ollama",
            model=cfg["model"],
            content=data.get("message", {}).get("content", ""),
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
        )

    # ── Streaming ─────────────────────────────────────────────────────

    async def stream_query(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        provider: str = "",
    ):
        """Streaming query — yield token-by-token. Supporta tutti i provider.

        Args:
            messages: Chat history [{"role": "user"|"assistant", "content": "..."}]
            system: System prompt
            provider: Provider da usare (default: active_provider)

        Yields:
            str: Ogni token/chunk della risposta
        """
        self._refresh_config()
        provider = provider or settings.active_provider

        if provider not in self._providers:
            yield f"[ERROR] Provider '{provider}' non configurato"
            return

        cfg = self._providers[provider]

        if cfg["type"] == "ollama":
            async for chunk in self._stream_ollama(messages, system, cfg):
                yield chunk
        elif cfg["type"] == "gemini":
            async for chunk in self._stream_gemini(messages, system, cfg):
                yield chunk
        elif cfg["type"] == "claude":
            async for chunk in self._stream_claude(messages, system, cfg):
                yield chunk
        elif cfg["type"] in ("openai", "openai_compat"):
            async for chunk in self._stream_openai(messages, system, cfg):
                yield chunk

    async def _stream_ollama(self, messages: list[dict], system: str, cfg: dict):
        """Streaming da Ollama."""
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        async with self._client.stream(
            "POST",
            f"{cfg['url']}/api/chat",
            json={"model": cfg["model"], "messages": all_messages, "stream": True},
        ) as resp:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def _stream_gemini(self, messages: list[dict], system: str, cfg: dict):
        """Streaming da Gemini (SSE)."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:streamGenerateContent"
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
            contents.append({"role": "model", "parts": [{"text": "Capito, procedo."}]})
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        async with self._client.stream(
            "POST", url,
            params={"key": cfg["api_key"], "alt": "sse"},
            json={"contents": contents},
        ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        for p in parts:
                            text = p.get("text", "")
                            if text:
                                yield text
                    except (json.JSONDecodeError, IndexError):
                        continue

    async def _stream_claude(self, messages: list[dict], system: str, cfg: dict):
        """Streaming da Claude (SSE)."""
        body: dict[str, Any] = {
            "model": cfg["model"],
            "max_tokens": 4096,
            "messages": messages,
            "stream": True,
        }
        if system:
            body["system"] = system

        async with self._client.stream(
            "POST", "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": cfg["api_key"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                        if data.get("type") == "content_block_delta":
                            text = data.get("delta", {}).get("text", "")
                            if text:
                                yield text
                    except json.JSONDecodeError:
                        continue

    async def _stream_openai(self, messages: list[dict], system: str, cfg: dict):
        """Streaming da OpenAI e provider OpenAI-compatibili (Grok, Mercury, Qwen3)."""
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        base_url = cfg.get("base_url", "https://api.openai.com/v1")

        async with self._client.stream(
            "POST", f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json={"model": cfg["model"], "messages": all_messages, "stream": True},
        ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                        continue
                    try:
                        data = json.loads(line[6:])
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    @_llm_retry
    async def _call_gemini(self, prompt: str, system: str, cfg: dict) -> LLMResponse:
        """Chiamata a Google Gemini API."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"

        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
            contents.append({"role": "model", "parts": [{"text": "Capito, procedo."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        resp = await self._client.post(
            url,
            params={"key": cfg["api_key"]},
            json={"contents": contents},
        )
        resp.raise_for_status()
        data = resp.json()

        content = ""
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            content = "".join(p.get("text", "") for p in parts)

        usage = data.get("usageMetadata", {})
        return LLMResponse(
            provider="gemini",
            model=cfg["model"],
            content=content,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
        )

    @_llm_retry
    async def _call_claude(self, prompt: str, system: str, cfg: dict) -> LLMResponse:
        """Chiamata a Anthropic Claude API."""
        messages = [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {
            "model": cfg["model"],
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            body["system"] = system

        resp = await self._client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": cfg["api_key"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage = data.get("usage", {})
        return LLMResponse(
            provider="claude",
            model=cfg["model"],
            content=content,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
        )

    @_llm_retry
    async def _call_openai(self, prompt: str, system: str, cfg: dict) -> LLMResponse:
        """Chiamata a OpenAI e provider OpenAI-compatibili (Grok, Mercury, Qwen3)."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        base_url = cfg.get("base_url", "https://api.openai.com/v1")

        resp = await self._client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json={"model": cfg["model"], "messages": messages},
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return LLMResponse(
            provider="openai",
            model=cfg["model"],
            content=content,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )
