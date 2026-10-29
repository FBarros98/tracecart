"""Background sampler that feeds the `orders.stuck` gauge (see core/telemetry.py)."""

import asyncio
import logging
from collections import Counter
from datetime import timedelta

from app.core.telemetry import (
    STUCK_AFTER_SECONDS,
    STUCK_SAMPLE_INTERVAL_SECONDS,
    set_stuck_orders,
    value_band,
)
from app.database.base import utcnow
from app.database.session import SessionLocal
from app.repositories.order_repository import OrderRepository

logger = logging.getLogger(__name__)


async def sample_stuck_orders() -> None:
    older_than = utcnow() - timedelta(seconds=STUCK_AFTER_SECONDS)
    async with SessionLocal() as session:
        amounts = await OrderRepository(session).stuck_amounts(older_than)
    set_stuck_orders(Counter(value_band(amount) for amount in amounts))


async def run_stuck_orders_sampler() -> None:
    while True:
        try:
            await sample_stuck_orders()
        except Exception:
            logger.warning("Stuck orders sampling failed", exc_info=True)
        await asyncio.sleep(STUCK_SAMPLE_INTERVAL_SECONDS)
