from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol

from botocore.exceptions import ClientError

from api.gtfs.source import FeedMetadata, GtfsError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class Archive(Protocol):
    def preserve(self, path: Path, source: str, metadata: FeedMetadata) -> str: ...


class S3Archive:
    def __init__(self, client: "S3Client", bucket: str):
        self.client = client
        self.bucket = bucket

    def preserve(self, path: Path, source: str, metadata: FeedMetadata) -> str:
        key = f"gtfs/{source}/{metadata.sha256}.zip"
        with path.open("rb") as body:
            self._put(body, key, metadata)
        return key

    def _put(self, body: BinaryIO, key: str, metadata: FeedMetadata) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="application/zip",
                Metadata={"sha256": metadata.sha256},
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if exc.response["Error"].get("Code") not in {"PreconditionFailed", "412"}:
                raise GtfsError("archive_write_failed") from None
            existing = self.client.head_object(Bucket=self.bucket, Key=key)
            if (
                existing.get("Metadata", {}).get("sha256") != metadata.sha256
                or existing.get("ContentLength") != metadata.size
            ):
                raise GtfsError("archive_conflict") from None
