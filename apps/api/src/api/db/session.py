from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from api.config import get_settings

settings = get_settings()
engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
