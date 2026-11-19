import argparse
import asyncio
import json
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.config import get_settings
from api.documents.contracts import DocumentMetadata
from api.documents.service import DocumentCatalogue
from api.storage.__main__ import archive_from_settings
from api.storage.s3 import CollisionError


async def register(path: Path, metadata_path: Path) -> None:
    # Validar os metadados antes de abrir conexão ou gravar no S3.
    metadata = DocumentMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8-sig"))
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        catalogue = DocumentCatalogue(
            async_sessionmaker(engine, expire_on_commit=False), archive_from_settings(settings)
        )
        result = await catalogue.register(path, metadata)
        # JSON ASCII preserva Unicode sem depender da página de código do terminal Windows.
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=True, indent=2))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="US05: cadastrar PDF no acervo documental")
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("register", help="Preservar PDF e registrar seus metadados")
    importer.add_argument("--file", type=Path, required=True)
    importer.add_argument("--metadata", type=Path, required=True, help="JSON UTF-8 com metadados")
    args = parser.parse_args()
    try:
        asyncio.run(register(args.file, args.metadata))
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, item["loc"])) or "JSON" for item in exc.errors())
        parser.exit(1, f"Metadados inválidos: {fields}. Confira o contrato do acervo.\n")
    except (OSError, ValueError) as exc:
        # OSError pode conter caminhos pessoais; não emitir detalhes de bibliotecas.
        message = (
            str(exc)
            if isinstance(exc, ValueError)
            else "falha na leitura de arquivos ou conexão com os serviços locais"
        )
        parser.exit(1, message + "\n")
    except CollisionError:
        parser.exit(1, "Conflito no original S3; nada foi sobrescrito.\n")
    except (BotoCoreError, ClientError, SQLAlchemyError):
        parser.exit(1, "Falha no banco ou S3; confira os serviços e tente novamente.\n")


if __name__ == "__main__":
    main()
