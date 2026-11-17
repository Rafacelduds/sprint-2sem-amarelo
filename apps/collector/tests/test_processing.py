from pathlib import Path

import duckdb
from collector.processing import write_example_parquet


def test_write_example_parquet(tmp_path: Path) -> None:
    destination = write_example_parquet(tmp_path / "events.parquet")

    assert destination.exists()
    with duckdb.connect(":memory:") as connection:
        count = connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(destination)],
        ).fetchone()
    assert count == (2,)
