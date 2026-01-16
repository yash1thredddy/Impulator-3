# Testing Strategy

> Comprehensive testing approach for IMPULATOR (Single Container Architecture)
> Last Updated: 2024-12-31

---

## Testing Pyramid

```text
                    ┌─────────────┐
                    │    E2E      │  ← Few, slow, high confidence
                    │   Tests     │
                    ├─────────────┤
                    │ Integration │  ← Some, medium speed
                    │   Tests     │
                    ├─────────────┤
                    │    Unit     │  ← Many, fast, foundational
                    │   Tests     │
                    └─────────────┘
```

---

## Test Directory Structure

```text
Impulator/tests/
├── conftest.py                    # Shared fixtures
├── unit/
│   ├── test_config.py             # Configuration tests
│   ├── test_executor.py           # ThreadPoolExecutor tests
│   ├── test_azure_sync.py         # Azure sync logic (mocked)
│   ├── test_job_service.py        # Job CRUD operations
│   ├── test_schemas.py            # Pydantic models
│   ├── test_validation.py         # Input validation
│   ├── test_efficiency_metrics.py # Metric calculations
│   └── test_oqpla_scoring.py      # Scoring logic
├── integration/
│   ├── test_api_health.py         # Health endpoints
│   ├── test_api_jobs.py           # Job API endpoints
│   ├── test_database.py           # SQLite operations
│   └── test_azure_storage.py      # Azure Blob (requires creds)
├── e2e/
│   ├── test_compound_flow.py      # Full compound processing
│   ├── test_job_lifecycle.py      # Job submit → complete
│   └── test_concurrent_jobs.py    # Multiple simultaneous jobs
└── fixtures/
    ├── sample_compounds.json      # Test compounds
    └── expected_results/          # Expected outputs
```

---

## Unit Tests

### 1. Executor Tests

```python
# tests/unit/test_executor.py
import pytest
from unittest.mock import MagicMock, patch
from backend.core.executor import JobExecutor

class TestJobExecutor:

    @pytest.fixture
    def executor(self):
        return JobExecutor(max_workers=2)

    def test_submit_job(self, executor):
        """Test job submission."""
        def dummy_task(job_id):
            return f"completed_{job_id}"

        job_id = executor.submit("test-1", dummy_task)
        assert job_id == "test-1"
        assert executor.get_active_count() >= 0

    def test_has_capacity(self, executor):
        """Test capacity check."""
        assert executor.has_capacity() is True

    def test_stats(self, executor):
        """Test executor statistics."""
        stats = executor.stats()
        assert "max_workers" in stats
        assert "active_jobs" in stats
        assert "has_capacity" in stats
        assert stats["max_workers"] == 2

    def test_cancel_nonexistent_job(self, executor):
        """Test cancelling non-existent job."""
        result = executor.cancel("nonexistent")
        assert result is False

    def test_shutdown(self, executor):
        """Test graceful shutdown."""
        executor.shutdown(wait=False)
        # Should not raise


class TestJobExecutorConcurrency:

    def test_max_workers_limit(self):
        """Test that max workers is respected."""
        executor = JobExecutor(max_workers=1)
        assert executor._max_workers == 1
```

### 2. Azure Sync Tests (Mocked)

```python
# tests/unit/test_azure_sync.py
import pytest
from unittest.mock import patch, MagicMock
from backend.core.azure_sync import (
    is_azure_configured,
    download_db_from_azure,
    sync_db_to_azure,
    upload_result_to_azure,
)

class TestAzureSync:

    def test_is_azure_configured_false(self):
        """Test when Azure is not configured."""
        with patch('backend.core.azure_sync.settings') as mock_settings:
            mock_settings.AZURE_CONNECTION_STRING = ""
            assert is_azure_configured() is False

    def test_is_azure_configured_true(self):
        """Test when Azure is configured."""
        with patch('backend.core.azure_sync.settings') as mock_settings:
            mock_settings.AZURE_CONNECTION_STRING = "DefaultEndpoints..."
            assert is_azure_configured() is True

    def test_download_db_not_configured(self):
        """Test download when Azure not configured."""
        with patch('backend.core.azure_sync.is_azure_configured', return_value=False):
            result = download_db_from_azure()
            assert result is True  # Graceful skip

    def test_sync_db_not_configured(self):
        """Test sync when Azure not configured."""
        with patch('backend.core.azure_sync.is_azure_configured', return_value=False):
            result = sync_db_to_azure()
            assert result is True  # Graceful skip

    def test_upload_result_not_configured(self):
        """Test upload when Azure not configured."""
        with patch('backend.core.azure_sync.is_azure_configured', return_value=False):
            result = upload_result_to_azure("/path/to/file.zip", "Aspirin")
            assert result is True  # Graceful skip
```

### 3. Job Service Tests

```python
# tests/unit/test_job_service.py
import pytest
from unittest.mock import MagicMock, patch
from backend.services.job_service import JobService
from backend.models.database import JobStatus, JobType

class TestJobService:

    @pytest.fixture
    def service(self):
        return JobService()

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.query = MagicMock()
        return db

    def test_create_job(self, service, mock_db):
        """Test job creation."""
        job = service.create_job(
            mock_db,
            JobType.SINGLE,
            {"compound_name": "Aspirin", "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O"}
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_get_active_jobs(self, service, mock_db):
        """Test getting active jobs."""
        mock_query = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = service.get_active_jobs(mock_db)
        assert isinstance(result, list)
```

### 4. Schema Tests

```python
# tests/unit/test_schemas.py
import pytest
from pydantic import ValidationError
from backend.models.schemas import JobCreate, JobResponse, ActiveJobResponse

class TestJobCreateSchema:

    def test_valid_job_create(self):
        """Test valid job creation schema."""
        job = JobCreate(
            compound_name="Aspirin",
            smiles="CC(=O)OC1=CC=CC=C1C(=O)O",
            similarity_threshold=90
        )
        assert job.compound_name == "Aspirin"
        assert job.similarity_threshold == 90

    def test_invalid_similarity_threshold(self):
        """Test invalid similarity threshold."""
        with pytest.raises(ValidationError):
            JobCreate(
                compound_name="Test",
                smiles="CCO",
                similarity_threshold=150  # > 100
            )

    def test_empty_compound_name(self):
        """Test empty compound name."""
        with pytest.raises(ValidationError):
            JobCreate(
                compound_name="",
                smiles="CCO"
            )

    def test_default_activity_types(self):
        """Test default activity types."""
        job = JobCreate(
            compound_name="Test",
            smiles="CCO"
        )
        assert job.activity_types is None
```

---

## Integration Tests

### 1. Health Endpoint Tests

```python
# tests/integration/test_api_health.py
import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    return TestClient(app)

class TestHealthEndpoints:

    def test_health_check(self, client):
        """Test basic health check."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "version" in data
        assert "database" in data
        assert "azure_configured" in data
        assert "executor_active_jobs" in data

    def test_readiness_probe(self, client):
        """Test readiness probe."""
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_liveness_probe(self, client):
        """Test liveness probe."""
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_executor_stats(self, client):
        """Test executor statistics endpoint."""
        response = client.get("/api/v1/health/executor")
        assert response.status_code == 200
        data = response.json()
        assert "max_workers" in data
        assert "active_jobs" in data
        assert "has_capacity" in data
```

### 2. Job API Tests

```python
# tests/integration/test_api_jobs.py
import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    return TestClient(app)

class TestJobEndpoints:

    def test_submit_job(self, client):
        """Test job submission."""
        response = client.post("/api/v1/jobs", json={
            "compound_name": "TestCompound",
            "smiles": "CCO",
            "similarity_threshold": 90
        })

        # May return 200 or 429 (queue full)
        assert response.status_code in [200, 429]

        if response.status_code == 200:
            data = response.json()
            assert "id" in data
            assert data["status"] == "pending"

    def test_get_active_jobs(self, client):
        """Test getting active jobs."""
        response = client.get("/api/v1/jobs/active")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_jobs(self, client):
        """Test listing jobs with pagination."""
        response = client.get("/api/v1/jobs?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    def test_get_nonexistent_job(self, client):
        """Test getting non-existent job."""
        response = client.get("/api/v1/jobs/nonexistent-id")
        assert response.status_code == 404
```

### 3. Database Tests

```python
# tests/integration/test_database.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.core.database import Base
from backend.models.database import Job, Compound, JobStatus, JobType

@pytest.fixture
def db_session():
    """Create in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

class TestJobModel:

    def test_create_job(self, db_session):
        """Test job creation."""
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

    def test_update_job_progress(self, db_session):
        """Test updating job progress."""
        job = Job(id="test-job-2", job_type=JobType.SINGLE)
        db_session.add(job)
        db_session.commit()

        job.progress = 50.0
        job.current_step = "Processing..."
        job.status = JobStatus.PROCESSING
        db_session.commit()

        retrieved = db_session.query(Job).filter(Job.id == "test-job-2").first()
        assert retrieved.progress == 50.0
        assert retrieved.status == JobStatus.PROCESSING


class TestCompoundModel:

    def test_create_compound(self, db_session):
        """Test compound creation."""
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
```

---

## Test Configuration

### pytest.ini

```ini
[pytest]
testpaths = Impulator/tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests requiring database
    e2e: marks end-to-end tests
    azure: marks tests requiring Azure credentials
```

### conftest.py

```python
# tests/conftest.py
import pytest
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["AZURE_CONNECTION_STRING"] = ""  # Disable Azure in tests

@pytest.fixture(scope="session")
def test_compounds():
    """Sample compounds for testing."""
    return [
        {"name": "Ethanol", "smiles": "CCO"},
        {"name": "Aspirin", "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O"},
        {"name": "Caffeine", "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"},
    ]

@pytest.fixture
def mock_azure():
    """Mock Azure for tests."""
    with patch('backend.core.azure_sync.is_azure_configured', return_value=False):
        yield
```

---

## Running Tests

### Commands

```bash
# Run all tests
cd Impulator
pytest tests/

# Run with coverage
pytest --cov=backend --cov-report=html tests/

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v

# Run excluding slow tests
pytest -m "not slow"

# Run specific test file
pytest tests/unit/test_executor.py -v

# Run with verbose output
pytest -v --tb=long
```

### Coverage Requirements

| Module | Target Coverage |
|--------|-----------------|
| `backend/core/executor.py` | 90% |
| `backend/core/azure_sync.py` | 80% |
| `backend/services/job_service.py` | 90% |
| `backend/api/v1/jobs.py` | 85% |
| `backend/api/v1/health.py` | 95% |
| **Overall** | **>80%** |

---

## CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Run unit tests
        run: pytest Impulator/tests/unit -v --cov=backend

      - name: Run integration tests
        run: pytest Impulator/tests/integration -v

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```
