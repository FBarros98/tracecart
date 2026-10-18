import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order
from app.models.enums import OrderStatus


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, order_id: uuid.UUID) -> Order | None:
        return await self.session.get(Order, order_id)

    async def get_for_update(self, order_id: uuid.UUID) -> Order | None:
        statement = (
            select(Order)
            .where(Order.id == order_id)
            .with_for_update(of=Order)
            .execution_options(populate_existing=True)
        )
        return await self.session.scalar(statement)

    async def list(
        self,
        customer_id: uuid.UUID | None,
        status: OrderStatus | None,
        limit: int,
        offset: int,
    ) -> Sequence[Order]:
        statement = select(Order)
        if customer_id is not None:
            statement = statement.where(Order.customer_id == customer_id)
        if status is not None:
            statement = statement.where(Order.status == status)
        statement = statement.order_by(Order.created_at.desc(), Order.id).limit(limit).offset(offset)
        return (await self.session.scalars(statement)).all()

    def add(self, order: Order) -> None:
        self.session.add(order)
