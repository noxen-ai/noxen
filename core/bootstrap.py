# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
"""Noxen — Bootstrap Health Checks.

Esegue health checks all'avvio per verificare che tutti i
componenti necessari siano disponibili e funzionanti.
"""

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import httpx

from core.logger import get_logger

logger = get_logger("bootstrap")


@dataclass
class HealthCheckResult:
    """Risultato di un singolo health check."""
    name: str
    status: str       # "ok" | "warning" | "error"
    message: str
    required: bool    # se True e status="error" -> abort


@dataclass
class BootstrapResult:
    """Risultato complessivo del bootstrap."""
    success: bool
    checks: List[HealthCheckResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class NoxenBootstrap:
    """Esegue health checks all'avvio di Noxen.

    Checks obbligatori (required=True):
    - Qdrant raggiungibile
    - Embedding provider funzionante
    - Directory dati scrivibili
    - Tenant default esistente

    Checks opzionali (required=False):
    - Claude Code CLI nel PATH
    - GitHub token configurato
    - Exa API key configurata
    - Firecrawl API key configurata
    """

    def __init__(self, settings, qdrant_client, tenant_repo):
        self._settings = settings
        self._qdrant = qdrant_client
        self._tenant_repo = tenant_repo

    async def run(self) -> BootstrapResult:
        """Esegue tutti i checks in sequenza."""
        checks = []

        # Checks obbligatori
        checks.append(await self._check_internet())
        checks.append(await self._check_license_key())
        checks.append(await self._check_qdrant())
        checks.append(await self._check_embedding())
        checks.append(await self._check_data_dirs())
        checks.append(await self._check_default_tenant())

        # Checks opzionali
        checks.append(await self._check_claude_cli())
        checks.append(await self._check_github_token())
        checks.append(await self._check_exa_key())
        checks.append(await self._check_firecrawl_key())

        errors = [
            c.message for c in checks
            if c.status == "error" and c.required
        ]
        warnings = [
            c.message for c in checks
            if c.status == "warning" or
               (c.status == "error" and not c.required)
        ]

        # Log risultati
        for check in checks:
            if check.status == "ok":
                logger.info("bootstrap_check_ok", check=check.name)
            elif check.status == "warning":
                logger.warning(
                    "bootstrap_check_warning",
                    check=check.name,
                    message=check.message,
                )
            else:
                level = "error" if check.required else "warning"
                getattr(logger, level)(
                    "bootstrap_check_failed",
                    check=check.name,
                    message=check.message,
                    required=check.required,
                )

        success = len(errors) == 0

        if not success:
            logger.error("bootstrap_failed", errors=errors)
        else:
            ok_count = len([c for c in checks if c.status == "ok"])
            logger.info(
                "bootstrap_complete",
                warnings=len(warnings),
                checks_passed=ok_count,
                total_checks=len(checks),
            )

        return BootstrapResult(
            success=success,
            checks=checks,
            errors=errors,
            warnings=warnings,
        )

    async def _check_internet(self) -> HealthCheckResult:
        """Verifica connessione internet."""
        try:
            async with httpx.AsyncClient() as client:
                await client.get("https://api.anthropic.com", timeout=5.0)
            return HealthCheckResult(
                name="internet",
                status="ok",
                message="Internet connection OK",
                required=True,
            )
        except Exception:
            return HealthCheckResult(
                name="internet",
                status="error",
                message=(
                    "No internet connection. "
                    "Noxen requires internet for: "
                    "LLM providers, license validation, "
                    "Research Agent. "
                    "Check your connection and restart."
                ),
                required=True,
            )

    async def _check_license_key(self) -> HealthCheckResult:
        """Verifica che la license key sia configurata e valida.

        Usa cache locale per non bloccare l'avvio se il server
        licenze non è raggiungibile (grace period).
        """
        license_key = self._settings.noxen_license_key
        cache_path = Path(self._settings.data_dir) / ".license_cache.json"
        grace_days = self._settings.license_grace_period_days

        # No key configured
        if not license_key:
            return HealthCheckResult(
                name="license_key",
                status="warning",
                message=(
                    "Nessuna license key configurata. "
                    "Esegui: noxen auth  oppure imposta NOXEN_LICENSE_KEY nel .env"
                ),
                required=False,
            )

        # Try to validate against server
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self._settings.license_server_url}/v1/license/validate",
                    json={"key": license_key, "version": "0.3.0"},
                    timeout=5.0,
                )
                data = r.json()

            if data.get("valid"):
                # Cache successful validation
                cache_data = {
                    "valid": True,
                    "plan": data.get("plan", "unknown"),
                    "validated_at": time.time(),
                }
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(cache_data))
                except Exception:
                    pass

                return HealthCheckResult(
                    name="license_key",
                    status="ok",
                    message=f"License valida (plan: {data.get('plan', 'unknown')})",
                    required=False,
                )
            else:
                return HealthCheckResult(
                    name="license_key",
                    status="warning",
                    message=(
                        "License key non valida. "
                        "Verifica su https://noxen.ai/dashboard"
                    ),
                    required=False,
                )

        except Exception:
            # Server non raggiungibile — controlla cache (grace period)
            if cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text())
                    validated_at = cached.get("validated_at", 0)
                    elapsed_days = (time.time() - validated_at) / 86400

                    if cached.get("valid") and elapsed_days <= grace_days:
                        return HealthCheckResult(
                            name="license_key",
                            status="ok",
                            message=(
                                f"License in cache (grace period: "
                                f"{int(grace_days - elapsed_days)}d rimanenti)"
                            ),
                            required=False,
                        )
                except Exception:
                    pass

            return HealthCheckResult(
                name="license_key",
                status="warning",
                message=(
                    "Impossibile validare la license key "
                    "(server non raggiungibile, nessuna cache valida). "
                    "Funzionalità limitate."
                ),
                required=False,
            )

    async def _check_qdrant(self) -> HealthCheckResult:
        """Verifica che Qdrant sia raggiungibile."""
        try:
            ok = await self._qdrant.health_check()
            if ok:
                return HealthCheckResult(
                    name="qdrant",
                    status="ok",
                    message="Qdrant raggiungibile",
                    required=True,
                )
            return HealthCheckResult(
                name="qdrant",
                status="error",
                message=(
                    f"Qdrant non raggiungibile su {self._settings.qdrant_url}. "
                    f"Avvia con: cd docker/qdrant && docker-compose up -d"
                ),
                required=True,
            )
        except Exception as e:
            return HealthCheckResult(
                name="qdrant",
                status="error",
                message=(
                    f"Qdrant errore: {e}. "
                    f"Avvia con: cd docker/qdrant && docker-compose up -d"
                ),
                required=True,
            )

    async def _check_embedding(self) -> HealthCheckResult:
        """Verifica che il provider embedding funzioni."""
        try:
            from core.embedding_provider import FastEmbedProvider
            provider = FastEmbedProvider()
            result = await provider.embed(["test"])
            if result and len(result[0]) > 0:
                return HealthCheckResult(
                    name="embedding",
                    status="ok",
                    message="FastEmbed funzionante",
                    required=True,
                )
            return HealthCheckResult(
                name="embedding",
                status="error",
                message="FastEmbed ha ritornato risultato vuoto",
                required=True,
            )
        except Exception as e:
            return HealthCheckResult(
                name="embedding",
                status="error",
                message=(
                    f"Embedding provider errore: {e}. "
                    f"Esegui: pip install fastembed"
                ),
                required=True,
            )

    async def _check_data_dirs(self) -> HealthCheckResult:
        """Verifica che le directory dati siano scrivibili."""
        dirs = [
            Path(self._settings.data_dir),
            Path(self._settings.research_sandbox_dir),
        ]
        failed = []
        for d in dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
                test_file = d / ".write_test"
                test_file.write_text("test")
                test_file.unlink()
            except Exception:
                failed.append(str(d))

        if failed:
            return HealthCheckResult(
                name="data_dirs",
                status="error",
                message=f"Directory non scrivibili: {', '.join(failed)}",
                required=True,
            )
        return HealthCheckResult(
            name="data_dirs",
            status="ok",
            message="Directory dati OK",
            required=True,
        )

    async def _check_default_tenant(self) -> HealthCheckResult:
        """Verifica che il tenant default esista."""
        try:
            tenant = await self._tenant_repo.ensure_default_tenant()
            return HealthCheckResult(
                name="default_tenant",
                status="ok",
                message=f"Tenant default: {tenant.id}",
                required=True,
            )
        except Exception as e:
            return HealthCheckResult(
                name="default_tenant",
                status="error",
                message=f"Tenant default errore: {e}",
                required=True,
            )

    async def _check_claude_cli(self) -> HealthCheckResult:
        """Verifica che Claude Code CLI sia nel PATH."""
        claude_path = shutil.which("claude")
        if claude_path:
            return HealthCheckResult(
                name="claude_cli",
                status="ok",
                message=f"Claude CLI: {claude_path}",
                required=False,
            )
        return HealthCheckResult(
            name="claude_cli",
            status="error",
            message=(
                "Claude Code CLI non trovato nel PATH. "
                "L'Execution Engine non funzionera'. "
                "Installa con: npm install -g @anthropic-ai/claude-code"
            ),
            required=False,
        )

    async def _check_github_token(self) -> HealthCheckResult:
        """Verifica che il GitHub token sia configurato."""
        if self._settings.github_token:
            return HealthCheckResult(
                name="github_token",
                status="ok",
                message="GitHub token configurato",
                required=False,
            )
        return HealthCheckResult(
            name="github_token",
            status="warning",
            message=(
                "GitHub token non configurato. "
                "Research Agent funzionera' con rate limit ridotto. "
                "Configura: NOXEN_GITHUB_TOKEN=..."
            ),
            required=False,
        )

    async def _check_exa_key(self) -> HealthCheckResult:
        """Verifica che la Exa API key sia configurata."""
        if self._settings.exa_api_key:
            return HealthCheckResult(
                name="exa_api_key",
                status="ok",
                message="Exa API key configurata",
                required=False,
            )
        return HealthCheckResult(
            name="exa_api_key",
            status="warning",
            message=(
                "Exa API key non configurata. "
                "Web research limitato. "
                "Configura: NOXEN_EXA_API_KEY=..."
            ),
            required=False,
        )

    async def _check_firecrawl_key(self) -> HealthCheckResult:
        """Verifica che la Firecrawl API key sia configurata."""
        if self._settings.firecrawl_api_key:
            return HealthCheckResult(
                name="firecrawl_key",
                status="ok",
                message="Firecrawl API key configurata",
                required=False,
            )
        return HealthCheckResult(
            name="firecrawl_key",
            status="warning",
            message=(
                "Firecrawl API key non configurata. "
                "Estrazione documentazione limitata. "
                "Configura: NOXEN_FIRECRAWL_API_KEY=..."
            ),
            required=False,
        )
