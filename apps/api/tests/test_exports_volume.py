"""Regressão independente de serviços para o volume apontado na revisão US09."""

import gzip
import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import duckdb
import pytest
from api.exports.contract import LICENSE, SOURCE
from api.exports.service import Capture, build_parquet
from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive


def payload(index: int, body_size: int) -> bytes:
    return b'{"capture":' + str(index).encode() + b',"l":[],"extra":"' + b"x" * body_size + b'"}\n'


@pytest.mark.parametrize(
    ("count", "compressed", "body_size"),
    [(128, False, 1048576), (256, True, 1048576), (12, False, 12 * 1048576)],
)
def test_export_larger_than_old_memory_budget(
    tmp_path: Path,
    count: int,
    compressed: bool,
    body_size: int,
) -> None:
    captures: list[Capture] = []
    expected: dict[str, tuple[str, int]] = {}
    for index in range(count):
        body = payload(index, body_size)
        checksum = hashlib.sha256(body).hexdigest()
        stored = gzip.compress(body, mtime=0) if compressed else body
        identity = UUID(int=index + 1)
        ref = ObjectRef(
            bucket="synthetic",
            key=f"raw/{index}",
            sha256=checksum,
            stored_sha256=hashlib.sha256(stored).hexdigest(),
            size=len(body),
            stored_size=len(stored),
            encoding="gzip" if compressed else "identity",
        )
        captures.append(
            Capture(
                identity, UUID(int=1), datetime(2026, 5, 18, 12, tzinfo=UTC), "/Posicao", None, ref
            )
        )
        expected[str(identity)] = (checksum, len(body))
    assert sum(size for _, size in expected.values()) > 128 * 1024 * 1024

    def download(ref: ObjectRef, destination: Path) -> None:
        body = payload(int(ref.key.split("/")[-1]), body_size)
        destination.write_bytes(gzip.compress(body, mtime=0) if compressed else body)

    archive = Mock(spec=S3Archive)
    archive.download.side_effect = download
    target = tmp_path / "day.parquet"
    build_parquet(captures, archive, date(2026, 5, 18), target)
    with duckdb.connect() as connection:
        # Conferir todos os bytes por hash sem carregar todos os corpos no teste.
        rows = connection.execute(
            "SELECT captura_id, sha256(corpo_original), octet_length(corpo_original), "
            "sha256_original FROM read_parquet(?)",
            [str(target)],
        ).fetchall()
        assert len(rows) == count
        for identity, checksum, size, recorded_hash in rows:
            assert (checksum, size) == expected[identity]
            assert recorded_hash == checksum
        metadata = dict(
            connection.execute(
                "SELECT decode(key), decode(value) FROM parquet_kv_metadata(?)",
                [str(target)],
            ).fetchall()
        )
        assert metadata["license"] == LICENSE and metadata["source"] == SOURCE
        groups = connection.execute(
            "SELECT count(DISTINCT row_group_id) FROM parquet_metadata(?)",
            [str(target)],
        ).fetchone()
        assert groups is not None and groups[0] > 1
    assert not target.with_suffix(".payload").exists()
