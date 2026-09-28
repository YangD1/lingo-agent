"""Password hashing (argon2id via pwdlib) and JWT access tokens (ADR 0003)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.settings import Settings

ALGORITHM = "HS256"
TOKEN_TYPE = "access"

_hasher = PasswordHash.recommended()
# Verified against when the email is unknown, so both failure paths cost one argon2 run
# and response timing doesn't reveal which emails are registered.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Returns (ok, new_hash); new_hash is set when parameters changed and it should be saved."""
    return _hasher.verify_and_update(password, password_hash)


def burn_verify_time(password: str) -> None:
    _hasher.verify(password, _DUMMY_HASH)


def create_access_token(user_id: uuid.UUID, settings: Settings, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "type": TOKEN_TYPE,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    try:
        # Pinning `algorithms` blocks alg=none and algorithm-confusion attacks.
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
        if claims.get("type") != TOKEN_TYPE:
            raise InvalidTokenError("wrong token type")
        return uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
