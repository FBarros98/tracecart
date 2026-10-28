import logging
import uuid
from decimal import Decimal
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.exceptions import PaymentServiceTimeoutError, PaymentServiceUnavailableError
from app.models.enums import PaymentMethod
from app.schemas.payment import PaymentResult

logger = logging.getLogger(__name__)


class PaymentClient:
    """HTTP client for the Payment Service. Timeouts are configured on the shared httpx client."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def create_payment(
        self, order_id: uuid.UUID, amount: Decimal, method: PaymentMethod, card_number: str | None = None
    ) -> PaymentResult:
        payload = {"order_id": str(order_id), "amount": str(amount), "method": method.value}
        if card_number is not None:
            payload["card_number"] = card_number
        response = await self._send("POST", "/payments", json=payload)
        if response.status_code in (200, 201):
            return self._parse(response)
        raise self._unexpected_response(response)

    async def get_payment_by_order(self, order_id: uuid.UUID) -> PaymentResult | None:
        response = await self._send("GET", f"/payments/by-order/{order_id}")
        if response.status_code == 404:
            return None
        if response.status_code == 200:
            return self._parse(response)
        raise self._unexpected_response(response)

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise PaymentServiceTimeoutError(
                f"Payment Service did not respond within the configured timeout ({method} {url})"
            ) from exc
        except httpx.TransportError as exc:
            raise PaymentServiceUnavailableError(
                f"Could not communicate with the Payment Service ({method} {url}): {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _parse(response: httpx.Response) -> PaymentResult:
        try:
            return PaymentResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise PaymentServiceUnavailableError("Payment Service returned an invalid response") from exc

    @staticmethod
    def _unexpected_response(response: httpx.Response) -> PaymentServiceUnavailableError:
        logger.warning(
            "Unexpected Payment Service response: %s %s -> HTTP %s",
            response.request.method,
            response.request.url.path,
            response.status_code,
        )
        return PaymentServiceUnavailableError(
            f"Payment Service responded with HTTP {response.status_code}"
        )
