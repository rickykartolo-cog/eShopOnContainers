"""Port of ``CatalogContextSeed``: preconfigured data, optional CSV
customization (``UseCustomizationData``), HiLo-generated ids, idempotent
(seeds only when each table is empty)."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_fixed

from catalog_api.models import (
    CatalogBrand,
    CatalogItem,
    CatalogType,
    catalog_brand_hilo,
    catalog_hilo,
    catalog_type_hilo,
)
from catalog_api.settings import CatalogSettings

logger = structlog.get_logger(__name__)

PRECONFIGURED_BRANDS = ["Azure", ".NET", "Visual Studio", "SQL Server", "Other"]
PRECONFIGURED_TYPES = ["Mug", "T-Shirt", "Sheet", "USB Memory Stick"]

# (type_id, brand_id, stock, description, name, price, picture)
PRECONFIGURED_ITEMS = [
    (2, 2, 100, ".NET Bot Black Hoodie", ".NET Bot Black Hoodie", Decimal("19.5"), "1.png"),
    (1, 2, 100, ".NET Black & White Mug", ".NET Black & White Mug", Decimal("8.50"), "2.png"),
    (2, 5, 100, "Prism White T-Shirt", "Prism White T-Shirt", Decimal("12"), "3.png"),
    (2, 2, 100, ".NET Foundation T-shirt", ".NET Foundation T-shirt", Decimal("12"), "4.png"),
    (3, 5, 100, "Roslyn Red Sheet", "Roslyn Red Sheet", Decimal("8.5"), "5.png"),
    (2, 2, 100, ".NET Blue Hoodie", ".NET Blue Hoodie", Decimal("12"), "6.png"),
    (2, 5, 100, "Roslyn Red T-Shirt", "Roslyn Red T-Shirt", Decimal("12"), "7.png"),
    (2, 5, 100, "Kudu Purple Hoodie", "Kudu Purple Hoodie", Decimal("8.5"), "8.png"),
    (1, 5, 100, "Cup<T> White Mug", "Cup<T> White Mug", Decimal("12"), "9.png"),
    (3, 2, 100, ".NET Foundation Sheet", ".NET Foundation Sheet", Decimal("12"), "10.png"),
    (3, 2, 100, "Cup<T> Sheet", "Cup<T> Sheet", Decimal("8.5"), "11.png"),
    (2, 5, 100, "Prism White TShirt", "Prism White TShirt", Decimal("12"), "12.png"),
]


@retry(reraise=True, stop=stop_after_attempt(10), wait=wait_fixed(5))
async def seed(session: AsyncSession, settings: CatalogSettings) -> None:
    use_custom = settings.use_customization_data
    setup_path = settings.setup_path

    if not await _any(session, CatalogBrand):
        brands = _brands_from_csv(setup_path) if use_custom else None
        for brand in brands or PRECONFIGURED_BRANDS:
            session.add(CatalogBrand(Id=await catalog_brand_hilo.next_id(session), Brand=brand))
        await session.commit()

    if not await _any(session, CatalogType):
        types = _types_from_csv(setup_path) if use_custom else None
        for type_name in types or PRECONFIGURED_TYPES:
            session.add(CatalogType(Id=await catalog_type_hilo.next_id(session), Type=type_name))
        await session.commit()

    if not await _any(session, CatalogItem):
        items = await (_items_from_csv(session, setup_path) if use_custom else _preconfigured_items(session))
        for item in items:
            session.add(item)
        await session.commit()
    logger.info("catalog_seed_complete")


async def _any(session: AsyncSession, model) -> bool:
    return bool((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _preconfigured_items(session: AsyncSession) -> list[CatalogItem]:
    return [
        CatalogItem(
            Id=await catalog_hilo.next_id(session),
            CatalogTypeId=type_id,
            CatalogBrandId=brand_id,
            AvailableStock=stock,
            Description=description,
            Name=name,
            Price=price,
            PictureFileName=picture,
            RestockThreshold=0,
            MaxStockThreshold=0,
            OnReorder=False,
        )
        for type_id, brand_id, stock, description, name, price, picture in PRECONFIGURED_ITEMS
    ]


def _brands_from_csv(setup_path: Path) -> list[str] | None:
    return _single_column_csv(setup_path / "CatalogBrands.csv", "catalogbrand")


def _types_from_csv(setup_path: Path) -> list[str] | None:
    return _single_column_csv(setup_path / "CatalogTypes.csv", "catalogtype")


def _single_column_csv(path: Path, header: str) -> list[str] | None:
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0].strip().strip('"').lower() != header:
        logger.error("csv_header_mismatch", path=str(path), expected=header)
        return None
    values = [line.strip().strip('"').strip() for line in lines[1:]]
    return [value for value in values if value] or None


async def _items_from_csv(session: AsyncSession, setup_path: Path) -> list[CatalogItem]:
    path = setup_path / "CatalogItems.csv"
    if not path.exists():
        return await _preconfigured_items(session)

    type_lookup = {
        row.Type: row.Id for row in (await session.execute(select(CatalogType))).scalars()
    }
    brand_lookup = {
        row.Brand: row.Id for row in (await session.execute(select(CatalogBrand))).scalars()
    }

    items: list[CatalogItem] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return await _preconfigured_items(session)
        fieldnames = [name.strip().lower() for name in reader.fieldnames]
        required = {"catalogtypename", "catalogbrandname", "description", "name", "price", "picturefilename"}
        if not required.issubset(fieldnames):
            logger.error("csv_header_mismatch", path=str(path))
            return await _preconfigured_items(session)
        for raw in reader:
            row = {key.strip().lower(): (value or "").strip().strip('"').strip() for key, value in raw.items()}
            try:
                type_name, brand_name = row["catalogtypename"], row["catalogbrandname"]
                if type_name not in type_lookup or brand_name not in brand_lookup:
                    raise ValueError(f"unknown type/brand: {type_name}/{brand_name}")
                items.append(
                    CatalogItem(
                        Id=await catalog_hilo.next_id(session),
                        CatalogTypeId=type_lookup[type_name],
                        CatalogBrandId=brand_lookup[brand_name],
                        Description=row["description"],
                        Name=row["name"],
                        Price=Decimal(row["price"]),
                        PictureFileName=row["picturefilename"],
                        AvailableStock=int(row.get("availablestock") or 0),
                        RestockThreshold=int(row.get("restockthreshold") or 0),
                        MaxStockThreshold=int(row.get("maxstockthreshold") or 0),
                        OnReorder=(row.get("onreorder") or "false").lower() == "true",
                    )
                )
            except (ValueError, KeyError, InvalidOperation) as exc:
                logger.error("csv_row_skipped", error=str(exc))
    return items
