"""SQLAlchemy models for the frozen Marketing SQL Server write model
(`contracts/db/marketing.sqlschema.txt`): tables ``Campaign``/``Rule`` with the
EF Core TPH discriminator ``RuleTypeId`` and HiLo sequences ``campaign_hilo``/
``rule_hilo`` (increment 10, matching EF Core ``UseSqlServerIdentityColumn``-free
``ForSqlServerUseSequenceHiLo``)."""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Sequence, UnicodeText, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

HILO_BLOCK_SIZE = 10

CAMPAIGN_HILO = Sequence("campaign_hilo", start=1, increment=HILO_BLOCK_SIZE)
RULE_HILO = Sequence("rule_hilo", start=1, increment=HILO_BLOCK_SIZE)

USER_PROFILE_RULE_TYPE = 1
PURCHASE_HISTORY_RULE_TYPE = 2
USER_LOCATION_RULE_TYPE = 3


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "Campaign"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    Name: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    Description: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    From: Mapped[datetime] = mapped_column("From", DateTime, nullable=False)
    To: Mapped[datetime] = mapped_column("To", DateTime, nullable=False)
    PictureUri: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    DetailsUri: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    PictureName: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)

    Rules: Mapped[list[Rule]] = relationship(
        "Rule", back_populates="Campaign_", cascade="all, delete-orphan", lazy="noload"
    )


class Rule(Base):
    """TPH base for ``UserProfileRule``/``PurchaseHistoryRule``/``UserLocationRule``,
    discriminated by ``RuleTypeId`` exactly as the EF Core model."""

    __tablename__ = "Rule"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    CampaignId: Mapped[int] = mapped_column(
        Integer, ForeignKey("Campaign.Id", ondelete="CASCADE"), nullable=False
    )
    Description: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    RuleTypeId: Mapped[int] = mapped_column(Integer, nullable=False)
    LocationId: Mapped[int | None] = mapped_column(Integer, nullable=True)

    Campaign_: Mapped[Campaign] = relationship(Campaign, back_populates="Rules", lazy="noload")

    __mapper_args__ = {"polymorphic_on": RuleTypeId}


class UserProfileRule(Rule):
    __mapper_args__ = {"polymorphic_identity": USER_PROFILE_RULE_TYPE}


class PurchaseHistoryRule(Rule):
    __mapper_args__ = {"polymorphic_identity": PURCHASE_HISTORY_RULE_TYPE}


class UserLocationRule(Rule):
    __mapper_args__ = {"polymorphic_identity": USER_LOCATION_RULE_TYPE}


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


campaign_hilo = HiLoGenerator(CAMPAIGN_HILO)
rule_hilo = HiLoGenerator(RULE_HILO)
