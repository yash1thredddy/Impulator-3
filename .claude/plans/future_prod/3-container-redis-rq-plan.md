# Backend/Frontend Separation Plan for IMPULATOR

> **Version**: 3.0 (Simplified for HF Spaces Free Tier)
> **Last Updated**: 2024-12-31
> **Status**: Ready for Implementation

---

## Overview

Single-container architecture for HuggingFace Spaces free tier:
- **Backend**: FastAPI with BackgroundTasks + ThreadPoolExecutor
- **Frontend**: Streamlit (calls FastAPI via HTTP)
- **Database**: SQLite (job state + compound metadata)
- **Caching**: In-memory LRU (max 2000 per function)
- **Real-time**: SSE/Polling for progress
- **Container**: 1 single container

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      SINGLE CONTAINER                            │
│                                                                  │
│  ┌──────────────────┐         ┌──────────────────────────────┐  │
│  │    Streamlit     │  HTTP   │          FastAPI             │  │
│  │    (Port 7860)   │────────►│        (Port 8000)           │  │
│  │                  │         │                              │  │
│  │  - UI Forms      │         │  ┌────────────────────────┐  │  │
│  │  - Visualizations│◄────────│  │   ThreadPoolExecutor   │  │  │
│  │  - Progress bars │   SSE   │  │   (max_workers=2)      │  │  │
│  └──────────────────┘         │  └────────────────────────┘  │  │
│                               │             │                 │  │
│                               │      ┌──────┴──────┐         │  │
│                               │      ▼             ▼         │  │
│                               │  ┌───────┐   ┌──────────┐    │  │
│                               │  │SQLite │   │LRU Cache │    │  │
│                               │  │(jobs) │   │(2000/fn) │    │  │
│                               │  └───────┘   └──────────┘    │  │
│                               └──────────────────────────────┘  │
│                                          │                       │
│                                          ▼                       │
│                               ┌──────────────────────┐          │
│                               │   External APIs      │          │
│                               │  ChEMBL, PDB, etc.   │          │
│                               └──────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
Impulator/
├── backend/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # Settings (pydantic-settings)
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py       # Route aggregator
│   │       ├── health.py       # GET /health
│   │       ├── jobs.py         # POST /jobs, GET /jobs/{id}
│   │       └── compounds.py    # GET /compounds, GET /compounds/{name}
│   ├── core/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLAlchemy + SQLite
│   │   └── executor.py         # ThreadPoolExecutor wrapper
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py         # Job, Compound ORM models
│   │   └── schemas.py          # Pydantic request/response
│   └── services/
│       ├── __init__.py
│       ├── job_service.py      # Job CRUD + state management
│       └── compound_service.py # Processing logic wrapper
├── frontend/
│   ├── __init__.py
│   ├── app.py                  # Streamlit main app
│   ├── api_client.py           # HTTP client for FastAPI
│   └── components/             # UI components
│       ├── __init__.py
│       ├── input_form.py
│       ├── progress.py
│       └── results.py
├── modules/                    # Chemistry modules (decoupled)
│   ├── __init__.py
│   ├── api_client.py           # ChEMBL API (with LRU cache)
│   ├── pdb_client.py           # PDB API (with LRU cache)
│   ├── data_processor.py       # Main processing logic
│   ├── oqpla_scoring.py        # OQPLA scoring
│   ├── pains_filter.py         # PAINS filtering
│   └── storage.py              # ZIP/result storage
├── data/                       # SQLite + results (gitignored)
├── requirements.txt
├── Dockerfile
├── start.sh
└── .env.example
```

---

## Phase 1: Simplify Existing Backend (Update)

### Goal
Remove Redis dependencies, simplify to LRU cache.

### Files to Modify

**1. `backend/config.py`** - Remove Redis settings:
```python
class Settings(BaseSettings):
    APP_NAME: str = "Impulator"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    # Server
    HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    FRONTEND_PORT: int = 7860

    # Database
    DATABASE_URL: str = "sqlite:///./data/impulator.db"

    # Job executor
    MAX_WORKERS: int = 2  # Limit concurrent jobs
    JOB_TIMEOUT: int = 3600  # 1 hour max

    # Cache
    CACHE_SIZE: int = 2000  # Per function

    # External APIs
    CHEMBL_API_URL: str = "https://www.ebi.ac.uk/chembl/api/data"
    PDB_API_URL: str = "https://search.rcsb.org/rcsbsearch/v2/query"

    # Storage
    DATA_DIR: Path = Path("./data")
    RESULTS_DIR: Path = Path("./data/results")
```

**2. Delete `backend/core/cache.py`** - No longer needed (using functools.lru_cache)

**3. Update `backend/core/database.py`** - Remove Redis health check

---

## Phase 2: Job Executor + Management

### Goal
Create ThreadPoolExecutor-based job system with SQLite state.

### Files to Create

**1. `backend/core/executor.py`** - Job executor:
```python
"""
ThreadPoolExecutor-based job executor.
Limits concurrent jobs and tracks state in SQLite.
"""
import uuid
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Dict, Any, Optional

from backend.config import settings

logger = logging.getLogger(__name__)


class JobExecutor:
    """Manages background job execution with concurrency limits."""

    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or settings.MAX_WORKERS
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._futures: Dict[str, Future] = {}

    def submit(
        self,
        job_id: str,
        func: Callable,
        *args,
        **kwargs
    ) -> str:
        """
        Submit a job for background execution.

        Args:
            job_id: Unique job identifier
            func: Function to execute
            *args, **kwargs: Arguments for the function

        Returns:
            job_id
        """
        future = self._executor.submit(func, job_id, *args, **kwargs)
        self._futures[job_id] = future

        # Cleanup callback
        future.add_done_callback(lambda f: self._cleanup(job_id))

        logger.info(f"Job {job_id} submitted")
        return job_id

    def _cleanup(self, job_id: str):
        """Remove completed future from tracking."""
        self._futures.pop(job_id, None)

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending job."""
        future = self._futures.get(job_id)
        if future and not future.done():
            return future.cancel()
        return False

    def is_running(self, job_id: str) -> bool:
        """Check if job is currently running."""
        future = self._futures.get(job_id)
        return future is not None and future.running()

    def get_queue_size(self) -> int:
        """Get number of pending/running jobs."""
        return len(self._futures)

    def shutdown(self, wait: bool = True):
        """Shutdown executor."""
        self._executor.shutdown(wait=wait)


# Global executor instance
job_executor = JobExecutor()
```

**2. `backend/services/job_service.py`** - Job state management:
```python
"""
Job state management with SQLite persistence.
"""
import uuid
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from backend.models.database import Job, JobStatus, JobType
from backend.core.database import get_db_session
from backend.core.executor import job_executor


class JobService:
    """Manages job lifecycle and state."""

    @staticmethod
    def create_job(
        db: Session,
        job_type: JobType,
        input_params: Dict[str, Any]
    ) -> Job:
        """Create a new job record."""
        job = Job(
            id=str(uuid.uuid4()),
            job_type=job_type,
            status=JobStatus.PENDING,
            input_params=json.dumps(input_params),
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def get_job(db: Session, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        return db.query(Job).filter(Job.id == job_id).first()

    @staticmethod
    def update_progress(
        db: Session,
        job_id: str,
        progress: float,
        current_step: str = None,
        status: JobStatus = None
    ):
        """Update job progress."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.progress = progress
            if current_step:
                job.current_step = current_step
            if status:
                job.status = status
                if status == JobStatus.PROCESSING and not job.started_at:
                    job.started_at = datetime.utcnow()
                elif status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                    job.completed_at = datetime.utcnow()
            db.commit()

    @staticmethod
    def complete_job(
        db: Session,
        job_id: str,
        result_path: str = None,
        result_summary: Dict = None
    ):
        """Mark job as completed."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.completed_at = datetime.utcnow()
            if result_path:
                job.result_path = result_path
            if result_summary:
                job.result_summary = json.dumps(result_summary)
            db.commit()

    @staticmethod
    def fail_job(db: Session, job_id: str, error_message: str):
        """Mark job as failed."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = error_message
            job.completed_at = datetime.utcnow()
            db.commit()

    @staticmethod
    def cancel_job(db: Session, job_id: str) -> bool:
        """Cancel a job."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if job and job.status in [JobStatus.PENDING, JobStatus.PROCESSING]:
            # Try to cancel in executor
            cancelled = job_executor.cancel(job_id)
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.utcnow()
            db.commit()
            return True
        return False

    @staticmethod
    def list_jobs(
        db: Session,
        limit: int = 20,
        offset: int = 0,
        status: JobStatus = None
    ) -> List[Job]:
        """List jobs with optional filtering."""
        query = db.query(Job)
        if status:
            query = query.filter(Job.status == status)
        return query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()


job_service = JobService()
```

**3. `backend/api/v1/jobs.py`** - Job API endpoints:
```python
"""
Job management API endpoints.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.executor import job_executor
from backend.services.job_service import job_service
from backend.services.compound_service import process_compound_job
from backend.models.database import JobStatus, JobType
from backend.models.schemas import (
    JobCreate,
    JobResponse,
    JobProgress,
    ErrorResponse,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("", response_model=JobResponse)
async def create_job(
    request: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a new compound processing job.
    Returns immediately with job_id for polling.
    """
    # Check queue capacity
    if job_executor.get_queue_size() >= job_executor.max_workers * 2:
        raise HTTPException(
            status_code=429,
            detail="Job queue is full. Please try again later."
        )

    # Create job record
    job = job_service.create_job(
        db,
        job_type=JobType.SINGLE,
        input_params={
            "compound_name": request.compound_name,
            "smiles": request.smiles,
            "similarity_threshold": request.similarity_threshold,
            "activity_types": request.activity_types,
        }
    )

    # Submit to executor
    job_executor.submit(
        job.id,
        process_compound_job,
        request.compound_name,
        request.smiles,
        request.similarity_threshold,
        request.activity_types,
    )

    return JobResponse.model_validate(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get job status and progress."""
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


@router.get("/{job_id}/stream")
async def stream_job_progress(job_id: str, db: Session = Depends(get_db)):
    """
    SSE endpoint for real-time job progress.

    Usage:
        const eventSource = new EventSource('/api/v1/jobs/{id}/stream');
        eventSource.onmessage = (e) => console.log(JSON.parse(e.data));
    """
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        while True:
            # Refresh job state
            db.refresh(job)

            data = {
                "job_id": job.id,
                "status": job.status.value,
                "progress": job.progress,
                "current_step": job.current_step,
            }
            yield f"data: {json.dumps(data)}\n\n"

            # Stop if job is done
            if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """Cancel a pending or running job."""
    success = job_service.cancel_job(db, job_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Job cannot be cancelled (already completed or not found)"
        )
    return {"status": "cancelled"}
```

---

## Phase 3: Compound Processing Service

### Goal
Wrap chemistry modules with progress callbacks, no Streamlit dependencies.

### Files to Create

**1. `backend/services/compound_service.py`**:
```python
"""
Compound processing service.
Wraps chemistry modules with progress tracking.
"""
import logging
from typing import List, Optional, Callable
from datetime import datetime

from backend.core.database import get_db_session
from backend.services.job_service import job_service
from backend.models.database import JobStatus

# Import chemistry modules (will be decoupled)
from modules.api_client import get_similar_compounds, get_activities
from modules.data_processor import process_activities
from modules.oqpla_scoring import calculate_oqpla_scores
from modules.pains_filter import filter_pains
from modules.storage import save_results

logger = logging.getLogger(__name__)


def process_compound_job(
    job_id: str,
    compound_name: str,
    smiles: str,
    similarity_threshold: int = 90,
    activity_types: Optional[List[str]] = None,
):
    """
    Main compound processing function.
    Runs in background thread, updates progress in SQLite.
    """
    try:
        with get_db_session() as db:
            # Mark as processing
            job_service.update_progress(
                db, job_id,
                progress=0.0,
                current_step="Starting...",
                status=JobStatus.PROCESSING
            )

        # Step 1: Find similar compounds (20%)
        _update_progress(job_id, 5.0, "Searching ChEMBL for similar compounds...")
        similar_compounds = get_similar_compounds(smiles, similarity_threshold)
        _update_progress(job_id, 20.0, f"Found {len(similar_compounds)} similar compounds")

        # Step 2: Fetch activities (40%)
        _update_progress(job_id, 25.0, "Fetching bioactivity data...")
        activities = get_activities(similar_compounds, activity_types)
        _update_progress(job_id, 40.0, f"Retrieved {len(activities)} activities")

        # Step 3: Process and filter (60%)
        _update_progress(job_id, 45.0, "Processing activities...")
        processed = process_activities(activities)
        _update_progress(job_id, 50.0, "Applying PAINS filter...")
        filtered = filter_pains(processed)
        _update_progress(job_id, 60.0, f"{len(filtered)} compounds after filtering")

        # Step 4: OQPLA scoring (80%)
        _update_progress(job_id, 65.0, "Calculating OQPLA scores...")
        scored = calculate_oqpla_scores(filtered, smiles)
        _update_progress(job_id, 80.0, "Scoring complete")

        # Step 5: Save results (100%)
        _update_progress(job_id, 85.0, "Saving results...")
        result_path = save_results(compound_name, scored)

        # Complete job
        with get_db_session() as db:
            job_service.complete_job(
                db, job_id,
                result_path=result_path,
                result_summary={
                    "compound_name": compound_name,
                    "similar_compounds": len(similar_compounds),
                    "total_activities": len(activities),
                    "filtered_compounds": len(filtered),
                    "imp_candidates": len(scored[scored["is_imp_candidate"]]) if "is_imp_candidate" in scored.columns else 0,
                }
            )

        logger.info(f"Job {job_id} completed successfully")

    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        with get_db_session() as db:
            job_service.fail_job(db, job_id, str(e))


def _update_progress(job_id: str, progress: float, step: str):
    """Helper to update job progress."""
    with get_db_session() as db:
        job_service.update_progress(db, job_id, progress, step)
```

---

## Phase 4: Decouple Chemistry Modules

### Goal
Remove all `st.*` calls from modules, add LRU caching.

### Files to Modify

**1. `modules/api_client.py`** - Remove Streamlit, add LRU:
```python
"""
ChEMBL API client with LRU caching.
"""
import logging
from functools import lru_cache
from typing import List, Optional, Dict, Any

import requests

from backend.config import settings

logger = logging.getLogger(__name__)
CACHE_SIZE = settings.CACHE_SIZE


@lru_cache(maxsize=CACHE_SIZE)
def get_compound_by_smiles(smiles: str) -> Optional[Dict[str, Any]]:
    """Fetch compound info from ChEMBL by SMILES."""
    # Implementation...
    pass


@lru_cache(maxsize=CACHE_SIZE)
def get_similar_compounds(
    smiles: str,
    similarity_threshold: int = 90
) -> List[str]:
    """Find similar compounds in ChEMBL."""
    # Implementation...
    pass


@lru_cache(maxsize=CACHE_SIZE)
def get_activities(
    compound_ids: tuple,  # Must be tuple for lru_cache (hashable)
    activity_types: tuple = None
) -> List[Dict]:
    """Fetch bioactivity data for compounds."""
    # Implementation...
    pass
```

**2. Similar changes for:**
- `modules/pdb_client.py` - Add `@lru_cache`, remove `st.*`
- `modules/data_processor.py` - Remove `st.progress()`, use callback
- `modules/oqpla_scoring.py` - Remove `st.info()`, pure functions

---

## Phase 5: Streamlit Frontend

### Goal
Create new Streamlit app that calls FastAPI backend.

### Files to Create

**1. `frontend/api_client.py`** - HTTP client:
```python
"""
HTTP client for FastAPI backend.
"""
import time
from typing import Optional, Dict, Any

import httpx

from backend.config import settings


class APIClient:
    """Client for backend API calls."""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or f"http://localhost:{settings.API_PORT}"
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def submit_job(
        self,
        compound_name: str,
        smiles: str,
        similarity_threshold: int = 90,
        activity_types: list = None,
    ) -> Dict[str, Any]:
        """Submit a processing job."""
        response = self.client.post(
            "/api/v1/jobs",
            json={
                "compound_name": compound_name,
                "smiles": smiles,
                "similarity_threshold": similarity_threshold,
                "activity_types": activity_types,
            }
        )
        response.raise_for_status()
        return response.json()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get job status."""
        response = self.client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def poll_job(
        self,
        job_id: str,
        callback: callable = None,
        interval: float = 0.5
    ) -> Dict[str, Any]:
        """Poll job until complete."""
        while True:
            job = self.get_job(job_id)

            if callback:
                callback(job)

            if job["status"] in ["completed", "failed", "cancelled"]:
                return job

            time.sleep(interval)

    def get_compounds(self, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """List processed compounds."""
        response = self.client.get(
            "/api/v1/compounds",
            params={"page": page, "limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def health_check(self) -> bool:
        """Check if backend is healthy."""
        try:
            response = self.client.get("/api/v1/health")
            return response.status_code == 200
        except:
            return False


# Global client instance
api_client = APIClient()
```

**2. `frontend/app.py`** - Main Streamlit app:
```python
"""
Streamlit frontend for Impulator.
"""
import streamlit as st
from frontend.api_client import api_client

st.set_page_config(page_title="Impulator", layout="wide")

# Check backend health
if not api_client.health_check():
    st.error("Backend is not available. Please wait...")
    st.stop()

st.title("Impulator - Impurity Modulator")

# Sidebar - Input form
with st.sidebar:
    st.header("Process New Compound")

    compound_name = st.text_input("Compound Name")
    smiles = st.text_input("SMILES")
    similarity = st.slider("Similarity Threshold", 50, 100, 90)

    if st.button("Process", disabled=not (compound_name and smiles)):
        # Submit job
        job = api_client.submit_job(compound_name, smiles, similarity)
        st.session_state["current_job"] = job["id"]
        st.rerun()

# Main area - Progress or Results
if "current_job" in st.session_state:
    job_id = st.session_state["current_job"]
    job = api_client.get_job(job_id)

    if job["status"] == "processing":
        st.subheader(f"Processing: {job['current_step']}")
        st.progress(job["progress"] / 100)

        # Auto-refresh
        import time
        time.sleep(1)
        st.rerun()

    elif job["status"] == "completed":
        st.success("Processing complete!")
        st.json(job.get("result_summary", {}))

        if st.button("Start New"):
            del st.session_state["current_job"]
            st.rerun()

    elif job["status"] == "failed":
        st.error(f"Processing failed: {job.get('error_message')}")

        if st.button("Try Again"):
            del st.session_state["current_job"]
            st.rerun()

else:
    # Show compound list
    st.subheader("Processed Compounds")
    compounds = api_client.get_compounds()

    if compounds["items"]:
        for c in compounds["items"]:
            with st.expander(c["compound_name"]):
                st.write(f"SMILES: {c['smiles']}")
                st.write(f"Activities: {c['total_activities']}")
                st.write(f"IMP Candidates: {c['imp_candidates']}")
    else:
        st.info("No compounds processed yet. Use the sidebar to start.")
```

---

## Phase 6: Single Container Deployment

### Files to Create

**1. `Dockerfile`**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Expose ports
EXPOSE 7860 8000

# Start script
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
```

**2. `start.sh`**:
```bash
#!/bin/bash

# Start FastAPI in background
uvicorn backend.main:app --host 0.0.0.0 --port 8000 &

# Wait for FastAPI to be ready
sleep 2

# Start Streamlit (foreground)
streamlit run frontend/app.py --server.port 7860 --server.address 0.0.0.0
```

**3. `requirements.txt`**:
```
# Backend
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
sqlalchemy>=2.0.0

# HTTP Client
httpx>=0.25.0

# Frontend
streamlit>=1.29.0

# Chemistry
rdkit>=2023.9.0
pandas>=2.0.0
numpy>=1.24.0

# Utilities
python-dotenv>=1.0.0
```

---

## Implementation Order

| Phase | Tasks | Est. Files |
|-------|-------|------------|
| **1** | Simplify config, remove Redis | 3 |
| **2** | Executor + Job service + API | 4 |
| **3** | Compound processing service | 1 |
| **4** | Decouple modules (copy + modify) | 6 |
| **5** | Streamlit frontend | 3 |
| **6** | Dockerfile + start script | 3 |
| **Total** | | **~20 files** |

---

## Success Criteria

1. ✅ Single container runs on HF Spaces free tier
2. ✅ Non-blocking UI (submit job, poll progress)
3. ✅ Real-time progress updates
4. ✅ No external dependencies (Redis, etc.)
5. ✅ Max 2 concurrent jobs (prevent overload)
6. ⚠️ Jobs lost on restart (acceptable)
