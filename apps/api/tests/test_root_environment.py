from pathlib import Path

import pytest
from api.collection.runner import CollectionSettings
from api.config import Settings
from api.gtfs.runner import GtfsSettings


def test_all_python_entrypoints_use_root_environment_from_any_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[3]
    monkeypatch.chdir(tmp_path)
    for settings in (Settings, CollectionSettings, GtfsSettings):
        assert settings.model_config.get("env_file") == root / ".env"
