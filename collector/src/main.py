from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from sqlalchemy import text

from .database import engine
from .logging import setup_logging
from .providers import get_all_providers
from .routers import analytics, sync
from .schemas import HealthResponse

setup_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("collector.startup", service="collector")
    yield
    await engine.dispose()
    logger.info("collector.shutdown", service="collector")


app = FastAPI(title="Social Analytics Collector", version="0.1.0", lifespan=lifespan)
app.include_router(sync.router)
app.include_router(analytics.router)


@app.get("/health", response_model=HealthResponse)
async def health():
    db_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    providers = {}
    for provider in await get_all_providers():
        if await provider.is_configured():
            providers[provider.platform] = "configured"
        else:
            providers[provider.platform] = "missing_credentials"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db=db_status,
        providers=providers,
    )
