import os
import subprocess
from pathlib import Path

from sqlalchemy.engine import make_url


def postgres_tool(tool: str, database_url: str, path: Path) -> None:
    """Credenciais somente no ambiente do filho; nunca na linha de comando."""
    url = make_url(database_url)
    environment = dict(os.environ)
    environment.update(
        {
            "PGHOST": url.host or "localhost",
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "",
            "PGPASSWORD": url.password or "",
            "PGDATABASE": url.database or "",
            "PGCONNECT_TIMEOUT": "10",
        }
    )
    command: list[str] = []
    if container := os.getenv("PG_TOOLS_CONTAINER"):
        # Conveniência local; o container de produção possui os clientes instalados.
        environment["PGHOST"] = os.getenv("PG_TOOLS_HOST", "localhost")
        environment["PGPORT"] = os.getenv("PG_TOOLS_PORT", "5432")
        command = ["docker", "exec", "-i"]
        for name in ["PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGCONNECT_TIMEOUT"]:
            command.extend(["-e", name])
        command.append(container)
    if tool == "pg_dump":
        command += [tool, "--format=custom", "--no-owner", "--no-privileges"]
        with path.open("xb") as output:
            result = subprocess.run(
                command,
                env=environment,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=6 * 60 * 60,
                check=False,
            )
    elif tool == "pg_restore":
        command += [
            tool,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            environment["PGDATABASE"],
        ]
        with path.open("rb") as source:
            result = subprocess.run(
                command,
                env=environment,
                stdin=source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=6 * 60 * 60,
                check=False,
            )
    else:
        raise ValueError("ferramenta PostgreSQL desconhecida")
    if result.returncode:
        raise RuntimeError(f"{tool} falhou; código {result.returncode}")
