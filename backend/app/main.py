"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings, shadowed_env_vars
from .db import init_db
from .llm.router import aclose_llm
from .logging_setup import get_logger

log = get_logger(__name__)
from .routers import email, jobs, linkedin, outreach, resume, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stale = shadowed_env_vars()
    if stale:
        log.warning(
            "These shell variables override different values in backend/.env: %s. "
            "Unset them or start the backend from a fresh terminal.",
            ", ".join(stale),
        )
    yield
    await aclose_llm()


def create_app() -> FastAPI:
    cfg = get_settings()
    # Idempotent: ensures tables exist even when the app is used without the
    # ASGI lifespan (e.g. TestClient created without a context manager).
    init_db()
    app = FastAPI(title=cfg.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(resume.router)
    app.include_router(outreach.router)
    app.include_router(jobs.router)
    app.include_router(email.router)
    app.include_router(linkedin.router)
    app.include_router(settings.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": cfg.app_name}

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
