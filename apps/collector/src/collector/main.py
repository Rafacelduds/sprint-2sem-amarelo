import logging
import time

from collector.config import get_settings
from collector.storage import create_s3_client, list_raw_objects

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    settings = get_settings()
    client = create_s3_client(settings)
    logger.info("Coletor iniciado; bucket=%s", settings.s3_bucket)

    while True:
        objects = list_raw_objects(client, settings.s3_bucket)
        logger.info("Coletor aguardando trabalho; objetos_brutos=%d", len(objects))
        time.sleep(settings.collector_poll_seconds)


if __name__ == "__main__":
    run()
