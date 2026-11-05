from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .storage import get_storage
from .routers import admin, analysis, auth, campaigns, classification, dashboard, defense, ideas, platform, voting


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
    app.include_router(defense.router)
    app.include_router(voting.router)

    if settings.storage_backend == "local":
        storage = Path(settings.storage_dir)
        storage.mkdir(parents=True, exist_ok=True)
        app.mount("/files", StaticFiles(directory=storage), name="files")
    else:
        image_types = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}

        @app.get("/files/{path:path}", include_in_schema=False)
        def public_file(path: str) -> Response:
            # Logotipos e banners (só imagens). Os anexos das ideias ficam no armazenamento privado.
            extension = path.rsplit(".", 1)[-1].lower()
            data = get_storage().read(path) if extension in image_types else None
            if data is None:
                raise HTTPException(404, "Arquivo não encontrado.")
            return Response(data, media_type=image_types[extension],
                            headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    if settings.frontend_dist:
        # Produção: o mesmo serviço entrega o app (React). Rotas do app caem no index.html.
        dist = Path(settings.frontend_dist).resolve()
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith(("api/", "files/")):
                raise HTTPException(404, "Não encontrado.")
            target = (dist / path).resolve()
            if path and target.is_relative_to(dist) and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
