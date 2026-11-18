from pathlib import Path

import boto3
import pytest
from api.gtfs.source import GtfsError, inspect_feed
from api.gtfs.storage import S3Archive
from botocore.stub import ANY, Stubber
from test_gtfs_source import feed_bytes


@pytest.mark.parametrize("conflict", [False, True])
def test_existing_object_is_checked_without_overwriting(tmp_path: Path, conflict: bool) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(feed_bytes())
    metadata = inspect_feed(path)
    client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    key = f"gtfs/sptrans/{metadata.sha256}.zip"
    with Stubber(client) as stub:
        stub.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
            expected_params={
                "Bucket": "test",
                "Key": key,
                "Body": ANY,
                "ContentType": "application/zip",
                "Metadata": {"sha256": metadata.sha256},
                "IfNoneMatch": "*",
            },
        )
        stub.add_response(
            "head_object",
            {
                "Metadata": {"sha256": "bad" if conflict else metadata.sha256},
                "ContentLength": metadata.size,
            },
            {"Bucket": "test", "Key": key},
        )
        if conflict:
            with pytest.raises(GtfsError, match="archive_conflict"):
                S3Archive(client, "test").preserve(path, "sptrans", metadata)
        else:
            assert S3Archive(client, "test").preserve(path, "sptrans", metadata) == key
        stub.assert_no_pending_responses()
