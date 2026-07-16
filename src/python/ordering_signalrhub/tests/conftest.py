import base64
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "signalrhub-test-key"


def contracts_events_dir() -> Path:
    override = os.environ.get("CONTRACTS_EVENTS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "contracts" / "events"


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
                    {
                        "kty": "RSA",
                        "kid": KID,
                        "use": "sig",
                        "alg": "RS256",
                        "n": _b64(numbers.n),
                        "e": _b64(numbers.e),
                    }
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

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def idp():
    server = HTTPServer(("127.0.0.1", 0), _IdpHandler)
    issuer = f"http://127.0.0.1:{server.server_address[1]}"
    _IdpHandler.issuer = issuer
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield issuer
    server.shutdown()


def make_token(
    issuer: str,
    audience: str = "orders.signalrhub",
    user_name: str | None = "alice@eshop",
    exp_offset: int = 3600,
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": str(uuid.uuid4()),
        "exp": now + exp_offset,
        "nbf": now - 10,
        "iat": now,
    }
    if user_name is not None:
        claims["unique_name"] = user_name
        claims["preferred_username"] = user_name
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})
