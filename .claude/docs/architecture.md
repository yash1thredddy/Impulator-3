# IMPULATOR System Architecture

> Version: 4.0 (Single Container)
> Last Updated: 2024-12-31
> Future Scale Plan: See `.claude/plans/future_prod/3-container-redis-rq-plan.md`

---

## Architecture Overview

Single-container architecture optimized for flexible deployment (local, HF Spaces, Streamlit Cloud, VPS):

| Component | Choice |
|-----------|--------|
| **Backend** | FastAPI + ThreadPoolExecutor (max 2 workers) |
| **Frontend** | Streamlit (polls FastAPI via HTTP) |
| **Database** | SQLite → Azure Blob (immediate sync) |
| **Caching** | In-memory LRU (2000/function) |
| **Progress** | Polling (1s interval) + Sidebar status bar |
| **Storage** | Azure Blob (single source of truth) |
| **Container** | 1 single container |

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SINGLE CONTAINER                             │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      STREAMLIT (Port 7860)                      │ │
│  │                                                                  │ │
│  │  ┌─────────────────┐  ┌────────────────────────────────────┐   │ │
│  │  │     SIDEBAR     │  │           MAIN AREA                │   │ │
│  │  │                 │  │                                    │   │ │
│  │  │  [Input Form]   │  │  - Compound Browser                │   │ │
│  │  │  Name: ______   │  │  - Results Visualization           │   │ │
│  │  │  SMILES: _____  │  │  - Job Detail View                 │   │ │
│  │  │  [Process]      │  │                                    │   │ │
│  │  │                 │  │                                    │   │ │
│  │  │  ─────────────  │  │                                    │   │ │
│  │  │  Active Jobs    │  │                                    │   │ │
│  │  │  ├─ Aspirin     │  │                                    │   │ │
│  │  │  │  ████░░ 45%  │  │                                    │   │ │
│  │  │  │  Fetching... │  │                                    │   │ │
│  │  │  └─ Ibuprofen   │  │                                    │   │ │
│  │  │     ██████ 80%  │  │                                    │   │ │
│  │  └─────────────────┘  └────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│                              │ HTTP Polling (1s)                     │
│                              ▼                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      FASTAPI (Port 8000)                        │ │
│  │                                                                  │ │
│  │  Endpoints:                                                      │ │
│  │  POST /api/v1/jobs           → Submit job                       │ │
│  │  GET  /api/v1/jobs/active    → Get active jobs (for sidebar)    │ │
│  │  GET  /api/v1/jobs/{id}      → Get job status                   │ │
│  │  POST /api/v1/jobs/{id}/cancel → Cancel job                     │ │
│  │  GET  /api/v1/compounds      → List compounds                   │ │
│  │                                                                  │ │
│  │  ┌──────────────────────────────────────────────────────────┐   │ │
│  │  │              ThreadPoolExecutor (max_workers=2)           │   │ │
│  │  │                                                           │   │ │
│  │  │   [Job 1: Processing]         [Job 2: Processing]        │   │ │
│  │  │         │                            │                    │   │ │
│  │  │         ▼                            ▼                    │   │ │
│  │  │   Update SQLite               Update SQLite               │   │ │
│  │  │         │                            │                    │   │ │
│  │  │         └──────────┬─────────────────┘                    │   │ │
│  │  │                    ▼                                      │   │ │
│  │  │          On Complete: Sync to Azure                       │   │ │
│  │  └──────────────────────────────────────────────────────────┘   │ │
│  │                                                                  │ │
│  │         ┌────────────────┬────────────────┐                     │ │
│  │         ▼                ▼                ▼                     │ │
│  │   ┌──────────┐    ┌──────────┐    ┌──────────┐                 │ │
│  │   │  SQLite  │    │LRU Cache │    │ External │                 │ │
│  │   │  (jobs)  │    │(2000/fn) │    │   APIs   │                 │ │
│  │   └────┬─────┘    └──────────┘    └──────────┘                 │ │
│  │        │                                                        │ │
│  └────────┼────────────────────────────────────────────────────────┘ │
│           │                                                          │
│           │ Immediate Sync (on job complete)                         │
│           ▼                                                          │
│   ┌───────────────────────────────────────────────────────────────┐ │
│   │                        AZURE BLOB                              │ │
│   │                  (Single Source of Truth)                      │ │
│   │                                                                 │ │
│   │   impulator.db          results/                               │ │
│   │   (SQLite backup)       ├── Aspirin.zip                        │ │
│   │                         ├── Ibuprofen.zip                      │ │
│   │                         └── ...                                │ │
│   └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Container | Single | Works on HF Spaces free tier, Streamlit Cloud, local, VPS |
| Job Queue | ThreadPoolExecutor (2 workers) | No Redis needed, limits API rate |
| Progress Updates | Polling (1s) | Works with Streamlit's rerun model |
| Job Visibility | Sidebar always shows active jobs | User can browse while jobs run |
| Data Persistence | Immediate sync to Azure | No data loss on container restart |
| Caching | LRU (2000/function) | Simple, no Redis overhead |

---

## Data Flow Diagrams

### Flow 1: Submit New Compound

```
┌────────┐     ┌───────────┐     ┌─────────┐     ┌──────────┐
│  User  │────►│ Streamlit │────►│ FastAPI │────►│ Executor │
└────────┘     └───────────┘     └─────────┘     └──────────┘
    │               │                 │               │
    │  Enter        │  POST           │  Create job   │
    │  compound     │  /api/jobs      │  in SQLite    │
    │               │                 │               │
    │               │◄────────────────│               │
    │               │  {job_id}       │               │
    │               │                 │               │
    │               │  Poll /active   │               │
    │               │────────────────►│               │
    │               │                 │               │
    │               │                 │               │──────┐
    │               │                 │               │      │
    │               │                 │               │ Process
    │               │                 │               │ compound
    │               │                 │               │      │
    │               │                 │◄──────────────│◄─────┘
    │               │                 │  Update       │
    │               │◄────────────────│  progress     │
    │               │  Poll response  │               │
    │  See progress │                 │               │
    │               │                 │               │
    │               │                 │◄──────────────│
    │               │                 │  Job complete │
    │               │◄────────────────│  + Azure sync │
    │               │  Status: done   │               │
    │  See results  │                 │               │
```

### Flow 2: View Existing Compound

```
┌────────┐     ┌───────────┐     ┌──────────┐     ┌─────────────┐
│  User  │────►│ Streamlit │────►│  SQLite  │     │ Azure Blob  │
└────────┘     └───────────┘     └──────────┘     └─────────────┘
    │               │                  │                  │
    │  List         │  GET /compounds  │                  │
    │  compounds    │  (via API)       │                  │
    │               │                  │                  │
    │◄──────────────│◄─────────────────│                  │
    │  Card grid    │  Metadata        │                  │
    │               │                  │                  │
    │  Click        │                  │                  │
    │  compound     │  Read ZIP        │                  │
    │               │──────────────────│──────────────────│
    │               │                  │                  │
    │◄──────────────│◄─────────────────│──────────────────│
    │  Full details │  Results data    │  ZIP contents    │
    │  + charts     │                  │                  │
```

---

## Data Persistence Strategy

### Azure Blob = Single Source of Truth

```
CONTAINER STARTUP                          CONTAINER RUNNING
─────────────────                          ─────────────────
       │                                          │
       ▼                                          ▼
┌─────────────┐                           ┌─────────────┐
│ Azure Blob  │ ──Download──►             │   SQLite    │
│impulator.db │                           │  (local)    │
└─────────────┘                           └──────┬──────┘
                                                 │
                                                 │ On Job Complete
                                                 │
                                          ┌──────▼──────┐
                                          │ Upload ZIP  │
                                          │ + Sync DB   │
                                          └──────┬──────┘
                                                 │
                                                 ▼
                                          ┌─────────────┐
                                          │ Azure Blob  │
                                          │ (updated)   │
                                          └─────────────┘
```

| Event | Action |
|-------|--------|
| **Container starts** | Download `impulator.db` from Azure |
| **Job completes** | Upload result ZIP → Sync SQLite → Immediately |
| **Container stops** | Final sync (graceful shutdown) |

**No periodic sync** - immediate sync on every job completion.

---

## Module Architecture

### Backend Modules

```
backend/
├── main.py                          # FastAPI application + lifespan
├── config.py                        # Configuration (no Redis)
│
├── api/v1/
│   ├── router.py                    # Route aggregator
│   ├── health.py                    # Health + executor stats
│   ├── jobs.py                      # Job endpoints
│   └── compounds.py                 # Compound endpoints (future)
│
├── core/
│   ├── database.py                  # SQLite + SQLAlchemy
│   ├── executor.py                  # ThreadPoolExecutor wrapper
│   └── azure_sync.py                # Azure Blob sync utilities
│
├── models/
│   ├── database.py                  # ORM models (Job, Compound)
│   └── schemas.py                   # Pydantic schemas
│
└── services/
    ├── job_service.py               # Job CRUD + progress updates
    └── compound_service.py          # Processing logic + Azure upload
```

### Processing Modules (Decoupled)

```
modules/
├── api_client.py          # ChEMBL API (@lru_cache)
├── pdb_client.py          # PDB API (@lru_cache)
├── data_processor.py      # Processing (no st.*)
├── oqpla_scoring.py       # Scoring (no st.*)
├── pains_filter.py        # Filtering
└── storage.py             # ZIP + Azure upload
```

### Frontend Modules

```
frontend/
├── app.py                 # Streamlit main
├── api_client.py          # HTTP client for FastAPI
└── components/
    ├── sidebar.py         # Input form + active jobs display
    ├── browser.py         # Compound browser
    └── results.py         # Results visualization
```

---

## Deployment Flexibility

This architecture works across multiple deployment targets:

| Target | Works? | Notes |
|--------|--------|-------|
| **Local (dev)** | Yes | `python -m backend.main` + `streamlit run frontend/app.py` |
| **HuggingFace Spaces** | Yes | Single container, free tier compatible |
| **Streamlit Cloud** | Yes | Can run FastAPI as subprocess |
| **Docker (any cloud)** | Yes | AWS ECS, GCP Cloud Run, Azure Container Apps |
| **VPS/Dedicated** | Yes | Just run the container or processes directly |

---

## Security Considerations

### Input Validation
- SMILES sanitization via RDKit
- Compound name filesystem safety
- SQL injection prevention (SQLAlchemy ORM)
- Request size limits

### API Security
- CORS configuration for Streamlit origin
- Rate limiting on all external API calls
- Request timeout limits
- Error message sanitization

### Data Security
- No credentials in code
- Environment variables for secrets
- Azure connection string in env vars

---

## Future Scaling

When you outgrow this setup, upgrade to:
**`.claude/plans/future_prod/3-container-redis-rq-plan.md`**

**Upgrade triggers:**
- Need >10 concurrent users
- Need >2 parallel processing jobs
- Need job persistence across restarts
- Moving to paid HF Spaces Pro or self-hosted
