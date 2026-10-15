"""The setup guide (ADR 0042): where each step stands, and marking the guide finished.

The steps save through the pages' own endpoints (profile, tutor, connections); this
only reads what is set up now, so the guide and the settings pages always agree.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlacementSession, Tenant, User, UserProfile
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.providers.config import resolve_route
from app.providers.errors import NoModelConfiguredError
from app.providers.llm import get_providers_config
from app.providers.tenant import load_provider_context
from app.tutor import service as tutor_service

router = APIRouter(prefix="/me/setup", tags=["setup"])


class SetupStepsOut(BaseModel):
    # Each is true when that step's settings are made, by the guide or elsewhere.
    profile: bool  # a name to be called by, or the explanation language
    model: bool  # a chat model is usable, the learner's own or their main account's
    goals: bool  # any of goal, target exam, daily minutes, interests
    tutor: bool  # the assistant's name or looks chosen
    placement: bool  # a placement test finished


class SetupOut(BaseModel):
    # Null: not finished yet, so the app sends the learner to the guide (§1).
    completed_at: datetime | None
    steps: SetupStepsOut


async def _model_ready(session: AsyncSession, tenant: Tenant) -> bool:
    try:
        resolve_route(
            get_providers_config(), await load_provider_context(session, tenant.id), "llm", "chat"
        )
    except NoModelConfiguredError:
        return False
    return True


async def _setup_out(session: AsyncSession, user: User, tenant: Tenant) -> SetupOut:
    profile = await session.get(UserProfile, user.id)
    tutor = await tutor_service.get_tutor(session, user.id)
    placement = await session.scalar(
        select(
            exists().where(PlacementSession.user_id == user.id, PlacementSession.status == "done")
        )
    )
    return SetupOut(
        completed_at=user.setup_completed_at,
        steps=SetupStepsOut(
            profile=bool(user.display_name or (profile and profile.explanation_language)),
            model=await _model_ready(session, tenant),
            goals=bool(
                profile
                and (
                    profile.goal
                    or profile.target_exam
                    or profile.daily_minutes
                    or profile.interests
                )
            ),
            tutor=bool(tutor and (tutor.name or tutor.avatar)),
            placement=bool(placement),
        ),
    )


@router.get("")
async def get_setup(user: CurrentUser, tenant: CurrentTenant, session: SessionDep) -> SetupOut:
    return await _setup_out(session, user, tenant)


@router.post("/complete")
async def complete_setup(user: CurrentUser, tenant: CurrentTenant, session: SessionDep) -> SetupOut:
    """Finish the guide; finishing it again (re-entered later) just moves the time."""
    user.setup_completed_at = datetime.now(UTC)
    await session.commit()
    return await _setup_out(session, user, tenant)
