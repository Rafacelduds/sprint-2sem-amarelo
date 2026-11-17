from pathlib import Path

import duckdb


def write_example_parquet(destination: Path) -> Path:
    """Write a tiny Parquet file as a smoke test for DuckDB processing."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE events (id INTEGER, label VARCHAR)")
        connection.executemany(
            "INSERT INTO events VALUES (?, ?)",
            [(1, "collector-ready"), (2, "parquet-ready")],
        )
        connection.execute(
            "COPY events TO ? (FORMAT PARQUET)",
            [str(destination)],
        )
    finally:
        connection.close()
    return destination
