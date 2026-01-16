"""
Pydantic schemas for API request/response validation.
"""
import re
from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict, field_validator

# Try to import RDKit for SMILES validation
try:
    from rdkit import Chem
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False


# Enums
class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    SINGLE = "single"
    BATCH = "batch"


# Job Schemas
class JobCreate(BaseModel):
    """Request schema for creating a job."""

    compound_name: str = Field(..., min_length=1, max_length=100)
    smiles: str = Field(..., min_length=1, max_length=5000)
    similarity_threshold: int = Field(default=90, ge=50, le=100)
    activity_types: Optional[List[str]] = None
    # Session ID for user isolation (passed from frontend)
    session_id: Optional[str] = None

    @field_validator('smiles')
    @classmethod
    def validate_smiles(cls, v: str) -> str:
        """Validate SMILES string format and optionally chemical validity."""
        # Basic format validation
        if not v or not v.strip():
            raise ValueError('SMILES string cannot be empty')

        v = v.strip()

        # Check for dangerous characters (prevent injection)
        if re.search(r'[<>{}|\\`]', v):
            raise ValueError('SMILES contains invalid characters')

        # Use RDKit for chemical validation if available
        if RDKIT_AVAILABLE:
            mol = Chem.MolFromSmiles(v)
            if mol is None:
                raise ValueError('Invalid SMILES: could not parse as a valid molecule')

        return v

    @field_validator('compound_name')
    @classmethod
    def validate_compound_name(cls, v: str) -> str:
        """Validate compound name for safety."""
        if not v or not v.strip():
            raise ValueError('Compound name cannot be empty')

        v = v.strip()

        # Check for dangerous HTML/script characters
        if re.search(r'[<>{}]', v):
            raise ValueError('Compound name contains invalid characters')

        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "compound_name": "Aspirin",
                "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "similarity_threshold": 90,
                "activity_types": ["IC50", "Ki"],
                "session_id": "abc123-session-uuid",
            }
        }
    )


class BatchJobCreate(BaseModel):
    """Request schema for creating a batch job."""

    compounds: List[JobCreate] = Field(..., min_length=1, max_length=100)
    # Session ID for user isolation (applied to all jobs in batch)
    session_id: Optional[str] = None
    # Skip compounds that already have results
    skip_existing: bool = Field(default=True)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "compounds": [
                    {"compound_name": "Aspirin", "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O"},
                    {"compound_name": "Ibuprofen", "smiles": "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O"},
                ],
                "session_id": "abc123-session-uuid",
                "skip_existing": True,
            }
        }
    )


class JobResponse(BaseModel):
    """Response schema for job status."""

    id: str
    job_type: JobType
    status: JobStatus
    progress: float = Field(ge=0, le=100)
    current_step: Optional[str] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # Session and batch tracking
    session_id: Optional[str] = None
    batch_id: Optional[str] = None
    # Extracted from input_params for convenience
    compound_name: Optional[str] = None
    smiles: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class JobProgress(BaseModel):
    """Schema for job progress updates (polling)."""

    job_id: str
    status: JobStatus
    progress: float
    current_step: Optional[str] = None
    message: Optional[str] = None


class ActiveJobResponse(BaseModel):
    """Response schema for active jobs in sidebar."""

    id: str
    status: JobStatus
    progress: float
    current_step: Optional[str] = None
    compound_name: Optional[str] = None
    batch_id: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CheckDuplicatesRequest(BaseModel):
    """Request schema for checking duplicate compounds."""

    compound_names: List[str] = Field(..., min_length=1, max_length=100)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "compound_names": ["Aspirin", "Ibuprofen", "Quercetin"]
            }
        }
    )


class CheckDuplicatesResponse(BaseModel):
    """Response schema for duplicate check."""

    existing: List[str] = Field(default_factory=list, description="Compounds that already have results")
    processing: List[str] = Field(default_factory=list, description="Compounds currently being processed")
    new: List[str] = Field(default_factory=list, description="Compounds that are new")


class BatchSummary(BaseModel):
    """Summary of a batch of jobs for sidebar display."""

    batch_id: str
    total_jobs: int
    completed: int
    processing: int
    pending: int
    failed: int
    cancelled: int = 0
    overall_progress: float = Field(ge=0, le=100)
    created_at: Optional[datetime] = None
    # Sample of compound names in this batch
    compound_names: List[str] = []


class JobListResponse(BaseModel):
    """Paginated list of jobs."""

    items: List[JobResponse]
    total: int
    page: int
    page_size: int
    pages: int


# Compound Schemas
class CompoundBase(BaseModel):
    """Base compound schema."""

    compound_name: str
    chembl_id: Optional[str] = None
    smiles: Optional[str] = None


class CompoundCreate(CompoundBase):
    """Schema for creating a compound entry."""

    total_activities: int = 0
    imp_candidates: int = 0
    avg_oqpla_score: Optional[float] = None
    storage_path: Optional[str] = None


class CompoundResponse(CompoundBase):
    """Response schema for compound listing."""

    id: int
    total_activities: int
    imp_candidates: int
    avg_oqpla_score: Optional[float] = None
    storage_path: Optional[str] = None
    processed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CompoundList(BaseModel):
    """Paginated list of compounds."""

    items: List[CompoundResponse]
    total: int
    page: int
    page_size: int
    pages: int


# Health Schemas
class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str
    database: bool
    azure_configured: bool
    executor_active_jobs: int
    timestamp: datetime


class ExecutorStats(BaseModel):
    """Executor statistics response."""

    max_workers: int
    active_jobs: int
    has_capacity: bool
    job_ids: List[str]


# Error Schemas
class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    error_code: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Compound not found",
                "error_code": "NOT_FOUND",
            }
        }
    )
