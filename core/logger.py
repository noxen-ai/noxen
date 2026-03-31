"""Structured logging via structlog — configurazione centralizzata.

Step 0.6 della migrazione v0.3.0: logging strutturato JSON-ready
per observability, debugging e futura integrazione con log aggregators.

Uso:
    from core.logger import get_logger

    logger = get_logger("noxen.engine")
    logger.info("engine started", project="myapp", goals=5)
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """Configura structlog + logging standard.

    Args:
        level: Livello di log (DEBUG, INFO, WARNING, ERROR).
        json_output: Se True, output JSON (per produzione/log aggregators).
                     Se False, output colorato human-readable (per sviluppo).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processors per tutti i logger
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        # Produzione: JSON puro per log aggregators
        renderer = structlog.processors.JSONRenderer()
    else:
        # Sviluppo: output colorato human-friendly
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=40,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configura anche il logging standard per librerie terze
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Riduci verbosita' di librerie rumorose
    for noisy in ("httpx", "httpcore", "chromadb", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """Ottieni un logger strutturato.

    Args:
        name: Nome del logger (es. "noxen.engine").

    Returns:
        BoundLogger con supporto per key-value logging.

    Esempio:
        logger = get_logger("noxen.spider")
        logger.info("scan started", project="myapp", mode="deep")
        logger.warning("slow query", duration_ms=1500, table="users")
    """
    return structlog.get_logger(name)
