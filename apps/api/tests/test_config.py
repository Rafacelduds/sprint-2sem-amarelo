from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from api.collection.runner import CollectionSettings
from api.config import Settings
from api.live import LivePositions
from test_live import payload

TOKEN_NAMES = ("CHAVE_API_OLHO_VIVO", "OLHOVIVO_TOKEN", "OLHO_VIVO_TOKEN")


@pytest.fixture(autouse=True)
def isolated_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in TOKEN_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setitem(CollectionSettings.model_config, "env_file", None)


@pytest.mark.parametrize("name", TOKEN_NAMES)
@pytest.mark.parametrize("source", ["environment", "dotenv"])
def test_map_and_collector_accept_same_token(
    name: str, source: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    entries = {alias: "" for alias in TOKEN_NAMES}
    if source == "dotenv":
        entries[name] = "synthetic"
    else:
        monkeypatch.setenv(name, "synthetic")
    env.write_text(
        "\n".join(f"{alias}={value}" for alias, value in entries.items()), encoding="utf-8"
    )
    monkeypatch.setitem(Settings.model_config, "env_file", env)
    monkeypatch.setitem(CollectionSettings.model_config, "env_file", env)
    assert Settings().olho_vivo_token.get_secret_value() == "synthetic"
    assert CollectionSettings().olhovivo_token.get_secret_value() == "synthetic"


def test_map_and_collector_use_same_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    for index, name in enumerate(TOKEN_NAMES):
        monkeypatch.setenv(name, str(index))
    assert Settings().olho_vivo_token.get_secret_value() == "0"
    assert CollectionSettings().olhovivo_token.get_secret_value() == "0"


def test_process_overrides_dotenv_even_with_different_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    env.write_text("CHAVE_API_OLHO_VIVO=from-file\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env)
    monkeypatch.setitem(CollectionSettings.model_config, "env_file", env)
    monkeypatch.setenv("OLHO_VIVO_TOKEN", "from-process")
    assert Settings().olho_vivo_token.get_secret_value() == "from-process"
    assert CollectionSettings().olhovivo_token.get_secret_value() == "from-process"


@pytest.mark.parametrize("name", TOKEN_NAMES)
async def test_live_fetch_authenticates_with_collection_token_alias(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, "synthetic")
    settings = Settings()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("Autenticar"):
            assert request.url.params["token"] == "synthetic"
            return httpx.Response(200, json=True)
        return httpx.Response(200, json=payload())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://test")
    monkeypatch.setattr("api.live.get_settings", lambda: settings)
    monkeypatch.setattr("api.live.httpx.AsyncClient", Mock(return_value=client))
    result = await LivePositions().fetch()
    assert result.vehicles[0].id == "123"
    assert len(requests) == 2
