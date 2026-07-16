"""Dependency health-check adapters against the real test topology."""

import json

import pytest

from eshop_common.health.checks import (
    HttpUrlHealthCheck,
    MongoHealthCheck,
    RabbitMQHealthCheck,
    RedisHealthCheck,
    SqlServerHealthCheck,
)
from eshop_common.health.core import HealthCheckRegistry, HealthStatus, write_health_check_ui_response
from eshop_common.testing import rabbitmq_host

pytestmark = pytest.mark.integration


async def test_sqlserver_check_healthy(sql_engine):
    result = await SqlServerHealthCheck(sql_engine, name="CatalogDB-check").check()
    assert result.status is HealthStatus.Healthy


async def test_redis_check_healthy(redis_client):
    result = await RedisHealthCheck(redis_client).check()
    assert result.status is HealthStatus.Healthy


async def test_mongo_check_healthy(mongo_client):
    result = await MongoHealthCheck(mongo_client).check()
    assert result.status is HealthStatus.Healthy


async def test_rabbitmq_check_healthy():
    result = await RabbitMQHealthCheck(host=rabbitmq_host()).check()
    assert result.status is HealthStatus.Healthy


async def test_rabbitmq_check_unhealthy_when_unreachable():
    result = await RabbitMQHealthCheck(host="nonexistent-host-xyz").check()
    assert result.status is HealthStatus.Unhealthy


async def test_http_url_check_unhealthy_when_unreachable():
    result = await HttpUrlHealthCheck("http://nonexistent-host-xyz/hc", name="identityapi-check").check()
    assert result.status is HealthStatus.Unhealthy


async def test_full_hc_report_with_real_dependencies(sql_engine, redis_client, mongo_client):
    registry = HealthCheckRegistry()
    registry.add(SqlServerHealthCheck(sql_engine, name="CatalogDB-check"))
    registry.add(RedisHealthCheck(redis_client, name="redis-check"))
    registry.add(MongoHealthCheck(mongo_client, name="mongodb-check"))
    registry.add(RabbitMQHealthCheck(host=rabbitmq_host(), name="rabbitmqbus-check"))
    response = write_health_check_ui_response(await registry.run())
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["status"] == "Healthy"
    assert set(body["entries"]) == {
        "self",
        "CatalogDB-check",
        "redis-check",
        "mongodb-check",
        "rabbitmqbus-check",
    }
