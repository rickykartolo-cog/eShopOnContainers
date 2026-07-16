"""A small typed in-repo dispatcher standing in for MediatR.

``Mediator.send`` runs the ported ``ValidatorBehavior`` (command validation) and
then the registered command handler. ``Mediator.publish`` dispatches domain
events sequentially to their handlers, matching ``MediatorExtension
.DispatchDomainEventsAsync`` ordering semantics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from ordering_api.commands import CommandValidationError


class SupportsValidation(Protocol):
    def validate_command(self) -> list[str]: ...


class Mediator:
    def __init__(self) -> None:
        self._command_handlers: dict[type, Callable[..., Awaitable[object]]] = {}
        self._event_handlers: dict[type, list[Callable[..., Awaitable[None]]]] = {}

    def register_command(
        self, command_type: type, handler: Callable[..., Awaitable[object]]
    ) -> None:
        self._command_handlers[command_type] = handler

    def register_domain_event(
        self, event_type: type, handler: Callable[..., Awaitable[None]]
    ) -> None:
        self._event_handlers.setdefault(event_type, []).append(handler)

    async def send(self, command: SupportsValidation, ctx: object) -> object:
        failures = command.validate_command()
        if failures:
            raise CommandValidationError(type(command).__name__, failures)
        handler = self._command_handlers[type(command)]
        return await handler(command, ctx)

    async def publish(self, domain_event: object, ctx: object) -> None:
        for handler in self._event_handlers.get(type(domain_event), []):
            await handler(domain_event, ctx)
