"""Read side: SQLAlchemy Core ``text()`` ports of the Dapper queries in
``OrderQueries.cs`` — same SQL semantics, aliases and response field names
(lowercase, exactly as the frozen OpenAPI ``Order``/``OrderSummary``/``CardType``
schemas)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ordering_api.serialization import unspecified_datetime

GET_ORDER_SQL = text(
    """select o.Id as ordernumber,o.OrderDate as date, o.Description as description,
        o.Address_City as city, o.Address_Country as country, o.Address_State as state, o.Address_Street as street, o.Address_ZipCode as zipcode,
        os.Name as status,
        oi.ProductName as productname, oi.Units as units, oi.UnitPrice as unitprice, oi.PictureUrl as pictureurl
        FROM ordering.orders o
        LEFT JOIN ordering."orderItems" oi ON o.Id = oi.OrderId
        LEFT JOIN ordering.orderstatus os on o.OrderStatusId = os.Id
        WHERE o.Id=:id"""
)

GET_ORDERS_FROM_USER_SQL = text(
    """SELECT o.Id as ordernumber,o.OrderDate as date,os.Name as status, SUM(oi.Units*oi.UnitPrice) as total
        FROM ordering.orders o
        LEFT JOIN ordering."orderItems" oi ON  o.Id = oi.OrderId
        LEFT JOIN ordering.orderstatus os on o.OrderStatusId = os.Id
        LEFT JOIN ordering.buyers ob on o.BuyerId = ob.Id
        WHERE ob.IdentityGuid = :userId
        GROUP BY o.Id, o.OrderDate, os.Name
        ORDER BY o.Id"""
)

GET_CARD_TYPES_SQL = text("SELECT * FROM ordering.cardtypes")


class OrderNotFoundError(KeyError):
    """Port of the KeyNotFoundException the Dapper query raised for missing orders."""


async def get_order(session: AsyncSession, order_id: int) -> dict:
    result = (await session.execute(GET_ORDER_SQL, {"id": order_id})).mappings().all()
    if not result:
        raise OrderNotFoundError(order_id)
    first = result[0]
    order = {
        "ordernumber": first["ordernumber"],
        "date": _date_text(first["date"]),
        "status": first["status"],
        "description": first["description"],
        "street": first["street"],
        "city": first["city"],
        "zipcode": first["zipcode"],
        "country": first["country"],
        "orderitems": [],
        "total": Decimal(0),
    }
    for item in result:
        order["orderitems"].append(
            {
                "productname": item["productname"],
                "units": item["units"],
                "unitprice": float(item["unitprice"]),
                "pictureurl": item["pictureurl"],
            }
        )
        order["total"] += item["units"] * _as_decimal(item["unitprice"])
    return order


async def get_orders_from_user(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    rows = (await session.execute(GET_ORDERS_FROM_USER_SQL, {"userId": str(user_id)})).mappings()
    return [
        {
            "ordernumber": row["ordernumber"],
            "date": _date_text(row["date"]),
            "status": row["status"],
            "total": float(row["total"]) if row["total"] is not None else 0.0,
        }
        for row in rows
    ]


async def get_card_types(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(GET_CARD_TYPES_SQL)).mappings()
    return [{"id": row["Id"], "name": row["Name"]} for row in rows]


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _date_text(value: object) -> str:
    if isinstance(value, datetime):
        return unspecified_datetime(value)
    if isinstance(value, str):  # SQLite test fixture stores ISO text
        return unspecified_datetime(datetime.fromisoformat(value))
    raise TypeError(f"Unexpected date value {value!r}")
