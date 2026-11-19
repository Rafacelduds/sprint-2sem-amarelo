from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition
from api.gtfs.models import GtfsCapture, GtfsVersion
from api.main import create_app
from api.reliability.models import DailyReport
from api.reliability.service import build_gaps, build_report, publish, schedule_references
from api.storage.s3 import S3Archive
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection_postgres import sessions as sessions  # noqa: F401
from test_storage import archive as archive  # noqa: F401

START = datetime(2026, 11, 19, 3, tzinfo=UTC)


def cycle(offset: int, status: str = "success", interval: int | None = 30) -> CollectionCycle:
    return CollectionCycle(
        id=uuid4(),
        scheduled_at=START + timedelta(seconds=offset),
        status=status,
        interval_seconds=interval,
        error_code="https://secret.invalid?token=private",
    )


def test_gaps_cross_midnight_preserve_causes_and_unknown_stoppages() -> None:
    gaps = build_gaps(
        [
            cycle(-15),
            cycle(15, "origin_failure"),
            cycle(45, "origin_failure"),
            cycle(75, "storage_failure"),
            cycle(135),
        ],
        START,
        START + timedelta(seconds=165),
        30,
    )
    assert [
        (int((g.start - START).total_seconds()), int((g.end - START).total_seconds()), g.cause)
        for g in gaps
    ] == [
        (15, 75, "origin_failure"),
        (75, 105, "storage_failure"),
        (105, 135, "no_cycle_record"),
    ]
    assert gaps[0].possible_maintenance and not gaps[0].maintenance_confirmed
    assert not gaps[-1].possible_maintenance
    assert "private" not in str(gaps)


@pytest.mark.parametrize(
    "status,cause",
    [
        ("running", "unfinished_cycle"),
        ("interrupted", "interrupted"),
        ("other", "unknown_cycle_status"),
    ],
)
def test_unknown_status_is_never_reported_as_success(status: str, cause: str) -> None:
    gaps = build_gaps([cycle(0, status)], START, START + timedelta(seconds=30), 30)
    assert len(gaps) == 1 and gaps[0].cause == cause


def test_configured_interval_jitter_and_empty_day() -> None:
    end = START + timedelta(seconds=95)
    assert not build_gaps([cycle(0, interval=60), cycle(65)], START, end, 15)
    gaps = build_gaps([], START, end, 30)
    assert len(gaps) == 1 and gaps[0].start == START and gaps[0].end == end
    assert gaps[0].evidence == "inferred_absence"


def test_coincident_cycles_never_hide_failure_or_change_sources() -> None:
    success, failure = cycle(0), cycle(0, "storage_failure")
    end = START + timedelta(seconds=30)
    forward = build_gaps([success, failure], START, end, 30)
    assert forward == build_gaps([failure, success], START, end, 30)
    assert len(forward) == 1 and forward[0].cause == "storage_failure"
    assert success.status == "success" and failure.status == "storage_failure"


async def test_report_versions_no_future_leak_and_no_raw_changes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    day = date(2026, 11, 19)
    now = START + timedelta(minutes=5)
    async with sessions.begin() as session:
        session.add_all([cycle(0), cycle(30, "origin_failure", None), cycle(60)])
        for index, (offset, source, covered) in enumerate(
            [
                (-3600, "sptrans", True),
                (60, "sptrans", True),
                (120, "other", True),
                (180, "sptrans", False),
                (600, "sptrans", True),
            ]
        ):
            sha = str(index) * 64
            session.add(
                GtfsVersion(
                    sha256=sha,
                    size=1,
                    bucket="private",
                    object_key="private",
                    starts_on=day,
                    ends_on=day if covered else day - timedelta(days=1),
                    coverage_basis="calendar",
                )
            )
            await session.flush()
            session.add(
                GtfsCapture(
                    id=uuid4(),
                    source_id=source,
                    source_url="https://private.invalid",
                    captured_at=START + timedelta(seconds=offset),
                    version_sha256=sha,
                )
            )
        await session.flush()
        snapshot = uuid4()
        session.add(
            CollectionSnapshot(
                id=snapshot,
                cycle_id=(await session.scalars(select(CollectionCycle.id))).first(),
                endpoint="/Posicao",
                collected_at=START,
                body=b"untouched",
            )
        )
        await session.flush()
        session.add(
            VehiclePosition(
                id=uuid4(),
                snapshot_id=snapshot,
                collected_at=START,
                in_garage=False,
                gtfs_version_sha256="0" * 64,
                gtfs_link_status="matched",
            )
        )
    async with sessions() as session:
        report = await build_report(
            session, day, now=now, interval=30, source_id="sptrans", schedules=[]
        )
        assert report.provisional and report.period_start == START
        assert report.cycles == 3 and report.legacy_interval_cycles == 1
        assert [p.sha256 for p in report.gtfs_reference_periods] == ["0" * 64, "1" * 64]
        assert report.gtfs_reference_periods[0].end == START + timedelta(seconds=60)
        assert report.gtfs_used[0].observations == 1
        assert report.schedules_status == "no_manifest_for_day"
        assert "private" not in report.model_dump_json()
        assert await session.scalar(select(CollectionSnapshot.body)) == b"untouched"
        assert await session.scalar(select(func.count()).select_from(CollectionCycle)) == 3


async def test_future_rejected_and_empty_day_explicit(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        with pytest.raises(ValueError):
            await build_report(
                session,
                date(2026, 11, 20),
                now=START,
                interval=30,
                source_id="sptrans",
                schedules=[],
            )
        report = await build_report(
            session,
            date(2026, 11, 19),
            now=START + timedelta(days=1),
            interval=30,
            source_id="sptrans",
            schedules=[],
        )
        assert report.gap_seconds == 86400 and not report.provisional
        assert report.gtfs_reference_periods[0].sha256 is None


async def test_publish_read_public_api_and_failure_preserves_previous(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    path = tmp_path / "schedule.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "synthetic-us04",
                "service_date": "2026-11-19",
                "started_at": START.isoformat(),
                "finished_at": (START + timedelta(seconds=10)).isoformat(),
                "lines": [{"source_sha256": "a" * 64}],
                "complete": True,
                "has_discrepancies": True,
                "source_url": "https://private.invalid?token=secret",
            }
        ),
        encoding="utf-8",
    )
    archive.put(path, "manifests/schedules/synthetic.json", content_type="application/json")
    now = START + timedelta(days=1)
    report = await publish(
        sessions, archive, date(2026, 11, 19), now=now, interval=30, source_id="sptrans"
    )
    assert report.schedule_references[0].source_hashes == ["a" * 64]
    assert report.schedule_references[0].has_discrepancies
    # Regeneração não duplica a publicação nem sobrescreve uma mais nova.
    await publish(
        sessions,
        archive,
        report.day,
        now=now - timedelta(seconds=1),
        interval=60,
        source_id="sptrans",
    )
    monkeypatch.setattr("api.db.session.SessionFactory", sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://test",
    ) as client:
        response = await client.get("/reports/reliability/2026-11-19")
        assert response.status_code == 200
        assert response.json() == report.model_dump(mode="json")
        assert "private" not in response.text and "secret" not in response.text
        assert (await client.get("/reports/reliability/2026-11-18")).status_code == 404
        assert (await client.get("/reports/reliability/invalid")).status_code == 422
    # Bytes corruptos impedem nova publicação; o documento anterior é preservado.
    archive.client.put_object(
        Bucket=archive.bucket, Key="manifests/schedules/synthetic.json", Body=b"broken"
    )
    with pytest.raises((ValueError, KeyError)):
        await publish(
            sessions,
            archive,
            report.day,
            now=now + timedelta(seconds=1),
            interval=30,
            source_id="sptrans",
        )
    async with sessions() as session:
        stored = await session.get(DailyReport, report.day)
        assert stored and stored.document == report.model_dump(mode="json")


def test_schedule_manifest_refuses_unzoned_dates(archive: S3Archive, tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        '{"run_id":"x","service_date":"2026-11-19","started_at":"2026-11-19T00:00:00",'
        '"finished_at":"2026-11-19T01:00:00","lines":[],"complete":true,'
        '"has_discrepancies":false}',
        encoding="utf-8",
    )
    archive.put(path, "manifests/schedules/invalid.json")
    with pytest.raises(ValueError, match="período inválido"):
        schedule_references(archive, date(2026, 11, 19))


async def test_api_database_failure_returns_safe_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.db.session.SessionFactory", Mock(side_effect=SQLAlchemyError("private"))
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://test",
    ) as client:
        response = await client.get("/reports/reliability/2026-11-19")
        assert response.status_code == 503 and "private" not in response.text


async def test_watch_attempts_today_even_if_yesterday_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.reliability import __main__ as cli

    class StopWatch(Exception):
        pass

    engine = Mock(dispose=AsyncMock())
    publisher = AsyncMock(
        side_effect=[ValueError("private"), Mock(model_dump_json=Mock(return_value="ok"))]
    )
    monkeypatch.setattr("sys.argv", ["reliability", "--watch"])
    monkeypatch.setattr(cli, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(cli, "async_sessionmaker", Mock())
    monkeypatch.setattr(cli, "archive_from_settings", Mock())
    monkeypatch.setattr(cli, "publish", publisher)
    monkeypatch.setattr(cli.asyncio, "sleep", AsyncMock(side_effect=StopWatch))
    with pytest.raises(StopWatch):
        await cli.main()
    assert publisher.await_count == 2
    assert publisher.await_args_list[1].args[2] - publisher.await_args_list[0].args[2] == timedelta(
        days=1
    )
    engine.dispose.assert_awaited_once()
