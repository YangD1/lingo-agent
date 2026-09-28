import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.security import (
    ALGORITHM,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.settings import Settings

SETTINGS = Settings(_env_file=None, jwt_secret="k" * 32, jwt_expire_minutes=60)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse")
    assert hashed.startswith("$argon2id$")
    assert "correct horse" not in hashed
    assert verify_password("correct horse", hashed)[0] is True
    assert verify_password("wrong horse", hashed)[0] is False


def test_same_password_hashes_differently() -> None:
    assert hash_password("same-password") != hash_password("same-password")  # random salt


def test_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id, SETTINGS), SETTINGS) == user_id


def test_expired_token_rejected() -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    token = create_access_token(uuid.uuid4(), SETTINGS, now=long_ago)
    with pytest.raises(InvalidTokenError, match="expired"):
        decode_access_token(token, SETTINGS)


def test_token_signed_with_other_secret_rejected() -> None:
    other = Settings(_env_file=None, jwt_secret="z" * 32)
    with pytest.raises(InvalidTokenError):
        decode_access_token(create_access_token(uuid.uuid4(), other), SETTINGS)


def test_tampered_token_rejected() -> None:
    token = create_access_token(uuid.uuid4(), SETTINGS)
    header, _payload, signature = token.split(".")
    forged_payload = jwt.utils.base64url_encode(
        b'{"sub":"' + str(uuid.uuid4()).encode() + b'","type":"access","iat":1,"exp":9999999999}'
    ).decode()
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{forged_payload}.{signature}", SETTINGS)


def test_alg_none_rejected() -> None:
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": 1, "exp": 9999999999},
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SETTINGS)


def test_token_without_type_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=5)},
        SETTINGS.jwt_secret,
        algorithm=ALGORITHM,
    )
    with pytest.raises(InvalidTokenError, match="type"):
        decode_access_token(token, SETTINGS)
