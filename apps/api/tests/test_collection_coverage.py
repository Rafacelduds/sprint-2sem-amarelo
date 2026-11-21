from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
from api.backup.routes import get_sessions
from api.collection.coverage import summarize
from api.collection.models import CollectionCycle
from api.main import create_app
from sqlalchemy.exc import SQLAlchemyError


def test_public_summary_is_sanitized_and_explicit_about_age() -> None:
    now = datetime.now(UTC)
    cycle = CollectionCycle(
        id=uuid4(),
        scheduled_at=now - timedelta(hours=1),
        status="origin_failure",
        diagnostics={
            "status": "origin_failure",
            "road_saved": True,
            "garages_saved": 24,
            "failures": {
                "company_600": "https://private.invalid/secret:http_500",
                "private-token": "secret",
            },
        },
    )
    view = summarize(cycle, now)
    assert view.status == "partial" and view.stale
    assert view.failed_garage_companies == [600]
    assert view.road_saved and view.garages_saved == 24
    assert "secret" not in view.model_dump_json()
    assert "private" not in view.model_dump_json()
    cycle.status = "success"
    assert summarize(cycle, now).status == "complete"
    assert summarize(cycle, now).stale
    assert summarize(None, now).status == "unknown"


async def test_public_route_has_no_auth_and_hides_database_error() -> None:
    app = create_app()
    factory = Mock(return_value=AsyncMock())
    factory.return_value.__aenter__.return_value.scalar.side_effect = SQLAlchemyError(
        "private-password"
    )
    app.dependency_overrides[get_sessions] = lambda: factory
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        response = await c.get("/collection/coverage")
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert "private-password" not in response.text
