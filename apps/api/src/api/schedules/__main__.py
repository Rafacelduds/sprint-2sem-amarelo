import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from api.config import get_settings
from api.gtfs.source import GtfsError
from api.schedules.catalog import load_reference
from api.schedules.runner import OfficialSource, run
from api.storage.__main__ import archive_from_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="US04: capturar programação e gerar partidas")
    parser.add_argument("--lines", help="Letreiros separados por vírgula; padrão: amostra ordenada")
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument(
        "--day-type",
        choices=["U", "S", "D"],
        required=True,
        help="Tipo de dia confirmado pelo operador, inclusive em feriados",
    )
    parser.add_argument(
        "--gtfs-file", type=Path, help="ZIP de referência da US02, usado na ausência"
    )
    parser.add_argument("--output", type=Path, default=Path("data/schedules"))
    parser.add_argument("--code-version", default="working-tree")
    parser.add_argument(
        "--gtfs-source-id", help="Buscar alternativa no catálogo US02/PostgreSQL/S3"
    )
    args = parser.parse_args()
    if args.sample < 1:
        parser.error("--sample deve ser positivo")
    lines = [value.strip() for value in args.lines.split(",")] if args.lines else None
    if lines and not all(lines):
        parser.error("--lines contém um identificador vazio")
    settings = get_settings()
    archive = archive_from_settings(settings)
    if args.gtfs_file and args.gtfs_source_id:
        parser.error("escolha --gtfs-file ou --gtfs-source-id")
    day = datetime.now(ZoneInfo("America/Sao_Paulo")).date()

    def loader(directory: Path) -> Path | None:
        return asyncio.run(load_reference(settings, args.gtfs_source_id, day, directory))

    # Uma execução por invocação; agendamento depende da frequência aprovada pelo PO.
    base_url = settings.schedule_source_url
    try:
        with httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=30,
            headers={
                "Origin": "https://www.sptrans.com.br",
                "Referer": "https://www.sptrans.com.br/",
                "User-Agent": "sprint-amarelo-us04/1.0",
            },
        ) as client:
            started = time.monotonic()
            report = run(
                OfficialSource(client),
                archive,
                args.output,
                day=day,
                day_type=args.day_type,
                lines=lines,
                sample=args.sample,
                gtfs_file=args.gtfs_file,
                gtfs_loader=loader if args.gtfs_source_id else None,
                code_version=args.code_version,
            )
            print(
                json.dumps(
                    {
                        "run_id": report["run_id"],
                        "complete": report["complete"],
                        "official_lines_checked": report["official_lines_checked"],
                        "official_lines_concordant": report["official_lines_concordant"],
                        "has_discrepancies": report["has_discrepancies"],
                        "seconds": round(time.monotonic() - started, 2),
                    }
                )
            )
            if not report["complete"]:
                raise SystemExit(1)
            if report["has_discrepancies"]:
                raise SystemExit(2)
    except (httpx.HTTPError, ValueError, RuntimeError, GtfsError) as exc:
        # Não imprimir URL configurada nem credenciais de serviços.
        parser.exit(1, f"US04 falhou: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
