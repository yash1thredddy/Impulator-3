# Known Issues & Solutions

> This document tracks known issues, potential problems, and their solutions.

---

## Input Validation Issues

### Issue 1: Invalid SMILES Strings

**Problem**: Users may enter invalid or malformed SMILES strings.

**Symptoms**:
- RDKit parsing errors
- Null molecule objects
- Downstream calculation failures

**Solution**:
```python
from rdkit import Chem

def validate_smiles(smiles: str) -> tuple[bool, str]:
    """
    Comprehensive SMILES validation.

    Returns:
        (is_valid, error_message)
    """
    if not smiles or not isinstance(smiles, str):
        return False, "SMILES is empty or not a string"

    # Remove whitespace
    smiles = smiles.strip()

    # Check for obviously invalid characters
    valid_chars = set("CNOPSFIBrcnopsfi[]()=#@+-.0123456789\\/%")
    invalid = set(smiles) - valid_chars
    if invalid:
        return False, f"Invalid characters: {invalid}"

    # Try RDKit parsing
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return False, "RDKit could not parse this SMILES"

        # Additional sanity checks
        if mol.GetNumAtoms() == 0:
            return False, "Molecule has no atoms"

        if mol.GetNumAtoms() > 500:
            return False, "Molecule too large (>500 atoms)"

        # Check for disconnected fragments
        frags = Chem.GetMolFrags(mol)
        if len(frags) > 1:
            return False, f"SMILES contains {len(frags)} disconnected fragments"

        return True, ""

    except Exception as e:
        return False, f"Parsing error: {str(e)}"

# In Streamlit
is_valid, error = validate_smiles(user_input)
if not is_valid:
    st.error(f"Invalid SMILES: {error}")
    st.stop()
```

**Prevention**:
- Validate on client-side before submission
- Show SMILES structure preview
- Provide example SMILES

---

### Issue 2: Invalid InChI Strings

**Problem**: InChI strings may be malformed or truncated.

**Solution**:
```python
from rdkit import Chem

def validate_inchi(inchi: str) -> tuple[bool, str]:
    if not inchi:
        return False, "InChI is empty"

    if not inchi.startswith("InChI="):
        return False, "InChI must start with 'InChI='"

    # Check version
    if not inchi.startswith("InChI=1"):
        return False, "Only InChI version 1 is supported"

    try:
        mol = Chem.MolFromInchi(inchi)
        if mol is None:
            return False, "RDKit could not parse this InChI"
        return True, ""
    except Exception as e:
        return False, f"Parsing error: {str(e)}"
```

---

### Issue 3: Compound Name Issues

**Problem**: Compound names may contain filesystem-unsafe characters.

**Solution**:
```python
import re

def sanitize_compound_name(name: str) -> str:
    """
    Sanitize compound name for filesystem safety.
    """
    if not name:
        raise ValueError("Compound name cannot be empty")

    # Remove or replace unsafe characters
    unsafe = '<>:"/\\|?*'
    for char in unsafe:
        name = name.replace(char, '_')

    # Remove leading/trailing whitespace and dots
    name = name.strip(' .')

    # Limit length
    if len(name) > 100:
        name = name[:100]

    # Ensure not empty after sanitization
    if not name:
        raise ValueError("Compound name is empty after sanitization")

    return name

def validate_compound_name(name: str) -> tuple[bool, str]:
    if not name:
        return False, "Name is empty"

    if len(name) > 100:
        return False, "Name too long (max 100 chars)"

    unsafe = set(name) & set('<>:"/\\|?*')
    if unsafe:
        return False, f"Unsafe characters: {unsafe}"

    # Check for reserved names (Windows)
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT1'}
    if name.upper() in reserved:
        return False, f"'{name}' is a reserved name"

    return True, ""
```

---

## API Issues

### Issue 4: ChEMBL Rate Limiting

**Problem**: Too many requests cause 429 errors.

**Symptoms**:
- HTTP 429 responses
- "Too Many Requests" errors
- Temporary bans

**Solution**:
```python
import time
from functools import wraps

class RateLimiter:
    def __init__(self, calls_per_second: float = 10):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0

    def wait(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()

chembl_limiter = RateLimiter(calls_per_second=10)

def rate_limited(limiter):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter.wait()
            return func(*args, **kwargs)
        return wrapper
    return decorator

@rate_limited(chembl_limiter)
def fetch_chembl_data(compound_id):
    # API call here
    pass
```

**With Redis (for distributed workers)**:
```python
from redis import Redis

class DistributedRateLimiter:
    def __init__(self, redis: Redis, key: str, max_calls: int, period: int):
        self.redis = redis
        self.key = key
        self.max_calls = max_calls
        self.period = period

    def acquire(self) -> bool:
        current = self.redis.get(self.key)
        if current is None:
            self.redis.setex(self.key, self.period, 1)
            return True
        elif int(current) < self.max_calls:
            self.redis.incr(self.key)
            return True
        return False

    def wait_and_acquire(self, timeout: int = 60) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if self.acquire():
                return True
            time.sleep(0.1)
        return False
```

---

### Issue 5: ChEMBL API Timeouts

**Problem**: Large similarity searches may timeout.

**Solution**:
```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session_with_retries(
    retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple = (500, 502, 503, 504)
):
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Usage
session = create_session_with_retries()
response = session.get(url, timeout=30)
```

---

### Issue 6: PDB API Issues (rcsb-api Library Bug)

**Problem**: The rcsb-api library uses HTTP instead of HTTPS.

**Symptoms**:
- "HTTP is not supported" errors
- SSL/TLS errors

**Solution**: Use custom REST client instead:
```python
import requests

class PDBClient:
    """Custom PDB client using direct REST API."""

    BASE_URL = "https://search.rcsb.org/rcsbsearch/v2/query"

    def search_similar(self, smiles: str, threshold: float = 0.7) -> list:
        query = {
            "query": {
                "type": "terminal",
                "service": "chemical",
                "parameters": {
                    "type": "descriptor",
                    "descriptor_type": "SMILES",
                    "value": smiles,
                    "match_type": "similar",
                    "similarity_cutoff": threshold
                }
            },
            "return_type": "entry"
        }

        response = requests.post(
            self.BASE_URL,
            json=query,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            return data.get("result_set", [])
        else:
            return []
```

---

### Issue 7: ClassyFire API Unavailability

**Problem**: ClassyFire API may be slow or unavailable.

**Solution**:
```python
def get_classification_with_fallback(smiles: str) -> dict:
    """Get classification with fallback to NPClassifier."""
    try:
        # Try ClassyFire first
        result = get_classyfire_classification(smiles, timeout=10)
        if result:
            return {"source": "classyfire", **result}
    except Exception as e:
        logger.warning(f"ClassyFire failed: {e}")

    try:
        # Fallback to NPClassifier
        result = get_npclassifier_classification(smiles)
        if result:
            return {"source": "npclassifier", **result}
    except Exception as e:
        logger.warning(f"NPClassifier failed: {e}")

    # Return empty classification
    return {"source": "none", "class": "Unknown", "superclass": "Unknown"}
```

---

## Database Issues

### Issue 8: SQLite Concurrent Write Issues

**Problem**: SQLite doesn't handle concurrent writes well.

**Symptoms**:
- "database is locked" errors
- Write timeouts

**Solution**:
```python
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Use WAL mode and connection pooling
engine = create_engine(
    "sqlite:///data/impulator.db",
    connect_args={
        "check_same_thread": False,
        "timeout": 30
    },
    poolclass=StaticPool,  # Single connection for writes
)

# Enable WAL mode
with engine.connect() as conn:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
```

**For high concurrency (future)**:
- Migrate to PostgreSQL
- Use read replicas

---

### Issue 9: SQLite File Corruption

**Problem**: SQLite database may corrupt on crash.

**Solution**:
```python
import shutil
from datetime import datetime

def backup_database(db_path: str, backup_dir: str):
    """Create timestamped backup of SQLite database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{backup_dir}/impulator_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path

def sync_to_blob(db_path: str):
    """Sync SQLite to Azure Blob for durability."""
    from modules.azure_storage import upload_to_blob
    upload_to_blob(db_path, "backups/impulator.db")
```

---

## Worker Issues

### Issue 10: Worker Crashes Mid-Job

**Problem**: If worker crashes, job is lost.

**Solution**:
```python
# RQ automatically handles this with job timeouts
from rq import Queue

queue = Queue(
    connection=redis,
    default_timeout=3600,  # 1 hour max
    job_timeout=3600
)

# Job will be marked as failed if worker crashes
# Can implement retry logic:
@job('default', retry_count=3)
def process_compound_task(job_id, ...):
    # Processing logic
    pass
```

**Recovery**:
```python
def recover_stuck_jobs():
    """Mark stuck jobs as failed."""
    from backend.models.database import Job
    from datetime import datetime, timedelta

    with get_db_session() as session:
        stuck_jobs = session.query(Job).filter(
            Job.status == 'processing',
            Job.started_at < datetime.utcnow() - timedelta(hours=2)
        ).all()

        for job in stuck_jobs:
            job.status = 'failed'
            job.error_message = 'Job timed out (worker may have crashed)'
            job.completed_at = datetime.utcnow()

        session.commit()
```

---

### Issue 11: Memory Issues with Large Batches

**Problem**: Processing many compounds exhausts memory.

**Solution**:
```python
def process_batch_with_chunking(compounds: list, chunk_size: int = 10):
    """Process batch in chunks to limit memory usage."""
    import gc

    for i in range(0, len(compounds), chunk_size):
        chunk = compounds[i:i+chunk_size]

        for compound in chunk:
            result = process_single_compound(compound)
            yield result

        # Force garbage collection between chunks
        gc.collect()
```

---

## Storage Issues

### Issue 12: Azure Blob Connection Failures

**Problem**: Azure Blob may be temporarily unavailable.

**Solution**:
```python
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import AzureError
import time

def upload_with_retry(blob_client, data, max_retries: int = 3):
    """Upload with exponential backoff."""
    for attempt in range(max_retries):
        try:
            blob_client.upload_blob(data, overwrite=True)
            return True
        except AzureError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Upload failed, retrying in {wait_time:.1f}s: {e}")
            time.sleep(wait_time)
    return False
```

---

### Issue 13: Large ZIP Files

**Problem**: ZIP files may be too large for efficient transfer.

**Solution**:
```python
import zipfile

def create_compressed_zip(folder_path: str, output_path: str):
    """Create compressed ZIP file."""
    with zipfile.ZipFile(
        output_path,
        'w',
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6  # Balance compression vs speed
    ) as zf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, folder_path)
                zf.write(file_path, arcname)
```

---

## Streamlit Issues

### Issue 14: Session State Lost on Refresh

**Problem**: Streamlit session state resets on page refresh.

**Solution**:
```python
# Store job_id in URL query params
import streamlit as st

# On job submission
st.query_params["job_id"] = job_id

# On page load
def get_current_job():
    # Check query params first
    job_id = st.query_params.get("job_id")
    if job_id:
        return job_id

    # Fall back to session state
    return st.session_state.get("current_job_id")
```

---

### Issue 15: Browser Connection Timeout

**Problem**: Long SSE connections may timeout.

**Solution**:
```python
# Send heartbeat events
async def event_generator():
    last_heartbeat = time.time()

    while True:
        # Send heartbeat every 30 seconds
        if time.time() - last_heartbeat > 30:
            yield f"event: heartbeat\ndata: ping\n\n"
            last_heartbeat = time.time()

        # Regular progress updates
        job = get_job(job_id)
        yield f"event: progress\ndata: {json.dumps(job)}\n\n"

        if job['status'] in ['completed', 'failed']:
            break

        await asyncio.sleep(0.5)
```

---

## Performance Issues

### Issue 16: Slow Compound Listing

**Problem**: Loading all compounds is slow.

**Solution**:
```python
# Use SQLite for metadata, not ZIP files
def list_compounds(page: int = 1, limit: int = 50) -> list:
    """Fast compound listing from SQLite."""
    offset = (page - 1) * limit
    with get_db_session() as session:
        compounds = session.query(Compound)\
            .order_by(Compound.processed_at.desc())\
            .offset(offset)\
            .limit(limit)\
            .all()
        return compounds

# Only load full data when viewing details
def get_compound_details(name: str):
    """Load full data from ZIP on demand."""
    return load_results(name)
```

---

### Issue 17: Slow Visualization Rendering

**Problem**: Plotly charts slow with large datasets.

**Solution**:
```python
import plotly.express as px

def create_optimized_scatter(df, x, y, color):
    """Create scatter plot with sampling for large datasets."""
    MAX_POINTS = 5000

    if len(df) > MAX_POINTS:
        # Random sample for display
        display_df = df.sample(MAX_POINTS)
        title = f"Showing {MAX_POINTS} of {len(df)} points"
    else:
        display_df = df
        title = f"{len(df)} points"

    fig = px.scatter(
        display_df, x=x, y=y, color=color,
        title=title,
        render_mode='webgl'  # GPU acceleration
    )
    return fig
```

---

## Common Error Messages & Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "Invalid SMILES" | Malformed input | Validate before processing |
| "database is locked" | Concurrent writes | Use WAL mode, increase timeout |
| "HTTP 429" | Rate limited | Implement backoff |
| "Connection refused" | Redis/backend down | Check docker-compose |
| "Job not found" | Invalid job_id | Check SQLite, verify ID |
| "SMILES too large" | >500 atoms | Reject or warn user |
| "Memory error" | Large batch | Process in chunks |
| "Timeout" | Slow API | Increase timeout, add retries |
