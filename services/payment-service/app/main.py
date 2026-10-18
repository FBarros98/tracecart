import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, payments
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.database.session import engine
from app.services.fault_injector import FaultInjector

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s (environment=%s)", settings.service_name, settings.environment)
    FaultInjector(settings).log_configuration()
    try:
        yield
    finally:
        logger.info("Shutting down %s", settings.service_name)
        await engine.dispose()
        logger.info("Shutdown complete")


app = FastAPI(
    title="TraceCart Payment Service",
    description="Simulated payment processing for TraceCart, with controlled fault injection.",
    version="1.0.0",
    lifespan=lifespan,
)
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(payments.router)
