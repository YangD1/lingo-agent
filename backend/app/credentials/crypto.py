"""Envelope-free AES-256-GCM encryption for tenant credentials (ADR 0004 §3).

Ciphertext format:  v1:<key_id>:<nonce_b64>:<ciphertext_b64>

- A fresh random 96-bit nonce per encryption (never reuse a nonce with the same key).
- The AAD binds a ciphertext to the row that owns it: copying one tenant's encrypted
  key into another tenant's row makes decryption fail instead of leaking the key.
- Master keys come from CREDENTIALS_ENCRYPTION_KEYS ("id:base64key,id:base64key").
  The first key encrypts; every listed key can decrypt, which is what makes rotation
  possible (add a new key in front, re-encrypt, then drop the old one).

CLI: `python -m app.credentials.crypto gen-key`
"""

import base64
import binascii
import os
import re
import secrets
import sys
import uuid
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.settings import get_settings

VERSION = "v1"
KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12
_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


class KeyringError(ValueError):
    """CREDENTIALS_ENCRYPTION_KEYS is missing or malformed."""


class DecryptError(Exception):
    """Ciphertext is malformed, tampered with, bound to another row, or its key is gone."""


@dataclass(frozen=True)
class Keyring:
    keys: dict[str, bytes]
    primary_id: str

    def encrypt(self, plaintext: str, aad: bytes) -> str:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self.keys[self.primary_id]).encrypt(nonce, plaintext.encode(), aad)
        return ":".join((VERSION, self.primary_id, _b64(nonce), _b64(ciphertext)))

    def decrypt(self, token: str, aad: bytes) -> str:
        try:
            version, key_id, nonce_b64, ciphertext_b64 = token.split(":")
        except ValueError as exc:
            raise DecryptError("malformed ciphertext") from exc
        if version != VERSION:
            raise DecryptError(f"unsupported ciphertext version {version!r}")
        key = self.keys.get(key_id)
        if key is None:
            raise DecryptError(f"unknown key id {key_id!r} (was it removed from the keyring?)")
        try:
            plaintext = AESGCM(key).decrypt(_unb64(nonce_b64), _unb64(ciphertext_b64), aad)
        except (InvalidTag, binascii.Error, ValueError) as exc:
            raise DecryptError("ciphertext failed authentication") from exc
        return plaintext.decode()

    def needs_rotation(self, token: str) -> bool:
        """True if `token` was encrypted with a key other than the current primary."""
        parts = token.split(":")
        return len(parts) != 4 or parts[1] != self.primary_id


def parse_keyring(raw: str) -> Keyring:
    entries = [entry.strip() for entry in raw.split(",") if entry.strip()]
    if not entries:
        raise KeyringError(
            "CREDENTIALS_ENCRYPTION_KEYS is empty; generate one with "
            "`python -m app.credentials.crypto gen-key` (or `make gen-key`)"
        )
    keys: dict[str, bytes] = {}
    for entry in entries:
        key_id, sep, key_b64 = entry.partition(":")
        if not sep or not _KEY_ID.match(key_id):
            raise KeyringError(f"bad keyring entry for id {key_id!r}: expected 'id:base64key'")
        if key_id in keys:
            raise KeyringError(f"duplicate key id {key_id!r}")
        try:
            key = _unb64(key_b64)
        except (binascii.Error, ValueError) as exc:
            raise KeyringError(f"key {key_id!r} is not valid base64") from exc
        if len(key) != KEY_BYTES:
            raise KeyringError(f"key {key_id!r} must be {KEY_BYTES} bytes, got {len(key)}")
        keys[key_id] = key
    return Keyring(keys=keys, primary_id=entries[0].partition(":")[0])


@lru_cache
def get_keyring() -> Keyring:
    return parse_keyring(get_settings().credentials_encryption_keys)


def connection_aad(tenant_id: uuid.UUID, connection_id: uuid.UUID) -> bytes:
    return f"lingo:provider_connection:{tenant_id}:{connection_id}".encode()


def generate_key_entry(key_id: str | None = None) -> str:
    key_id = key_id or f"k{secrets.token_hex(3)}"
    if not _KEY_ID.match(key_id):
        raise KeyringError(f"invalid key id {key_id!r}")
    return f"{key_id}:{_b64(os.urandom(KEY_BYTES))}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode())


if __name__ == "__main__":
    if sys.argv[1:] == ["gen-key"]:
        print(generate_key_entry())
    else:
        print("usage: python -m app.credentials.crypto gen-key", file=sys.stderr)
        sys.exit(2)
