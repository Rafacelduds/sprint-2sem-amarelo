import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.config import Settings, get_settings
from api.storage.contracts import ObjectRef, ProcessingManifest
from api.storage.s3 import S3Archive
from api.storage.service import ArchiveService, exclusive

logger = logging.getLogger(__name__)


def archive_from_settings(settings: Settings) -> S3Archive:
    archive = S3Archive(
        settings.s3_bucket,
        endpoint=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key or None,
        secret_key=settings.s3_secret_key or None,
    )
    if settings.s3_restore_map:
        contents = json.loads(settings.s3_restore_map.read_text(encoding="utf-8"))
        archive.relocations = {
            identity: ObjectRef.model_validate(ref) for identity, ref in contents.items()
        }
    return archive


def inventory_bytes(refs: list[ObjectRef]) -> bytes:
    """Transformação técnica determinística, não é um indicador operacional."""
    rows = [{"key": ref.key, "sha256": ref.sha256, "bytes": ref.size} for ref in refs]
    return json.dumps(sorted(rows, key=lambda row: str(row["key"])), sort_keys=True).encode()


async def main() -> None:
    parser = argparse.ArgumentParser(description="US12: acervo bruto e proveniência")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Criar bucket local e habilitar versionamento")
    archive_parser = sub.add_parser("archive", help="Arquivar inbox pendente")
    archive_parser.add_argument("--watch", action="store_true")
    importer = sub.add_parser("import-history", help="Preservar arquivos Parquet recebidos")
    importer.add_argument("--path", type=Path, required=True)
    importer.add_argument("--dataset", required=True)
    recorder = sub.add_parser("record-manifest")
    recorder.add_argument("--path", type=Path, required=True)
    inventory = sub.add_parser("inventory", help="Criar inventário técnico reproduzível")
    inventory.add_argument("--dataset", required=True)
    inventory.add_argument("--code-version", required=True)
    inventory.add_argument("--period-start", type=datetime.fromisoformat, required=True)
    inventory.add_argument("--period-end", type=datetime.fromisoformat, required=True)
    replay = sub.add_parser("replay-inventory")
    replay.add_argument("--manifest-key", required=True)
    args = parser.parse_args()
    settings = get_settings()
    archive = archive_from_settings(settings)
    if args.command == "init":
        await asyncio.to_thread(archive.initialize)
        return
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    service = ArchiveService(async_sessionmaker(engine, expire_on_commit=False), archive)
    try:
        async with exclusive(engine, 710112) as guard:
            if args.command == "archive":
                while True:
                    await guard.execute(text("SELECT 1"))
                    try:
                        count = await service.archive_pending()
                        logger.info("archive_batch count=%s", count)
                    except Exception as exc:
                        if not args.watch:
                            raise
                        logger.error("archive_batch_failed type=%s", type(exc).__name__)
                        await asyncio.sleep(5)
                        continue
                    if not count:
                        if not args.watch:
                            break
                        await asyncio.sleep(5)
            elif args.command == "import-history":
                files = sorted(args.path.glob("*.parquet"))
                if not files:
                    raise ValueError("nenhum Parquet encontrado")
                for path in files:
                    ref = await service.import_file(path, args.dataset)
                    print(ref.model_dump_json())
            elif args.command == "record-manifest":
                manifest = ProcessingManifest.model_validate_json(args.path.read_bytes())
                print((await service.record(manifest)).model_dump_json())
            elif args.command == "inventory":
                refs = list(archive.objects(f"raw/received/{args.dataset}/"))
                run_id = uuid4()
                with TemporaryDirectory(prefix="amarelo-inventory-") as temporary:
                    path = Path(temporary) / "inventory.json"
                    path.write_bytes(inventory_bytes(refs))
                    output = await asyncio.to_thread(
                        archive.put,
                        path,
                        f"derived/inventory/{run_id}.json",
                        content_type="application/json",
                    )
                manifest = ProcessingManifest(
                    run_id=run_id,
                    dataset=args.dataset,
                    period_start=args.period_start,
                    period_end=args.period_end,
                    code_version=args.code_version,
                    rule_version="archive-inventory-v1",
                    inputs=refs,
                    outputs=[output],
                )
                print((await service.record(manifest)).model_dump_json())
            elif args.command == "replay-inventory":
                with TemporaryDirectory(prefix="amarelo-replay-") as temporary:
                    path = Path(temporary) / "manifest"
                    archive.download(archive.reference(args.manifest_key), path)
                    manifest = ProcessingManifest.model_validate_json(path.read_bytes())
                    if manifest.rule_version != "archive-inventory-v1":
                        raise ValueError("regra não é inventário técnico")
                    for ref in manifest.inputs:
                        archive.verify(ref)
                    output = Path(temporary) / "output"
                    archive.download(manifest.outputs[0], output)
                    if output.read_bytes() != inventory_bytes(manifest.inputs):
                        raise ValueError("reprodução divergente")
                    print(json.dumps({"reproduced": True, "inputs": len(manifest.inputs)}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except Exception as exc:
        logger.error("storage_failed type=%s", type(exc).__name__)
        raise SystemExit(1) from None
