"""ASGI entry point.

The compiled front-end is served from ``backend/app/static`` so that running the
tool needs nothing but Python — no Node, no separate dev server, no Docker.
"""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fastapi import Depends

from .api.auth_routes import current_user, project_guard, router as auth_router
from .api.composite_routes import router as composite_router
from .api.criticality_routes import router as criticality_router
from .api.ner_routes import router as ner_router
from .api.routes import router
from .config import settings
from .db import init_db

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Python guesses a file's type from the Windows registry. On many machines
# (an editor or a runtime rewrote HKCR\.js) ``.js`` comes back as
# ``text/plain``, the browser refuses the module script and the page stays
# white with no error on screen. The types the interface needs are fixed here,
# whatever the registry says.
for _type, _ext in (("text/javascript", ".js"), ("text/javascript", ".mjs"),
                    ("text/css", ".css"), ("image/svg+xml", ".svg"),
                    ("application/wasm", ".wasm"), ("application/json", ".json")):
    mimetypes.add_type(_type, _ext)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # The drawing numbers of books imported before 10 Sep 2026 are read off
    # their title blocks after the application is up, not before: it is a
    # second a page on a real book, and the watchdog restarts anything that
    # has not answered for a minute. Each book commits on its own.
    import threading

    from . import migrate
    from .db import SessionLocal

    def _sheet_numbers() -> None:
        totals = migrate.backfill_all_sheet_numbers(SessionLocal)
        if any(totals.values()):
            print(f"sheet numbers read from the title blocks: {totals}", flush=True)
        # Same thread, same reason: a book imported before 2.4.1 that yielded
        # no space is read once more for its room-name labels.
        spaces = migrate.backfill_all_name_only_spaces(SessionLocal)
        if any(spaces.values()):
            print(f"name-only spaces: {spaces}", flush=True)
        # 2.14.0: a key plan has no spaces and a name-only label is a space
        # only when it reads as a known space name — once per book.
        cleaned = migrate.backfill_all_spaces_2140(SessionLocal)
        if any(cleaned.values()):
            print(f"2.14.0 spaces pass: {cleaned}", flush=True)

    threading.Thread(target=_sheet_numbers, name="sheet-numbers", daemon=True).start()
    yield


app = FastAPI(title=settings.app_name, version=settings.version,
              description=settings.disclaimer, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _who_is_asking(request, call_next):
    """Put the signed-in username where the audit log reads it (4.2.0)."""
    from . import auth as _A
    from . import services as _S
    from .db import SessionLocal as _SL
    token = request.cookies.get("ner_session")
    name = None
    if token:
        db = _SL()
        try:
            u = _A.resolve_session(db, token)
            name = u.username if u is not None else None
        except Exception:                              # noqa: BLE001 — never block a request on this
            name = None
        finally:
            db.close()
    reset = _S.CURRENT_ACTOR.set(name)
    try:
        return await call_next(request)
    finally:
        _S.CURRENT_ACTOR.reset(reset)


# Sign-in and the data notice are reachable without an account; everything else
# requires one, and anything with a project in its path is additionally checked
# against who owns it.
app.include_router(auth_router, prefix="/api")
_guarded = [Depends(current_user), Depends(project_guard)]
app.include_router(router, prefix="/api", dependencies=_guarded)
app.include_router(ner_router, prefix="/api", dependencies=_guarded)
app.include_router(criticality_router, prefix="/api", dependencies=_guarded)
# 5.0.0: the composite map — one map per level of a book, built on request.
app.include_router(composite_router, prefix="/api", dependencies=_guarded)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": settings.version}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve the single-page app, letting the client router own the URL."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
