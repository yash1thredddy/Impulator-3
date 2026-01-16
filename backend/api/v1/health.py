"""
Health check endpoints.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.config import settings
from backend.core.database import get_db
from backend.core.executor import job_executor
from backend.core.azure_sync import is_azure_configured
from backend.models.schemas import HealthResponse, ExecutorStats

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Check health of all services.

    Returns:
        HealthResponse with status of database and executor
    """
    # Check database
    db_healthy = False
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if db_healthy else "degraded",
        version=settings.APP_VERSION,
        database=db_healthy,
        azure_configured=is_azure_configured(),
        executor_active_jobs=job_executor.get_active_count(),
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)) -> dict:
    """
    Kubernetes/container readiness probe.
    Returns 200 if service is ready to accept traffic.
    """
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        # Don't expose internal error details
        return {"status": "not ready", "error": "Database connection failed"}


@router.get("/live")
async def liveness_check() -> dict:
    """
    Kubernetes/container liveness probe.
    Returns 200 if service is alive.
    """
    return {"status": "alive"}


@router.get("/executor", response_model=ExecutorStats)
async def executor_stats() -> ExecutorStats:
    """
    Get executor statistics.

    Returns:
        ExecutorStats with current job queue status
    """
    stats = job_executor.stats()
    return ExecutorStats(**stats)
