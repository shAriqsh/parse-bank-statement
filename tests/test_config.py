import os
from pathlib import Path
import pytest
from bank_statement.config import load_gemini_api_key


def test_load_gemini_api_key_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key-12345")
    key = load_gemini_api_key()
    assert key == "test-api-key-12345"


def test_load_gemini_api_key_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=key-from-dotenv-file\n", encoding="utf-8")

    key = load_gemini_api_key(dotenv_path=env_file)
    assert key == "key-from-dotenv-file"


def test_load_gemini_api_key_from_google_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key-67890")
    key = load_gemini_api_key()
    assert key == "test-google-key-67890"


def test_load_gemini_api_key_missing_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        load_gemini_api_key(dotenv_path=Path("non_existent_env_file"))


def test_get_gemini_client_initializes_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from bank_statement.config import get_gemini_client
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key-12345")
    client = get_gemini_client()
    assert client is not None
