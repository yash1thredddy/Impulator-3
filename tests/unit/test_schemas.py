"""
Unit tests for Pydantic schemas.
"""
import pytest
from pydantic import ValidationError


class TestJobCreateSchema:
    """Tests for JobCreate schema."""

    def test_valid_job_create(self):
        """Test valid job creation schema."""
        from backend.models.schemas import JobCreate
        job = JobCreate(
            compound_name="Aspirin",
            smiles="CC(=O)OC1=CC=CC=C1C(=O)O",
            similarity_threshold=90
        )
        assert job.compound_name == "Aspirin"
        assert job.similarity_threshold == 90

    def test_default_similarity_threshold(self):
        """Test default similarity threshold."""
        from backend.models.schemas import JobCreate
        job = JobCreate(
            compound_name="Test",
            smiles="CCO"
        )
        assert job.similarity_threshold == 90  # Default

    def test_invalid_similarity_threshold_too_high(self):
        """Test similarity threshold > 100 is invalid."""
        from backend.models.schemas import JobCreate
        with pytest.raises(ValidationError):
            JobCreate(
                compound_name="Test",
                smiles="CCO",
                similarity_threshold=150
            )

    def test_invalid_similarity_threshold_too_low(self):
        """Test similarity threshold < 0 is invalid."""
        from backend.models.schemas import JobCreate
        with pytest.raises(ValidationError):
            JobCreate(
                compound_name="Test",
                smiles="CCO",
                similarity_threshold=-10
            )

    def test_empty_compound_name(self):
        """Test empty compound name is invalid."""
        from backend.models.schemas import JobCreate
        with pytest.raises(ValidationError):
            JobCreate(
                compound_name="",
                smiles="CCO"
            )

    def test_empty_smiles(self):
        """Test empty SMILES is invalid."""
        from backend.models.schemas import JobCreate
        with pytest.raises(ValidationError):
            JobCreate(
                compound_name="Test",
                smiles=""
            )

    def test_default_activity_types(self):
        """Test default activity types is None."""
        from backend.models.schemas import JobCreate
        job = JobCreate(
            compound_name="Test",
            smiles="CCO"
        )
        assert job.activity_types is None


class TestActiveJobResponseSchema:
    """Tests for ActiveJobResponse schema."""

    def test_valid_active_job_response(self):
        """Test valid active job response."""
        from backend.models.schemas import ActiveJobResponse
        from backend.models.database import JobStatus

        response = ActiveJobResponse(
            id="test-123",
            status=JobStatus.PROCESSING,
            progress=45.5,
            current_step="Fetching activities",
            compound_name="Aspirin"
        )
        assert response.id == "test-123"
        assert response.progress == 45.5


class TestExecutorStatsSchema:
    """Tests for ExecutorStats schema."""

    def test_valid_executor_stats(self):
        """Test valid executor stats."""
        from backend.models.schemas import ExecutorStats

        stats = ExecutorStats(
            max_workers=2,
            active_jobs=1,
            has_capacity=True,
            job_ids=["job-1"]
        )
        assert stats.max_workers == 2
        assert stats.active_jobs == 1
        assert stats.has_capacity is True
        assert "job-1" in stats.job_ids
