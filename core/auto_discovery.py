"""Noxen - Auto Discovery.

Scansiona una cartella progetto e scopre automaticamente:
  - Microservizi (sotto-cartelle con composer.json, package.json, ecc.)
  - Framework e linguaggio per ognuno
  - Configurazioni DB (.env, config files)
  - Entry points e struttura

Genera un ecosystem-map.json usato dal motore di orchestrazione.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("noxen.discovery")

# File che indicano la root di un microservizio
SERVICE_MARKERS = {
    "composer.json": "php",
    "package.json": "javascript",
    "requirements.txt": "python",
    "Pipfile": "python",
    "pyproject.toml": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pom.xml": "java",
    "build.gradle": "java",
    "mix.exs": "elixir",
}

# Pattern per detectare framework dal contenuto
FRAMEWORK_PATTERNS = {
    "laravel": [r'"laravel/framework"', r"artisan"],
    "symfony": [r'"symfony/framework-bundle"'],
    "express": [r'"express"', r"require\(['\"]express['\"]"],
    "nestjs": [r'"@nestjs/core"'],
    "nextjs": [r'"next"'],
    "nuxt": [r'"nuxt"'],
    "vue": [r'"vue"'],
    "react": [r'"react"'],
    "angular": [r'"@angular/core"'],
    "django": [r'"django"', r"DJANGO_SETTINGS_MODULE"],
    "flask": [r'"flask"', r"from flask"],
    "fastapi": [r'"fastapi"', r"from fastapi"],
    "rails": [r"gem ['\"]rails['\"]"],
    "spring": [r"spring-boot"],
    "gin": [r'"github.com/gin-gonic/gin"'],
}

# File che contengono configurazione DB
DB_CONFIG_FILES = [
    ".env", ".env.local", ".env.production",
    "config/database.php", "config/database.yml", "config/database.js",
    "database.yml", "knexfile.js", "ormconfig.json", "ormconfig.ts",
    "prisma/schema.prisma", "drizzle.config.ts",
]

# Pattern per estrarre credenziali DB da .env
DB_ENV_PATTERNS = {
    "host": [r"DB_HOST=(.+)", r"MYSQL_HOST=(.+)", r"DATABASE_HOST=(.+)"],
    "port": [r"DB_PORT=(.+)", r"MYSQL_PORT=(.+)", r"DATABASE_PORT=(.+)"],
    "user": [r"DB_USERNAME=(.+)", r"DB_USER=(.+)", r"MYSQL_USER=(.+)"],
    "password": [r"DB_PASSWORD=(.+)", r"MYSQL_PASSWORD=(.+)", r"DATABASE_PASSWORD=(.+)"],
    "database": [r"DB_DATABASE=(.+)", r"DB_NAME=(.+)", r"MYSQL_DATABASE=(.+)"],
}


@dataclass
class ServiceInfo:
    """Informazioni su un singolo microservizio scoperto."""
    name: str
    path: str                         # Path assoluto
    language: str = "unknown"
    framework: str = "unknown"
    has_db: bool = False
    db_config: dict[str, str] = field(default_factory=dict)
    entry_points: list[str] = field(default_factory=list)
    dependencies_file: str = ""
    file_count: int = 0
    structure: list[str] = field(default_factory=list)  # Top-level dirs


@dataclass
class EcosystemMap:
    """Mappa completa dell'ecosistema progetto."""
    root_path: str
    services: list[ServiceInfo] = field(default_factory=list)
    total_services: int = 0
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    db_configs_found: int = 0


class AutoDiscovery:
    """Scansiona un progetto e genera la mappa dell'ecosistema."""

    def __init__(self, root_path: Path) -> None:
        self.root = root_path
        self.map: EcosystemMap | None = None

    def scan(self) -> EcosystemMap:
        """Scansiona il progetto e ritorna la mappa."""
        logger.info(f"Scansione ecosistema: {self.root}")

        services: list[ServiceInfo] = []

        # Prima controlla se la root stessa e' un progetto
        root_service = self._scan_directory(self.root)
        if root_service and root_service.language != "unknown":
            root_service.name = self.root.name
            services.append(root_service)

        # Poi scansiona le sotto-cartelle (1 livello)
        if self.root.is_dir():
            for item in sorted(self.root.iterdir()):
                if not item.is_dir():
                    continue
                if item.name.startswith((".","_")) or item.name in (
                    "node_modules", "vendor", "__pycache__", ".git",
                    "dist", "build", ".venv", "venv",
                ):
                    continue

                svc = self._scan_directory(item)
                if svc and svc.language != "unknown":
                    services.append(svc)
                else:
                    # Scansiona un livello piu' in basso (monorepo con packages/)
                    for sub in sorted(item.iterdir()):
                        if sub.is_dir() and not sub.name.startswith((".", "_")):
                            deep_svc = self._scan_directory(sub)
                            if deep_svc and deep_svc.language != "unknown":
                                deep_svc.name = f"{item.name}/{sub.name}"
                                services.append(deep_svc)

        languages = list(set(s.language for s in services if s.language != "unknown"))
        frameworks = list(set(s.framework for s in services if s.framework != "unknown"))

        self.map = EcosystemMap(
            root_path=str(self.root),
            services=services,
            total_services=len(services),
            languages=sorted(languages),
            frameworks=sorted(frameworks),
            db_configs_found=sum(1 for s in services if s.has_db),
        )

        logger.info(
            f"Scoperto ecosistema: {len(services)} servizi, "
            f"linguaggi: {languages}, framework: {frameworks}"
        )
        return self.map

    def save_map(self, output_dir: Path) -> Path:
        """Salva la mappa come JSON."""
        if not self.map:
            self.scan()
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "ecosystem-map.json"
        path.write_text(json.dumps(asdict(self.map), indent=2, default=str))
        logger.info(f"Mappa salvata: {path}")
        return path

    def _scan_directory(self, path: Path) -> ServiceInfo | None:
        """Scansiona una singola directory come potenziale microservizio."""
        if not path.is_dir():
            return None

        svc = ServiceInfo(
            name=path.name,
            path=str(path),
        )

        # Detecta linguaggio da marker file
        for marker_file, language in SERVICE_MARKERS.items():
            if (path / marker_file).exists():
                svc.language = language
                svc.dependencies_file = marker_file
                break

        if svc.language == "unknown":
            return svc  # Ritorna comunque, il chiamante decide

        # Detecta framework
        svc.framework = self._detect_framework(path, svc.dependencies_file)

        # Cerca config DB
        db_cfg = self._find_db_config(path)
        if db_cfg:
            svc.has_db = True
            svc.db_config = db_cfg

        # Entry points
        svc.entry_points = self._find_entry_points(path, svc.language, svc.framework)

        # Struttura top-level
        svc.structure = [
            item.name for item in sorted(path.iterdir())
            if item.is_dir() and not item.name.startswith(".")
            and item.name not in ("node_modules", "vendor", "__pycache__", ".git")
        ][:20]  # Max 20 dirs

        # Conteggio file
        try:
            svc.file_count = sum(
                1 for f in path.rglob("*")
                if f.is_file()
                and not any(p in str(f) for p in ["node_modules", "vendor", "__pycache__", ".git"])
            )
        except Exception:
            svc.file_count = 0

        return svc

    def _detect_framework(self, path: Path, deps_file: str) -> str:
        """Detecta il framework leggendo il file dipendenze."""
        deps_path = path / deps_file
        if not deps_path.exists():
            return "unknown"

        try:
            content = deps_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return "unknown"

        for framework, patterns in FRAMEWORK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content):
                    return framework

        return "unknown"

    def _find_db_config(self, path: Path) -> dict[str, str]:
        """Cerca configurazione DB nel progetto."""
        config: dict[str, str] = {}

        for cfg_file in DB_CONFIG_FILES:
            cfg_path = path / cfg_file
            if not cfg_path.exists():
                continue

            try:
                content = cfg_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for key, patterns in DB_ENV_PATTERNS.items():
                for pattern in patterns:
                    m = re.search(pattern, content)
                    if m:
                        config[key] = m.group(1).strip().strip('"').strip("'")
                        break

        return config

    def _find_entry_points(self, path: Path, language: str, framework: str) -> list[str]:
        """Trova i probabili entry point del servizio."""
        candidates: list[str] = []

        entry_map = {
            "php": ["index.php", "public/index.php", "artisan", "server.php"],
            "javascript": ["index.js", "src/index.js", "server.js", "app.js", "src/main.ts", "src/app.ts"],
            "python": ["main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "src/main.py"],
            "go": ["main.go", "cmd/main.go"],
            "ruby": ["config.ru", "app.rb"],
            "java": ["src/main/java"],
            "rust": ["src/main.rs"],
        }

        for candidate in entry_map.get(language, []):
            if (path / candidate).exists():
                candidates.append(candidate)

        return candidates
