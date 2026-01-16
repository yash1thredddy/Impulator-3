"""
Job API endpoints.
Handles job submission, status tracking, and cancellation.

Session Isolation:
- Each browser session has a unique session_id (passed in X-Session-ID header)
- Users only see their own jobs in the sidebar
- Jobs can be grouped into batches for bulk operations

Rate Limiting:
- Per-session rate limiting to prevent abuse
- Configurable limits for single jobs and batch submissions
"""
import logging
import time
import threading
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.executor import job_executor
from backend.core.scheduler import job_scheduler
from backend.core import sanitize_compound_name
from backend.models.database import JobStatus, JobType
from backend.models.schemas import (
    JobCreate,
    BatchJobCreate,
    JobResponse,
    JobListResponse,
    ActiveJobResponse,
    BatchSummary,
    ErrorResponse,
    CheckDuplicatesRequest,
    CheckDuplicatesResponse,
)
from backend.services.job_service import job_service
from backend.core.azure_sync import delete_result_from_azure
from backend.core.audit import (
    log_rate_limit_exceeded,
    log_job_cancelled,
    log_job_deleted,
)
from backend.config import settings

logger = logging.getLogger(__name__)

# Rate limiting configuration
RATE_LIMIT_WINDOW_SECONDS = 60  # 1 minute window
RATE_LIMIT_MAX_JOBS = 10  # Max 10 single jobs per minute per session
RATE_LIMIT_MAX_BATCH = 3  # Max 3 batch submissions per minute per session


class RateLimiter:
    """Simple in-memory rate limiter per session.

    Thread-safe implementation using defaultdict and locks.
    Automatically cleans up old entries to prevent memory leaks.
    """

    def __init__(self):
        self._requests: dict = defaultdict(list)  # session_id -> [timestamps]
        self._lock = threading.Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # Cleanup every 5 minutes

    def _cleanup_old_entries(self) -> None:
        """Remove old timestamps from all sessions."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        sessions_to_remove = []

        for session_id, timestamps in self._requests.items():
            # Filter out old timestamps
            self._requests[session_id] = [t for t in timestamps if t > cutoff]
            if not self._requests[session_id]:
                sessions_to_remove.append(session_id)

        # Remove empty sessions
        for session_id in sessions_to_remove:
            del self._requests[session_id]

        self._last_cleanup = now

    def check_rate_limit(self, session_id: str, limit: int) -> tuple[bool, int]:
        """Check if request is within rate limit.

        Args:
            session_id: Session identifier (or IP if no session)
            limit: Maximum requests allowed in window

        Returns:
            Tuple of (allowed: bool, remaining: int)
        """
        if not session_id:
            session_id = "anonymous"

        with self._lock:
            self._cleanup_old_entries()

            now = time.time()
            cutoff = now - RATE_LIMIT_WINDOW_SECONDS

            # Filter old timestamps for this session
            timestamps = [t for t in self._requests[session_id] if t > cutoff]
            self._requests[session_id] = timestamps

            if len(timestamps) >= limit:
                return False, 0

            # Add new timestamp
            self._requests[session_id].append(now)
            return True, limit - len(timestamps) - 1


# Global rate limiter instance
rate_limiter = RateLimiter()

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def _job_to_response(job) -> JobResponse:
    """Convert Job model to JobResponse, extracting compound info from input_params."""
    import json

    data = {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "current_step": job.current_step,
        "result_path": job.result_path,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "session_id": job.session_id,
        "batch_id": job.batch_id,
    }

    # Extract compound_name and smiles from input_params
    if job.input_params:
        try:
            params = json.loads(job.input_params)
            data["compound_name"] = params.get("compound_name")
            data["smiles"] = params.get("smiles")
        except (json.JSONDecodeError, TypeError):
            pass

    return JobResponse(**data)


@router.post(
    "",
    response_model=JobResponse,
    status_code=201,
    responses={429: {"model": ErrorResponse}},
    summary="Submit a new job",
)
async def create_job(
    request: JobCreate,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """
    Submit a new compound processing job.

    The job runs in the background. Use GET /jobs/{id} to check status.
    Jobs are queued in SQLite and picked up by the scheduler.

    Headers:
        X-Session-ID: Optional session ID for user isolation

    Rate Limit:
        Max 10 jobs per minute per session
    """
    # Use session_id from header or request body
    session_id = x_session_id or request.session_id

    # Check rate limit
    allowed, remaining = rate_limiter.check_rate_limit(session_id, RATE_LIMIT_MAX_JOBS)
    if not allowed:
        logger.warning(f"Rate limit exceeded for session {session_id}")
        log_rate_limit_exceeded(session_id, "single_job", RATE_LIMIT_MAX_JOBS)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MAX_JOBS} jobs per minute.",
            headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
        )

    # Create job record with session_id (status: PENDING)
    job = job_service.create_job(
        db,
        JobType.SINGLE,
        request.model_dump(exclude={"session_id"}),
        session_id=session_id,
    )

    # Trigger scheduler to start processing (if not already running)
    job_scheduler.trigger()

    logger.info(f"Job {job.id} queued for {request.compound_name} (session={session_id}, remaining={remaining})")
    return _job_to_response(job)


@router.post(
    "/check-duplicates",
    response_model=CheckDuplicatesResponse,
    summary="Check for duplicate compounds",
)
async def check_duplicates(
    request: CheckDuplicatesRequest,
    db: Session = Depends(get_db),
):
    """
    Check which compounds already exist or are being processed.

    Use this before batch submission to show users which compounds
    will be skipped, allowing them to confirm before proceeding.

    Returns:
        - existing: Compounds that already have results in Azure/local storage
        - processing: Compounds currently being processed
        - new: Compounds that will be processed
    """
    compound_names = request.compound_names

    # Check for already processed compounds
    existing_map = job_service.check_existing_compounds(db, compound_names)
    existing = [name for name, exists in existing_map.items() if exists]

    # Check for currently processing compounds
    pending_map = job_service.check_pending_compounds(db, compound_names)
    processing = list(pending_map.keys())

    # Calculate new compounds
    skip_set = set(existing) | set(processing)
    new = [name for name in compound_names if name not in skip_set]

    logger.info(f"Duplicate check: {len(existing)} existing, {len(processing)} processing, {len(new)} new")

    return CheckDuplicatesResponse(
        existing=existing,
        processing=processing,
        new=new,
    )


@router.post(
    "/batch",
    status_code=201,
    responses={429: {"model": ErrorResponse}},
    summary="Submit a batch of jobs",
)
async def create_batch_job(
    request: BatchJobCreate,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """
    Submit multiple compound processing jobs.

    Each compound is processed as a separate job, linked by batch_id.

    Features:
    - Skips compounds that already have results (if skip_existing=True)
    - Skips compounds currently being processed
    - Groups all jobs under a single batch_id for batch operations

    Headers:
        X-Session-ID: Optional session ID for user isolation

    Returns:
        Dict with created jobs, skipped compounds, and batch summary
    """
    # Use session_id from header or request body
    session_id = x_session_id or request.session_id

    # Check rate limit for batch submissions
    allowed, remaining = rate_limiter.check_rate_limit(
        f"{session_id}_batch", RATE_LIMIT_MAX_BATCH
    )
    if not allowed:
        logger.warning(f"Batch rate limit exceeded for session {session_id}")
        log_rate_limit_exceeded(session_id, "batch_job", RATE_LIMIT_MAX_BATCH)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MAX_BATCH} batch submissions per minute.",
            headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
        )

    # Generate a batch_id to link all jobs
    batch_id = job_service.generate_batch_id()

    # Check for duplicates if skip_existing is enabled
    compound_names = [c.compound_name for c in request.compounds]

    skipped_existing = []
    skipped_processing = []

    if request.skip_existing:
        # Check for already processed compounds
        existing = job_service.check_existing_compounds(db, compound_names)
        skipped_existing = [name for name, exists in existing.items() if exists]

        # Check for currently processing compounds
        pending = job_service.check_pending_compounds(db, compound_names)
        skipped_processing = list(pending.keys())

    # Filter compounds to process
    skip_names = set(skipped_existing) | set(skipped_processing)
    compounds_to_process = [c for c in request.compounds if c.compound_name not in skip_names]

    if not compounds_to_process:
        return {
            "batch_id": batch_id,
            "jobs": [],
            "skipped_existing": skipped_existing,
            "skipped_processing": skipped_processing,
            "message": "All compounds already exist or are being processed",
        }

    # Create all jobs in SQLite (status: PENDING)
    # Scheduler will pick them up and process 2 at a time
    jobs = []
    for compound in compounds_to_process:
        job = job_service.create_job(
            db,
            JobType.BATCH,
            compound.model_dump(exclude={"session_id"}),
            session_id=session_id,
            batch_id=batch_id,
        )
        jobs.append(_job_to_response(job))

    # Trigger scheduler to start processing (if not already running)
    job_scheduler.trigger()

    logger.info(f"Batch {batch_id}: {len(jobs)} jobs queued (session={session_id})")

    return {
        "batch_id": batch_id,
        "jobs": jobs,
        "skipped_existing": skipped_existing,
        "skipped_processing": skipped_processing,
        "total_submitted": len(jobs),
        "total_skipped": len(skip_names),
    }


@router.get(
    "",
    response_model=JobListResponse,
    summary="List all jobs",
)
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    List all jobs with optional status filter and pagination.
    """
    statuses = [status] if status else None
    result = job_service.list_jobs(db, statuses=statuses, page=page, page_size=page_size)

    return JobListResponse(
        items=[_job_to_response(j) for j in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        pages=result["pages"],
    )


@router.get(
    "/active",
    response_model=List[ActiveJobResponse],
    summary="Get active jobs for sidebar",
)
async def get_active_jobs(
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """
    Get active (pending/processing) jobs for the current session.

    Used by the frontend sidebar to display job progress.
    Users only see their own jobs when X-Session-ID is provided.

    Headers:
        X-Session-ID: Session ID for filtering jobs (required for isolation)
    """
    return job_service.get_active_jobs(db, session_id=x_session_id)


@router.get(
    "/batch/{batch_id}",
    response_model=BatchSummary,
    summary="Get batch summary",
)
async def get_batch_summary(
    batch_id: str,
    db: Session = Depends(get_db),
):
    """
    Get summary statistics for a batch of jobs.

    Returns overall progress and status counts.
    """
    summary = job_service.get_batch_summary(db, batch_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Batch not found")
    return summary


@router.post(
    "/batch/{batch_id}/cancel",
    summary="Cancel all jobs in a batch",
)
async def cancel_batch(
    batch_id: str,
    db: Session = Depends(get_db),
):
    """
    Cancel all pending/processing jobs in a batch.

    Already completed or failed jobs are not affected.
    """
    cancelled_count = job_service.cancel_batch(db, batch_id)

    # Also cancel in executor
    # Note: Jobs already running may not stop immediately
    return {
        "batch_id": batch_id,
        "cancelled_count": cancelled_count,
        "message": f"Cancelled {cancelled_count} jobs in batch",
    }


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get job status",
)
async def get_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    """
    Get the current status of a job.

    Poll this endpoint (1s interval) to track progress.
    """
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _job_to_response(job)


@router.get(
    "/{job_id}/detail",
    responses={404: {"model": ErrorResponse}},
    summary="Get detailed job info",
)
async def get_job_detail(
    job_id: str,
    db: Session = Depends(get_db),
):
    """
    Get detailed job information including parsed input parameters.
    """
    job = job_service.get_job_with_params(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    summary="Cancel a job",
)
async def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """
    Cancel a pending or processing job.

    Note: Jobs already running may not be cancelled immediately.
    """
    import json

    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Job cannot be cancelled (status: {job.status.value})",
        )

    # Extract compound name for audit log
    compound_name = None
    if job.input_params:
        try:
            params = json.loads(job.input_params)
            compound_name = params.get("compound_name")
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to cancel in executor
    executor_cancelled = job_executor.cancel(job_id)

    # Always mark as cancelled in DB
    job = job_service.cancel_job(db, job_id)

    # Audit log
    log_job_cancelled(x_session_id or "unknown", job_id, compound_name)

    if not executor_cancelled:
        logger.warning(f"Job {job_id} marked cancelled but was already running")

    return _job_to_response(job)


@router.delete(
    "/{job_id}",
    responses={404: {"model": ErrorResponse}},
    summary="Delete a job record",
)
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """
    Delete a job record and associated result files.

    - Deletes job from database
    - Deletes result ZIP from Azure
    - Deletes local result files

    Only completed, failed, or cancelled jobs can be deleted.
    """
    import json
    from pathlib import Path

    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in [JobStatus.PENDING, JobStatus.PROCESSING]:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete active jobs. Cancel first.",
        )

    # Extract compound name from job params for file cleanup
    compound_name = None
    if job.input_params:
        try:
            params = json.loads(job.input_params)
            compound_name = params.get("compound_name")
        except (json.JSONDecodeError, TypeError):
            pass

    # Clean up result files
    if compound_name:
        # Sanitize name (consistent with compound_service)
        safe_name = sanitize_compound_name(compound_name)

        # Delete from Azure
        delete_result_from_azure(compound_name)

        # Delete local ZIP if exists
        local_zip = settings.RESULTS_DIR / f"{safe_name}.zip"
        if local_zip.exists():
            try:
                local_zip.unlink()
                logger.info(f"Deleted local result: {local_zip}")
            except Exception as e:
                logger.warning(f"Failed to delete local result: {e}")

    # Audit log before deletion
    log_job_deleted(x_session_id or "unknown", job_id, compound_name)

    # Delete job record from database
    job_service.delete_job(db, job_id)

    return {
        "message": "Job and results deleted",
        "job_id": job_id,
        "compound_name": compound_name,
    }
