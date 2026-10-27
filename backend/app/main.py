from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .routers import admin, analysis, auth, campaigns, classification, dashboard, ideas, platform


def create_app() -> FastAPI:
    settings = get_settings()
    if not settings.allow_tenant_override and (settings.secret_key.startswith("troque") or len(settings.secret_key) < 32):
        raise RuntimeError("Em produção, defina SECRET_KEY com pelo menos 32 caracteres aleatórios.")
    app = FastAPI(title="Flash Inova", version="0.1.0")
    app.include_router(auth.router)
    app.include_router(platform.router)
    app.include_router(admin.router)
    app.include_router(campaigns.router)
    app.include_router(ideas.router)
    app.include_router(analysis.router)
    app.include_router(classification.router)
    app.include_router(dashboard.router)

    storage = Path(settings.storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=storage), name="files")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
