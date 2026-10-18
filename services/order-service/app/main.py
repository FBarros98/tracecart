import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import customers, health, orders, products
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.database.session import engine

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Starting %s (environment=%s, payment_service_url=%s, payment_timeout=%ss)",
        settings.service_name,
        settings.environment,
        settings.payment_service_url,
        settings.payment_service_timeout_seconds,
    )
    app.state.payment_http_client = httpx.AsyncClient(
        base_url=settings.payment_service_url,
        timeout=httpx.Timeout(settings.payment_service_timeout_seconds),
    )
    try:
        yield
    finally:
        logger.info("Shutting down %s", settings.service_name)
        await app.state.payment_http_client.aclose()
        await engine.dispose()
        logger.info("Shutdown complete")


app = FastAPI(
    title="TraceCart Order Service",
    description="Customers, products, stock and order lifecycle for the TraceCart mini e-commerce.",
    version="1.0.0",
    lifespan=lifespan,
)
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(customers.router)
app.include_router(products.router)
app.include_router(orders.router)
