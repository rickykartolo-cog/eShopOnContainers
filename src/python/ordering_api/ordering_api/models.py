"""SQLAlchemy models doubling as DDD aggregates for the frozen Ordering SQL Server
schema (`contracts/db/ordering.sqlschema.txt`): schema ``ordering``, tables
orders/orderItems/buyers/cardtypes/orderstatus/paymentmethods/requests, HiLo
sequences ``ordering.orderseq``/``buyerseq``/``paymentseq`` and dbo
``orderitemseq`` (increment 10, matching EF Core ``UseHiLo``).

The aggregate behaviors (state machine, invariants, domain-event recording) are
line-for-line ports of ``Order``/``OrderItem``/``Buyer``/``PaymentMethod`` in
``Ordering.Domain``; field-backed private properties map to the same column
names the EF configurations assign (e.g. ``_orderStatusId`` -> ``OrderStatusId``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DECIMAL, DateTime, ForeignKey, Integer, Sequence, Unicode, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DEFAULT_SCHEMA = "ordering"
HILO_BLOCK_SIZE = 10

ORDER_HILO = Sequence("orderseq", schema=DEFAULT_SCHEMA, start=1, increment=HILO_BLOCK_SIZE)
BUYER_HILO = Sequence("buyerseq", schema=DEFAULT_SCHEMA, start=1, increment=HILO_BLOCK_SIZE)
PAYMENT_HILO = Sequence("paymentseq", schema=DEFAULT_SCHEMA, start=1, increment=HILO_BLOCK_SIZE)
ORDER_ITEM_HILO = Sequence("orderitemseq", start=1, increment=HILO_BLOCK_SIZE)


class OrderingDomainException(Exception):
    """Port of ``OrderingDomainException``."""


class OrderStatus:
    """Port of the ``OrderStatus`` enumeration (seed values in ordering.orderstatus)."""

    Submitted = (1, "submitted")
    AwaitingValidation = (2, "awaitingvalidation")
    StockConfirmed = (3, "stockconfirmed")
    Paid = (4, "paid")
    Shipped = (5, "shipped")
    Cancelled = (6, "cancelled")

    ALL = [Submitted, AwaitingValidation, StockConfirmed, Paid, Shipped, Cancelled]

    @classmethod
    def name_of(cls, status_id: int) -> str:
        for sid, name in cls.ALL:
            if sid == status_id:
                return name
        raise OrderingDomainException(f"Possible values for OrderStatus: {status_id}")


class CardType:
    """Port of the ``CardType`` enumeration (seed values in ordering.cardtypes)."""

    ALL = [(1, "Amex"), (2, "Visa"), (3, "MasterCard")]


# --- Domain events (ports of Ordering.Domain/Events) ---


@dataclass
class OrderStartedDomainEvent:
    order: Order
    user_id: str
    user_name: str | None
    card_type_id: int
    card_number: str | None
    card_security_number: str | None
    card_holder_name: str | None
    card_expiration: datetime


@dataclass
class OrderStatusChangedToAwaitingValidationDomainEvent:
    order_id: int
    order_items: list[OrderItem]


@dataclass
class OrderStatusChangedToStockConfirmedDomainEvent:
    order_id: int


@dataclass
class OrderStatusChangedToPaidDomainEvent:
    order_id: int
    order_items: list[OrderItem]


@dataclass
class OrderShippedDomainEvent:
    order: Order


@dataclass
class OrderCancelledDomainEvent:
    order: Order


@dataclass
class BuyerAndPaymentMethodVerifiedDomainEvent:
    buyer: Buyer
    payment: PaymentMethod
    order_id: int


class Base(DeclarativeBase):
    pass


class DomainEntity:
    """Domain-event recording shared by aggregate entities (port of ``Entity``)."""

    @property
    def domain_events(self) -> list[Any]:
        events = self.__dict__.get("_pending_domain_events")
        if events is None:
            events = self.__dict__["_pending_domain_events"] = []
        return events

    def add_domain_event(self, event: Any) -> None:
        self.domain_events.append(event)

    def clear_domain_events(self) -> None:
        self.domain_events.clear()


class CardTypeRow(Base):
    __tablename__ = "cardtypes"
    __table_args__ = {"schema": DEFAULT_SCHEMA}

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Name: Mapped[str] = mapped_column(Unicode(200), nullable=False)


class OrderStatusRow(Base):
    __tablename__ = "orderstatus"
    __table_args__ = {"schema": DEFAULT_SCHEMA}

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Name: Mapped[str] = mapped_column(Unicode(200), nullable=False)


class ClientRequest(Base):
    """Idempotency row for the ``ordering.requests`` table."""

    __tablename__ = "requests"
    __table_args__ = {"schema": DEFAULT_SCHEMA}

    Id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    Name: Mapped[str] = mapped_column(Unicode, nullable=False)
    Time: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PaymentMethod(Base, DomainEntity):
    __tablename__ = "paymentmethods"
    __table_args__ = {"schema": DEFAULT_SCHEMA}

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Alias: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    BuyerId: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DEFAULT_SCHEMA}.buyers.Id"), nullable=False
    )
    CardHolderName: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    CardNumber: Mapped[str] = mapped_column(Unicode(25), nullable=False)
    CardTypeId: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DEFAULT_SCHEMA}.cardtypes.Id"), nullable=False
    )
    Expiration: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __init__(
        self,
        card_type_id: int,
        alias: str,
        card_number: str | None,
        security_number: str | None,
        card_holder_name: str | None,
        expiration: datetime,
    ) -> None:
        if not card_number:
            raise OrderingDomainException("cardNumber")
        if not security_number:
            raise OrderingDomainException("securityNumber")
        if not card_holder_name:
            raise OrderingDomainException("cardHolderName")
        if _as_naive_utc(expiration) < datetime.utcnow():
            raise OrderingDomainException("expiration")
        super().__init__(
            Alias=alias,
            CardNumber=card_number,
            CardHolderName=card_holder_name,
            Expiration=_as_naive_utc(expiration),
            CardTypeId=card_type_id,
        )

    def is_equal_to(self, card_type_id: int, card_number: str, expiration: datetime) -> bool:
        return (
            self.CardTypeId == card_type_id
            and self.CardNumber == card_number
            and self.Expiration == _as_naive_utc(expiration)
        )


class Buyer(Base, DomainEntity):
    __tablename__ = "buyers"
    __table_args__ = {"schema": DEFAULT_SCHEMA}

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    IdentityGuid: Mapped[str] = mapped_column(Unicode(200), nullable=False, unique=True)
    Name: Mapped[str | None] = mapped_column(Unicode, nullable=True)

    payment_methods: Mapped[list[PaymentMethod]] = relationship(
        PaymentMethod, lazy="selectin", cascade="all, delete-orphan"
    )

    def __init__(self, identity: str, name: str | None) -> None:
        if not identity or not identity.strip():
            raise OrderingDomainException("identity")
        if not name or not name.strip():
            raise OrderingDomainException("name")
        super().__init__(IdentityGuid=identity, Name=name)

    def verify_or_add_payment_method(
        self,
        card_type_id: int,
        alias: str,
        card_number: str | None,
        security_number: str | None,
        card_holder_name: str | None,
        expiration: datetime,
        order_id: int,
    ) -> PaymentMethod:
        existing = next(
            (
                p
                for p in self.payment_methods
                if p.is_equal_to(card_type_id, card_number or "", expiration)
            ),
            None,
        )
        if existing is not None:
            self.add_domain_event(BuyerAndPaymentMethodVerifiedDomainEvent(self, existing, order_id))
            return existing
        payment = PaymentMethod(
            card_type_id, alias, card_number, security_number, card_holder_name, expiration
        )
        self.payment_methods.append(payment)
        self.add_domain_event(BuyerAndPaymentMethodVerifiedDomainEvent(self, payment, order_id))
        return payment


class OrderItem(Base, DomainEntity):
    __tablename__ = "orderItems"
    __table_args__ = {"schema": DEFAULT_SCHEMA}

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Discount: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False)
    OrderId: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DEFAULT_SCHEMA}.orders.Id"), nullable=False
    )
    PictureUrl: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    ProductId: Mapped[int] = mapped_column(Integer, nullable=False)
    ProductName: Mapped[str] = mapped_column(Unicode, nullable=False)
    UnitPrice: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False)
    Units: Mapped[int] = mapped_column(Integer, nullable=False)

    def __init__(
        self,
        product_id: int,
        product_name: str | None,
        unit_price: Decimal,
        discount: Decimal,
        picture_url: str | None,
        units: int = 1,
    ) -> None:
        if units <= 0:
            raise OrderingDomainException("Invalid number of units")
        if (unit_price * units) < discount:
            raise OrderingDomainException("The total of order item is lower than applied discount")
        super().__init__(
            ProductId=product_id,
            ProductName=product_name,
            UnitPrice=unit_price,
            Discount=discount,
            Units=units,
            PictureUrl=picture_url,
        )

    def get_current_discount(self) -> Decimal:
        return self.Discount

    def get_units(self) -> int:
        return self.Units

    def get_unit_price(self) -> Decimal:
        return self.UnitPrice

    def get_order_item_product_name(self) -> str:
        return self.ProductName

    def get_picture_uri(self) -> str | None:
        return self.PictureUrl

    def set_new_discount(self, discount: Decimal) -> None:
        if discount < 0:
            raise OrderingDomainException("Discount is not valid")
        self.Discount = discount

    def add_units(self, units: int) -> None:
        if units < 0:
            raise OrderingDomainException("Invalid units")
        self.Units += units


class Order(Base, DomainEntity):
    __tablename__ = "orders"
    __table_args__ = {"schema": DEFAULT_SCHEMA}

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    BuyerId: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(f"{DEFAULT_SCHEMA}.buyers.Id"), nullable=True
    )
    OrderDate: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    OrderStatusId: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DEFAULT_SCHEMA}.orderstatus.Id"), nullable=False
    )
    # No FK to paymentmethods since migration 20190808132242_Change_Relation_Of_Orders.
    PaymentMethodId: Mapped[int | None] = mapped_column(Integer, nullable=True)
    Description: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    Address_City: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    Address_Country: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    Address_State: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    Address_Street: Mapped[str | None] = mapped_column(Unicode, nullable=True)
    Address_ZipCode: Mapped[str | None] = mapped_column(Unicode, nullable=True)

    order_items: Mapped[list[OrderItem]] = relationship(
        OrderItem, lazy="selectin", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._is_draft = False

    @classmethod
    def new_draft(cls) -> Order:
        order = cls()
        order._is_draft = True
        return order

    @classmethod
    def create(
        cls,
        user_id: str,
        user_name: str | None,
        address: Address,
        card_type_id: int,
        card_number: str | None,
        card_security_number: str | None,
        card_holder_name: str | None,
        card_expiration: datetime,
        buyer_id: int | None = None,
        payment_method_id: int | None = None,
    ) -> Order:
        order = cls(
            BuyerId=buyer_id,
            PaymentMethodId=payment_method_id,
            OrderStatusId=OrderStatus.Submitted[0],
            OrderDate=datetime.utcnow(),
            Address_Street=address.street,
            Address_City=address.city,
            Address_State=address.state,
            Address_Country=address.country,
            Address_ZipCode=address.zip_code,
        )
        order.add_domain_event(
            OrderStartedDomainEvent(
                order,
                user_id,
                user_name,
                card_type_id,
                card_number,
                card_security_number,
                card_holder_name,
                card_expiration,
            )
        )
        return order

    @property
    def status_name(self) -> str:
        return OrderStatus.name_of(self.OrderStatusId)

    def add_order_item(
        self,
        product_id: int,
        product_name: str | None,
        unit_price: Decimal,
        discount: Decimal,
        picture_url: str | None,
        units: int = 1,
    ) -> None:
        existing = next((o for o in self.order_items if o.ProductId == product_id), None)
        if existing is not None:
            if discount > existing.get_current_discount():
                existing.set_new_discount(discount)
            existing.add_units(units)
        else:
            self.order_items.append(
                OrderItem(product_id, product_name, unit_price, discount, picture_url, units)
            )

    def set_payment_id(self, payment_method_id: int) -> None:
        self.PaymentMethodId = payment_method_id

    def set_buyer_id(self, buyer_id: int) -> None:
        self.BuyerId = buyer_id

    def set_awaiting_validation_status(self) -> None:
        if self.OrderStatusId == OrderStatus.Submitted[0]:
            self.add_domain_event(
                OrderStatusChangedToAwaitingValidationDomainEvent(self.Id, list(self.order_items))
            )
            self.OrderStatusId = OrderStatus.AwaitingValidation[0]

    def set_stock_confirmed_status(self) -> None:
        if self.OrderStatusId == OrderStatus.AwaitingValidation[0]:
            self.add_domain_event(OrderStatusChangedToStockConfirmedDomainEvent(self.Id))
            self.OrderStatusId = OrderStatus.StockConfirmed[0]
            self.Description = "All the items were confirmed with available stock."

    def set_paid_status(self) -> None:
        if self.OrderStatusId == OrderStatus.StockConfirmed[0]:
            self.add_domain_event(OrderStatusChangedToPaidDomainEvent(self.Id, list(self.order_items)))
            self.OrderStatusId = OrderStatus.Paid[0]
            self.Description = (
                'The payment was performed at a simulated "American Bank checking bank '
                'account ending on XX35071"'
            )

    def set_shipped_status(self) -> None:
        if self.OrderStatusId != OrderStatus.Paid[0]:
            self._status_change_exception(OrderStatus.Shipped)
        self.OrderStatusId = OrderStatus.Shipped[0]
        self.Description = "The order was shipped."
        self.add_domain_event(OrderShippedDomainEvent(self))

    def set_cancelled_status(self) -> None:
        if self.OrderStatusId in (OrderStatus.Paid[0], OrderStatus.Shipped[0]):
            self._status_change_exception(OrderStatus.Cancelled)
        self.OrderStatusId = OrderStatus.Cancelled[0]
        self.Description = "The order was cancelled."
        self.add_domain_event(OrderCancelledDomainEvent(self))

    def set_cancelled_status_when_stock_is_rejected(
        self, order_stock_rejected_items: list[int]
    ) -> None:
        if self.OrderStatusId == OrderStatus.AwaitingValidation[0]:
            self.OrderStatusId = OrderStatus.Cancelled[0]
            rejected_names = [
                item.get_order_item_product_name()
                for item in self.order_items
                if item.ProductId in order_stock_rejected_items
            ]
            description = ", ".join(rejected_names)
            self.Description = f"The product items don't have stock: ({description})."

    def _status_change_exception(self, status_to_change: tuple[int, str]) -> None:
        raise OrderingDomainException(
            f"Is not possible to change the order status from {self.status_name} "
            f"to {status_to_change[1]}."
        )

    def get_total(self) -> Decimal:
        return sum(
            (item.get_units() * item.get_unit_price() for item in self.order_items), Decimal(0)
        )


@dataclass
class Address:
    """Port of the ``Address`` value object (owned entity columns ``Address_*``)."""

    street: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    zip_code: str | None = None


@dataclass
class HiLoGenerator:
    """EF Core ``HiLoValueGenerator`` semantics: each ``NEXT VALUE FOR`` call
    reserves the id block ``[value, value + increment - 1]``."""

    sequence: Sequence
    block_size: int = HILO_BLOCK_SIZE
    _next: int = 0
    _max: int = -1
    _sqlite_low: int = 1
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def next_id(self, session: AsyncSession) -> int:
        async with self._lock:
            if self._next > self._max:
                low = await self._next_block_low(session)
                self._next = int(low)
                self._max = self._next + self.block_size - 1
            value = self._next
            self._next += 1
            return value

    async def _next_block_low(self, session: AsyncSession) -> int:
        bind = session.get_bind()
        if bind.dialect.name == "sqlite":
            # SQLite (tests only) has no sequences; emulate the block reservation.
            low = self._sqlite_low
            self._sqlite_low += self.block_size
            return low
        return (await session.execute(select(self.sequence.next_value()))).scalar_one()


order_hilo = HiLoGenerator(ORDER_HILO)
buyer_hilo = HiLoGenerator(BUYER_HILO)
payment_hilo = HiLoGenerator(PAYMENT_HILO)
order_item_hilo = HiLoGenerator(ORDER_ITEM_HILO)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
