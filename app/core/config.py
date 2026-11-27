from pydantic import Field, RedisDsn, SecretStr
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
