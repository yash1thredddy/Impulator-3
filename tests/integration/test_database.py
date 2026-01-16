"""
Integration tests for database models and operations.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_session():
    """Create an in-memory test database session."""
    from backend.core.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestJobModel:
    """Tests for Job database model."""

    def test_create_job(self, db_session):
        """Test creating a job record."""
        from backend.models.database import Job, JobStatus, JobType

        job = Job(
            id="test-job-1",
            job_type=JobType.SINGLE,
            status=JobStatus.PENDING,
            input_params='{"compound_name": "Test"}'
        )
        db_session.add(job)
        db_session.commit()

        retrieved = db_session.query(Job).filter(Job.id == "test-job-1").first()
        assert retrieved is not None
        assert retrieved.status == JobStatus.PENDING
        assert retrieved.job_type == JobType.SINGLE

    def test_update_job_progress(self, db_session):
        """Test updating job progress."""
        from backend.models.database import Job, JobStatus, JobType

        job = Job(id="test-job-2", job_type=JobType.SINGLE)
        db_session.add(job)
        db_session.commit()

        job.progress = 50.0
        job.current_step = "Processing..."
        job.status = JobStatus.PROCESSING
        db_session.commit()

        retrieved = db_session.query(Job).filter(Job.id == "test-job-2").first()
        assert retrieved.progress == 50.0
        assert retrieved.current_step == "Processing..."
        assert retrieved.status == JobStatus.PROCESSING

    def test_job_defaults(self, db_session):
        """Test job default values."""
        from backend.models.database import Job, JobStatus, JobType

        job = Job(id="test-job-3", job_type=JobType.SINGLE)
        db_session.add(job)
        db_session.commit()

        retrieved = db_session.query(Job).filter(Job.id == "test-job-3").first()
        assert retrieved.status == JobStatus.PENDING
        assert retrieved.progress == 0.0
        assert retrieved.current_step is None
        assert retrieved.error_message is None


class TestCompoundModel:
    """Tests for Compound database model."""

    def test_create_compound(self, db_session):
        """Test creating a compound record."""
        from backend.models.database import Compound

        compound = Compound(
            compound_name="Aspirin",
            smiles="CC(=O)OC1=CC=CC=C1C(=O)O",
            total_activities=100
        )
        db_session.add(compound)
        db_session.commit()

        retrieved = db_session.query(Compound).filter(
            Compound.compound_name == "Aspirin"
        ).first()
        assert retrieved is not None
        assert retrieved.total_activities == 100
        assert retrieved.smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"

    def test_compound_unique_name(self, db_session):
        """Test compound name uniqueness."""
        from backend.models.database import Compound
        from sqlalchemy.exc import IntegrityError

        compound1 = Compound(compound_name="UniqueTest", smiles="CCO")
        db_session.add(compound1)
        db_session.commit()

        compound2 = Compound(compound_name="UniqueTest", smiles="CCCO")
        db_session.add(compound2)

        with pytest.raises(IntegrityError):
            db_session.commit()
