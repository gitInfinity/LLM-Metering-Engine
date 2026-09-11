from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from src.core.logging import configure_logging, info
from src.db.database import engine
from src.core.errors import register_error_handlers
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    info(__name__, "API started")
    try:
        yield
    finally:
        engine.dispose()
        info(__name__, "API stopped")


app = FastAPI(title="LLM Metering API", lifespan=lifespan)
app.include_router(router)
register_error_handlers(app)


@app.middleware("http")
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

