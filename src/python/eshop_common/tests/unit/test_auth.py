import base64
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Annotated

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from eshop_common.auth import KNOWN_AUDIENCES, JwtBearer, OidcJwtValidator

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "test-key-1"


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class _IdpHandler(BaseHTTPRequestHandler):
    issuer = ""

    def do_GET(self):
        numbers = KEY.public_key().public_numbers()
        if self.path == "/.well-known/openid-configuration":
            body = {"issuer": self.issuer, "jwks_uri": f"{self.issuer}/jwks"}
        elif self.path == "/jwks":
            body = {
                "keys": [
                    {"kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256",
                     "n": _b64(numbers.n), "e": _b64(numbers.e)}
                ]
            }
        else:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture(scope="module")
def idp():
    server = HTTPServer(("127.0.0.1", 0), _IdpHandler)
    issuer = f"http://127.0.0.1:{server.server_address[1]}"
    _IdpHandler.issuer = issuer
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield issuer
    server.shutdown()


def make_token(issuer: str, audience: str | list[str], exp_offset: int = 3600, nbf_offset: int = -10) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": str(uuid.uuid4()),
        "exp": now + exp_offset,
        "nbf": now + nbf_offset,
        "iat": now,
    }
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})


async def test_valid_token_accepted(idp):
    validator = OidcJwtValidator(authority=idp, audience="basket")
    claims = await validator.validate(make_token(idp, "basket"))
    assert claims["aud"] == "basket"


async def test_wrong_audience_rejected(idp):
    validator = OidcJwtValidator(authority=idp, audience="orders")
    with pytest.raises(jwt.InvalidAudienceError):
        await validator.validate(make_token(idp, "basket"))


async def test_multi_audience_token_accepts_exact_service_audience(idp):
    validator = OidcJwtValidator(authority=idp, audience="orders")
    claims = await validator.validate(make_token(idp, ["orders", "basket"]))
    assert "orders" in claims["aud"]


async def test_expired_token_rejected(idp):
    validator = OidcJwtValidator(authority=idp, audience="basket")
    with pytest.raises(jwt.ExpiredSignatureError):
        await validator.validate(make_token(idp, "basket", exp_offset=-10))


async def test_not_before_in_future_rejected(idp):
    validator = OidcJwtValidator(authority=idp, audience="basket")
    with pytest.raises(jwt.ImmatureSignatureError):
        await validator.validate(make_token(idp, "basket", nbf_offset=3600))


async def test_wrong_issuer_rejected(idp):
    validator = OidcJwtValidator(authority=idp, audience="basket")
    await validator.validate(make_token(idp, "basket"))  # prime discovery
    with pytest.raises(jwt.InvalidIssuerError):
        await validator.validate(make_token("http://evil.example", "basket"))


async def test_tampered_signature_rejected(idp):
    validator = OidcJwtValidator(authority=idp, audience="basket")
    token = make_token(idp, "basket")
    with pytest.raises(jwt.PyJWTError):
        await validator.validate(token[:-4] + "AAAA")


def test_known_audiences_preserved():
    assert KNOWN_AUDIENCES == {
        "basket",
        "orders",
        "marketing",
        "locations",
        "orders.signalrhub",
        "webhooks",
        "mobileshoppingagg",
        "webshoppingagg",
    }


def test_fastapi_dependency_enforces_bearer(idp):
    app = FastAPI()
    bearer = JwtBearer(OidcJwtValidator(authority=idp, audience="basket"))

    @app.get("/protected")
    async def protected(claims: Annotated[dict, Depends(bearer)]):
        return {"sub": claims["sub"]}

    client = TestClient(app)
    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers={"Authorization": "Basic abc"}).status_code == 401
    ok = client.get("/protected", headers={"Authorization": f"Bearer {make_token(idp, 'basket')}"})
    assert ok.status_code == 200
    bad = client.get("/protected", headers={"Authorization": f"Bearer {make_token(idp, 'orders')}"})
    assert bad.status_code == 401
    assert bad.headers["WWW-Authenticate"] == "Bearer"
