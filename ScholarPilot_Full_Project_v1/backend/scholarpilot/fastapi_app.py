"""Optional FastAPI adapter.

Install requirements-fastapi.txt, then run:
    uvicorn scholarpilot.fastapi_app:app --reload --port 8000
"""

import asyncio
import threading
import time

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import get_config
from .security import (
    AuthenticationError,
    ConcurrencyLimitExceeded,
    RateLimitExceeded,
    SearchSecurity,
    SecurityConfigurationError,
    request_identity_keys,
)
from .service import (
    LiveSearchError,
    SearchService,
    api_error,
    new_request_id,
)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=6, max_length=800)
    limit: int = Field(default=10, ge=1, le=50)


app = FastAPI(
    title="ScholarPilot API",
    version=__version__,
    description="Complex academic query planning and paper ranking backend.",
)
config = get_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.security.cors_allowed_origins),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-ScholarPilot-User",
    ],
)
service = SearchService()
security = SearchSecurity(config.security)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "ok": True,
        "ready": security.proxy_token_configured,
        "backend": {
            "service": "scholarpilot-fastapi",
            "adapter": "fastapi",
            "version": __version__,
        },
        "service": "scholarpilot-fastapi",
        "version": __version__,
        "llm": service.llm_info(),
        "academicSources": service.academic_sources_info(),
        "security": security.status(),
    }


@app.exception_handler(RequestValidationError)
async def validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_id = new_request_id(request.headers.get("x-request-id"))
    return JSONResponse(
        status_code=400,
        content=api_error(
            code="invalid_request",
            message="搜索请求不符合 API Schema。",
            request_id=request_id,
            validationErrors=exc.errors(),
        ),
    )


@app.exception_handler(Exception)
async def unexpected_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Keep unexpected adapter failures inside the versioned error contract."""
    del exc
    request_id = new_request_id(request.headers.get("x-request-id"))
    return JSONResponse(
        status_code=500,
        content=api_error(
            code="internal_error",
            message="服务发生未预期错误，请稍后重试。",
            request_id=request_id,
            retryable=True,
        ),
    )


@app.post("/api/search")
async def search(
    payload: SearchRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    x_scholarpilot_user: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> JSONResponse:
    request_id = new_request_id(x_request_id)
    auth_started = time.perf_counter()
    try:
        security.authorize(authorization)
        forwarded_for = (
            request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for")
            or request.headers.get("x-real-ip")
        )
        identity_keys = request_identity_keys(
            user_id=x_scholarpilot_user,
            forwarded_for=forwarded_for,
            remote_addr=request.client.host if request.client else None,
        )
        cancel_event = threading.Event()

        def execute_search() -> dict[str, object]:
            with security.admit(identity_keys):
                auth_queue_ms = int(
                    (time.perf_counter() - auth_started) * 1000
                )
                return service.search(
                    payload.query,
                    payload.limit,
                    request_id=request_id,
                    cancel_event=cancel_event,
                    auth_queue_ms=auth_queue_ms,
                )

        task = asyncio.create_task(run_in_threadpool(execute_search))
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=0.1)
            if done:
                break
            if await request.is_disconnected():
                cancel_event.set()
        result = await task
        return JSONResponse(status_code=200, content=result)
    except SecurityConfigurationError as exc:
        return JSONResponse(
            status_code=503,
            content=api_error(
                code="backend_auth_not_configured",
                message=str(exc),
                request_id=request_id,
            ),
        )
    except AuthenticationError as exc:
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content=api_error(
                code="unauthorized",
                message=str(exc),
                request_id=request_id,
            ),
        )
    except RateLimitExceeded as exc:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after_seconds)},
            content=api_error(
                code="rate_limit_exceeded",
                message=str(exc),
                request_id=request_id,
                retryable=True,
                retry_after_seconds=exc.retry_after_seconds,
            ),
        )
    except ConcurrencyLimitExceeded as exc:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "1"},
            content=api_error(
                code="concurrency_limit_exceeded",
                message=str(exc),
                request_id=request_id,
                retryable=True,
                retry_after_seconds=1,
            ),
        )
    except LiveSearchError as exc:
        if not exc.request_id:
            exc.request_id = request_id
        return JSONResponse(status_code=502, content=exc.to_api())
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=api_error(
                code="invalid_request",
                message=str(exc),
                request_id=request_id,
            ),
        )
