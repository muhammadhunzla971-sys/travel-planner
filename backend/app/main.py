"""FastAPI entrypoint. Step 1: skeleton + health endpoints."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

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


@app.get("/")
async def root() -> dict:
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
