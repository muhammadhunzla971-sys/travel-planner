"""FastAPI entrypoint. Step 1: skeleton + health endpoints."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.api.routes import router as api_router
from app.config import get_settings
from app.web import PAGE_HTML

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent travel planner: orchestrator + flight, stay and activities agents.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router, prefix="/api")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home() -> HTMLResponse:
    return HTMLResponse(PAGE_HTML)


@app.get("/api-info")
async def api_info() -> dict:
    return {"message": f"{settings.app_name} is running", "docs": "/docs"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        # Only report whether a key is set, never the key itself.
        "llm_key_configured": bool(
            settings.groq_api_key if settings.llm_provider == "groq" else settings.gemini_api_key
        ),
    }
