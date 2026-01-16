# IMPULATOR Project Context

## Quick Reference

| Aspect | Current State |
|--------|---------------|
| Frontend | Streamlit (polls backend API) |
| Backend | FastAPI + ThreadPoolExecutor |
| Queue | ThreadPoolExecutor (2 workers) |
| Database | SQLite (metadata) |
| Cache | In-memory LRU (2000/function) |
| Storage | Azure Blob (single source of truth) |
| Progress | HTTP Polling (1s interval) |
| Container | Single container |

---

## What is IMPULATOR?

IMPULATOR (IMPs Navigator) is a scientific web application for analyzing chemical compounds to identify **Invalid Metabolic Panaceas (IMPs)** - compounds that appear to have exceptional bioactivity but are actually assay artifacts.

### Core Features

1. **Compound Analysis** - Process compounds via SMILES/InChI input
2. **Similarity Search** - Find similar compounds in ChEMBL
3. **Efficiency Metrics** - Calculate SEI, BEI, NSEI, NBEI
4. **OQPLA Scoring** - Multi-criteria quality assessment
5. **IMP Classification** - Identify potential false positives
6. **Assay Interference** - Detect PAINS, aggregation, redox issues
7. **Batch Processing** - Process CSV files with multiple compounds
8. **Visualization** - Interactive Plotly charts, 3D molecule viewer

---

## Architecture Overview

Single-container deployment (works on HF Spaces, Streamlit Cloud, local, VPS):

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         SINGLE CONTAINER                             │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  STREAMLIT (Port 7860)                                        │   │
│  │  - Sidebar: Input form + Active jobs display                  │   │
│  │  - Main: Compound browser + Results visualization             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              │ HTTP Polling (1s)                     │
│                              ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  FASTAPI (Port 8000)                                          │   │
│  │  - ThreadPoolExecutor (2 workers)                             │   │
│  │  - SQLite for job/compound metadata                           │   │
│  │  - Immediate Azure sync on job complete                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  AZURE BLOB (Single Source of Truth)                          │   │
│  │  - impulator.db (SQLite backup)                               │   │
│  │  - results/*.zip (compound results)                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## External API Dependencies

### ChEMBL (Primary)

- **Purpose**: Compound similarity search, bioactivity data
- **Endpoints**: Similarity, Activities, Molecules
- **Rate Limit**: ~10 req/sec (unofficial)
- **Client**: `chembl_webresource_client`
- **Cache**: `@lru_cache(maxsize=2000)`

### RCSB PDB

- **Purpose**: Structural evidence for OQPLA scoring
- **Endpoints**: Search, Structure data
- **Rate Limit**: ~5 req/sec
- **Client**: Custom REST (not rcsb-api library - it's broken)
- **Cache**: `@lru_cache(maxsize=2000)`

### ClassyFire

- **Purpose**: Chemical classification
- **Endpoints**: Classify compound
- **Rate Limit**: Unknown, be conservative

### NPClassifier

- **Purpose**: Natural product classification
- **Endpoints**: Classify compound
- **Rate Limit**: Unknown, be conservative

---

## Key Modules

### Backend Structure

```text
Impulator/backend/
├── main.py                 # FastAPI app + lifespan (Azure sync)
├── config.py               # Settings (no Redis)
├── api/v1/
│   ├── router.py           # Route aggregator
│   ├── health.py           # Health + executor stats
│   └── jobs.py             # Job CRUD endpoints
├── core/
│   ├── database.py         # SQLite + SQLAlchemy
│   ├── executor.py         # ThreadPoolExecutor wrapper
│   └── azure_sync.py       # Azure Blob sync utilities
├── models/
│   ├── database.py         # ORM models (Job, Compound)
│   └── schemas.py          # Pydantic schemas
└── services/
    ├── job_service.py      # Job state management
    └── compound_service.py # Processing logic
```

### Processing Modules (to be decoupled)

```text
modules/
├── api_client.py          # ChEMBL + ClassyFire API
├── pdb_client.py          # RCSB PDB API
├── data_processor.py      # Main processing pipeline
├── oqpla_scoring.py       # O[Q/P/L]A scoring system
├── imp_classifier.py      # IMP classification
└── assay_interference_filter.py  # PAINS, aggregation, etc.
```

---

## Data Flow

### Non-blocking Processing

```text
User Input → Streamlit → POST /api/v1/jobs → [Immediate Response]
                              ↓
                    ThreadPoolExecutor → [Background 5-30 min]
                              ↓
                    Write ZIP + Update SQLite
                              ↓
                    Sync to Azure (immediate)
                              ↓
Streamlit polls ← GET /jobs/active ← Job Complete
                              ↓
        Display (read from storage)
```

---

## File Storage

### Local Filesystem

```text
data/
├── impulator.db           # SQLite database
└── results/               # Result ZIPs (temporary)
```

### Azure Blob Storage

```text
impulator/
├── impulator.db           # SQLite backup (source of truth)
└── results/
    ├── Aspirin.zip
    ├── Ibuprofen.zip
    └── ...
```

---

## Configuration

### Environment Variables

```bash
# Azure Storage
AZURE_CONNECTION_STRING=...
AZURE_CONTAINER=impulator

# Backend
API_HOST=0.0.0.0
API_PORT=8000
FRONTEND_PORT=7860
DATABASE_URL=sqlite:///./data/impulator.db

# Processing
MAX_WORKERS=2
JOB_TIMEOUT=3600
CACHE_SIZE=2000
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/v1/health | Health check + executor stats |
| GET | /api/v1/health/executor | Executor statistics |
| POST | /api/v1/jobs | Submit new job |
| GET | /api/v1/jobs | List all jobs (paginated) |
| GET | /api/v1/jobs/active | Get active jobs (for sidebar) |
| GET | /api/v1/jobs/{id} | Get job status |
| POST | /api/v1/jobs/{id}/cancel | Cancel job |
| DELETE | /api/v1/jobs/{id} | Delete job record |

---

## Commands

### Development

```bash
# Start backend only
cd Impulator
python -m backend.main

# Start frontend only
streamlit run frontend/app.py --server.port=7860

# Start both (using start.sh)
./start.sh
```

### Testing

```bash
# Run all tests
pytest Impulator/tests/

# Run with coverage
pytest --cov=backend Impulator/tests/
```

### Docker

```bash
# Build and run
docker build -t impulator .
docker run -p 7860:7860 -p 8000:8000 impulator
```

---

## Documentation Index

- `.claude/agents.md` - Development guidelines
- `.claude/progress.md` - Implementation progress
- `.claude/docs/architecture.md` - System design
- `.claude/docs/testing-strategy.md` - Test approach
- `.claude/docs/issues-and-solutions.md` - Troubleshooting
- `.claude/docs/future-integrations.md` - PubChem, etc.
- `.claude/plans/future_prod/3-container-redis-rq-plan.md` - Future scaling plan
