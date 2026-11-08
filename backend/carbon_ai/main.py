import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import init_db


def _setup_file_logging() -> None:
    log_file = settings.log_dir / "carbon_ai_app.log"
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(log_file):
            return
    handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)


def create_app() -> FastAPI:
    _setup_file_logging()
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5500",
            "http://localhost:5500",
            "http://127.0.0.1:5501",
            "http://localhost:5501",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()

    @app.get("/")
    def root() -> dict[str, str]:
        return {"message": "Carbon AI Project API is running"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8017, reload=True)
