from pydantic import AnyHttpUrl, Field, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHOPPING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "shopping_assistant"
    postgres_user: str = "shopping_app"
    postgres_password: SecretStr = Field(min_length=1)
    redis_url: RedisDsn = Field(default=RedisDsn("redis://127.0.0.1:6379/0"), repr=False)
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, allow_inf_nan=False)

    semantic_search_enabled: bool = False
    embedding_timeout_seconds: float = Field(default=8, gt=0, le=60)

    ollama_enabled: bool = False
    ollama_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:11434")
    ollama_model: str = Field(default="qwen2.5:1.5b", min_length=1, max_length=160)
    ollama_connection_timeout_seconds: float = Field(default=2, gt=0, le=15)
    ollama_generation_timeout_seconds: float = Field(default=45, gt=0, le=180)
    ollama_retries: int = Field(default=1, ge=0, le=2)
    ollama_concurrency: int = Field(default=1, ge=1, le=8)
    ollama_temperature: float = Field(default=0.1, ge=0, le=1)
    ollama_max_tokens: int = Field(default=512, ge=32, le=4096)
    ollama_context_tokens: int = Field(default=4096, ge=2048, le=32768)

    chat_session_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    chat_history_limit: int = Field(default=12, ge=2, le=50)

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
