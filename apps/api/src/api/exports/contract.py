from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Sao_Paulo")
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
SOURCE = "https://api.olhovivo.sptrans.com.br/v2.1"
RULE = "raw-responses-parquet-v1"
DICTIONARY: dict[str, str] = {
    "captura_id": "VARCHAR: UUID da resposta; uma linha por resposta original, sem deduplicação.",
    "ciclo_id": "VARCHAR: UUID do ciclo de coleta.",
    "coletado_em": "TIMESTAMPTZ: instante de captura em UTC; não é horário GPS.",
    "endpoint": "VARCHAR: endpoint da captura (/Posicao ou /Posicao/Garagem).",
    "empresa": "INTEGER nullable: código da empresa nas capturas de garagem.",
    "fonte": "VARCHAR: endereço original da API SPTrans Olho Vivo, sem credenciais.",
    "sha256_original": "VARCHAR: SHA-256 dos bytes originais de corpo_original.",
    "corpo_original": (
        "BLOB: resposta JSON original completa, descomprimida, byte a byte. "
        "Inclui campos não modelados, linhas, veículos, horários GPS e respostas vazias. "
        "Decodifique como UTF-8 e leia JSON para acessar os registros."
    ),
}


def bounds(day: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, time(), ZONE).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time(), ZONE).astimezone(UTC),
    )


def deadline(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(6), ZONE)
