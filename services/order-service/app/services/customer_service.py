import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Customer
from app.repositories.customer_repository import CustomerRepository
from app.schemas.customer import CustomerCreate

logger = logging.getLogger(__name__)


class CustomerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.customers = CustomerRepository(session)

    async def create(self, data: CustomerCreate) -> Customer:
        try:
            async with self.session.begin():
                if await self.customers.get_by_email(data.email) is not None:
                    raise ConflictError("A customer with this email already exists")
                if await self.customers.get_by_cpf(data.cpf) is not None:
                    raise ConflictError("A customer with this CPF already exists")
                customer = Customer(name=data.name, email=data.email, cpf=data.cpf)
                self.customers.add(customer)
        except IntegrityError as exc:
            # A concurrent request inserted the same email/CPF between the check and the commit.
            raise ConflictError("A customer with this email or CPF already exists") from exc
        # Intencional: o CPF (sintético) vai em claro no log para que o Cribl o mascare na pipeline.
        logger.info("Customer created: customer_id=%s cpf=%s", customer.id, customer.cpf)
        return customer

    async def get(self, customer_id: uuid.UUID) -> Customer:
        customer = await self.customers.get(customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} not found")
        return customer

    async def list(self, limit: int, offset: int) -> Sequence[Customer]:
        return await self.customers.list(limit, offset)
