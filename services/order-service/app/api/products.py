import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies import ProductServiceDep
from app.models import Product
from app.models.enums import ProductCategory
from app.schemas.common import ErrorResponse
from app.schemas.product import ProductCreate, ProductRead

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
async def create_product(payload: ProductCreate, service: ProductServiceDep) -> Product:
    return await service.create(payload)


@router.get("", response_model=list[ProductRead])
async def list_products(
    service: ProductServiceDep,
    category: ProductCategory | None = None,
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Sequence[Product]:
    return await service.list(category, active_only, limit, offset)


@router.get("/{product_id}", response_model=ProductRead, responses={404: {"model": ErrorResponse}})
async def get_product(product_id: uuid.UUID, service: ProductServiceDep) -> Product:
    return await service.get(product_id)
