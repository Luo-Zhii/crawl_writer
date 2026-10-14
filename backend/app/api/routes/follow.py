"""Auto-update for followed novels: status, manual check, clearing badges."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, func, select

from app.api.schemas import FollowCheckResult, FollowStatus
from app.db.models import Novel
from app.db.repository import NovelRepository
from app.db.session import get_session
from app.db.settings_store import SettingsStore

router = APIRouter(prefix="/follow", tags=["follow"])


def _scheduler(request: Request):
    scheduler = getattr(request.app.state, "follow_scheduler", None)
    if scheduler is None:
        # Only happens if the app was built without a lifespan, e.g. in a
        # test client that skips startup.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Scheduler is not running"
        )
    return scheduler


@router.get("/status", response_model=FollowStatus)
def follow_status(
    request: Request, session: Session = Depends(get_session)
) -> FollowStatus:
    """Whether auto-update is on, and when it next fires."""
    store = SettingsStore(session)
    scheduler = getattr(request.app.state, "follow_scheduler", None)
    unseen = session.exec(select(func.sum(Novel.new_chapters))).one()

    return FollowStatus(
        enabled=store.follow_enabled,
        interval_hours=store.follow_interval_hours,
        running=bool(scheduler and scheduler.running),
        next_run_at=scheduler.next_run() if scheduler else None,
        followed_count=NovelRepository(session).count(followed=True),
        new_chapters=int(unseen or 0),
    )


@router.post("/check-now", response_model=FollowCheckResult)
async def check_now(request: Request) -> FollowCheckResult:
    """Run a check immediately instead of waiting for the timer.

    Works even when auto-update is switched off: the button is also how a
    user who distrusts background jobs drives updates by hand.
    """
    result = await _scheduler(request).check_now()
    return FollowCheckResult(job_ids=result.job_ids, considered=result.considered)


@router.post("/{novel_id}/seen", status_code=status.HTTP_204_NO_CONTENT)
def mark_seen(novel_id: int, session: Session = Depends(get_session)) -> None:
    """Clear the "new chapters" badge for one novel."""
    repo = NovelRepository(session)
    novel = repo.get(novel_id)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    if novel.new_chapters:
        repo.update(novel, new_chapters=0)
