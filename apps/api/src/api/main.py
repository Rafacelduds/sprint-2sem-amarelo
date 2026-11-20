from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.config import get_settings
from api.documents.routes import router as documents_router
from api.exports.routes import router as exports_router
from api.live import router as live_router
from api.network import router as network_router
from api.reliability.routes import router as reliability_router
from api.schedules.routes import router as schedules_router


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API mínima para validar a stack da Sprint Amarelo.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/health", tags=["health"], response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="api")

    application.include_router(live_router)
    application.include_router(network_router)
    application.include_router(exports_router)
    application.include_router(reliability_router)
    application.include_router(documents_router)
    application.include_router(schedules_router)
    return application


app = create_app()
