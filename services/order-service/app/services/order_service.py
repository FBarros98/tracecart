"""Order lifecycle rules.

Stock is reserved on creation and released exactly once, on PAYMENT_FAILED or on CANCELLED from
PENDING; transitions run under a row lock, so it is never released or decremented twice.

No database transaction is held while calling the Payment Service. On timeout/failure the order
stays in PAYMENT_PROCESSING and a new POST /orders/{id}/pay reconciles it by order_id.
"""

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.payment_client import PaymentClient
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PaymentServiceError,
)
from app.core.telemetry import orders_created, orders_payments, orders_revenue, tracer, value_band
from app.models import Order, OrderItem
from app.models.enums import OrderStatus, PaymentMethod
from app.repositories.customer_repository import CustomerRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.order import OrderCreate
from app.schemas.payment import FINAL_PAYMENT_STATUSES, PaymentResult, PaymentStatus

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(self, session: AsyncSession, payment_client: PaymentClient) -> None:
        self.session = session
        self.payment_client = payment_client
        self.orders = OrderRepository(session)
        self.products = ProductRepository(session)
        self.customers = CustomerRepository(session)

    async def get(self, order_id: uuid.UUID) -> Order:
        order = await self.orders.get(order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")
        return order

    async def list(
        self, customer_id: uuid.UUID | None, status: OrderStatus | None, limit: int, offset: int
    ) -> Sequence[Order]:
        return await self.orders.list(customer_id, status, limit, offset)

    async def create(self, data: OrderCreate) -> Order:
        quantities: dict[uuid.UUID, int] = {}
        for item in data.items:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity

        async with self.session.begin():
            if await self.customers.get(data.customer_id) is None:
                raise BusinessRuleError(f"Customer {data.customer_id} not found")

            # row locks prevent overselling
            products = await self.products.lock_many(quantities)
            missing = [str(product_id) for product_id in quantities if product_id not in products]
            if missing:
                raise BusinessRuleError(f"Products not found: {', '.join(missing)}")

            items: list[OrderItem] = []
            total = Decimal("0.00")
            for product_id in sorted(quantities):
                product, quantity = products[product_id], quantities[product_id]
                if not product.is_active:
                    raise BusinessRuleError(f"Product {product_id} is inactive and cannot be purchased")
                if product.stock_quantity < quantity:
                    raise ConflictError(
                        f"Insufficient stock for product {product_id}: "
                        f"requested {quantity}, available {product.stock_quantity}"
                    )
                product.stock_quantity -= quantity
                items.append(OrderItem(product_id=product_id, quantity=quantity, unit_price=product.price))
                total += product.price * quantity

            order = Order(
                customer_id=data.customer_id,
                payment_method=data.payment_method,
                status=OrderStatus.PENDING,
                total_amount=total,
                items=items,
            )
            self.orders.add(order)

        orders_created.add(1, {"value_band": value_band(order.total_amount)})
        logger.info(
            "Order created: order_id=%s customer_id=%s items=%d total_amount=%s payment_method=%s",
            order.id,
            order.customer_id,
            len(items),
            order.total_amount,
            order.payment_method,
        )
        return order

    async def pay(
        self, order_id: uuid.UUID, card_number: str | None = None
    ) -> tuple[Order, PaymentResult | None]:
        with tracer.start_as_current_span("order.pay") as span:
            span.set_attribute("order.id", str(order_id))
            async with self.session.begin():
                order = await self._get_for_update(order_id)
                span.set_attribute("order.amount", float(order.total_amount))
                band = value_band(order.total_amount)
                span.set_attribute("order.value_band", band)
                if order.status == OrderStatus.CANCELLED:
                    raise ConflictError("Cancelled orders cannot be paid")
                if order.status == OrderStatus.PAID:
                    raise ConflictError("Order is already paid")
                if order.status == OrderStatus.PAYMENT_FAILED:
                    raise ConflictError("Payment for this order was declined; create a new order")
                reconciling = order.status == OrderStatus.PAYMENT_PROCESSING
                order.status = OrderStatus.PAYMENT_PROCESSING

            try:
                payment = await self._request_payment(order, reconciling, card_number)
            except PaymentServiceError as exc:
                span.set_attribute("payment.outcome", "timeout")
                orders_payments.add(1, {"value_band": band, "outcome": "timeout"})
                logger.warning(
                    "Payment outcome unknown for order_id=%s; order kept in PAYMENT_PROCESSING: %s",
                    order_id,
                    exc.message,
                )
                raise type(exc)(
                    f"{exc.message}. The payment outcome is unknown and order {order_id} remains in "
                    f"PAYMENT_PROCESSING. Retry POST /orders/{order_id}/pay to reconcile."
                ) from exc

            outcome = payment.status.value.lower()
            span.set_attribute("payment.outcome", outcome)
            orders_payments.add(1, {"value_band": band, "outcome": outcome})
            if payment.status == PaymentStatus.APPROVED:
                orders_revenue.add(float(order.total_amount), {"value_band": band})
            return await self._apply_payment_result(order_id, payment), payment

    async def cancel(self, order_id: uuid.UUID) -> Order:
        async with self.session.begin():
            order = await self._get_for_update(order_id)
            if order.status == OrderStatus.PAID:
                raise ConflictError("Paid orders cannot be cancelled")
            if order.status == OrderStatus.CANCELLED:
                raise ConflictError("Order is already cancelled")
            if order.status == OrderStatus.PAYMENT_PROCESSING:
                raise ConflictError(
                    "A payment is in progress for this order; "
                    f"call POST /orders/{order_id}/pay to reconcile before cancelling"
                )
            if order.status == OrderStatus.PENDING:
                await self._release_stock(order)
            order.status = OrderStatus.CANCELLED
        logger.info("Order cancelled: order_id=%s", order_id)
        return order

    async def _request_payment(
        self, order: Order, reconciling: bool, card_number: str | None = None
    ) -> PaymentResult:
        if reconciling:
            existing = await self.payment_client.get_payment_by_order(order.id)
            logger.info(
                "Reconciling order_id=%s: payment_status=%s",
                order.id,
                existing.status if existing else "NOT_FOUND",
            )
            if existing is not None and existing.status in FINAL_PAYMENT_STATUSES:
                return existing
        # The Payment Service is idempotent by order_id, so retrying the POST is safe.
        logger.info("Requesting payment: order_id=%s amount=%s", order.id, order.total_amount)
        # the card number is only forwarded, never persisted
        card = card_number if order.payment_method == PaymentMethod.CREDIT_CARD else None
        return await self.payment_client.create_payment(order.id, order.total_amount, order.payment_method, card)

    async def _apply_payment_result(self, order_id: uuid.UUID, payment: PaymentResult) -> Order:
        async with self.session.begin():
            order = await self._get_for_update(order_id)
            if order.status != OrderStatus.PAYMENT_PROCESSING:
                return order
            if payment.status == PaymentStatus.APPROVED:
                order.status = OrderStatus.PAID
            elif payment.status == PaymentStatus.DECLINED:
                order.status = OrderStatus.PAYMENT_FAILED
                await self._release_stock(order)
        logger.info(
            "Payment result applied: order_id=%s payment_id=%s payment_status=%s order_status=%s",
            order_id,
            payment.id,
            payment.status,
            order.status,
        )
        return order

    async def _get_for_update(self, order_id: uuid.UUID) -> Order:
        order = await self.orders.get_for_update(order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")
        return order

    async def _release_stock(self, order: Order) -> None:
        for item in sorted(order.items, key=lambda order_item: order_item.product_id):
            await self.products.increase_stock(item.product_id, item.quantity)
        logger.info("Stock released: order_id=%s", order.id)
