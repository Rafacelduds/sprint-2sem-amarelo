"""Faz uma consulta pontual à API Olho Vivo e preserva a resposta original."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = "https://api.olhovivo.sptrans.com.br/v2.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPOSITORY_ROOT / "apps" / "api" / ".env"


def read_key_from_env_file(path: Path) -> str | None:
    if not path.is_file():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "CHAVE_API_OLHO_VIVO":
            return value.strip().strip('"').strip("'") or None
    return None


def get_api_key() -> str:
    api_key = os.environ.get("CHAVE_API_OLHO_VIVO") or read_key_from_env_file(ENV_FILE)
    if not api_key:
        raise RuntimeError("Defina CHAVE_API_OLHO_VIVO no ambiente ou em apps/api/.env.")
    return api_key


def request_bytes(opener, request: Request, *, operation: str) -> bytes:
    try:
        with opener.open(request, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        raise RuntimeError(f"{operation} falhou com HTTP {error.code}.") from None
    except URLError as error:
        raise RuntimeError(f"{operation} falhou por erro de conexão.") from error


def default_output(captured_at: datetime) -> Path:
    day = captured_at.strftime("%Y-%m-%d")
    timestamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    return REPOSITORY_ROOT / "data" / "raw" / "olho-vivo" / day / f"posicao-{timestamp}.json"


def collect(output: Path | None = None) -> dict[str, object]:
    api_key = get_api_key()
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [
        ("User-Agent", "Sprint-Amarelo/0.1 Olho-Vivo research client"),
        ("Accept", "application/json"),
    ]
    auth_query = urlencode({"token": api_key})
    auth_request = Request(f"{BASE_URL}/Login/Autenticar?{auth_query}", data=b"", method="POST")
    authenticated = (
        request_bytes(opener, auth_request, operation="Autenticação").decode("utf-8").strip()
    )
    if authenticated != "true":
        raise RuntimeError("A API Olho Vivo recusou a autenticação.")

    captured_at = datetime.now(UTC)
    payload = request_bytes(
        opener,
        Request(f"{BASE_URL}/Posicao", method="GET"),
        operation="Consulta de posições",
    )
    document = json.loads(payload)
    lines = document.get("l", [])
    vehicle_count = sum(len(line.get("vs", [])) for line in lines)

    destination = output or default_output(captured_at)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as raw_file:
        raw_file.write(payload)
        raw_file.flush()
        os.fsync(raw_file.fileno())

    return {
        "captured_at": captured_at.isoformat(),
        "endpoint": "/Posicao",
        "path": str(destination.relative_to(REPOSITORY_ROOT)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "reference_time": document.get("hr"),
        "line_records": len(lines),
        "vehicles": vehicle_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consulta uma fotografia da Olho Vivo e preserva o JSON recebido."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Caminho de saída; por padrão usa data/raw/olho-vivo/<data>/.",
    )
    args = parser.parse_args()
    print(json.dumps(collect(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
