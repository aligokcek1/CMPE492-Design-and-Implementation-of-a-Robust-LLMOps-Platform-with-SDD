from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from .api import auth, deployment, gcp_credentials, lightning_ai_credentials, metrics, models, upload
from .api.dependencies import (  # re-exported for tests
    get_gcp_provider,
    get_lightning_ai_provider,
    reset_gcp_provider_for_tests,
    reset_lightning_ai_provider_for_tests,
)
from .api.errors import http_exception_handler
from .db.migrations import ensure_schema
from .services.deployment_orchestrator import deployment_orchestrator
from .services.monitoring_orchestrator import monitoring_orchestrator

_DECOMMISSION_INTERVAL_SECONDS = 60


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    refresh_task: asyncio.Task | None = None
    decommission_task: asyncio.Task | None = None
    if os.environ.get("LLMOPS_DISABLE_STATUS_REFRESH") != "1":
        refresh_task = asyncio.create_task(
            deployment_orchestrator.start_status_refresh_loop(
                gcp_provider_factory=get_gcp_provider,
                lightning_ai_provider_factory=get_lightning_ai_provider,
            )
        )
    if os.environ.get("LLMOPS_METRICS_DISABLED") != "1":
        await monitoring_orchestrator.reconcile_on_startup()

        async def _decommission_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(_DECOMMISSION_INTERVAL_SECONDS)
                    try:
                        await monitoring_orchestrator.run_decommission_cycle()
                    except Exception:  # noqa: BLE001
                        pass
            except asyncio.CancelledError:
                return

        decommission_task = asyncio.create_task(_decommission_loop())
    try:
        yield
    finally:
        if refresh_task is not None:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        if decommission_task is not None:
            decommission_task.cancel()
            try:
                await decommission_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="LLMOps Platform API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(models.router, prefix="/api", tags=["models"])
app.include_router(deployment.router, prefix="/api/deployment", tags=["deployment"])
app.include_router(deployment.real_router, prefix="/api/deployments", tags=["deployments"])
app.include_router(metrics.router, prefix="/api", tags=["metrics"])
app.include_router(gcp_credentials.router, prefix="/api/gcp/credentials", tags=["gcp"])
app.include_router(lightning_ai_credentials.router, prefix="/api/lightning/credentials", tags=["lightning-ai"])
app.mount("/metrics", make_asgi_app())


@app.get("/health")
async def health_check():
    return {"status": "ok"}


__all__ = [
    "app",
    "get_gcp_provider",
    "reset_gcp_provider_for_tests",
    "get_lightning_ai_provider",
    "reset_lightning_ai_provider_for_tests",
]
