"""Fernet encryption for the key config file.

The config blob is a base64 JSON envelope::

    {"salt": "<base64>", "token": "<base64 Fernet token>"}

The Fernet key is derived from the user's master password with
PBKDF2-HMAC-SHA256 (600_000 iterations). Pure `cryptography` library only.
"""

import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ITERATIONS = 600_000
_SALT_BYTES = 16


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_config(data: dict, password: str) -> bytes:
    """Encrypt a config dict with a master password. Returns the envelope bytes."""
    if not isinstance(data, dict):
        raise TypeError("data must be a dict")
    if not password:
        raise ValueError("password must not be empty")
    salt = os.urandom(_SALT_BYTES)
    fernet = Fernet(_derive_key(password, salt))
    token = fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    envelope = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "token": base64.b64encode(token).decode("ascii"),
    }
    return json.dumps(envelope).encode("utf-8")


def decrypt_config(blob: bytes, password: str) -> dict:
    """Decrypt an envelope produced by :func:`encrypt_config`.

    Raises ``ValueError`` when the password is wrong or the blob is corrupt.
    """
    if not password:
        raise ValueError("password must not be empty")
    try:
        envelope = json.loads(blob.decode("utf-8"))
        salt = base64.b64decode(envelope["salt"])
        token = base64.b64decode(envelope["token"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"corrupt config blob: {exc}") from exc
    fernet = Fernet(_derive_key(password, salt))
    try:
        raw = fernet.decrypt(token)
    except InvalidToken as exc:
        raise ValueError("wrong password or corrupt config blob") from exc
    return json.loads(raw.decode("utf-8"))
