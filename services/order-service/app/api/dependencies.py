from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.payment_client import PaymentClient
from app.database.session import get_session
from app.services.customer_service import CustomerService
from app.services.order_service import OrderService
from app.services.product_service import ProductService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_customer_service(session: SessionDep) -> CustomerService:
    return CustomerService(session)


def get_product_service(session: SessionDep) -> ProductService:
    return ProductService(session)


def get_order_service(session: SessionDep, request: Request) -> OrderService:
    return OrderService(session, PaymentClient(request.app.state.payment_http_client))


CustomerServiceDep = Annotated[CustomerService, Depends(get_customer_service)]
ProductServiceDep = Annotated[ProductService, Depends(get_product_service)]
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
