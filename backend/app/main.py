import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.deps import Db
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.modules.brokers.router import router as brokers_router
from app.modules.feeds.router import router as feeds_router
from app.modules.identity.router import router as identity_router
from app.modules.orders.router import router as orders_router
from app.modules.quotes.router import router as quotes_router
from app.modules.risk.router import router as risk_router
from app.modules.scanners.router import router as scanners_router
from app.modules.signals.clock_router import router as clock_router
from app.modules.signals.router import router as signals_router

logger = logging.getLogger("quantivo.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s %s %s %s %.1fms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Quantivo API",
        version="0.1.0",
        description=(
            "Trading assistant API. This build uses development OTP sign-in, Mani's sample "
            "scanner, and a Zerodha sign-in that cannot place orders."
        ),
    )
    app.add_middleware(RequestContextMiddleware)
    cors_kwargs: dict = {
        "allow_origins": settings.cors_origin_list,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    if settings.environment in {"development", "test"}:
        cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    app.add_middleware(CORSMiddleware, **cors_kwargs)
    app.include_router(identity_router)
    app.include_router(scanners_router)
    app.include_router(signals_router)
    app.include_router(clock_router)
    app.include_router(risk_router)
    app.include_router(brokers_router)
    app.include_router(orders_router)
    app.include_router(quotes_router)
    app.include_router(feeds_router)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {
            "status": "ok",
            "service": "quantivo-api",
            "environment": settings.environment,
            "live_trading_enabled": False,
            "auth_provider": settings.auth_provider,
        }

    @app.get("/ready", tags=["ops"])
    def ready(db: Db) -> dict:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for error in exc.errors():
            location = [str(item) for item in error["loc"] if item != "body"]
            fields.append({"field": ".".join(location), "message": error["msg"]})
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Check the submitted fields.",
                    "fields": fields,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Something went wrong."}},
        )

    return app


app = create_app()
