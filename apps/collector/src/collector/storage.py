from __future__ import annotations

from typing import TYPE_CHECKING

from boto3.session import Session

from collector.config import CollectorSettings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import ObjectTypeDef


def create_s3_client(settings: CollectorSettings) -> S3Client:
    session = Session(
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    return session.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=settings.s3_endpoint_url,
    )


def list_raw_objects(client: S3Client, bucket: str) -> list[ObjectTypeDef]:
    response = client.list_objects_v2(Bucket=bucket)
    return list(response.get("Contents", []))
