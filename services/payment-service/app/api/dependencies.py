from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.session import get_session
from app.services.fault_injector import FaultInjector
from app.services.payment_service import PaymentService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_payment_service(session: SessionDep) -> PaymentService:
    return PaymentService(session, FaultInjector(get_settings()))


PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
