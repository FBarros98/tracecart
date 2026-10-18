import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import OrderServiceDep
from app.models import Order
from app.models.enums import OrderStatus
from app.schemas.common import ErrorResponse
from app.schemas.order import OrderCreate, OrderPaymentResponse, OrderRead

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def create_order(payload: OrderCreate, service: OrderServiceDep) -> Order:
    return await service.create(payload)


@router.get("", response_model=list[OrderRead])
async def list_orders(
    service: OrderServiceDep,
    customer_id: uuid.UUID | None = None,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Sequence[Order]:
    return await service.list(customer_id, status_filter, limit, offset)


@router.get("/{order_id}", response_model=OrderRead, responses={404: {"model": ErrorResponse}})
async def get_order(order_id: uuid.UUID, service: OrderServiceDep) -> Order:
    return await service.get(order_id)


@router.post(
    "/{order_id}/pay",
    response_model=OrderPaymentResponse,
    responses={
        202: {"model": OrderPaymentResponse, "description": "Payment still processing"},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": ErrorResponse, "description": "Payment Service failed; outcome unknown"},
        504: {"model": ErrorResponse, "description": "Payment Service timed out; outcome unknown"},
    },
)
async def pay_order(order_id: uuid.UUID, response: Response, service: OrderServiceDep) -> OrderPaymentResponse:
    order, payment = await service.pay(order_id)
    if order.status == OrderStatus.PAYMENT_PROCESSING:
        response.status_code = status.HTTP_202_ACCEPTED
    return OrderPaymentResponse(order=OrderRead.model_validate(order), payment=payment)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderRead,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def cancel_order(order_id: uuid.UUID, service: OrderServiceDep) -> Order:
    return await service.cancel(order_id)
