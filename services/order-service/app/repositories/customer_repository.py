import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, customer_id: uuid.UUID) -> Customer | None:
        return await self.session.get(Customer, customer_id)

    async def get_by_email(self, email: str) -> Customer | None:
        return await self.session.scalar(select(Customer).where(Customer.email == email))

    async def get_by_cpf(self, cpf: str) -> Customer | None:
        return await self.session.scalar(select(Customer).where(Customer.cpf == cpf))

    async def list(self, limit: int, offset: int) -> Sequence[Customer]:
        statement = select(Customer).order_by(Customer.created_at, Customer.id).limit(limit).offset(offset)
        return (await self.session.scalars(statement)).all()

    def add(self, customer: Customer) -> None:
        self.session.add(customer)
