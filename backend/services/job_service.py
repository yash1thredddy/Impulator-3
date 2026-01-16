"""
Job service for CRUD operations and state management.
Handles job creation, progress updates, and completion tracking.
"""
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.models.database import Job, JobStatus, JobType
from backend.core.azure_sync import sync_db_to_azure

logger = logging.getLogger(__name__)


def _safe_json_loads(json_str: Optional[str], default: Any = None) -> Any:
    """Safely parse JSON string, returning default on failure."""
    if not json_str:
        return default
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse JSON: {e}")
        return default


class JobService:
    """Service for job management operations."""

    def create_job(
        self,
        db: Session,
        job_type: JobType,
        input_params: Dict[str, Any],
        session_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Job:
        """
        Create a new job record.

        Args:
            db: Database session
            job_type: Type of job (single/batch)
            input_params: Input parameters for the job
            session_id: Session ID for user isolation
            batch_id: Batch ID for grouping related jobs

        Returns:
            Created Job object
        """
        job = Job(
            id=str(uuid.uuid4()),
            job_type=job_type,
            status=JobStatus.PENDING,
            session_id=session_id,
            batch_id=batch_id,
            input_params=json.dumps(input_params),
            progress=0.0,
            current_step="Queued",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        logger.info(f"Created job {job.id} ({job_type.value}) session={session_id} batch={batch_id}")
        return job

    def generate_batch_id(self) -> str:
        """Generate a new batch ID for grouping jobs."""
        return str(uuid.uuid4())

    def get_job(self, db: Session, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return db.query(Job).filter(Job.id == job_id).first()

    def _get_job_for_update(self, db: Session, job_id: str) -> Optional[Job]:
        """Get a job by ID with row-level lock for safe updates.

        Uses with_for_update() to prevent race conditions when
        multiple threads try to update the same job.
        """
        return (
            db.query(Job)
            .filter(Job.id == job_id)
            .with_for_update()
            .first()
        )

    def get_job_with_params(self, db: Session, job_id: str) -> Optional[Dict]:
        """Get job with parsed input parameters."""
        job = self.get_job(db, job_id)
        if not job:
            return None

        result = job.to_dict()
        if job.input_params:
            result["input_params"] = _safe_json_loads(job.input_params, {})
        if job.result_summary:
            result["result_summary"] = _safe_json_loads(job.result_summary, {})
        return result

    def list_jobs(
        self,
        db: Session,
        statuses: Optional[List[JobStatus]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict:
        """
        List jobs with optional status filter and pagination.

        Args:
            db: Database session
            statuses: Optional list of statuses to filter by
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Dict with items, total, page info
        """
        query = db.query(Job)

        if statuses:
            query = query.filter(Job.status.in_(statuses))

        total = query.count()
        pages = (total + page_size - 1) // page_size

        jobs = (
            query.order_by(desc(Job.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "items": jobs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_active_jobs(
        self,
        db: Session,
        session_id: Optional[str] = None,
        include_recent_minutes: int = 2,
    ) -> List[Dict]:
        """
        Get active (pending/processing) jobs and recently completed jobs for sidebar.

        Includes recently completed/failed jobs so users can see "View" button
        before they disappear from the list.

        Args:
            db: Database session
            session_id: Session ID to filter by (None returns all - for admin)
            include_recent_minutes: Include completed jobs from last N minutes

        Returns:
            List of job dicts with progress info
        """
        from datetime import timedelta

        # Get pending/processing jobs
        active_query = db.query(Job).filter(
            Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])
        )
        if session_id:
            active_query = active_query.filter(Job.session_id == session_id)
        active_jobs = active_query.all()

        # Get recently completed/failed jobs (within last N minutes)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=include_recent_minutes)
        recent_query = db.query(Job).filter(
            Job.status.in_([JobStatus.COMPLETED, JobStatus.FAILED]),
            Job.completed_at >= recent_cutoff
        )
        if session_id:
            recent_query = recent_query.filter(Job.session_id == session_id)
        recent_jobs = recent_query.all()

        # Combine and sort by created_at
        all_jobs = active_jobs + recent_jobs
        all_jobs.sort(key=lambda j: j.created_at or datetime.min.replace(tzinfo=timezone.utc))

        result = []
        for job in all_jobs:
            item = {
                "id": job.id,
                "status": job.status.value,
                "progress": job.progress,
                "current_step": job.current_step,
                "batch_id": job.batch_id,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
            # Extract compound name from input params
            params = _safe_json_loads(job.input_params, {})
            item["compound_name"] = params.get("compound_name", "Unknown")
            result.append(item)

        return result

    def get_batch_summary(self, db: Session, batch_id: str) -> Dict:
        """
        Get summary statistics for a batch of jobs.

        Args:
            db: Database session
            batch_id: Batch ID to summarize

        Returns:
            Dict with batch statistics
        """
        jobs = db.query(Job).filter(Job.batch_id == batch_id).all()

        if not jobs:
            return {}

        completed = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
        processing = sum(1 for j in jobs if j.status == JobStatus.PROCESSING)
        pending = sum(1 for j in jobs if j.status == JobStatus.PENDING)
        failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)
        cancelled = sum(1 for j in jobs if j.status == JobStatus.CANCELLED)

        # Overall progress: average of all job progress
        total_progress = sum(j.progress for j in jobs)
        overall_progress = total_progress / len(jobs) if jobs else 0

        # Get compound names
        compound_names = []
        for job in jobs[:5]:  # Limit to first 5 for display
            params = _safe_json_loads(job.input_params, {})
            compound_names.append(params.get("compound_name", "Unknown"))

        return {
            "batch_id": batch_id,
            "total_jobs": len(jobs),
            "completed": completed,
            "processing": processing,
            "pending": pending,
            "failed": failed,
            "cancelled": cancelled,
            "overall_progress": overall_progress,
            "created_at": jobs[0].created_at.isoformat() if jobs[0].created_at else None,
            "compound_names": compound_names,
        }

    def cancel_batch(self, db: Session, batch_id: str) -> int:
        """
        Cancel all pending/processing jobs in a batch.

        Args:
            db: Database session
            batch_id: Batch ID to cancel

        Returns:
            Number of jobs cancelled
        """
        jobs = (
            db.query(Job)
            .filter(
                Job.batch_id == batch_id,
                Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])
            )
            .all()
        )

        cancelled_count = 0
        for job in jobs:
            job.status = JobStatus.CANCELLED
            job.current_step = "Cancelled"
            job.completed_at = datetime.now(timezone.utc)
            cancelled_count += 1

        if cancelled_count > 0:
            db.commit()
            logger.info(f"Cancelled {cancelled_count} jobs in batch {batch_id}")

        return cancelled_count

    def check_existing_compounds(
        self,
        db: Session,
        compound_names: List[str],
    ) -> Dict[str, bool]:
        """
        Check which compounds already have completed results.

        Checks both local SQLite Compound table AND Azure Blob storage.
        This ensures duplicates are detected even if local DB is out of sync.

        Args:
            db: Database session
            compound_names: List of compound names to check

        Returns:
            Dict mapping compound_name -> exists (True if already processed)
        """
        from backend.models.database import Compound
        from backend.core.azure_sync import check_result_exists_in_azure, is_azure_configured

        # Batch query: get all matching compounds in a single query
        existing_compounds = (
            db.query(Compound.compound_name)
            .filter(Compound.compound_name.in_(compound_names))
            .all()
        )
        local_existing = {row[0] for row in existing_compounds}

        result = {}
        for name in compound_names:
            if name in local_existing:
                result[name] = True
            elif is_azure_configured():
                # Only check Azure for compounds not found locally
                result[name] = check_result_exists_in_azure(name)
            else:
                result[name] = False

        return result

    def check_pending_compounds(
        self,
        db: Session,
        compound_names: List[str],
    ) -> Dict[str, str]:
        """
        Check which compounds are currently being processed.

        Args:
            db: Database session
            compound_names: List of compound names to check

        Returns:
            Dict mapping compound_name -> job_id (if pending/processing)
        """
        # Single query to get all pending/processing jobs
        pending_jobs = (
            db.query(Job)
            .filter(Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]))
            .all()
        )

        # Build a map of compound_name -> job_id for all pending jobs
        compound_to_job = {}
        for job in pending_jobs:
            params = _safe_json_loads(job.input_params, {})
            compound_name = params.get("compound_name")
            if compound_name:
                compound_to_job[compound_name] = job.id

        # Return only the requested compound names that are pending
        result = {}
        compound_names_set = set(compound_names)
        for name, job_id in compound_to_job.items():
            if name in compound_names_set:
                result[name] = job_id

        return result

    def update_progress(
        self,
        db: Session,
        job_id: str,
        progress: float,
        current_step: str,
        status: Optional[JobStatus] = None,
    ) -> Optional[Job]:
        """
        Update job progress with row-level locking to prevent race conditions.

        Args:
            db: Database session
            job_id: Job ID
            progress: Progress percentage (0-100)
            current_step: Description of current step
            status: Optional status update
        """
        job = self._get_job_for_update(db, job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for progress update")
            return None

        job.progress = progress
        job.current_step = current_step

        if status:
            job.status = status
            if status == JobStatus.PROCESSING and not job.started_at:
                job.started_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(job)
        return job

    def complete_job(
        self,
        db: Session,
        job_id: str,
        result_path: str,
        result_summary: Dict[str, Any],
    ) -> Optional[Job]:
        """
        Mark job as completed, update Compound table, and trigger Azure sync.

        Uses row-level locking to prevent race conditions.

        Args:
            db: Database session
            job_id: Job ID
            result_path: Path to result file
            result_summary: Summary statistics
        """
        job = self._get_job_for_update(db, job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for completion")
            return None

        job.status = JobStatus.COMPLETED
        job.progress = 100.0
        job.current_step = "Completed"
        job.result_path = result_path
        job.result_summary = json.dumps(result_summary)
        job.completed_at = datetime.now(timezone.utc)

        # Update Compound table for local DB consistency
        self._update_compound_entry(db, result_summary, result_path)

        db.commit()
        db.refresh(job)

        # Immediate sync to Azure
        sync_db_to_azure()

        logger.info(f"Job {job_id} completed successfully")
        return job

    def _update_compound_entry(
        self,
        db: Session,
        result_summary: Dict[str, Any],
        result_path: str
    ) -> None:
        """
        Create or update Compound entry in local database.

        This ensures the Compound table stays in sync with completed jobs,
        without waiting for the next startup sync from Azure.

        Args:
            db: Database session
            result_summary: Summary from job processing
            result_path: Path to result file
        """
        from backend.models.database import Compound

        compound_name = result_summary.get('compound_name')
        if not compound_name:
            logger.warning("No compound_name in result_summary, skipping Compound update")
            return

        try:
            # Check if compound exists
            existing = db.query(Compound).filter(
                Compound.compound_name == compound_name
            ).first()

            if existing:
                # Update existing entry
                existing.smiles = result_summary.get('smiles') or result_summary.get('query_smiles')
                existing.chembl_id = result_summary.get('chembl_id', '')
                existing.total_activities = result_summary.get('total_activities', 0)
                existing.imp_candidates = result_summary.get('imp_candidates', 0)
                existing.avg_oqpla_score = result_summary.get('avg_oqpla_score')
                existing.storage_path = result_path
                logger.info(f"Updated Compound entry: {compound_name}")
            else:
                # Create new entry
                compound = Compound(
                    compound_name=compound_name,
                    smiles=result_summary.get('smiles') or result_summary.get('query_smiles'),
                    chembl_id=result_summary.get('chembl_id', ''),
                    total_activities=result_summary.get('total_activities', 0),
                    imp_candidates=result_summary.get('imp_candidates', 0),
                    avg_oqpla_score=result_summary.get('avg_oqpla_score'),
                    storage_path=result_path,
                )
                db.add(compound)
                logger.info(f"Created Compound entry: {compound_name}")

        except Exception as e:
            logger.error(f"Failed to update Compound entry for {compound_name}: {e}")

    def fail_job(
        self,
        db: Session,
        job_id: str,
        error_message: str,
    ) -> Optional[Job]:
        """
        Mark job as failed with row-level locking.

        Args:
            db: Database session
            job_id: Job ID
            error_message: Error description
        """
        job = self._get_job_for_update(db, job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for failure")
            return None

        job.status = JobStatus.FAILED
        job.current_step = "Failed"
        job.error_message = error_message
        job.completed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(job)

        # Sync to Azure (even failures should be persisted)
        sync_db_to_azure()

        logger.error(f"Job {job_id} failed: {error_message}")
        return job

    def cancel_job(
        self,
        db: Session,
        job_id: str,
    ) -> Optional[Job]:
        """
        Mark job as cancelled with row-level locking.

        Args:
            db: Database session
            job_id: Job ID
        """
        job = self._get_job_for_update(db, job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for cancellation")
            return None

        if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            logger.warning(f"Job {job_id} cannot be cancelled (status: {job.status})")
            return job

        job.status = JobStatus.CANCELLED
        job.current_step = "Cancelled"
        job.completed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(job)

        logger.info(f"Job {job_id} cancelled")
        return job

    def delete_job(self, db: Session, job_id: str) -> bool:
        """
        Delete a job record.

        Args:
            db: Database session
            job_id: Job ID

        Returns:
            True if deleted, False if not found
        """
        job = self.get_job(db, job_id)
        if not job:
            return False

        db.delete(job)
        db.commit()
        logger.info(f"Job {job_id} deleted")
        return True


# Global service instance
job_service = JobService()
