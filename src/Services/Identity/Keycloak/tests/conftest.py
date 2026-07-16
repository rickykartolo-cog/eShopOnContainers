import os
import sys

import pytest
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "migration"))
sys.path.insert(0, os.path.join(HERE, "..", "realm"))

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:5106").rstrip("/")
REALM = os.environ.get("KEYCLOAK_REALM", "eshop")


def keycloak_available():
    try:
        resp = requests.get(f"{KEYCLOAK_URL}/realms/{REALM}/.well-known/openid-configuration", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


requires_keycloak = pytest.mark.skipif(
    not keycloak_available(),
    reason=f"Keycloak with realm '{REALM}' not reachable at {KEYCLOAK_URL} "
    "(start it with: docker compose -f docker-compose.keycloak.yml up -d)",
)


@pytest.fixture(scope="session")
def keycloak_url():
    return KEYCLOAK_URL


@pytest.fixture(scope="session")
def realm():
    return REALM


@pytest.fixture(scope="session")
def admin():
    from keycloak_admin import KeycloakAdmin

    return KeycloakAdmin(base_url=KEYCLOAK_URL, realm=REALM)
