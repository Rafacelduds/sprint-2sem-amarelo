"""Resolve a identidade US02 no armazenamento original ou recuperado pela US32."""

from pydantic import TypeAdapter

from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive


def resolve_object(
    archive: S3Archive, *, bucket: str, key: str, sha256: str, size: int
) -> ObjectRef:
    # A US02 não guarda VersionId; o mapa US32 contém as identidades versionadas.
    identity_adapter = TypeAdapter(tuple[str, str, str | None])
    restored = [
        ref
        for identity, ref in archive.relocations.items()
        if identity_adapter.validate_json(identity)[:2] == (bucket, key)
    ]
    if restored:
        references = restored
    elif bucket == archive.bucket:
        references = [archive.reference(key)]
    else:
        raise ValueError("GTFS em bucket diferente sem mapa de restauração válido")
    for ref in references:
        if ref.bucket != archive.bucket:
            raise ValueError("mapa GTFS aponta para bucket diferente do configurado")
        if (
            ref.sha256 != sha256
            or ref.stored_sha256 != sha256
            or ref.size != size
            or ref.stored_size != size
            or ref.encoding != "identity"
        ):
            raise ValueError("referência GTFS diverge do conteúdo catalogado")
    return references[0]
