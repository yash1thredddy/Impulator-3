"""
Backend configuration with environment variable support.
Simplified for single-container deployment (local, HF Spaces, Streamlit Cloud, etc.)
"""
from pathlib import Path
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "Impulator"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    # Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    FRONTEND_PORT: int = 7860

    # Database
    DATABASE_URL: str = "sqlite:///./data/impulator.db"

    # Executor (ThreadPoolExecutor for background jobs)
    MAX_WORKERS: int = 2  # Concurrent job limit
    JOB_TIMEOUT: int = 3600  # 1 hour max per job

    # Cache (in-memory LRU per function)
    CACHE_SIZE: int = 2000  # Per function LRU size

    # External APIs
    CHEMBL_API_URL: str = "https://www.ebi.ac.uk/chembl/api/data"
    PDB_API_URL: str = "https://search.rcsb.org/rcsbsearch/v2/query"

    # Rate limiting
    API_RATE_LIMIT: int = 10  # requests per second

    # Storage
    DATA_DIR: Path = Path("./data")
    RESULTS_DIR: Path = Path("./data/results")

    # Azure Blob (single source of truth)
    AZURE_CONNECTION_STRING: str = ""
    AZURE_CONTAINER: str = "impulator"

    # CORS (comma-separated string in .env, parsed to list)
    CORS_ORIGINS: str = "http://localhost:7860,http://localhost:8501"

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS string into list."""
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience exports
settings = get_settings()
