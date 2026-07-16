"""Unit tests for ASP.NET Identity hash parsing / Keycloak credential conversion.

These run offline (no Keycloak needed) and prove the migration handles the
ASP.NET Core Identity v3 PBKDF2 format used by the .NET Core 3.1 baseline,
the legacy v2 format, and forced-reset fallback for unknown formats.
"""
import base64
import hashlib
import json
import struct

import pytest

from aspnet_hash import (
    UnsupportedHashError,
    parse_aspnet_password_hash,
    to_keycloak_credential,
    verify_password,
)

PASSWORD = "Pass@word1"  # seed password used by ApplicationDbContextSeed
SALT = b"0123456789abcdef"  # 16 bytes


def make_v3_hash(password=PASSWORD, prf=1, iterations=10000, salt=SALT, dklen=32):
    hash_name = {0: "sha1", 1: "sha256", 2: "sha512"}[prf]
    subkey = hashlib.pbkdf2_hmac(hash_name, password.encode(), salt, iterations, dklen=dklen)
    raw = b"\x01" + struct.pack(">III", prf, iterations, len(salt)) + salt + subkey
    return base64.b64encode(raw).decode()


def make_v2_hash(password=PASSWORD, salt=SALT):
    subkey = hashlib.pbkdf2_hmac("sha1", password.encode(), salt, 1000, dklen=32)
    raw = b"\x00" + salt + subkey
    return base64.b64encode(raw).decode()


def test_parse_v3_sha256():
    parsed = parse_aspnet_password_hash(make_v3_hash())
    assert parsed["version"] == 3
    assert parsed["algorithm"] == "pbkdf2-sha256"
    assert parsed["iterations"] == 10000
    assert parsed["salt"] == SALT
    assert len(parsed["subkey"]) == 32


@pytest.mark.parametrize("prf,algorithm", [(0, "pbkdf2"), (1, "pbkdf2-sha256"), (2, "pbkdf2-sha512")])
def test_parse_v3_all_prfs(prf, algorithm):
    parsed = parse_aspnet_password_hash(make_v3_hash(prf=prf))
    assert parsed["algorithm"] == algorithm


def test_parse_v2():
    parsed = parse_aspnet_password_hash(make_v2_hash())
    assert parsed["version"] == 2
    assert parsed["algorithm"] == "pbkdf2"
    assert parsed["iterations"] == 1000


def test_verify_password_roundtrip():
    assert verify_password(make_v3_hash(), PASSWORD)
    assert not verify_password(make_v3_hash(), "wrong-password")
    assert verify_password(make_v2_hash(), PASSWORD)


def test_keycloak_credential_shape():
    cred = to_keycloak_credential(make_v3_hash())
    assert cred["type"] == "password"
    credential_data = json.loads(cred["credentialData"])
    secret_data = json.loads(cred["secretData"])
    assert credential_data["algorithm"] == "pbkdf2-sha256"
    assert credential_data["hashIterations"] == 10000
    assert base64.b64decode(secret_data["salt"]) == SALT
    assert len(base64.b64decode(secret_data["value"])) == 32


@pytest.mark.parametrize("bad", ["", "not-base64!!", base64.b64encode(b"\x09junk").decode()])
def test_unsupported_hashes_raise(bad):
    with pytest.raises(UnsupportedHashError):
        parse_aspnet_password_hash(bad)


def test_forced_reset_path():
    from import_users import to_keycloak_user

    user = {"Id": "not-a-guid", "UserName": "alice", "Email": "a@example.com", "PasswordHash": "garbage!!"}
    representation, reason = to_keycloak_user(user)
    assert reason is not None
    assert representation["requiredActions"] == ["UPDATE_PASSWORD"]
    assert "credentials" not in representation
