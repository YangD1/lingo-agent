import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.security import create_access_token
from app.auth.service import EmailTakenError, authenticate, register_user
from app.db.models import User
from app.deps import AUTH_COOKIE, CurrentTenant, CurrentUser, SessionDep, SettingsDep
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


_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    # Same message for unknown email and wrong password: don't reveal which emails exist.
    detail="invalid email or password",
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


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> UserOut:
    try:
        user = await register_user(session, body.email, body.password, body.display_name)
    except EmailTakenError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from exc
    _set_auth_cookie(response, user, settings)
    return UserOut.model_validate(user)


@router.post("/login")
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> UserOut:
    user = await authenticate(session, body.email, body.password)
    if user is None:
        raise _INVALID_CREDENTIALS
    _set_auth_cookie(response, user, settings)
    return UserOut.model_validate(user)


@router.post("/token")
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    settings: SettingsDep,
) -> TokenOut:
    """OAuth2 password flow for non-browser clients; returns a Bearer token, sets no cookie."""
    user = await authenticate(session, form.username, form.password)
    if user is None:
        raise _INVALID_CREDENTIALS
    return TokenOut(access_token=create_access_token(user.id, settings))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(
        AUTH_COOKIE, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
    )


@router.get("/me")
async def me(user: CurrentUser, tenant: CurrentTenant) -> MeOut:
    return MeOut(user=UserOut.model_validate(user), tenant=TenantOut.model_validate(tenant))
