"""FastAPI application entry point.

The API only answers requests; background work (sends, tailoring, schedules,
backups) runs in the separate worker process (`career-agent worker`).
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import env_file_path, get_settings, legacy_data_in_repo, shadowed_env_vars
from .db import init_db
from .llm.router import aclose_llm
from .logging_setup import get_logger
from .routers import applications, checks, email, jobs, linkedin, outreach, resume, settings, system

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stale = shadowed_env_vars()
    if stale:
        log.warning(
            "These shell variables override different values in %s: %s. "
            "Unset them or start the backend from a fresh terminal.",
            env_file_path(),
            ", ".join(stale),
        )
    if legacy_data_in_repo():
        log.warning(
            "Personal data is still inside the repository (%s). Stop the app and run "
            "`career-agent migrate-home` to move it to %s.",
            ", ".join(p.name for p in legacy_data_in_repo()),
            env_file_path().parent,
        )
    yield
    await aclose_llm()


def _token_ok(request: Request, token: str) -> bool:
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    supplied = supplied or request.cookies.get("ca_token", "")
    return bool(supplied) and hmac.compare_digest(supplied, token)


def create_app() -> FastAPI:
    cfg = get_settings()
    # Idempotent: ensures tables exist even when the app is used without the
    # ASGI lifespan (e.g. TestClient created without a context manager).
    init_db()
    app = FastAPI(title=cfg.app_name, version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if cfg.api_token:

        @app.middleware("http")
        async def require_token(request: Request, call_next):
            if request.url.path.startswith("/api/") and not _token_ok(request, cfg.api_token or ""):
                return JSONResponse({"detail": "Unauthorized: API token required"}, status_code=401)
            return await call_next(request)

    for module in (resume, outreach, jobs, email, linkedin, settings, applications, checks, system):
        app.include_router(module.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": cfg.app_name}

    dist = (Path(__file__).resolve().parent.parent / cfg.frontend_dist).resolve()
    if cfg.serve_frontend:
        if not (dist / "index.html").exists():
            log.warning("serve_frontend is on but %s has no build; run `npm run build` in frontend/", dist)
        else:

            @app.get("/{path:path}", include_in_schema=False)
            def spa(path: str) -> FileResponse:
                """Built UI: real files as-is, every other route to index.html (client routing)."""
                if path.startswith("api/"):
                    raise HTTPException(status_code=404, detail="Not Found")
                candidate = (dist / path).resolve()
                if path and candidate.is_file() and dist in candidate.parents:
                    return FileResponse(candidate)
                return FileResponse(dist / "index.html")

    return app


app = create_app()


def run() -> None:
    from .cli import main

    main()


if __name__ == "__main__":
    run()
