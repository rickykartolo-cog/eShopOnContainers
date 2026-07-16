"""Live tests against a running Keycloak with the imported eshop realm.

Skipped automatically when Keycloak is not reachable. Run with:

    docker compose -f docker-compose.keycloak.yml up -d
    KEYCLOAK_ADMIN_PASSWORD=... ESHOP_KEYCLOAK_MVCTEST_CLIENT_SECRET=... \
        python3 -m pytest Services/Identity/Keycloak/tests -v

Covers:
* realm import completeness/reproducibility against the live server;
* token issuance + JWKS validation for every IS4 audience;
* migration: a user imported with an ASP.NET Identity v3 hash can log in
  with the original password and receives IS4-equivalent claims.
"""
import base64
import hashlib
import json
import os
import struct
import uuid

import jwt as pyjwt
import pytest
import requests

from conftest import requires_keycloak
from import_users import to_keycloak_user

pytestmark = [
    requires_keycloak,
    pytest.mark.skipif(
        "KEYCLOAK_ADMIN_PASSWORD" not in os.environ,
        reason="KEYCLOAK_ADMIN_PASSWORD not set",
    ),
]

EXPECTED_AUDIENCES = {
    "orders", "basket", "marketing", "locations",
    "mobileshoppingagg", "webshoppingagg", "orders.signalrhub", "webhooks",
}
EXPECTED_CLIENTS = {
    "js", "xamarin", "mvc", "mvctest", "webhooksclient",
    "locationsswaggerui", "marketingswaggerui", "basketswaggerui",
    "orderingswaggerui", "mobileshoppingaggswaggerui",
    "webshoppingaggswaggerui", "webhooksswaggerui",
}
MVCTEST_SCOPES = "openid profile orders basket locations marketing webshoppingagg webhooks"


def test_realm_imported(admin):
    realm = admin.get_realm()
    assert realm["realm"] == "eshop"
    assert realm["enabled"] is True
    assert realm["accessTokenLifespan"] == 3600


def test_all_clients_imported(admin):
    client_ids = {c["clientId"] for c in admin.get_clients()}
    assert EXPECTED_CLIENTS <= client_ids


def test_all_audience_scopes_imported_exactly_once(admin):
    names = [s["name"] for s in admin.get_client_scopes()]
    for audience in EXPECTED_AUDIENCES | {"catalog", "eshop-profile"}:
        assert names.count(audience) == 1, f"scope {audience} imported {names.count(audience)} times"


def test_js_client_pkce_configuration(admin):
    js = next(c for c in admin.get_clients() if c["clientId"] == "js")
    assert js["publicClient"] is True
    assert js["standardFlowEnabled"] is True
    assert js["implicitFlowEnabled"] is False
    assert js["attributes"]["pkce.code.challenge.method"] == "S256"


def make_aspnet_v3_hash(password):
    salt = os.urandom(16)
    subkey = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 10000, dklen=32)
    return base64.b64encode(b"\x01" + struct.pack(">III", 1, 10000, 16) + salt + subkey).decode()


SAMPLE_PASSWORD = "Pass@word1"
SAMPLE_USER = {
    "Id": str(uuid.uuid4()),
    "UserName": "demouser@microsoft.com",
    "Email": "demouser@microsoft.com",
    "EmailConfirmed": True,
    "PhoneNumber": "1234567890",
    "CardNumber": "4012888888881881",
    "SecurityNumber": "535",
    "Expiration": "12/30",
    "CardHolderName": "DemoUser",
    "CardType": 1,
    "Street": "15703 NE 61st Ct",
    "City": "Redmond",
    "State": "WA",
    "Country": "U.S.",
    "ZipCode": "98052",
    "Name": "DemoUser",
    "LastName": "Alias",
}

# Claims ProfileService.GetClaimsFromUser issues for SAMPLE_USER.
EXPECTED_IS4_EQUIVALENT_CLAIMS = {
    "sub": SAMPLE_USER["Id"].lower(),
    "preferred_username": SAMPLE_USER["UserName"],
    "unique_name": SAMPLE_USER["UserName"],
    "name": SAMPLE_USER["Name"],
    "last_name": SAMPLE_USER["LastName"],
    "card_number": SAMPLE_USER["CardNumber"],
    "card_holder": SAMPLE_USER["CardHolderName"],
    "card_security_number": SAMPLE_USER["SecurityNumber"],
    "card_expiration": SAMPLE_USER["Expiration"],
    "address_city": SAMPLE_USER["City"],
    "address_country": SAMPLE_USER["Country"],
    "address_state": SAMPLE_USER["State"],
    "address_street": SAMPLE_USER["Street"],
    "address_zip_code": SAMPLE_USER["ZipCode"],
    "email": SAMPLE_USER["Email"],
}


@pytest.fixture(scope="module")
def migrated_user(admin):
    user = dict(SAMPLE_USER)
    user["PasswordHash"] = make_aspnet_v3_hash(SAMPLE_PASSWORD)
    representation, forced_reset = to_keycloak_user(user)
    assert forced_reset is None
    existing = admin.find_user(user["UserName"])
    if existing:
        admin.delete_user(existing["id"])
    admin.partial_import_users([representation])
    yield user
    created = admin.find_user(user["UserName"])
    if created:
        admin.delete_user(created["id"])


def password_grant(keycloak_url, realm, username, password, scope):
    secret = os.environ.get("ESHOP_KEYCLOAK_MVCTEST_CLIENT_SECRET")
    if not secret:
        pytest.skip("ESHOP_KEYCLOAK_MVCTEST_CLIENT_SECRET not set")
    resp = requests.post(
        f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "mvctest",
            "client_secret": secret,
            "username": username,
            "password": password,
            "scope": scope,
        },
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def decode_and_validate(keycloak_url, realm, access_token, audience):
    oidc = requests.get(
        f"{keycloak_url}/realms/{realm}/.well-known/openid-configuration", timeout=10
    ).json()
    jwks = requests.get(oidc["jwks_uri"], timeout=10).json()
    kid = pyjwt.get_unverified_header(access_token)["kid"]
    jwk = next(k for k in jwks["keys"] if k["kid"] == kid and k.get("use") == "sig")
    signing_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
    return pyjwt.decode(
        access_token,
        signing_key,
        algorithms=["RS256"],
        audience=audience,
        issuer=oidc["issuer"],
        options={"require": ["exp", "iat", "iss", "aud"]},
    )


def test_migrated_password_hash_allows_login(keycloak_url, realm, migrated_user):
    """The imported ASP.NET Identity v3 PBKDF2 hash must validate in Keycloak."""
    tokens = password_grant(keycloak_url, realm, migrated_user["UserName"], SAMPLE_PASSWORD, "openid")
    assert "access_token" in tokens


def test_wrong_password_rejected(keycloak_url, realm, migrated_user):
    secret = os.environ.get("ESHOP_KEYCLOAK_MVCTEST_CLIENT_SECRET")
    if not secret:
        pytest.skip("ESHOP_KEYCLOAK_MVCTEST_CLIENT_SECRET not set")
    resp = requests.post(
        f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "mvctest",
            "client_secret": secret,
            "username": migrated_user["UserName"],
            "password": "wrong-password",
            "scope": "openid",
        },
        timeout=30,
    )
    assert resp.status_code == 401


@pytest.mark.parametrize("scope,audience", [
    ("orders", "orders"),
    ("basket", "basket"),
    ("marketing", "marketing"),
    ("locations", "locations"),
    ("webshoppingagg", "webshoppingagg"),
    ("webhooks", "webhooks"),
])
def test_tokens_validate_for_each_audience(keycloak_url, realm, migrated_user, scope, audience):
    tokens = password_grant(
        keycloak_url, realm, migrated_user["UserName"], SAMPLE_PASSWORD, f"openid {scope}"
    )
    claims = decode_and_validate(keycloak_url, realm, tokens["access_token"], audience)
    aud = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    assert audience in aud
    assert scope in claims["scope"].split()


def test_migrated_user_claims_match_identityserver(keycloak_url, realm, migrated_user):
    """Old-vs-new claims comparison for a sample user (master prompt §4.5)."""
    tokens = password_grant(
        keycloak_url, realm, migrated_user["UserName"], SAMPLE_PASSWORD, MVCTEST_SCOPES
    )
    claims = decode_and_validate(keycloak_url, realm, tokens["access_token"], "orders")
    mismatches = {
        claim: {"expected": expected, "actual": claims.get(claim)}
        for claim, expected in EXPECTED_IS4_EQUIVALENT_CLAIMS.items()
        if claims.get(claim) != expected
    }
    assert not mismatches, json.dumps(mismatches, indent=2)
