"""Aggregates all API routes under a single router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, jobs, novels

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(novels.router)
api_router.include_router(jobs.router)
