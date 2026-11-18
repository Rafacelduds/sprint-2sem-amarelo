"""Operações em blocos: nenhum arquivo histórico inteiro precisa caber na RAM."""

import base64
import gzip
import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import boto3  # pyright: ignore[reportMissingTypeStubs]
from botocore.exceptions import ClientError

from api.storage.contracts import ObjectRef

CHUNK = 1024 * 1024


def digest(path: Path) -> tuple[str, int]:
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            checksum.update(block)
            size += len(block)
    return checksum.hexdigest(), size


class CollisionError(RuntimeError):
    pass


class S3Archive:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint: str | None = None,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
    ):
        self.bucket = bucket
        self.relocations: dict[str, ObjectRef] = {}
        self.client: Any = cast(Any, boto3).client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def initialize(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                raise
            self.client.create_bucket(Bucket=self.bucket)
        self.client.put_bucket_versioning(
            Bucket=self.bucket, VersioningConfiguration={"Status": "Enabled"}
        )

    def reference(self, key: str) -> ObjectRef:
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        metadata = dict[str, str](head["Metadata"])
        return ObjectRef(
            bucket=self.bucket,
            key=key,
            version_id=head.get("VersionId"),
            sha256=metadata.pop("original-sha256"),
            stored_sha256=metadata.pop("stored-sha256"),
            size=int(metadata.pop("original-size")),
            stored_size=int(head["ContentLength"]),
            encoding="gzip" if head.get("ContentEncoding") == "gzip" else "identity",
            content_type=head.get("ContentType", "application/octet-stream"),
            metadata=metadata,
        )

    def put(
        self,
        path: Path,
        key: str,
        *,
        compress: bool = False,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        resume: bool = False,
    ) -> ObjectRef:
        original_hash, size = digest(path)
        with TemporaryDirectory(prefix="amarelo-upload-") as temporary:
            stored = path
            if compress:
                stored = Path(temporary) / "payload.gz"
                with path.open("rb") as source, stored.open("wb") as target:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as zipped:
                        shutil.copyfileobj(source, zipped, CHUNK)
            stored_hash, stored_size = digest(stored)
            tags = dict(metadata or {})
            tags.update(
                {
                    "original-sha256": original_hash,
                    "original-size": str(size),
                    "stored-sha256": stored_hash,
                }
            )
            try:
                with stored.open("rb") as body:
                    result = self.client.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=body,
                        ContentLength=stored_size,
                        ContentType=content_type,
                        ContentEncoding="gzip" if compress else "identity",
                        Metadata=tags,
                        IfNoneMatch="*",
                        ChecksumSHA256=base64.b64encode(bytes.fromhex(stored_hash)).decode("ascii"),
                    )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in ("PreconditionFailed", "412"):
                    raise
                if not resume:
                    raise CollisionError(key) from None
                existing = self.reference(key)
                if (
                    existing.sha256 != original_hash
                    or existing.stored_sha256 != stored_hash
                    or existing.metadata != (metadata or {})
                ):
                    raise CollisionError(key) from None
                self.verify(existing)
                return existing
            reference = ObjectRef(
                bucket=self.bucket,
                key=key,
                version_id=result.get("VersionId"),
                sha256=original_hash,
                stored_sha256=stored_hash,
                size=size,
                stored_size=stored_size,
                encoding="gzip" if compress else "identity",
                content_type=content_type,
                metadata=metadata or {},
            )
            self.verify(reference)
            return reference

    def download(self, reference: ObjectRef, destination: Path) -> None:
        physical = self.relocations.get(self.identity(reference), reference)
        if (
            physical.bucket != self.bucket
            or physical.sha256 != reference.sha256
            or physical.stored_sha256 != reference.stored_sha256
        ):
            raise ValueError("bucket inesperado")
        options: dict[str, str] = {"Bucket": self.bucket, "Key": physical.key}
        if physical.version_id:
            options["VersionId"] = physical.version_id
        response = self.client.get_object(**options)
        try:
            with destination.open("xb") as output:
                while block := response["Body"].read(CHUNK):
                    output.write(block)
        finally:
            response["Body"].close()
        if digest(destination) != (reference.stored_sha256, reference.stored_size):
            raise ValueError("hash armazenado divergente: " + reference.key)
        if reference.encoding == "gzip":
            checksum = hashlib.sha256()
            size = 0
            with gzip.open(destination, "rb") as original:
                while block := original.read(CHUNK):
                    checksum.update(block)
                    size += len(block)
            if (checksum.hexdigest(), size) != (reference.sha256, reference.size):
                raise ValueError("hash original divergente: " + reference.key)
        elif (reference.sha256, reference.size) != (reference.stored_sha256, reference.stored_size):
            raise ValueError("referência sem compressão inconsistente")

    def verify(self, reference: ObjectRef) -> None:
        with TemporaryDirectory(prefix="amarelo-verify-") as temporary:
            self.download(reference, Path(temporary) / "object")

    def objects(self, prefix: str) -> Iterator[ObjectRef]:
        pages = self.client.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield self.reference(str(item["Key"]))

    @staticmethod
    def identity(ref: ObjectRef) -> str:
        return json.dumps([ref.bucket, ref.key, ref.version_id], separators=(",", ":"))

    def replicate(self, source: "S3Archive", ref: ObjectRef) -> ObjectRef:
        """Preserva os bytes armazenados e seus metadados, inclusive gzip."""
        with TemporaryDirectory(prefix="amarelo-copy-") as temporary:
            path = Path(temporary) / "object"
            source.download(ref, path)
            tags = dict(ref.metadata)
            tags.update(
                {
                    "original-sha256": ref.sha256,
                    "stored-sha256": ref.stored_sha256,
                    "original-size": str(ref.size),
                }
            )
            try:
                with path.open("rb") as body:
                    result = self.client.put_object(
                        Bucket=self.bucket,
                        Key=ref.key,
                        Body=body,
                        ContentLength=ref.stored_size,
                        ContentType=ref.content_type,
                        ContentEncoding=ref.encoding,
                        Metadata=tags,
                        IfNoneMatch="*",
                        ChecksumSHA256=base64.b64encode(bytes.fromhex(ref.stored_sha256)).decode(
                            "ascii"
                        ),
                    )
                copied = ref.model_copy(
                    update={
                        "bucket": self.bucket,
                        "version_id": result.get("VersionId"),
                    }
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in ("PreconditionFailed", "412"):
                    raise
                copied = self.reference(ref.key)
                if copied.model_dump(exclude={"bucket", "version_id"}) != ref.model_dump(
                    exclude={"bucket", "version_id"}
                ):
                    raise CollisionError(ref.key) from None
            self.verify(copied)
            return copied
