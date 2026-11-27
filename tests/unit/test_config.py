from pathlib import Path

import pytest

from app.core.config import Settings


def test_settings_read_env_file_and_allow_process_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SHOPPING_POSTGRES_PASSWORD='test@:/?#%'\nSHOPPING_POSTGRES_HOST=postgres\nAPI_PORT=8000\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SHOPPING_POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("SHOPPING_POSTGRES_HOST", "database")

    settings = Settings(_env_file=env_file)

    assert settings.database_url.drivername == "postgresql+asyncpg"
    assert settings.database_url.host == "database"
    assert settings.database_url.password == "test@:/?#%"
    assert "test@:/?#%" not in repr(settings)
