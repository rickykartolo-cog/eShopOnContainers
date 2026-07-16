"""SQLAlchemy models for the frozen Catalog SQL Server schema
(`contracts/db/catalog.sqlschema.txt`): tables ``Catalog``/``CatalogBrand``/
``CatalogType`` with HiLo sequences ``catalog_hilo``/``catalog_brand_hilo``/
``catalog_type_hilo`` (increment 10, matching EF Core ``UseHiLo``)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import DECIMAL, Boolean, ForeignKey, Integer, Sequence, Unicode, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

HILO_BLOCK_SIZE = 10

CATALOG_HILO = Sequence("catalog_hilo", start=1, increment=HILO_BLOCK_SIZE)
CATALOG_BRAND_HILO = Sequence("catalog_brand_hilo", start=1, increment=HILO_BLOCK_SIZE)
CATALOG_TYPE_HILO = Sequence("catalog_type_hilo", start=1, increment=HILO_BLOCK_SIZE)


class Base(DeclarativeBase):
    pass


class CatalogBrand(Base):
    __tablename__ = "CatalogBrand"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Brand: Mapped[str] = mapped_column(Unicode(100), nullable=False)


class CatalogType(Base):
    __tablename__ = "CatalogType"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Type: Mapped[str] = mapped_column(Unicode(100), nullable=False)


class CatalogItem(Base):
    __tablename__ = "Catalog"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Name: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    Description: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    Price: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False)
    PictureFileName: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    CatalogTypeId: Mapped[int] = mapped_column(Integer, ForeignKey("CatalogType.Id"), nullable=False)
    CatalogBrandId: Mapped[int] = mapped_column(Integer, ForeignKey("CatalogBrand.Id"), nullable=False)
    AvailableStock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    RestockThreshold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    MaxStockThreshold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    OnReorder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    CatalogType_: Mapped[CatalogType] = relationship(CatalogType, lazy="noload")
    CatalogBrand_: Mapped[CatalogBrand] = relationship(CatalogBrand, lazy="noload")

    def remove_stock(self, quantity_desired: int) -> int:
        """Port of ``CatalogItem.RemoveStock`` (same invariants and messages)."""
        from catalog_api.exceptions import CatalogDomainError

        if self.AvailableStock == 0:
            raise CatalogDomainError(f"Empty stock, product item {self.Name} is sold out")
        if quantity_desired <= 0:
            raise CatalogDomainError("Item units desired should be greater than zero")
        removed = min(quantity_desired, self.AvailableStock)
        self.AvailableStock -= removed
        return removed


class HiLoGenerator:
    """EF Core ``HiLoValueGenerator`` semantics: each ``NEXT VALUE FOR`` call
    reserves the id block ``[value, value + increment - 1]``."""

    def __init__(self, sequence: Sequence, block_size: int = HILO_BLOCK_SIZE) -> None:
        self._sequence = sequence
        self._block_size = block_size
        self._next = 0
        self._max = -1
        self._lock = asyncio.Lock()

    async def next_id(self, session: AsyncSession) -> int:
        async with self._lock:
            if self._next > self._max:
                low = (await session.execute(select(self._sequence.next_value()))).scalar_one()
                self._next = int(low)
                self._max = self._next + self._block_size - 1
            value = self._next
            self._next += 1
            return value


catalog_hilo = HiLoGenerator(CATALOG_HILO)
catalog_brand_hilo = HiLoGenerator(CATALOG_BRAND_HILO)
catalog_type_hilo = HiLoGenerator(CATALOG_TYPE_HILO)
