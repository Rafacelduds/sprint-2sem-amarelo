import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from api.config import Settings
from api.network_gtfs import FeedProvider, FeedReference
from api.storage.contracts import ObjectRef
from botocore.response import StreamingBody
from test_network_gtfs import make_feed


@pytest.mark.parametrize("corrupt_body", [False, True])
async def test_map_uses_restored_gtfs_with_cold_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corrupt_body: bool
) -> None:
    body = make_feed(tmp_path / "original.zip")
    sha = hashlib.sha256(body).hexdigest()
    logical = FeedReference(
        sha, datetime.now(UTC), "synthetic", "original", "gtfs/test/feed.zip", len(body)
    )
    restored = ObjectRef(
        bucket="restored",
        key=logical.key,
        version_id="restored-version",
        sha256=sha,
        stored_sha256=sha,
        size=len(body),
        stored_size=len(body),
    )
    mapping = tmp_path / "restore-map.json"
    mapping.write_text(
        json.dumps(
            {
                json.dumps([logical.bucket, logical.key, "original-version"]): restored.model_dump(
                    mode="json"
                ),
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        network_cache_dir=tmp_path / "cache",
        s3_bucket=restored.bucket,
        s3_endpoint_url="https://synthetic.invalid",
        s3_access_key="test",
        s3_secret_key="test",
        s3_restore_map=mapping,
    )
    client = Mock()

    def get_object(**kwargs: str) -> dict[str, StreamingBody]:
        assert kwargs == {"Bucket": "restored", "Key": logical.key, "VersionId": "restored-version"}
        received = b"x" * len(body) if corrupt_body else body
        return {"Body": StreamingBody(io.BytesIO(received), len(received))}

    client.get_object.side_effect = get_object
    monkeypatch.setattr("api.network_gtfs.get_settings", lambda: settings)
    # Patch the SDK boundary, keeping real restore-map parsing and hash verification.
    monkeypatch.setattr("api.storage.s3.boto3.client", Mock(return_value=client))

    async def latest() -> FeedReference:
        return logical

    monkeypatch.setattr("api.network_gtfs.latest_reference", latest)
    result = await FeedProvider().get()
    client.get_object.assert_called_once()
    if corrupt_body:
        assert result is None
        assert not (settings.network_cache_dir / sha / "feed.zip").exists()
        return
    assert result is not None
    match = result[1].match("701A-10", "Metro Vila Madalena")
    assert match is not None and result[1].geometry(match.shapes)
