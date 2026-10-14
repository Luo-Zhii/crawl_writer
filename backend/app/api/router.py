"""Aggregates all API routes under a single router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import follow, glossary, health, jobs, novels, settings

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(novels.router)
api_router.include_router(glossary.router)
api_router.include_router(jobs.router)
api_router.include_router(follow.router)
api_router.include_router(settings.router)
