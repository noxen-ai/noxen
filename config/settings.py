"""Noxen - Central Configuration."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    hub_root: Path = Path(__file__).parent.parent
    skills_dir: Path = Path.home() / "Neural-Hub" / "skills"
    data_dir: Path = Path.home() / "Neural-Hub" / "data"
    chroma_dir: Path = Path.home() / "Neural-Hub" / "data" / "chroma"  # DEPRECATED: kept for backward compat, use Qdrant

    # Ollama / LLM (default local backend)
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "llama3:8b"
    embedding_model: str = "nomic-embed-text"

    # Multi-LLM Providers (API keys)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Nuovi provider (OpenAI-compatible)
    grok_api_key: str = ""
    grok_model: str = "grok-4"
    grok_base_url: str = "https://api.x.ai/v1"
    mercury_api_key: str = ""
    mercury_model: str = "mercury-2"
    mercury_base_url: str = "https://api.inceptionlabs.ai/v1"
    qwen_api_key: str = ""
    qwen_model: str = "qwen3-235b-a22b"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Board mode
    llm_mode: str = "single"   # "single" or "board"
    active_provider: str = "ollama"  # ollama, gemini, claude, openai, grok, mercury, qwen
    board_chairman: str = "gemini"   # Who synthesizes the board consensus

    # MySQL (read-only analysis)
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = ""

    # Qdrant (vector database — replaces ChromaDB in v0.3.0)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # Research Agent
    github_token: str = ""
    exa_api_key: str = ""
    firecrawl_api_key: str = ""
    research_sandbox_dir: str = "./data/research_sandbox"
    research_max_repo_size_mb: int = 100
    research_clone_timeout_s: int = 120

    # Notification Engine (Phase 5)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    slack_bot_token: str = ""
    slack_channel_id: str = ""
    google_chat_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    notification_timeout_h: int = 24
    notification_reminder_m: int = 30

    # Multitenant (Phase 8)
    multitenant_enabled: bool = False  # False = on-premise, no auth
    admin_api_key: str = ""  # Admin key for tenant management

    # License (Device Auth)
    noxen_license_key: str = ""
    license_server_url: str = "https://api.noxen.ai"
    license_grace_period_days: int = 7

    # Server
    host: str = "0.0.0.0"
    port: int = 8400
    debug: bool = True

    # Indexing
    max_file_size_mb: int = 5
    chunk_size: int = 1000
    chunk_overlap: int = 200
    batch_size: int = 50  # Qdrant insert batch (RAM-friendly)

    # Ignored patterns (on top of .gitignore)
    global_ignore: list[str] = [
        "node_modules", "__pycache__", ".git", ".venv",
        "vendor", "dist", "build", ".next", ".nuxt",
        "*.pyc", "*.min.js", "*.min.css", "*.map",
        "*.lock", "package-lock.json", "yarn.lock",
    ]

    model_config = {"env_prefix": "NOXEN_"}


settings = Settings()
