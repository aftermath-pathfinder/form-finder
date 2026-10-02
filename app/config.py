from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_api_key: str = ""
    llm_model: str = "z-ai/glm-5.3"
    llm_timeout: float = 120.0
    llm_temperature: float = 0.2

    # Form templates + their parsed schemas live here. Your answers never do.
    data_dir: Path = Path("data")


@lru_cache
def get_settings() -> Settings:
    return Settings()
