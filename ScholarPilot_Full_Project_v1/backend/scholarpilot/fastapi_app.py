"""Optional FastAPI adapter.

Install requirements-fastapi.txt, then run:
    uvicorn scholarpilot.fastapi_app:app --reload --port 8000
"""

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .service import SearchService


class SearchRequest(BaseModel):
    query: str = Field(min_length=6, max_length=800)
    mode: Literal["demo", "live"] = "demo"
    limit: int = Field(default=10, ge=1, le=50)


app = FastAPI(
    title="ScholarPilot API",
    version="0.2.0",
    description="Complex academic query planning and paper ranking backend.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
service = SearchService()


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"ok": True, "service": "scholarpilot-fastapi", "version": "0.2.0"}


@app.post("/api/search")
def search(request: SearchRequest) -> dict[str, object]:
    try:
        return service.search(request.query, request.mode, request.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

