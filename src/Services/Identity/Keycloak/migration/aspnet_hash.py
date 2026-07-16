"""Conversion of ASP.NET Core Identity password hashes to Keycloak credentials.

ASP.NET Core Identity PasswordHasher formats (see
Microsoft.AspNetCore.Identity.PasswordHasher):

* Version 2 (marker byte 0x00): PBKDF2-HMAC-SHA1, 1000 iterations,
  128-bit salt, 256-bit subkey.
* Version 3 (marker byte 0x01, the .NET Core 3.1 default): PBKDF2 with a
  header of {prf: uint32, iterations: uint32, saltLength: uint32} in
  network byte order, followed by salt and subkey (256-bit subkey by
  default). PRF 0=HMAC-SHA1, 1=HMAC-SHA256, 2=HMAC-SHA512.

Keycloak stores PBKDF2 credentials natively (algorithms ``pbkdf2``,
``pbkdf2-sha256``, ``pbkdf2-sha512``), so both formats import without any
plaintext-password handling. Anything unparseable is flagged for a forced
secure reset (UPDATE_PASSWORD required action) instead.
"""
import base64
import hashlib
import hmac
import json
import struct

PRF_ALGORITHMS = {
    0: ("pbkdf2", "sha1"),
    1: ("pbkdf2-sha256", "sha256"),
    2: ("pbkdf2-sha512", "sha512"),
}


class UnsupportedHashError(Exception):
    """The password hash cannot be imported; force a secure reset."""


def parse_aspnet_password_hash(encoded: str) -> dict:
    """Parse a base64 ASP.NET Identity password hash into its components."""
    if not encoded:
        raise UnsupportedHashError("empty password hash")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise UnsupportedHashError(f"invalid base64: {exc}") from exc
    if not raw:
        raise UnsupportedHashError("empty decoded hash")

    marker = raw[0]
    if marker == 0x00:  # Identity v2
        if len(raw) != 1 + 16 + 32:
            raise UnsupportedHashError("malformed v2 hash length")
        return {
            "version": 2,
            "algorithm": "pbkdf2",
            "hash_name": "sha1",
            "iterations": 1000,
            "salt": raw[1:17],
            "subkey": raw[17:49],
        }
    if marker == 0x01:  # Identity v3
        if len(raw) < 13:
            raise UnsupportedHashError("malformed v3 header")
        prf, iterations, salt_len = struct.unpack(">III", raw[1:13])
        if prf not in PRF_ALGORITHMS:
            raise UnsupportedHashError(f"unknown PRF {prf}")
        if iterations < 1:
            raise UnsupportedHashError("invalid iteration count")
        salt = raw[13 : 13 + salt_len]
        subkey = raw[13 + salt_len :]
        if len(salt) != salt_len or not subkey:
            raise UnsupportedHashError("malformed v3 salt/subkey")
        algorithm, hash_name = PRF_ALGORITHMS[prf]
        return {
            "version": 3,
            "algorithm": algorithm,
            "hash_name": hash_name,
            "iterations": iterations,
            "salt": salt,
            "subkey": subkey,
        }
    raise UnsupportedHashError(f"unknown format marker 0x{marker:02x}")


def to_keycloak_credential(encoded: str) -> dict:
    """Convert an ASP.NET Identity hash to a Keycloak credential representation."""
    parsed = parse_aspnet_password_hash(encoded)
    return {
        "type": "password",
        "temporary": False,
        "credentialData": json.dumps(
            {
                "hashIterations": parsed["iterations"],
                "algorithm": parsed["algorithm"],
                "additionalParameters": {},
            }
        ),
        "secretData": json.dumps(
            {
                "value": base64.b64encode(parsed["subkey"]).decode("ascii"),
                "salt": base64.b64encode(parsed["salt"]).decode("ascii"),
                "additionalParameters": {},
            }
        ),
    }


def verify_password(encoded: str, password: str) -> bool:
    """Recompute PBKDF2 locally to validate an export before import (dry run)."""
    parsed = parse_aspnet_password_hash(encoded)
    derived = hashlib.pbkdf2_hmac(
        parsed["hash_name"],
        password.encode("utf-8"),
        parsed["salt"],
        parsed["iterations"],
        dklen=len(parsed["subkey"]),
    )
    return hmac.compare_digest(derived, parsed["subkey"])
