"""Runtime settings: proxy, cookies, rate limits, API keys."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.api.schemas import BrowserCheck, SettingsRead, SettingsUpdate
from app.db.session import get_session
from app.db.settings_store import SettingsStore

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsRead)
def read_settings(session: Session = Depends(get_session)) -> SettingsRead:
    """Current settings. API keys come back masked, never in full."""
    return SettingsRead(**SettingsStore(session).as_dict())


@router.put("", response_model=SettingsRead)
async def write_settings(
    payload: SettingsUpdate,
    request: Request,
    session: Session = Depends(get_session),
) -> SettingsRead:
    """Save settings and rebuild the fetcher so they take effect now."""
    store = SettingsStore(session)
    store.update(payload.model_dump(exclude_unset=True))

    manager = getattr(request.app.state, "job_manager", None)
    if manager is not None:
        await manager.reload_fetcher()

    return SettingsRead(**store.as_dict())


@router.post("/browser-check", response_model=BrowserCheck)
async def check_browser() -> BrowserCheck:
    """Report whether the headless browser actually works.

    Worth its own button: Playwright needs a separate browser download, and
    the failure otherwise only shows up mid-crawl on a protected site.
    """
    from app.fetch.browser import BrowserFetcher, BrowserUnavailable

    fetcher = BrowserFetcher()
    try:
        await fetcher.start()
    except BrowserUnavailable as exc:
        return BrowserCheck(available=False, detail=str(exc.message))
    except Exception as exc:  # pragma: no cover - environment dependent
        return BrowserCheck(available=False, detail=f"{type(exc).__name__}: {exc}")
    else:
        return BrowserCheck(available=True, detail="Chromium khởi động được.")
    finally:
        await fetcher.aclose()


@router.delete("/cookies/{domain}", response_model=SettingsRead)
def delete_cookie(domain: str, session: Session = Depends(get_session)) -> SettingsRead:
    store = SettingsStore(session)
    cookies = store.cookies
    key = domain.lower().removeprefix("www.")
    if key not in cookies:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cookie saved for that domain")
    cookies.pop(key)
    store.set_cookies(cookies)
    return SettingsRead(**store.as_dict())
