import uuid
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import utcnow
from app.models import Payment
from app.models.enums import PaymentMethod, PaymentStatus


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self.session.get(Payment, payment_id, populate_existing=True)

    async def get_by_order(self, order_id: uuid.UUID, for_update: bool = False) -> Payment | None:
        statement = (
            select(Payment)
            .where(Payment.order_id == order_id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def insert_if_absent(self, order_id: uuid.UUID, amount: Decimal, method: PaymentMethod) -> bool:
        """Insert a PROCESSING payment unless one already exists for the order. Returns True if inserted."""
        statement = (
            insert(Payment)
            .values(
                id=uuid.uuid4(),
                order_id=order_id,
                amount=amount,
                method=method,
                status=PaymentStatus.PROCESSING,
                processing_time_ms=0,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=[Payment.order_id])
            .returning(Payment.id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def finalize(
        self,
        payment_id: uuid.UUID,
        status: PaymentStatus,
        failure_reason: str | None,
        processing_time_ms: int,
    ) -> Payment | None:
        """Set the outcome only if the payment is still PROCESSING (first writer wins)."""
        statement = (
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == PaymentStatus.PROCESSING)
            .values(status=status, failure_reason=failure_reason, processing_time_ms=processing_time_ms)
            .returning(Payment)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()
