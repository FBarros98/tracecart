import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies import CustomerServiceDep
from app.models import Customer
from app.schemas.common import ErrorResponse
from app.schemas.customer import CustomerCreate, CustomerRead

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post(
    "",
    response_model=CustomerRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
async def create_customer(payload: CustomerCreate, service: CustomerServiceDep) -> Customer:
    return await service.create(payload)


@router.get("", response_model=list[CustomerRead])
async def list_customers(
    service: CustomerServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Sequence[Customer]:
    return await service.list(limit, offset)


@router.get("/{customer_id}", response_model=CustomerRead, responses={404: {"model": ErrorResponse}})
async def get_customer(customer_id: uuid.UUID, service: CustomerServiceDep) -> Customer:
    return await service.get(customer_id)
