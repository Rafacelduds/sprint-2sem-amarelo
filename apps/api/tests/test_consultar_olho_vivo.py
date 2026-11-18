import hashlib
import io
import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "consultar_olho_vivo.py"


@pytest.mark.parametrize("relative", [True, False])
def test_output_paths_report_success_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    relative: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHAVE_API_OLHO_VIVO", "synthetic-test-token")
    output = Path("captura.json") if relative else tmp_path / "externo" / "captura.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--output", str(output)])
    payload = b'{"hr":"12:00","l":[{"vs":[{"p":123}]}]}'
    with patch(
        "urllib.request.OpenerDirector.open",
        side_effect=[io.BytesIO(b"true"), io.BytesIO(payload)],
    ) as request:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert result["path"] == str(output.resolve())
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["vehicles"] == 1
    assert output.read_bytes() == payload
    assert request.call_count == 2
