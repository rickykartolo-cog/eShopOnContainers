"""Shared fixtures: in-memory event bus and settings built from plain dicts
(the compose environment-variable interface)."""

from __future__ import annotations

import pytest
from payment_test_helpers import InMemoryEventBus, make_settings

from payment_api.settings import PaymentSettings


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def settings() -> PaymentSettings:
    return make_settings()
