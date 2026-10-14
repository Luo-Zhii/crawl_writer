"""Per-novel glossary: the terms translation must never vary on."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.api.schemas import (
    GlossaryBulk,
    GlossaryTermCreate,
    GlossaryTermRead,
    JobRead,
    TranslateRequest,
)
from app.db.models import JobType, Lang
from app.db.repository import GlossaryRepository, NovelRepository
from app.db.session import get_session
from app.pipeline.manager import JobManager

router = APIRouter(prefix="/novels/{novel_id}", tags=["translate"])


def _require_novel(session: Session, novel_id: int):
    novel = NovelRepository(session).get(novel_id)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    return novel


def get_manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:  # pragma: no cover - set up in the app lifespan
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Background worker is not running"
        )
    return manager


@router.get("/glossary", response_model=list[GlossaryTermRead])
def list_terms(
    novel_id: int, session: Session = Depends(get_session)
) -> list[GlossaryTermRead]:
    _require_novel(session, novel_id)
    return [
        GlossaryTermRead.model_validate(term)
        for term in GlossaryRepository(session).list_for_novel(novel_id)
    ]


@router.post("/glossary", response_model=GlossaryTermRead, status_code=201)
def add_term(
    novel_id: int,
    payload: GlossaryTermCreate,
    session: Session = Depends(get_session),
) -> GlossaryTermRead:
    """Add a term, or change the reading of one already there."""
    _require_novel(session, novel_id)
    term = GlossaryRepository(session).upsert(
        novel_id, payload.source.strip(), payload.target.strip(), payload.note
    )
    return GlossaryTermRead.model_validate(term)


@router.put("/glossary", response_model=list[GlossaryTermRead])
def replace_terms(
    novel_id: int,
    payload: GlossaryBulk,
    session: Session = Depends(get_session),
) -> list[GlossaryTermRead]:
    """Replace the whole glossary. Used for pasting a list in one go."""
    _require_novel(session, novel_id)
    repo = GlossaryRepository(session)
    repo.replace_all(novel_id, payload.terms)
    return [GlossaryTermRead.model_validate(term) for term in repo.list_for_novel(novel_id)]


@router.delete("/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_term(
    novel_id: int, term_id: int, session: Session = Depends(get_session)
) -> None:
    _require_novel(session, novel_id)
    repo = GlossaryRepository(session)
    term = repo.get(term_id)
    if term is None or term.novel_id != novel_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")
    repo.delete(term)


@router.post("/translate", response_model=JobRead, status_code=202)
def start_translation(
    novel_id: int,
    payload: TranslateRequest | None = None,
    manager: JobManager = Depends(get_manager),
    session: Session = Depends(get_session),
) -> JobRead:
    """Queue a translation pass over everything already downloaded."""
    novel = _require_novel(session, novel_id)
    if novel.lang is Lang.vi:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This novel is already in Vietnamese"
        )

    force = bool(payload.force) if payload else False
    job = manager.create_job(
        novel_id=novel_id, job_type=JobType.translate, params={"force": force}
    )
    return JobRead.model_validate(job)
