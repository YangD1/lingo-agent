"""Tenant model settings: presets, connections, route overrides (ADR 0004 §6)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.errors import api_error
from app.credentials import service
from app.credentials.crypto import get_keyring
from app.credentials.service import CallParams, ConflictError, NotFoundError
from app.db.models import ProviderConnection
from app.deps import CurrentTenant, CurrentUser, Manager, SessionDep, SettingsDep
from app.providers.config import Section
from app.providers.errors import ProviderConfigError
from app.providers.llm import get_providers_config
from app.providers.model_catalog import ModelCategory, ModelListError

router = APIRouter(tags=["model settings"])


class PresetOut(BaseModel):
    name: str
    kind: str
    label: str | None
    base_url: str
    models: list[str]


class TaskRouteOut(BaseModel):
    section: Section
    task: str
    models: list[str]
    params: dict[str, Any]
    overridden: bool


class PresetsOut(BaseModel):
    presets: list[PresetOut]
    allow_private_networks: bool


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str | None = None
    name: str | None = None
    kind: str | None = None
    base_url: Annotated[str | None, Field(max_length=500)] = None
    api_key: Annotated[SecretStr | None, Field(max_length=500)] = None
    params: CallParams = CallParams()


class ConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: Annotated[str | None, Field(max_length=500)] = None
    api_key: Annotated[SecretStr | None, Field(max_length=500)] = None
    clear_api_key: bool = False
    params: CallParams | None = None
    enabled: bool | None = None


class ConnectionOut(BaseModel):
    """Never contains the key itself - only a hint of its last characters."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    base_url: str
    has_api_key: bool
    key_hint: str | None
    params: dict[str, Any]
    enabled: bool
    last_verified_at: datetime | None
    last_error: str | None

    @classmethod
    def of(cls, conn: ProviderConnection) -> "ConnectionOut":
        return cls.model_validate(
            {
                **{f: getattr(conn, f) for f in cls.model_fields if f != "has_api_key"},
                "has_api_key": conn.encrypted_api_key is not None,
            }
        )


class TestRequest(BaseModel):
    model: Annotated[str, Field(min_length=1, max_length=128)]


class TestOut(BaseModel):
    ok: bool
    error: str | None
    latency_ms: int


class ModelOut(BaseModel):
    id: str
    category: ModelCategory


class ModelsOut(BaseModel):
    models: list[ModelOut]


class RoutePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: Annotated[list[str], Field(min_length=1, max_length=5)]
    params: CallParams = CallParams()


def _bad_request(exc: Exception) -> HTTPException:
    return api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_provider_config", str(exc))


@router.get("/provider-presets")
async def presets(settings: SettingsDep, _: CurrentUser) -> PresetsOut:
    config = get_providers_config()
    return PresetsOut(
        presets=[
            PresetOut(name=n, kind=p.kind, label=p.label, base_url=p.base_url, models=p.models)
            for n, p in config.presets.items()
        ],
        allow_private_networks=settings.provider_allow_private_networks,
    )


@router.get("/tenant/connections", dependencies=[Manager])
async def list_connections(tenant: CurrentTenant, session: SessionDep) -> list[ConnectionOut]:
    return [ConnectionOut.of(c) for c in await service.list_connections(session, tenant.id)]


@router.post("/tenant/connections", status_code=status.HTTP_201_CREATED, dependencies=[Manager])
async def create_connection(
    body: ConnectionCreate, tenant: CurrentTenant, session: SessionDep, settings: SettingsDep
) -> ConnectionOut:
    try:
        conn = await service.create_connection(
            session,
            tenant_id=tenant.id,
            config=get_providers_config(),
            keyring=get_keyring(),
            allow_private=settings.provider_allow_private_networks,
            preset=body.preset,
            name=body.name,
            kind=body.kind,
            base_url=body.base_url,
            api_key=body.api_key,
            params=body.params,
        )
    except ProviderConfigError as exc:
        raise _bad_request(exc) from exc
    except ConflictError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "connection_name_taken", str(exc)) from exc
    return ConnectionOut.of(conn)


@router.patch("/tenant/connections/{connection_id}", dependencies=[Manager])
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionPatch,
    tenant: CurrentTenant,
    session: SessionDep,
    settings: SettingsDep,
) -> ConnectionOut:
    try:
        conn = await service.get_connection(session, tenant.id, connection_id)
        conn = await service.update_connection(
            session,
            conn,
            keyring=get_keyring(),
            allow_private=settings.provider_allow_private_networks,
            base_url=body.base_url,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
            params=body.params,
            enabled=body.enabled,
        )
    except NotFoundError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "connection_not_found", str(exc)) from exc
    except ProviderConfigError as exc:
        raise _bad_request(exc) from exc
    return ConnectionOut.of(conn)


@router.delete(
    "/tenant/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Manager],
)
async def delete_connection(
    connection_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> None:
    try:
        conn = await service.get_connection(session, tenant.id, connection_id)
    except NotFoundError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "connection_not_found", str(exc)) from exc
    await service.delete_connection(session, conn)


@router.post("/tenant/connections/{connection_id}/test", dependencies=[Manager])
async def verify_connection(
    connection_id: uuid.UUID, body: TestRequest, tenant: CurrentTenant, session: SessionDep
) -> TestOut:
    try:
        conn = await service.get_connection(session, tenant.id, connection_id)
    except NotFoundError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "connection_not_found", str(exc)) from exc
    ok, error, latency_ms = await service.verify_connection(
        session, conn, keyring=get_keyring(), model=body.model
    )
    return TestOut(ok=ok, error=error, latency_ms=latency_ms)


@router.get("/tenant/connections/{connection_id}/models", dependencies=[Manager])
async def list_connection_models(
    connection_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> ModelsOut:
    """Ask the vendor which models this connection serves (ADR 0007 §1). Uses no tokens."""
    try:
        conn = await service.get_connection(session, tenant.id, connection_id)
    except NotFoundError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "connection_not_found", str(exc)) from exc
    try:
        models = await service.list_connection_models(conn, keyring=get_keyring())
    except ModelListError as exc:
        raise api_error(status.HTTP_502_BAD_GATEWAY, "model_list_failed", str(exc)) from exc
    return ModelsOut(models=[ModelOut(id=m.id, category=m.category) for m in models])


@router.get("/tenant/routes", dependencies=[Manager])
async def list_routes(tenant: CurrentTenant, session: SessionDep) -> list[TaskRouteOut]:
    """Effective route for every known task: the tenant override, or the default."""
    config = get_providers_config()
    overrides = {
        (r.section, r.task): r for r in await service.list_route_overrides(session, tenant.id)
    }
    out: list[TaskRouteOut] = []
    for section in ("llm", "embedding"):
        spec = config.section(section)
        if spec is None:
            continue
        for task, default in spec.all_routes().items():
            override = overrides.get((section, task))
            out.append(
                TaskRouteOut(
                    section=section,
                    task=task,
                    models=override.models if override else default.models,
                    params=override.params if override else default.params,
                    overridden=override is not None,
                )
            )
    return out


@router.put("/tenant/routes/{section}/{task}", dependencies=[Manager])
async def put_route(
    section: Section, task: str, body: RoutePut, tenant: CurrentTenant, session: SessionDep
) -> TaskRouteOut:
    try:
        route = await service.put_route(
            session,
            tenant_id=tenant.id,
            config=get_providers_config(),
            section=section,
            task=task,
            models=body.models,
            params=body.params,
        )
    except ProviderConfigError as exc:
        raise _bad_request(exc) from exc
    return TaskRouteOut(
        section=section, task=task, models=route.models, params=route.params, overridden=True
    )


@router.delete(
    "/tenant/routes/{section}/{task}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Manager],
)
async def delete_route(
    section: Section, task: str, tenant: CurrentTenant, session: SessionDep
) -> None:
    try:
        await service.delete_route(session, tenant_id=tenant.id, section=section, task=task)
    except NotFoundError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, "route_not_found", str(exc)) from exc
