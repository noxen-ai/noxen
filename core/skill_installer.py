"""Noxen - Skill Installer.

Installa skill da:
  - GitHub URL (https://github.com/user/repo)
  - GitHub CLI shorthand (user/repo)
  - URL diretti a file .py (raw gist, raw GitHub)

Il sistema clona il repo in /skills/<gruppo>/<repo-name>/
e il SkillManager lo scopre automaticamente.

Gerarchia skill:
  skills/
    code_analysis/         <- gruppo (categoria)
      repo-a/              <- skill da GitHub
        __init__.py
        analyzer.py
      my_lint.py           <- skill singola
    devops/
      deploy_tool/
        __init__.py
    mia_skill.py           <- skill senza gruppo (root)

Nota sicurezza: tutti i comandi git usano asyncio.create_subprocess_exec
con argomenti separati (no shell injection).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger("noxen.installer")

REGISTRY_FILE = settings.data_dir / "installed_skills.json"
INSTALL_LOG_FILE = settings.data_dir / "install_log.json"


@dataclass
class InstalledSkill:
    """Traccia una skill installata da GitHub."""
    name: str
    source: str          # URL o user/repo originale
    install_path: str    # Path relativo a skills_dir
    group: str = ""      # Gruppo/categoria
    branch: str = "main"
    priority: int = 3    # Execution priority (1=orchestrator, 5=background)
    installed_at: float = 0.0


@dataclass
class RepoAnalysis:
    """Risultato dell'analisi pre-installazione di un repository."""
    url: str
    repo_name: str
    owner: str
    branch: str
    is_claude_skill: bool           # True se contiene indicatori di skill Claude Code
    confidence: str                 # "high", "medium", "low", "none"
    skill_indicators: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    recommendation: str = ""        # "install", "caution", "reject"
    summary: str = ""


class SkillInstaller:
    """Gestisce installazione, aggiornamento e rimozione di skill da GitHub."""

    def __init__(self) -> None:
        self.skills_dir = settings.skills_dir
        self._installed: dict[str, InstalledSkill] = {}
        self._install_log: list[dict] = []
        self._load_registry()
        self._load_install_log()

    # ── Public API ────────────────────────────────────────────────────

    @property
    def installed(self) -> dict[str, InstalledSkill]:
        return dict(self._installed)

    @property
    def install_log(self) -> list[dict]:
        return list(self._install_log)

    async def analyze_repo(self, url: str) -> RepoAnalysis:
        """Analizza un repo GitHub PRIMA dell'installazione.

        Shallow-clone in una directory temporanea, scansiona per indicatori
        di skill Claude Code, e restituisce un report dettagliato.
        """
        parsed = self._parse_github_url(url)
        if not parsed:
            return RepoAnalysis(
                url=url, repo_name="", owner="", branch="",
                is_claude_skill=False, confidence="none",
                warnings=["URL non valido. Usa: https://github.com/user/repo oppure user/repo"],
                recommendation="reject",
                summary="URL non riconosciuto come repository GitHub valido.",
            )

        owner, repo, branch = parsed
        repo_name = repo.removesuffix(".git")

        # Controlla se già installato
        dest = self.skills_dir / repo_name
        already_installed = dest.exists() or repo_name in self._installed

        # Shallow clone in temp directory
        tmpdir = Path(tempfile.mkdtemp(prefix="neuralhub_analyze_"))
        clone_url = f"https://github.com/{owner}/{repo_name}.git"

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", "--branch", branch,
                clone_url, str(tmpdir / repo_name),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                # Riprova senza branch
                proc = await asyncio.create_subprocess_exec(
                    "git", "clone", "--depth", "1",
                    clone_url, str(tmpdir / repo_name),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    err_msg = stderr.decode("utf-8", errors="replace").strip()
                    return RepoAnalysis(
                        url=url, repo_name=repo_name, owner=owner, branch=branch,
                        is_claude_skill=False, confidence="none",
                        warnings=[f"Clone fallito: {err_msg}"],
                        recommendation="reject",
                        summary=f"Impossibile clonare il repository: {err_msg}",
                    )

            repo_dir = tmpdir / repo_name
            indicators = self._scan_skill_indicators(repo_dir)

            # Calcola confidenza e raccomandazione
            confidence, recommendation, warnings = self._evaluate_indicators(
                indicators, repo_name, owner
            )

            if already_installed:
                warnings.append(f"Attenzione: '{repo_name}' è già installato. L'installazione aggiornerà la versione esistente.")

            # Sommario leggibile
            summary = self._build_analysis_summary(
                repo_name, owner, indicators, confidence, recommendation
            )

            return RepoAnalysis(
                url=url,
                repo_name=repo_name,
                owner=owner,
                branch=branch,
                is_claude_skill=confidence in ("high", "medium"),
                confidence=confidence,
                skill_indicators=indicators,
                warnings=warnings,
                recommendation=recommendation,
                summary=summary,
            )

        except Exception as e:
            logger.error(f"Errore analisi repo {url}: {e}")
            return RepoAnalysis(
                url=url, repo_name=repo_name, owner=owner, branch=branch,
                is_claude_skill=False, confidence="none",
                warnings=[f"Errore durante l'analisi: {str(e)}"],
                recommendation="reject",
                summary=f"Errore imprevisto durante l'analisi: {e}",
            )
        finally:
            # Cleanup temp directory
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _scan_skill_indicators(self, repo_dir: Path) -> dict[str, Any]:
        """Scansiona un repo per contenuto utile al RAG e indicatori skill.

        Il valore di un repo per Noxen dipende dalla CONOSCENZA
        documentale che contiene (markdown, docs, guide, SKILL.md, ecc.),
        non solo dalla struttura .claude-plugin formale.
        """
        indicators: dict[str, Any] = {
            # ── Formato nativo Claude Code ──
            "has_plugin_json": False,
            "has_marketplace_json": False,
            "has_claude_plugin_dir": False,
            "has_skills_dir": False,
            "skill_md_count": 0,
            "skill_md_files": [],
            "claude_md_count": 0,
            "claude_md_files": [],
            "command_files": [],
            "agent_files": [],
            "readme_mentions_claude": False,
            # ── Valore RAG: contenuto documentale ──
            "markdown_files_total": 0,
            "markdown_kb_total": 0,       # KB di testo .md
            "docs_dir_files": 0,          # file in docs/, documentation/, guides/
            "readme_kb": 0,               # KB del README principale
            "has_docs_dir": False,
            "knowledge_domains": [],       # domini di conoscenza rilevati
            # ── Struttura repo ──
            "top_level_contents": [],
            "languages_detected": [],
            "has_requirements_txt": False,
            "has_package_json": False,
            "has_pyproject_toml": False,
            "repo_size_files": 0,
            "code_files_count": 0,         # .py, .js, .ts, etc.
            "code_to_docs_ratio": 0.0,     # ratio codice/docs
        }

        # Top-level contents
        for item in sorted(repo_dir.iterdir()):
            if item.name.startswith("."):
                continue
            indicators["top_level_contents"].append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            })

        # ── .claude-plugin directory ──
        plugin_dir = repo_dir / ".claude-plugin"
        if plugin_dir.is_dir():
            indicators["has_claude_plugin_dir"] = True
            pjson = plugin_dir / "plugin.json"
            if pjson.exists():
                indicators["has_plugin_json"] = True
                try:
                    manifest = json.loads(pjson.read_text())
                    indicators["plugin_manifest"] = {
                        "name": manifest.get("name", ""),
                        "description": manifest.get("metadata", {}).get("description", "")
                            or manifest.get("description", ""),
                        "version": manifest.get("metadata", {}).get("version", "")
                            or manifest.get("version", ""),
                        "plugins_count": len(manifest.get("plugins", [])),
                    }
                except Exception:
                    pass

            mkt = plugin_dir / "marketplace.json"
            if mkt.exists():
                indicators["has_marketplace_json"] = True

            for sub_name, key in [("commands", "command_files"), ("agents", "agent_files")]:
                sub_dir = plugin_dir / sub_name
                if sub_dir.is_dir():
                    for f in sub_dir.glob("*.md"):
                        indicators[key].append(str(f.relative_to(repo_dir)))

        # skills/ directory
        if (repo_dir / "skills").is_dir():
            indicators["has_skills_dir"] = True

        # ── Scan SKILL.md, CLAUDE.md (max 5 livelli) ──
        for skill_file in repo_dir.rglob("SKILL.md"):
            try:
                rel = skill_file.relative_to(repo_dir)
                if len(rel.parts) <= 5:
                    indicators["skill_md_count"] += 1
                    indicators["skill_md_files"].append(str(rel))
            except ValueError:
                pass

        for claude_file in repo_dir.rglob("CLAUDE.md"):
            try:
                rel = claude_file.relative_to(repo_dir)
                if len(rel.parts) <= 5 and claude_file.parent != repo_dir:
                    indicators["claude_md_count"] += 1
                    indicators["claude_md_files"].append(str(rel))
            except ValueError:
                pass

        # Commands & agents outside .claude-plugin
        for pattern, key in [("commands/*.md", "command_files"), ("agents/*.md", "agent_files")]:
            for f in repo_dir.rglob(pattern):
                rel_str = str(f.relative_to(repo_dir))
                if rel_str not in indicators[key]:
                    indicators[key].append(rel_str)

        # ── README principale ──
        for readme in ["README.md", "readme.md", "Readme.md"]:
            rpath = repo_dir / readme
            if rpath.exists():
                try:
                    content = rpath.read_text(encoding="utf-8", errors="replace")
                    indicators["readme_kb"] = round(len(content.encode("utf-8")) / 1024, 1)
                    cl = content.lower()
                    if any(kw in cl for kw in ["claude", "skill", "anthropic", "claude code", "claude-plugin"]):
                        indicators["readme_mentions_claude"] = True
                except Exception:
                    pass
                break

        # ── Scan completo: markdown, codice, docs ──
        code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
                     ".rb", ".swift", ".kt", ".c", ".cpp", ".cs", ".sh"}
        lang_exts = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby",
            ".swift": "Swift", ".kt": "Kotlin", ".c": "C", ".cpp": "C++",
            ".cs": "C#", ".md": "Markdown",
        }
        docs_dirs = {"docs", "documentation", "guides", "guide", "doc",
                     "tutorials", "examples", "wiki", "knowledge", "resources"}
        detected_langs: set[str] = set()
        file_count = 0
        code_count = 0
        md_count = 0
        md_bytes = 0
        docs_dir_count = 0

        for f in repo_dir.rglob("*"):
            if not f.is_file():
                continue
            try:
                rel_parts = f.relative_to(repo_dir).parts
            except ValueError:
                continue
            # Skip .git
            if rel_parts and rel_parts[0] == ".git":
                continue

            file_count += 1
            ext = f.suffix.lower()

            if ext in lang_exts:
                detected_langs.add(lang_exts[ext])

            if ext in code_exts:
                code_count += 1

            if ext == ".md":
                md_count += 1
                try:
                    md_bytes += f.stat().st_size
                except OSError:
                    pass

            # File dentro directory docs-like
            if rel_parts and rel_parts[0].lower() in docs_dirs:
                docs_dir_count += 1

        indicators["repo_size_files"] = file_count
        indicators["code_files_count"] = code_count
        indicators["languages_detected"] = sorted(detected_langs)
        indicators["markdown_files_total"] = md_count
        indicators["markdown_kb_total"] = round(md_bytes / 1024, 1)
        indicators["docs_dir_files"] = docs_dir_count
        indicators["has_docs_dir"] = docs_dir_count > 0
        indicators["has_requirements_txt"] = (repo_dir / "requirements.txt").exists()
        indicators["has_package_json"] = (repo_dir / "package.json").exists()
        indicators["has_pyproject_toml"] = (repo_dir / "pyproject.toml").exists()

        # Ratio codice/docs (0 = tutto docs, alto = quasi solo codice)
        if md_count > 0:
            indicators["code_to_docs_ratio"] = round(code_count / md_count, 1)
        else:
            indicators["code_to_docs_ratio"] = float(code_count) if code_count > 0 else 0

        # ── Rilevamento domini di conoscenza ──
        domain_keywords = {
            "security": ["security", "vulnerability", "cve", "owasp", "penetration", "firewall", "encryption"],
            "devops": ["docker", "kubernetes", "ci/cd", "terraform", "ansible", "deploy", "pipeline"],
            "frontend": ["react", "vue", "angular", "css", "html", "ui", "ux", "component"],
            "backend": ["api", "rest", "graphql", "database", "sql", "microservice", "server"],
            "ai/ml": ["machine learning", "deep learning", "neural", "model", "training", "llm", "ai"],
            "cloud": ["aws", "azure", "gcp", "cloud", "serverless", "lambda", "s3"],
            "testing": ["test", "testing", "unittest", "pytest", "jest", "coverage", "qa"],
            "privacy/gdpr": ["gdpr", "privacy", "data protection", "consent", "dpia", "compliance"],
            "accessibility": ["accessibility", "a11y", "wcag", "aria", "screen reader"],
            "iso": ["iso 27001", "iso 9001", "isms", "audit", "certification", "compliance"],
            "finance": ["accounting", "invoice", "tax", "financial", "ledger", "payment"],
            "hr": ["human resources", "employee", "payroll", "recruitment", "onboarding"],
        }
        # Campiona README + primi SKILL.md per rilevare domini
        sample_text = ""
        for readme in ["README.md", "readme.md"]:
            rp = repo_dir / readme
            if rp.exists():
                try:
                    sample_text += rp.read_text(encoding="utf-8", errors="replace").lower()
                except Exception:
                    pass
                break
        for sm in indicators["skill_md_files"][:5]:
            try:
                sample_text += (repo_dir / sm).read_text(encoding="utf-8", errors="replace").lower()
            except Exception:
                pass

        if sample_text:
            for domain, keywords in domain_keywords.items():
                if any(kw in sample_text for kw in keywords):
                    indicators["knowledge_domains"].append(domain)

        return indicators

    def _evaluate_indicators(
        self, indicators: dict[str, Any], repo_name: str, owner: str
    ) -> tuple[str, str, list[str]]:
        """Valuta il valore di un repo per il sistema RAG.

        Logica a 3 livelli:
          1. Formato nativo Claude Code (.claude-plugin, SKILL.md) → valore massimo
          2. Contenuto documentale ricco (docs/, molti .md, guide) → valore alto per RAG
          3. Solo codice sorgente, poca documentazione → valore basso
        """
        warnings: list[str] = []
        score = 0

        # ── Livello 1: Formato nativo Claude Code ──
        if indicators["has_plugin_json"]:
            score += 40
        if indicators["has_marketplace_json"]:
            score += 30
        if indicators["has_claude_plugin_dir"]:
            score += 20
        if indicators["skill_md_count"] > 0:
            score += 30
        if indicators["claude_md_count"] > 0:
            score += 15
        if indicators["has_skills_dir"]:
            score += 10
        if len(indicators["command_files"]) > 0:
            score += 15
        if len(indicators["agent_files"]) > 0:
            score += 15
        if indicators["readme_mentions_claude"]:
            score += 10

        # ── Livello 2: Valore RAG documentale ──
        md_kb = indicators["markdown_kb_total"]
        md_count = indicators["markdown_files_total"]
        docs_files = indicators["docs_dir_files"]
        readme_kb = indicators["readme_kb"]

        # Markdown ricco = conoscenza per il RAG
        if md_count >= 20:
            score += 25
        elif md_count >= 5:
            score += 15
        elif md_count >= 2:
            score += 5

        # Grande volume di testo documentale
        if md_kb >= 500:
            score += 20
        elif md_kb >= 100:
            score += 10
        elif md_kb >= 30:
            score += 5

        # Directory docs esplicita
        if docs_files >= 10:
            score += 15
        elif docs_files >= 3:
            score += 10
        elif indicators["has_docs_dir"]:
            score += 5

        # README sostanzioso (>10KB è una guida)
        if readme_kb >= 20:
            score += 10
        elif readme_kb >= 5:
            score += 5

        # Domini di conoscenza rilevati
        domains = indicators.get("knowledge_domains", [])
        if len(domains) >= 3:
            score += 15
        elif len(domains) >= 1:
            score += 8

        # ── Penalita' per repo di solo codice ──
        ratio = indicators["code_to_docs_ratio"]
        code_count = indicators["code_files_count"]

        if ratio > 20 and code_count > 100:
            # Repo con moltissimo codice e quasi zero docs
            warnings.append(
                f"Rapporto codice/docs molto alto ({ratio}:1). "
                "Il repo contiene principalmente codice sorgente con poca documentazione "
                "— valore limitato per il RAG."
            )
            score -= 15

        if indicators["repo_size_files"] > 500 and md_kb < 50:
            warnings.append(
                f"Repository grande ({indicators['repo_size_files']} file) "
                f"ma solo {md_kb:.0f} KB di documentazione markdown."
            )

        # ── Warnings informativi ──
        if score <= 0 and md_count == 0:
            warnings.append(
                "Nessun contenuto documentale trovato (zero file .md). "
                "Il repo non aggiunge conoscenza al sistema RAG."
            )
        elif score <= 0:
            warnings.append(
                "Contenuto documentale insufficiente per arricchire il RAG."
            )

        if indicators["has_pyproject_toml"] and not indicators["has_plugin_json"] and md_kb < 30:
            warnings.append(
                "Libreria Python (pyproject.toml) con poca documentazione — "
                "probabilmente non utile come fonte di conoscenza."
            )
        if indicators["has_package_json"] and not indicators["has_plugin_json"] and md_kb < 30:
            warnings.append(
                "Pacchetto Node (package.json) con poca documentazione — "
                "probabilmente non utile come fonte di conoscenza."
            )

        # ── Calcola confidence e recommendation ──
        if score >= 40:
            confidence = "high"
            recommendation = "install"
        elif score >= 20:
            confidence = "medium"
            recommendation = "install"
        elif score > 5:
            confidence = "low"
            recommendation = "caution"
        else:
            confidence = "none"
            recommendation = "reject"

        return confidence, recommendation, warnings

    def _build_analysis_summary(
        self,
        repo_name: str,
        owner: str,
        indicators: dict[str, Any],
        confidence: str,
        recommendation: str,
    ) -> str:
        """Costruisce un sommario leggibile dell'analisi."""
        lines = [f"Repository: {owner}/{repo_name}"]

        if indicators.get("plugin_manifest"):
            pm = indicators["plugin_manifest"]
            if pm.get("name"):
                lines.append(f"Plugin: {pm['name']}")
            if pm.get("description"):
                lines.append(f"Descrizione: {pm['description']}")
            if pm.get("version"):
                lines.append(f"Versione: {pm['version']}")

        # Contenuto skill nativo
        parts = []
        if indicators["skill_md_count"]:
            parts.append(f"{indicators['skill_md_count']} SKILL.md")
        if indicators["claude_md_count"]:
            parts.append(f"{indicators['claude_md_count']} CLAUDE.md")
        if indicators["command_files"]:
            parts.append(f"{len(indicators['command_files'])} comandi")
        if indicators["agent_files"]:
            parts.append(f"{len(indicators['agent_files'])} agenti")
        if parts:
            lines.append(f"Skill Claude: {', '.join(parts)}")

        # Valore RAG
        rag_parts = []
        md_count = indicators["markdown_files_total"]
        md_kb = indicators["markdown_kb_total"]
        if md_count > 0:
            rag_parts.append(f"{md_count} file .md ({md_kb:.0f} KB)")
        if indicators["has_docs_dir"]:
            rag_parts.append(f"docs/ ({indicators['docs_dir_files']} file)")
        if indicators["readme_kb"] >= 5:
            rag_parts.append(f"README {indicators['readme_kb']:.0f} KB")
        domains = indicators.get("knowledge_domains", [])
        if domains:
            rag_parts.append(f"domini: {', '.join(domains)}")
        if rag_parts:
            lines.append(f"Valore RAG: {', '.join(rag_parts)}")

        if indicators["languages_detected"]:
            lines.append(f"Linguaggi: {', '.join(indicators['languages_detected'])}")

        lines.append(f"File totali: {indicators['repo_size_files']} ({indicators['code_files_count']} codice, {md_count} docs)")

        conf_labels = {
            "high": "ALTA — Ricco di conoscenza per il RAG",
            "medium": "MEDIA — Contiene documentazione utile",
            "low": "BASSA — Poco contenuto documentale",
            "none": "NESSUNA — Non aggiunge conoscenza al RAG",
        }
        lines.append(f"Confidenza: {conf_labels.get(confidence, confidence)}")

        rec_labels = {
            "install": "Installazione consigliata",
            "caution": "Installazione possibile, verifica manualmente",
            "reject": "Installazione sconsigliata",
        }
        lines.append(f"Raccomandazione: {rec_labels.get(recommendation, recommendation)}")

        return "\n".join(lines)

    def _log_installation(
        self, url: str, repo_name: str, status: str,
        analysis: RepoAnalysis | None = None, error: str = "",
    ) -> None:
        """Registra un evento di installazione nel log."""
        entry = {
            "timestamp": time.time(),
            "url": url,
            "repo_name": repo_name,
            "status": status,  # "success", "failed", "rejected", "analyzed"
            "error": error,
        }
        if analysis:
            entry["confidence"] = analysis.confidence
            entry["recommendation"] = analysis.recommendation
            entry["is_claude_skill"] = analysis.is_claude_skill

        self._install_log.append(entry)
        # Mantieni solo gli ultimi 100 log
        if len(self._install_log) > 100:
            self._install_log = self._install_log[-100:]
        self._save_install_log()

    def _load_install_log(self) -> None:
        if INSTALL_LOG_FILE.exists():
            try:
                self._install_log = json.loads(INSTALL_LOG_FILE.read_text())
            except Exception:
                self._install_log = []
        else:
            self._install_log = []

    def _save_install_log(self) -> None:
        INSTALL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_LOG_FILE.write_text(json.dumps(self._install_log, indent=2))

    async def install_from_github(
        self,
        url: str,
        group: str = "",
        priority: int = 3,
    ) -> InstalledSkill:
        """Installa una skill da GitHub URL o shorthand user/repo."""
        parsed = self._parse_github_url(url)
        if not parsed:
            raise ValueError(
                f"URL non valido: {url}. "
                "Usa: https://github.com/user/repo oppure user/repo"
            )

        owner, repo, branch = parsed
        repo_name = repo.removesuffix(".git")

        # Determina la cartella di destinazione
        if group:
            dest = self.skills_dir / group / repo_name
        else:
            dest = self.skills_dir / repo_name

        # Se esiste gia', aggiorna
        if dest.exists():
            return await self._update_repo(dest, owner, repo_name, group)

        # Clone (argomenti separati, no shell)
        clone_url = f"https://github.com/{owner}/{repo_name}.git"
        dest.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Clonazione {clone_url} -> {dest}")
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", "--branch", branch,
            clone_url, str(dest),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            # Riprova senza --branch (il branch specificato potrebbe non esistere)
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1",
                clone_url, str(dest),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_msg = stderr.decode('utf-8', errors='replace')
                self._log_installation(url, repo_name, "failed", error=err_msg)
                raise RuntimeError(f"Clone fallito: {err_msg}")

        # Installa dipendenze se presente requirements.txt
        req_file = dest / "requirements.txt"
        if req_file.exists():
            logger.info(f"Installazione dipendenze da {req_file}")
            proc = await asyncio.create_subprocess_exec(
                "pip", "install", "-r", str(req_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

        # Registra
        info = InstalledSkill(
            name=repo_name,
            source=f"{owner}/{repo_name}",
            install_path=str(dest.relative_to(self.skills_dir)),
            group=group,
            branch=branch,
            priority=priority,
            installed_at=time.time(),
        )
        self._installed[repo_name] = info
        self._save_registry()

        self._log_installation(url, repo_name, "success")
        logger.info(f"Skill installata: {repo_name} ({group or 'root'})")
        return info

    async def install_from_raw_url(
        self,
        url: str,
        filename: str = "",
        group: str = "",
        priority: int = 3,
    ) -> InstalledSkill:
        """Installa un singolo file .py da URL diretto."""
        import httpx

        if not filename:
            filename = url.rstrip("/").split("/")[-1]
            if not filename.endswith(".py"):
                filename += ".py"

        if group:
            dest = self.skills_dir / group / filename
        else:
            dest = self.skills_dir / filename

        dest.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            dest.write_text(resp.text)

        name = filename.replace(".py", "")
        info = InstalledSkill(
            name=name,
            source=url,
            install_path=str(dest.relative_to(self.skills_dir)),
            group=group,
            priority=priority,
            installed_at=time.time(),
        )
        self._installed[name] = info
        self._save_registry()

        logger.info(f"Skill file installato: {filename}")
        return info

    async def update(self, name: str) -> str:
        """Aggiorna una skill installata (git pull)."""
        info = self._installed.get(name)
        if not info:
            return f"Skill '{name}' non trovata nel registro"

        dest = self.skills_dir / info.install_path
        if not dest.is_dir():
            return f"Directory non trovata: {dest}"

        git_dir = dest / ".git"
        if not git_dir.exists():
            return "Non e' un repository git, non aggiornabile"

        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(dest), "pull", "--ff-only",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return f"Update fallito: {stderr.decode('utf-8', errors='replace')}"

        return stdout.decode("utf-8", errors="replace").strip()

    async def uninstall(self, name: str) -> bool:
        """Rimuovi una skill installata."""
        info = self._installed.get(name)
        if not info:
            return False

        dest = self.skills_dir / info.install_path
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()

        # Pulisci cartella gruppo se vuota
        if info.group:
            group_dir = self.skills_dir / info.group
            if group_dir.exists() and not any(group_dir.iterdir()):
                group_dir.rmdir()

        del self._installed[name]
        self._save_registry()
        logger.info(f"Skill rimossa: {name}")
        return True

    def get_hierarchy(self) -> dict:
        """Ritorna la gerarchia completa delle skill organizzata per gruppi."""
        tree: dict[str, list] = {"_root": []}

        for item in sorted(self.skills_dir.iterdir()):
            if item.name.startswith("_") or item.name.startswith("."):
                continue

            if item.is_file() and item.suffix == ".py":
                tree["_root"].append({
                    "name": item.stem,
                    "type": "file",
                    "path": item.name,
                    "installed": item.stem in self._installed,
                })
            elif item.is_dir():
                group_name = item.name
                group_items: list[dict] = []

                for sub in sorted(item.iterdir()):
                    if sub.name.startswith("_") or sub.name.startswith("."):
                        continue
                    if sub.is_file() and sub.suffix == ".py":
                        group_items.append({
                            "name": sub.stem,
                            "type": "file",
                            "path": f"{group_name}/{sub.name}",
                            "installed": sub.stem in self._installed,
                        })
                    elif sub.is_dir() and (sub / "__init__.py").exists():
                        group_items.append({
                            "name": sub.name,
                            "type": "package",
                            "path": f"{group_name}/{sub.name}",
                            "installed": sub.name in self._installed,
                        })

                if group_items:
                    tree[group_name] = group_items

        return tree

    # ── Internal ──────────────────────────────────────────────────────

    async def _update_repo(
        self, dest: Path, owner: str, repo_name: str, group: str
    ) -> InstalledSkill:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(dest), "pull", "--ff-only",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        info = self._installed.get(repo_name, InstalledSkill(
            name=repo_name,
            source=f"{owner}/{repo_name}",
            install_path=str(dest.relative_to(self.skills_dir)),
            group=group,
            installed_at=time.time(),
        ))
        info.installed_at = time.time()
        self._installed[repo_name] = info
        self._save_registry()
        return info

    @staticmethod
    def _parse_github_url(url: str) -> tuple[str, str, str] | None:
        """Parsa URL GitHub in (owner, repo, branch)."""
        url = url.strip()

        # user/repo shorthand
        m = re.match(r"^([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)$", url)
        if m:
            return m.group(1), m.group(2), "main"

        # https://github.com/user/repo[.git][/tree/branch]
        m = re.match(
            r"https?://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)"
            r"(?:\.git)?(?:/tree/([a-zA-Z0-9_./%-]+))?$",
            url,
        )
        if m:
            branch = m.group(3) or "main"
            return m.group(1), m.group(2), branch

        # git@github.com:user/repo.git
        m = re.match(
            r"git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$",
            url,
        )
        if m:
            return m.group(1), m.group(2), "main"

        return None

    def _load_registry(self) -> None:
        if REGISTRY_FILE.exists():
            try:
                data = json.loads(REGISTRY_FILE.read_text())
                for name, info in data.items():
                    self._installed[name] = InstalledSkill(**info)
            except Exception as e:
                logger.warning(f"Errore caricamento registro skill: {e}")

    def _save_registry(self) -> None:
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {name: asdict(info) for name, info in self._installed.items()}
        REGISTRY_FILE.write_text(json.dumps(data, indent=2))
