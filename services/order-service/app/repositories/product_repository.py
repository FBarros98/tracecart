import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product
from app.models.enums import ProductCategory


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, product_id: uuid.UUID) -> Product | None:
        return await self.session.get(Product, product_id)

    async def get_by_name(self, name: str) -> Product | None:
        return await self.session.scalar(select(Product).where(Product.name == name))

    async def list(
        self, category: ProductCategory | None, active_only: bool, limit: int, offset: int
    ) -> Sequence[Product]:
        statement = select(Product)
        if category is not None:
            statement = statement.where(Product.category == category)
        if active_only:
            statement = statement.where(Product.is_active.is_(True))
        statement = statement.order_by(Product.name).limit(limit).offset(offset)
        return (await self.session.scalars(statement)).all()

    async def lock_many(self, product_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Product]:
        """SELECT ... FOR UPDATE in a deterministic order (by id) to avoid deadlocks."""
        statement = (
            select(Product)
            .where(Product.id.in_(list(product_ids)))
            .order_by(Product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {product.id: product for product in (await self.session.scalars(statement)).all()}

    async def increase_stock(self, product_id: uuid.UUID, quantity: int) -> None:
        await self.session.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(stock_quantity=Product.stock_quantity + quantity)
        )

    def add(self, product: Product) -> None:
        self.session.add(product)
