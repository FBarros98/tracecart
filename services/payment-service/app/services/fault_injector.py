"""Controlled fault injection. Each fault is opt-in, has its own rate and is evaluated independently."""

import asyncio
import logging
import random

from app.core.config import Settings
from app.core.exceptions import SimulatedDatabaseError, SimulatedUnexpectedError

logger = logging.getLogger(__name__)

DECLINE_REASONS = ("INSUFFICIENT_FUNDS", "SUSPECTED_FRAUD", "ISSUER_UNAVAILABLE", "LIMIT_EXCEEDED")


class FaultInjector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _triggered(enabled: bool, rate: float) -> bool:
        return enabled and rate > 0 and random.random() < rate

    def decline_reason(self) -> str | None:
        """Return a decline reason when the payment must be declined, otherwise None."""
        s = self.settings
        if not self._triggered(s.payment_decline_enabled, s.payment_decline_rate):
            return None
        reason = random.choice(DECLINE_REASONS)
        logger.warning("Simulated fault: payment declined (reason=%s)", reason)
        return reason

    async def apply_latency(self) -> None:
        s = self.settings
        if not s.payment_latency_enabled:
            return
        delay_ms = random.randint(s.payment_latency_min_ms, s.payment_latency_max_ms)
        if delay_ms <= 0:
            return
        logger.warning("Simulated fault: adding %d ms of latency", delay_ms)
        await asyncio.sleep(delay_ms / 1000)

    def maybe_fail_database(self, operation: str) -> None:
        s = self.settings
        if self._triggered(s.database_failure_enabled, s.database_failure_rate):
            logger.warning("Simulated fault: database failure during '%s'", operation)
            raise SimulatedDatabaseError("Database temporarily unavailable")

    def maybe_raise_unexpected_error(self) -> None:
        s = self.settings
        if self._triggered(s.unexpected_error_enabled, s.unexpected_error_rate):
            logger.warning("Simulated fault: unexpected internal error")
            raise SimulatedUnexpectedError("Simulated unexpected error")

    def log_configuration(self) -> None:
        s = self.settings
        logger.info(
            "Fault injection: decline=%s(rate=%s) latency=%s(%s-%s ms) "
            "database_failure=%s(rate=%s) unexpected_error=%s(rate=%s)",
            s.payment_decline_enabled,
            s.payment_decline_rate,
            s.payment_latency_enabled,
            s.payment_latency_min_ms,
            s.payment_latency_max_ms,
            s.database_failure_enabled,
            s.database_failure_rate,
            s.unexpected_error_enabled,
            s.unexpected_error_rate,
        )
