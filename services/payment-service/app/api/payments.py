import uuid

from fastapi import APIRouter, Response, status

from app.api.dependencies import PaymentServiceDep
from app.models import Payment
from app.schemas.common import ErrorResponse
from app.schemas.payment import PaymentCreate, PaymentRead

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": PaymentRead, "description": "Payment already existed for this order (idempotent)"},
        409: {"model": ErrorResponse, "description": "Order already has a payment with different data"},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse, "description": "Database temporarily unavailable"},
    },
)
async def create_payment(payload: PaymentCreate, response: Response, service: PaymentServiceDep) -> Payment:
    payment, created = await service.process(payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return payment


@router.get("/by-order/{order_id}", response_model=PaymentRead, responses={404: {"model": ErrorResponse}})
async def get_payment_by_order(order_id: uuid.UUID, service: PaymentServiceDep) -> Payment:
    return await service.get_by_order(order_id)


@router.get("/{payment_id}", response_model=PaymentRead, responses={404: {"model": ErrorResponse}})
async def get_payment(payment_id: uuid.UUID, service: PaymentServiceDep) -> Payment:
    return await service.get(payment_id)
