"""Conferência independente dos brutos oficiais e do Parquet de uma execução US04."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import duckdb


def audit(directory: Path) -> dict[str, object]:
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    day_type = {"U": 0, "S": 1, "D": 2}[report["day_type"]]
    raw_by_hash: dict[str, Path] = {}
    for capture in report["captures"]:
        # O nome vem do relatório local, nunca deve apontar para fora da execução.
        name = capture["name"]
        if Path(name).name != name:
            raise ValueError("nome de bruto inválido")
        path = directory / name
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != capture["reference"]["sha256"]:
            raise ValueError("hash de bruto divergente")
        raw_by_hash[sha] = path
    parquet = directory / "departures.parquet"
    if hashlib.sha256(parquet.read_bytes()).hexdigest() != report["output"]["sha256"]:
        raise ValueError("hash do Parquet divergente")
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT line, direction, count(*) FROM read_parquet(?) "
            "WHERE kind = 'official' GROUP BY line, direction",
            [str(parquet)],
        ).fetchall()
    written = {(str(line), str(direction)): int(count) for line, direction, count in rows}
    checks: list[dict[str, object]] = []
    for line in report["lines"]:
        if line["status"] != "official":
            continue
        detail = json.loads(raw_by_hash[line["source_sha256"]].read_bytes())
        if detail["codigoLinha"].strip() != line["line"]:
            raise ValueError("linha divergente")
        declared: Counter[str] = Counter()
        listed: Counter[str] = Counter()
        for direction, field in (("0", "partidasIda"), ("1", "partidasVolta")):
            for band in detail[field]:
                if band["tipoDia"] == day_type:
                    declared[direction] += band["totalPartidas"]
                    listed[direction] += len(band["horariosProgramados"])
            if written.get((line["line"], direction), 0) != listed[direction]:
                raise ValueError("Parquet não preserva a lista oficial")
        checks.append(
            {
                "line": line["line"],
                "declared": sum(declared.values()),
                "listed": sum(listed.values()),
                "written": sum(listed.values()),
                "counts_match": all(declared[d] == listed[d] for d in ("0", "1")),
            }
        )
    return {
        "run_id": report["run_id"],
        "official_lines": len(checks),
        "concordant": sum(row["counts_match"] is True for row in checks),
        "parquet_preserves_official_lists": True,
        "checks": checks,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), ensure_ascii=False, indent=2))
