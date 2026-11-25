"""Settings loaded from environment variables (and an optional .env file)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

PROVIDERS = ("groq", "ollama", "none")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"


@dataclass
class Settings:
    llm_provider: str = "none"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_model: str = "llama3.1:8b"
    db_path: str = "halcyon.db"
    hmac_secret: str = "halcyon-demo-secret"


def get_settings() -> Settings:
    load_dotenv()
    key = os.getenv("GROQ_API_KEY", "").strip()
    provider = os.getenv("LLM_PROVIDER", "groq" if key else "none").strip().lower()
    if provider not in PROVIDERS:
        provider = "none"
    return Settings(
        llm_provider=provider,
        groq_api_key=key,
        groq_model=os.getenv("GROQ_MODEL", "").strip() or Settings.groq_model,
        ollama_model=os.getenv("OLLAMA_MODEL", "").strip() or Settings.ollama_model,
        db_path=os.getenv("DB_PATH", "").strip() or Settings.db_path,
        hmac_secret=os.getenv("HMAC_SECRET", "").strip() or Settings.hmac_secret,
    )
