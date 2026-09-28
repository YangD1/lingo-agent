import uuid

import pytest

from app.credentials.crypto import (
    DecryptError,
    KeyringError,
    connection_aad,
    generate_key_entry,
    parse_keyring,
)

OLD = generate_key_entry("old")
NEW = generate_key_entry("new")
TENANT, CONN = uuid.uuid4(), uuid.uuid4()
AAD = connection_aad(TENANT, CONN)
SECRET = "sk-live-0123456789abcdef"


def test_roundtrip() -> None:
    ring = parse_keyring(NEW)
    token = ring.encrypt(SECRET, AAD)
    assert ring.decrypt(token, AAD) == SECRET


def test_ciphertext_hides_plaintext_and_is_randomized() -> None:
    ring = parse_keyring(NEW)
    first, second = ring.encrypt(SECRET, AAD), ring.encrypt(SECRET, AAD)
    assert SECRET not in first
    assert first != second  # fresh nonce every time
    assert first.startswith("v1:new:")


def test_ciphertext_is_bound_to_its_row() -> None:
    """Copying an encrypted key to another tenant's row must not decrypt."""
    ring = parse_keyring(NEW)
    token = ring.encrypt(SECRET, AAD)
    with pytest.raises(DecryptError):
        ring.decrypt(token, connection_aad(uuid.uuid4(), CONN))
    with pytest.raises(DecryptError):
        ring.decrypt(token, connection_aad(TENANT, uuid.uuid4()))


def test_tampering_is_detected() -> None:
    ring = parse_keyring(NEW)
    version, key_id, nonce, ciphertext = ring.encrypt(SECRET, AAD).split(":")
    flipped = ("B" if ciphertext[0] == "A" else "A") + ciphertext[1:]
    with pytest.raises(DecryptError):
        ring.decrypt(":".join((version, key_id, nonce, flipped)), AAD)


@pytest.mark.parametrize("token", ["garbage", "v2:new:a:b", "v1:new:%%%:%%%"])
def test_malformed_ciphertext(token: str) -> None:
    with pytest.raises(DecryptError):
        parse_keyring(NEW).decrypt(token, AAD)


def test_rotation() -> None:
    old_ring = parse_keyring(OLD)
    token = old_ring.encrypt(SECRET, AAD)

    rotating = parse_keyring(f"{NEW},{OLD}")  # new key first: encrypts; old still decrypts
    assert rotating.primary_id == "new"
    assert rotating.needs_rotation(token)
    assert rotating.decrypt(token, AAD) == SECRET
    reencrypted = rotating.encrypt(rotating.decrypt(token, AAD), AAD)
    assert not rotating.needs_rotation(reencrypted)

    only_new = parse_keyring(NEW)  # after rotation the old key can be dropped
    assert only_new.decrypt(reencrypted, AAD) == SECRET
    with pytest.raises(DecryptError, match="unknown key id 'old'"):
        only_new.decrypt(token, AAD)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "empty"),
        ("nocolon", "expected 'id:base64key'"),
        ("bad id!:AAAA", "expected 'id:base64key'"),
        ("k1:not-base64!!", "base64"),
        ("k1:" + "A" * 20, "must be 32 bytes"),
        (f"{NEW},{NEW}", "duplicate"),
    ],
)
def test_bad_keyrings_rejected(raw: str, message: str) -> None:
    with pytest.raises(KeyringError, match=message):
        parse_keyring(raw)
