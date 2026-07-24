"""Optional FastAPI adapter.

Install requirements-fastapi.txt, then run:
    uvicorn scholarpilot.fastapi_app:app --reload --port 8000
"""

from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
from .service import LiveSearchError, SearchService


class SearchRequest(BaseModel):
    query: str = Field(min_length=6, max_length=800)
    mode: Literal["demo", "live"] = "demo"
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


@app.post("/api/search")
def search(
    payload: SearchRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    x_scholarpilot_user: str | None = Header(default=None),
) -> dict[str, object]:
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
        with security.admit(identity_keys):
            return service.search(payload.query, payload.mode, payload.limit)
    except SecurityConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "backend_auth_not_configured",
                "message": str(exc),
            },
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            detail={"code": "unauthorized", "message": str(exc)},
        ) from exc
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after_seconds)},
            detail={
                "code": "rate_limit_exceeded",
                "message": str(exc),
                "retryAfterSeconds": exc.retry_after_seconds,
            },
        ) from exc
    except ConcurrencyLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": "1"},
            detail={
                "code": "concurrency_limit_exceeded",
                "message": str(exc),
            },
        ) from exc
    except LiveSearchError as exc:
        raise HTTPException(
            status_code=502,
            detail=exc.to_api()["error"],
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
