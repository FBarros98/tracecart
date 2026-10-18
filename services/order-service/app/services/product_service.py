import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Product
from app.models.enums import ProductCategory
from app.repositories.product_repository import ProductRepository
from app.schemas.product import ProductCreate

logger = logging.getLogger(__name__)


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.products = ProductRepository(session)

    async def create(self, data: ProductCreate) -> Product:
        try:
            async with self.session.begin():
                if await self.products.get_by_name(data.name) is not None:
                    raise ConflictError("A product with this name already exists")
                product = Product(**data.model_dump())
                self.products.add(product)
        except IntegrityError as exc:
            raise ConflictError("A product with this name already exists") from exc
        logger.info(
            "Product created: product_id=%s category=%s stock=%d",
            product.id,
            product.category,
            product.stock_quantity,
        )
        return product

    async def get(self, product_id: uuid.UUID) -> Product:
        product = await self.products.get(product_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found")
        return product

    async def list(
        self, category: ProductCategory | None, active_only: bool, limit: int, offset: int
    ) -> Sequence[Product]:
        return await self.products.list(category, active_only, limit, offset)
