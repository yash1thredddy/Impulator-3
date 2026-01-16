# API Optimization & InChIKey Update Plan (Jan 16, 2026)

## Summary

This plan consolidates the research and testing done for:
1. InChIKey-based duplicate detection
2. API batch optimization (ChEMBL and PDB)
3. Using InChIKey for PDB search (new insight)

---

> **STATUS: PENDING VALIDATION**
>
> The test script (`tests/test_api_batch_performance.py`) has NOT been run yet.
> This plan will be finalized based on actual test results. Expected performance
> numbers are theoretical estimates that need validation before implementation.

---

## Part 1: InChIKey for Duplicate Detection + PDB Search

### Current State

| Component | Current | Problem |
|-----------|---------|---------|
| Duplicate detection | compound_name only | "Aspirin" and "acetylsalicylic acid" NOT detected as same |
| PDB search | SMILES | SMILES variations cause cache misses |
| Storage | `results/{name}.zip` | O(n) listing, name collisions |

### Proposed: InChIKey Everywhere

InChIKey is an IUPAC standard 27-character hash:
- **Always 27 chars**: `BSYNRYMUTXBXSQ-UHFFFAOYSA-N`
- **100% deterministic**: Same structure = same InChIKey
- **RDKit already supports**: `MolToInchiKey(mol)`

**NEW INSIGHT**: PDB API supports InChIKey for chemical search!

```python
# PDB Search with InChIKey (modules/pdb_client.py)
query_payload = {
    "query": {
        "type": "terminal",
        "service": "chemical",
        "parameters": {
            "value": inchikey,              # Changed from SMILES
            "type": "descriptor",
            "descriptor_type": "InChIKey",  # Changed from "SMILES"
            "match_type": "graph-relaxed"
        }
    },
    ...
}
```

### Benefits of InChIKey

| Use Case | SMILES | InChIKey |
|----------|--------|----------|
| Duplicate detection | Multiple representations | 100% accurate |
| PDB search caching | May miss due to SMILES variants | 100% cache hits |
| Storage key | Variable length, needs sanitizing | Fixed 27 chars |

### Implementation Flow

```
User submits SMILES
    ↓
RDKit: Chem.MolFromSmiles(smiles)
    ↓
Generate: MolToInchiKey(mol)  ← Do this ONCE
    ↓
├── Check duplicate (InChIKey lookup in DB)
├── PDB search (using InChIKey)
└── Store in DB (compound.inchikey column)
```

---

## Part 2: API Batch Optimization

### Data Flow (Important!)

**ChEMBL (PRIMARY - main optimization target):**
```
1. User submits SMILES
2. Similarity search → returns ChEMBL IDs
3. Fetch bioactivity for ChEMBL IDs ← BOTTLENECK (sequential with batch_size=1)
```

**PDB (SECONDARY - for OQPLA structural evidence):**
```
1. search_similar_ligands(smiles/inchikey) → returns PDB IDs (single fast query)
2. get_batch_structure_resolutions(pdb_ids) → fetch resolution data (can use GraphQL)
```

### ChEMBL Optimization

**Current (slow):**
```python
# backend/services/compound_service.py - Sequential with batch_size=1
for chembl_id_dict in chembl_ids:
    chembl_id = chembl_id_dict.get('ChEMBL ID')
    activities = batch_fetch_activities([chembl_id], batch_size=1, max_workers=1)
```

**Proposed (fast):**
```python
# Batch all IDs at once
all_chembl_ids = [d.get('ChEMBL ID') for d in chembl_ids]
activities = batch_fetch_activities(
    all_chembl_ids,
    batch_size=50,      # ChEMBL recommended
    max_workers=4
)
```

**Expected speedup: 10x** (100 sequential calls → 2 batch calls)

### PDB Optimization

**Current (slow):**
```python
# modules/pdb_client.py - Sequential REST with delays
for pdb_id in pdb_ids:
    resolution = get_structure_resolution(pdb_id)
    time.sleep(0.2)  # Rate limit delay
```

**Proposed (fast) - GraphQL:**
```python
# Single GraphQL query for all PDB IDs
graphql_query = """
query($ids: [String!]!) {
    entries(entry_ids: $ids) {
        rcsb_id
        rcsb_entry_info { resolution_combined }
    }
}
"""
response = requests.post(
    "https://data.rcsb.org/graphql",
    json={"query": graphql_query, "variables": {"ids": pdb_ids}}
)
```

**Expected speedup: 10x+** (N requests → 1 request, no rate limits)

---

## Part 3: API Research & Rate Limits

### ChEMBL API Research

**Source**: [ChEMBL Web Services Documentation](https://chembl.gitbook.io/chembl-interface-documentation/web-services)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Recommended batch size | **50 IDs** | Used in official examples |
| Max pagination | 1000 results/page | Default is 20 |
| Bulk filter syntax | `molecule_chembl_id__in=[list]` | Works for activity, molecule endpoints |
| Rate limit | ~10 req/sec (unofficial) | No official documentation |
| Timeout issues | Common with large queries | ChEMBL client has no native timeout |
| Max URL length | ~8000 chars | Browser limit; ~200 IDs max in URL |

**ChEMBL Batch Query Syntax:**
```python
# Single ID (current - SLOW)
client.activity.filter(molecule_chembl_id="CHEMBL25")

# Batch IDs (proposed - FAST)
client.activity.filter(molecule_chembl_id__in=["CHEMBL25", "CHEMBL1642", ...])
```

**Key Insight**: The `__in` filter performs a single database query with an IN clause, dramatically faster than N separate queries.

---

### RCSB PDB API Research

**Source**: [RCSB PDB APIs Overview](https://www.rcsb.org/docs/programmatic-access/web-apis-overview)

#### REST API (Current)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Base URL | `https://data.rcsb.org/rest/v1/` | Core data API |
| Rate limit | ~5 req/sec | "handful of requests per second" |
| Rate limit response | HTTP 429 | Too Many Requests |
| Recovery strategy | Exponential backoff | Start with 1s, double each retry |
| Current delay | 0.2s per request | In `modules/pdb_client.py` |

#### GraphQL API (Proposed)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Endpoint | `https://data.rcsb.org/graphql` | Single endpoint |
| Rate limit | **None documented** | "No rate limits" per docs |
| Batch limit | Unknown | Tests will determine |
| Timeout | ~60s for large queries | Network dependent |

**GraphQL Advantages:**
1. **Single request for all IDs** - No pagination needed
2. **No rate limiting** - Currently no documented limits
3. **Select exact fields** - Only fetch what you need
4. **Atomic response** - All data or error, no partial states

**PDB Chemical Search (for InChIKey):**
```python
# SMILES search (current)
parameters = {
    "value": smiles,
    "type": "descriptor",
    "descriptor_type": "SMILES",
    "match_type": "graph-relaxed"
}

# InChIKey search (proposed - better caching)
parameters = {
    "value": inchikey,
    "type": "descriptor",
    "descriptor_type": "InChIKey",  # Same match_types supported
    "match_type": "graph-relaxed"
}
```

**Match Types Available:**
- `graph-relaxed` - Ignores stereochemistry
- `graph-relaxed-stereo` - Considers stereochemistry
- `graph-strict` - Exact match
- `fingerprint-similarity` - Tanimoto similarity search

---

## Part 4: Test Script Reference

> **TESTS NOT YET RUN** - Run tests before implementing to validate assumptions.

### Test File Location
```
tests/test_api_batch_performance.py
```

### How to Run
```bash
# Run all tests with verbose output
pytest tests/test_api_batch_performance.py -v -s

# Run specific test class
pytest tests/test_api_batch_performance.py::TestChEMBLRealFlow -v -s

# Run specific test
pytest tests/test_api_batch_performance.py::TestDataAccuracyVerification::test_chembl_data_accuracy -v -s
```

### Test Classes & Purpose

#### 1. `TestChEMBLBatchPerformance`
**Purpose**: Determine optimal ChEMBL batch sizes

| Test | What It Does |
|------|--------------|
| `test_activity_fetch_batch_sizes` | Tests batch sizes 1, 10, 25, 50, 100 for activity endpoint |
| `test_molecule_fetch_batch_sizes` | Tests batch sizes for molecule endpoint |
| `test_find_max_batch_size` | Tests 50-950 IDs to find URL length limits |

**Expected Output**: Timing data for each batch size, identify optimal size.

#### 2. `TestPDBBatchPerformance`
**Purpose**: Test PDB REST API rate limits

| Test | What It Does |
|------|--------------|
| `test_pdb_resolution_parallel` | Tests 1, 2, 5, 10 workers for parallel fetching |
| `test_pdb_with_delay` | Tests delays 0, 0.05, 0.1, 0.2, 0.5s |
| `test_pdb_burst_detection` | Finds how many requests before rate limit |

**Expected Output**: Identify when rate limiting kicks in.

#### 3. `TestDataAccuracyVerification` ⚠️ CRITICAL
**Purpose**: Ensure batch = sequential results (data integrity)

| Test | What It Does |
|------|--------------|
| `test_chembl_data_accuracy` | Compares sequential vs batch molecule data |
| `test_pdb_graphql_vs_rest_accuracy` | Compares REST vs GraphQL resolution data |
| `test_chembl_activity_data_accuracy` | Compares sequential vs batch activity data |
| `test_pdb_total_count_verification` | Verifies 50 PDB IDs return same count both ways |
| `test_chembl_total_count_verification` | Verifies 50 ChEMBL IDs return same count |

**Expected Output**: PASS = safe to use batch, FAIL = investigate before using.

#### 4. `TestBatchVsSequential`
**Purpose**: Direct speed comparison

| Test | What It Does |
|------|--------------|
| `test_chembl_batch_vs_sequential` | Compares 20 ID fetch: sequential vs batch |

**Expected Output**: Speedup factor (e.g., "Batch is 5.2x faster").

#### 5. `TestCurrentImplementation`
**Purpose**: Test existing codebase functions

| Test | What It Does |
|------|--------------|
| `test_current_batch_fetch_activities` | Tests `batch_fetch_activities()` with size=1 vs size=50 |

**Expected Output**: Validates the actual function we'll optimize.

#### 6. `TestPDBGraphQLVsREST`
**Purpose**: Compare GraphQL vs REST for PDB

| Test | What It Does |
|------|--------------|
| `test_graphql_batch_resolutions` | Tests GraphQL single-query for 20 IDs |
| `test_rest_vs_graphql_comparison` | Direct timing comparison for 10 IDs |
| `test_graphql_large_batch` | Tests GraphQL with 20, 50, 100, 200 IDs |

**Expected Output**: GraphQL speedup factor, max batch size.

#### 7. `TestPDBGraphQLExtendedData`
**Purpose**: Test GraphQL multi-field queries

| Test | What It Does |
|------|--------------|
| `test_graphql_full_structure_details` | Fetches resolution, method, title, DOI in one query |

**Expected Output**: Demonstrates GraphQL efficiency for multiple fields.

#### 8. `TestRealPDBFlow`
**Purpose**: Test actual IMPULATOR PDB data flow

| Test | What It Does |
|------|--------------|
| `test_real_pdb_flow_with_smiles` | SMILES → search_similar_ligands → fetch resolutions |

**Expected Output**: End-to-end timing for real workflow.

#### 9. `TestChEMBLRealFlow`
**Purpose**: Test actual IMPULATOR ChEMBL data flow

| Test | What It Does |
|------|--------------|
| `test_real_chembl_flow_with_smiles` | SMILES → similarity search → fetch activities |

**Expected Output**: End-to-end timing for real workflow.

---

### Test Results (THEORETICAL - Pending Validation)

| Operation | Before | After | Speedup |
|-----------|--------|-------|---------|
| ChEMBL 100 IDs | ~5 min | ~30s | **10x** |
| PDB 100 resolutions | ~2 min | ~2s | **60x** |
| Total job time | 5-10 min | 1-2 min | **5x** |

*These numbers are estimates based on API documentation. Actual results may vary.*

### What to Look For in Test Results

1. **ChEMBL Optimal Batch Size**: Is 50 truly optimal, or should we use 25 or 100?
2. **ChEMBL Max Batch Size**: What's the URL length limit? (expect ~200-500 IDs)
3. **PDB Rate Limit Threshold**: How many parallel requests before 429?
4. **GraphQL vs REST Speedup**: Is it really 10x+ faster?
5. **Data Accuracy**: Do batch queries return IDENTICAL data?

---

## Part 4: Implementation Checklist

### Phase 1: InChIKey Infrastructure
- [ ] Add `inchikey` column to Compound table (nullable first)
- [ ] Add `canonical_smiles` column to Compound table
- [ ] Add `entry_id` (UUID) column for storage path
- [ ] Create helper function to generate InChIKey from SMILES

### Phase 2: Duplicate Detection
- [ ] Generate InChIKey on job submission
- [ ] Check for existing InChIKey before processing
- [ ] Return duplicate warning with existing compound info
- [ ] Add frontend duplicate warning UI

### Phase 3: PDB Search with InChIKey
- [ ] Update `search_similar_ligands()` to accept InChIKey
- [ ] Change `descriptor_type` from "SMILES" to "InChIKey"
- [ ] Update LRU cache to use InChIKey as key

### Phase 4: PDB GraphQL
- [ ] Implement `get_batch_structure_resolutions_graphql()`
- [ ] Update `get_pdb_evidence_score()` to use GraphQL
- [ ] Remove sequential delays

### Phase 5: ChEMBL Batch Fix
- [ ] Update `compound_service.py` to batch all ChEMBL IDs
- [ ] Use `batch_size=50` instead of `1`
- [ ] Add progress callback for batch processing

### Phase 6: Storage Migration
- [ ] Create UUID-based storage paths: `results/{2-char}/{uuid}.zip`
- [ ] Write migration script for existing data
- [ ] Update Azure sync to use new paths

---

## Files to Modify

| File | Changes |
|------|---------|
| `backend/models/database.py` | Add `entry_id`, `inchikey`, `canonical_smiles` |
| `backend/services/job_service.py` | Generate InChIKey, check duplicates |
| `backend/services/compound_service.py` | Batch ChEMBL activity fetch |
| `modules/pdb_client.py` | InChIKey search, GraphQL resolution fetch |
| `backend/core/__init__.py` | Add `get_storage_path(entry_id)` |
| `backend/core/azure_sync.py` | UUID-based paths |
| `frontend/ui/components/job_form.py` | Duplicate warning UI |

---

## References

- [ChEMBL Web Services](https://chembl.gitbook.io/chembl-interface-documentation/web-services)
- [RCSB PDB Search API](https://search.rcsb.org/)
- [RCSB PDB GraphQL](https://data.rcsb.org/graphql)
- [InChIKey Standard](https://www.inchi-trust.org/)

---

## Next Steps

1. **RUN TESTS FIRST** - Execute `pytest tests/test_api_batch_performance.py -v -s`
2. Review test results and adjust plan if needed
3. Decide on migration strategy (immediate vs gradual)
4. Implement in phases, starting with InChIKey infrastructure

> **DO NOT IMPLEMENT** until tests are run and results are reviewed.
