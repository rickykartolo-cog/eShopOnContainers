"""Python replacement for Ordering.SignalrHub.

Realtime order-status notifications over Socket.IO at ``/hub/notificationhub``,
consuming the six ``OrderStatusChangedTo*IntegrationEvent`` messages and
emitting ``UpdatedOrderState`` to the authenticated buyer's room.
"""
