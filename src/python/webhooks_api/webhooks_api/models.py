"""SQLAlchemy mapping of the frozen Webhooks SQL Server schema
(`contracts/db/webhooks.sqlschema.txt`): dbo.Subscriptions with an identity
``Id`` and nullable nvarchar(max) columns, exactly as the EF Core model."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Integer, Unicode, UnicodeText
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class WebhookType(enum.IntEnum):
    CatalogItemPriceChange = 1
    OrderShipped = 2
    OrderPaid = 3

    @classmethod
    def try_parse(cls, value: str | None) -> WebhookType | None:
        """Port of ``Enum.TryParse<WebhookType>(value, ignoreCase: true)``:
        accepts member names case-insensitively and numeric strings."""
        if value is None:
            return None
        text = value.strip()
        for member in cls:
            if member.name.lower() == text.lower():
                return member
        try:
            return cls(int(text))
        except (ValueError, KeyError):
            return None


class Base(DeclarativeBase):
    type_annotation_map = {str: UnicodeText()}


class WebhookSubscription(Base):
    __tablename__ = "Subscriptions"

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    Type: Mapped[int] = mapped_column(Integer, nullable=False)
    Date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    DestUrl: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    Token: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    UserId: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)


# Only referenced for DDL in the SQL Server bootstrap; declared here to keep the
# frozen dump's nvarchar lengths for __EFMigrationsHistory documented in code.
class EFMigrationsHistory(Base):
    __tablename__ = "__EFMigrationsHistory"

    MigrationId: Mapped[str] = mapped_column(Unicode(150), primary_key=True)
    ProductVersion: Mapped[str] = mapped_column(Unicode(32), nullable=False)
