import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.api.errors import api_error
from app.auth.security import create_access_token
from app.auth.service import EmailTakenError, authenticate, register_user
from app.db.models import User
from app.deps import (
    AUTH_COOKIE,
    CurrentTenant,
    CurrentUser,
    RateLimiterDep,
    SessionDep,
    SettingsDep,
    per_ip,
    too_many_requests,
)
from app.ratelimit import RateLimitedError, RateLimiter, client_ip
from app.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Upper bound keeps argon2 hashing cost bounded against oversized inputs.
Password = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    display_name: Annotated[str | None, Field(max_length=100)] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(max_length=128)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    # Null until the setup guide is finished (ADR 0042 §1).
    setup_completed_at: datetime | None


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str | None, Field(max_length=100)] = None

    @field_validator("display_name")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str


class MeOut(BaseModel):
    user: UserOut
    tenant: TenantOut


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Same error for unknown email and wrong password: don't reveal which emails exist.
_INVALID_CREDENTIALS = api_error(
    status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "invalid email or password"
)


def _set_auth_cookie(response: Response, user: User, settings: Settings) -> None:
    response.set_cookie(
        AUTH_COOKIE,
        create_access_token(user.id, settings),
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def _login(
    request: Request, limiter: RateLimiter, session: SessionDep, email: str, password: str
) -> User:
    """Authenticate within the login limits, which count failures only (ADR 0035 §3)."""
    ip, email_key = client_ip(request), email.lower()
    keys = [("login", f"{ip} {email_key}"), ("login_ip", ip), ("login_email", email_key)]
    waits: list[RateLimitedError] = []
    for bucket, key in keys:
        try:
            limiter.check(bucket, key)
        except RateLimitedError as exc:
            waits.append(exc)
    if waits:
        # Refused before the password is checked, so it can't be probed meanwhile.
        raise too_many_requests(max(waits, key=lambda e: e.retry_after))
    user = await authenticate(session, email, password)
    if user is None:
        for bucket, key in keys:
            limiter.record(bucket, key)
        raise _INVALID_CREDENTIALS
    limiter.reset(*keys[0])
    return user


@router.post("/register", status_code=status.HTTP_201_CREATED, dependencies=[per_ip("signup")])
async def register(
    body: RegisterRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> UserOut:
    try:
        user = await register_user(session, body.email, body.password, body.display_name)
    except EmailTakenError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, "email_taken", "email already registered"
        ) from exc
    _set_auth_cookie(response, user, settings)
    return UserOut.model_validate(user)


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> UserOut:
    user = await _login(request, limiter, session, body.email, body.password)
    _set_auth_cookie(response, user, settings)
    return UserOut.model_validate(user)


@router.post("/token")
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> TokenOut:
    """OAuth2 password flow for non-browser clients; returns a Bearer token, sets no cookie."""
    user = await _login(request, limiter, session, form.username, form.password)
    return TokenOut(access_token=create_access_token(user.id, settings))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(
        AUTH_COOKIE, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
    )


@router.get("/me")
async def me(user: CurrentUser, tenant: CurrentTenant) -> MeOut:
    return MeOut(user=UserOut.model_validate(user), tenant=TenantOut.model_validate(tenant))


@router.patch("/me")
async def update_me(body: UserPatch, user: CurrentUser, session: SessionDep) -> UserOut:
    """The name the app calls the learner by (the setup guide's first step, ADR 0042 §2)."""
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await session.commit()
    return UserOut.model_validate(user)
