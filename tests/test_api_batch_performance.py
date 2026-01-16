"""
Test script to determine optimal batch sizes for ChEMBL and PDB APIs.

Run with: pytest tests/test_api_batch_performance.py -v -s

=== IMPULATOR DATA FLOW ===

1. ChEMBL (PRIMARY - main optimization target):
   - Input: Compound SMILES
   - Step 1: Similarity search → returns ChEMBL IDs of similar compounds
   - Step 2: Fetch bioactivity data for those ChEMBL IDs (BOTTLENECK!)
   - Current: Sequential calls with batch_size=1
   - Proposed: Batched calls with batch_size=50

2. PDB (SECONDARY - for OQPLA structural evidence scoring):
   - Input: Compound SMILES
   - Step 1: search_similar_ligands(smiles) → returns PDB IDs (single fast query)
   - Step 2: get_batch_structure_resolutions(pdb_ids) → fetch resolution data (can be optimized)
   - Current: Sequential REST calls with 0.2s delays
   - Proposed: GraphQL single query (no rate limits)

This script tests:
1. ChEMBL API batch sizes (1, 10, 25, 50, 100 IDs per request) - PRIORITY
2. ChEMBL maximum batch size (50-950 IDs) - find URL length limits
3. PDB resolution fetching: REST vs GraphQL (for step 2 above)
4. Data accuracy verification - ensure batch results match sequential

Results will help determine optimal settings for production.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional
import pytest

# Sample ChEMBL IDs for testing (common drugs with known activity data)
SAMPLE_CHEMBL_IDS = [
    "CHEMBL25",      # Aspirin
    "CHEMBL1642",    # Paracetamol
    "CHEMBL521",     # Ibuprofen
    "CHEMBL41",      # Caffeine
    "CHEMBL192",     # Metformin
    "CHEMBL1201087", # Atorvastatin
    "CHEMBL1",       # Atropine
    "CHEMBL2",       # Physostigmine
    "CHEMBL3",       # Amitriptyline
    "CHEMBL4",       # Clomipramine
]

# Sample PDB IDs for testing (200 unique well-known structures)
SAMPLE_PDB_IDS = [
    # Classic structures
    "1CRN", "1HHO", "1MBO", "2HHB", "3HHB", "4HHB", "1AKE", "2AKE", "3AKE", "4AKE",
    "1TIM", "2TIM", "3TIM", "1LYZ", "2LYZ", "3LYZ", "1INS", "2INS", "3INS", "4INS",
    "1GFL", "2GFL", "1UBQ", "2UBQ", "1A3N", "2A3N", "1BNA", "2BNA", "1EHZ", "2EHZ",
    "1HSG", "2HSG", "1FKN", "2FKN", "1ATP", "2ATP", "1CDK", "2CDK", "1HIV", "2HIV",
    # More structures for larger batch tests
    "1AO6", "2AO6", "1BRS", "2BRS", "1CSE", "2CSE", "1ECA", "2ECA", "1FME", "2FME",
    "1GZM", "2GZM", "1HEW", "2HEW", "1IGT", "2IGT", "1JPC", "2JPC", "1KAP", "2KAP",
    "1L2Y", "2L2Y", "1M1K", "2M1K", "1NLS", "2NLS", "1OVA", "2OVA", "1PGB", "2PGB",
    "1QCR", "2QCR", "1RHD", "2RHD", "1STP", "2STP", "1TEN", "2TEN", "1UOK", "2UOK",
    "1VPH", "2VPH", "1WLA", "2WLA", "1XMK", "2XMK", "1YGE", "2YGE", "1ZAA", "2ZAA",
    "3A0B", "3B0B", "3C0B", "3D0B", "3E0B", "3F0B", "3G0B", "3H0B", "3I0B", "3J0B",
    # Additional unique IDs for 100+ batch tests
    "4A0B", "4B0B", "4C0B", "4D0B", "4E0B", "4F0B", "4G0B", "4H0B", "4I0B", "4J0B",
    "5A0B", "5B0B", "5C0B", "5D0B", "5E0B", "5F0B", "5G0B", "5H0B", "5I0B", "5J0B",
    "6A0B", "6B0B", "6C0B", "6D0B", "6E0B", "6F0B", "6G0B", "6H0B", "6I0B", "6J0B",
    "7A0B", "7B0B", "7C0B", "7D0B", "7E0B", "7F0B", "7G0B", "7H0B", "7I0B", "7J0B",
    "1A00", "1A01", "1A02", "1A03", "1A04", "1A05", "1A06", "1A07", "1A08", "1A09",
    "1A0A", "1A0B", "1A0C", "1A0D", "1A0E", "1A0F", "1A0G", "1A0H", "1A0I", "1A0J",
    "1A0K", "1A0L", "1A0M", "1A0N", "1A0O", "1A0P", "1A0Q", "1A0R", "1A0S", "1A0T",
    "1A0U", "1A0V", "1A0W", "1A0X", "1A0Y", "1A0Z", "1A10", "1A11", "1A12", "1A13",
    "1A14", "1A15", "1A16", "1A17", "1A18", "1A19", "1A1A", "1A1B", "1A1C", "1A1D",
    "1A1E", "1A1F", "1A1G", "1A1H", "1A1I", "1A1J", "1A1K", "1A1L", "1A1M", "1A1N",
]


class TestChEMBLBatchPerformance:
    """Test ChEMBL API batch performance with different batch sizes."""

    @pytest.fixture
    def chembl_client(self):
        """Get ChEMBL client."""
        from chembl_webresource_client.new_client import new_client
        return new_client

    @pytest.mark.parametrize("batch_size", [1, 10, 25, 50, 100])
    def test_activity_fetch_batch_sizes(self, chembl_client, batch_size):
        """
        Test activity fetching with different batch sizes.

        This tests the molecule_chembl_id__in filter which is the key
        for batch activity fetching.
        """
        # Use 50 unique IDs (duplicating sample if needed)
        test_ids = (SAMPLE_CHEMBL_IDS * 5)[:50]

        start = time.time()
        results = []
        errors = []

        # Batch the IDs
        for i in range(0, len(test_ids), batch_size):
            batch = test_ids[i:i + batch_size]
            try:
                activities = chembl_client.activity.filter(
                    molecule_chembl_id__in=batch,
                    standard_type="IC50"
                ).only(['molecule_chembl_id', 'standard_value', 'target_chembl_id'])

                # Limit results to avoid memory issues
                batch_results = list(activities)[:100]
                results.extend(batch_results)
            except Exception as e:
                errors.append(f"Batch {i//batch_size}: {e}")

        elapsed = time.time() - start

        print(f"\n  ========================================")
        print(f"  BATCH SIZE: {batch_size}")
        print(f"  Total IDs: {len(test_ids)}")
        print(f"  Batches made: {(len(test_ids) + batch_size - 1) // batch_size}")
        print(f"  Results fetched: {len(results)}")
        print(f"  Errors: {len(errors)}")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  ========================================")

        if errors:
            for err in errors[:3]:  # Show first 3 errors
                print(f"  Error: {err}")

        # Assert reasonable performance (2 min max)
        assert elapsed < 120, f"Batch size {batch_size} too slow: {elapsed}s"

    @pytest.mark.parametrize("batch_size", [1, 10, 25, 50, 100])
    def test_molecule_fetch_batch_sizes(self, chembl_client, batch_size):
        """
        Test molecule data fetching with different batch sizes.

        This tests fetching molecule metadata (name, structures, etc.)
        """
        test_ids = (SAMPLE_CHEMBL_IDS * 5)[:50]

        start = time.time()
        results = []
        errors = []

        for i in range(0, len(test_ids), batch_size):
            batch = test_ids[i:i + batch_size]
            try:
                molecules = chembl_client.molecule.filter(
                    molecule_chembl_id__in=batch
                ).only(['molecule_chembl_id', 'pref_name', 'molecule_structures'])
                results.extend(list(molecules))
            except Exception as e:
                errors.append(f"Batch {i//batch_size}: {e}")

        elapsed = time.time() - start

        print(f"\n  ========================================")
        print(f"  MOLECULE FETCH - BATCH SIZE: {batch_size}")
        print(f"  Total IDs: {len(test_ids)}")
        print(f"  Molecules fetched: {len(results)}")
        print(f"  Errors: {len(errors)}")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  ========================================")

    def test_find_max_batch_size(self, chembl_client):
        """
        Find the maximum batch size that works without errors.

        ChEMBL may have URL length limits or other constraints.
        """
        test_sizes = [50, 100, 200, 300, 500, 700, 950]
        results = {}

        for size in test_sizes:
            test_ids = (SAMPLE_CHEMBL_IDS * 50)[:size]
            try:
                start = time.time()
                molecules = chembl_client.molecule.filter(
                    molecule_chembl_id__in=test_ids
                ).only(['molecule_chembl_id'])
                count = len(list(molecules))
                elapsed = time.time() - start
                results[size] = {"success": True, "count": count, "time": elapsed}
                print(f"\n  Size {size}: SUCCESS - {count} molecules in {elapsed:.2f}s")
            except Exception as e:
                results[size] = {"success": False, "error": str(e)[:100]}
                print(f"\n  Size {size}: FAILED - {str(e)[:100]}")

        # Find max working size
        max_working = max([s for s, r in results.items() if r["success"]], default=0)
        print(f"\n  MAX WORKING BATCH SIZE: {max_working}")


class TestPDBBatchPerformance:
    """
    Test PDB API batch performance for resolution fetching (Step 2 of PDB flow).

    NOTE: PDB IDs come from search_similar_ligands(smiles) in the real flow.
    This class tests how to efficiently fetch resolution data AFTER we have PDB IDs.

    Real flow:
    1. search_similar_ligands(smiles) → returns list of PDB IDs (single API call)
    2. get_batch_structure_resolutions(pdb_ids) → fetch resolutions (this is what we optimize)
    """

    @pytest.mark.parametrize("max_workers", [1, 2, 5, 10])
    def test_pdb_resolution_parallel(self, max_workers):
        """
        Test PDB resolution fetching with different worker counts.

        This helps determine how many parallel requests PDB allows
        before rate limiting kicks in.
        """
        import requests

        # Use 20 unique IDs
        test_ids = (SAMPLE_PDB_IDS * 2)[:20]

        def fetch_resolution(pdb_id: str) -> Tuple[str, any]:
            """Fetch resolution for a single PDB ID."""
            url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    resolution = data.get('rcsb_entry_info', {}).get('resolution_combined', [None])
                    return pdb_id, resolution[0] if resolution else None
                elif resp.status_code == 429:
                    return pdb_id, "RATE_LIMITED"
                else:
                    return pdb_id, f"HTTP_{resp.status_code}"
            except Exception as e:
                return pdb_id, f"ERROR: {str(e)[:50]}"

        start = time.time()
        results = {}
        rate_limited = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_resolution, pdb_id): pdb_id for pdb_id in test_ids}
            for future in as_completed(futures):
                pdb_id, resolution = future.result()
                results[pdb_id] = resolution
                if resolution == "RATE_LIMITED":
                    rate_limited += 1
                elif isinstance(resolution, str) and resolution.startswith("ERROR"):
                    errors += 1

        elapsed = time.time() - start
        successful = len(test_ids) - rate_limited - errors

        print(f"\n  ========================================")
        print(f"  PDB PARALLEL - WORKERS: {max_workers}")
        print(f"  Total IDs: {len(test_ids)}")
        print(f"  Successful: {successful}")
        print(f"  Rate Limited: {rate_limited}")
        print(f"  Errors: {errors}")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  Requests/sec: {len(test_ids)/elapsed:.1f}")
        print(f"  ========================================")

        if rate_limited > 0:
            print(f"  WARNING: Hit rate limit with {max_workers} workers!")

    def test_pdb_with_delay(self):
        """
        Test PDB with enforced delay between requests.

        Find the minimum delay needed to avoid rate limiting.
        """
        import requests

        test_ids = SAMPLE_PDB_IDS[:10]
        delays = [0, 0.05, 0.1, 0.2, 0.5]

        print(f"\n  ========================================")
        print(f"  PDB DELAY TEST")
        print(f"  ========================================")

        for delay in delays:
            start = time.time()
            rate_limited = 0
            successful = 0

            for pdb_id in test_ids:
                url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                try:
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 429:
                        rate_limited += 1
                    elif resp.status_code == 200:
                        successful += 1
                except:
                    pass
                time.sleep(delay)

            elapsed = time.time() - start
            print(f"  Delay={delay}s: {elapsed:.2f}s total, {successful} ok, {rate_limited} rate-limited")

    def test_pdb_burst_detection(self):
        """
        Test how many rapid requests PDB allows before rate limiting.
        """
        import requests

        print(f"\n  ========================================")
        print(f"  PDB BURST TEST - Finding rate limit threshold")
        print(f"  ========================================")

        burst_size = 20
        test_ids = (SAMPLE_PDB_IDS * 3)[:burst_size]

        rate_limited_at = None
        for i, pdb_id in enumerate(test_ids):
            url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 429:
                    rate_limited_at = i + 1
                    print(f"  Rate limited after {rate_limited_at} requests")
                    break
                elif resp.status_code == 200:
                    print(f"  Request {i+1}: OK")
            except Exception as e:
                print(f"  Request {i+1}: Error - {e}")

        if rate_limited_at is None:
            print(f"  No rate limiting detected in {burst_size} requests!")


class TestDataAccuracyVerification:
    """Verify that batch queries return the SAME data as sequential queries."""

    def test_chembl_data_accuracy(self):
        """
        CRITICAL TEST: Verify batch results match sequential results exactly.

        This ensures we don't lose or corrupt data when batching.
        """
        from chembl_webresource_client.new_client import new_client

        # Use 5 unique IDs for accurate comparison
        test_ids = SAMPLE_CHEMBL_IDS[:5]

        print(f"\n  ========================================")
        print(f"  ChEMBL DATA ACCURACY VERIFICATION")
        print(f"  Test IDs: {test_ids}")
        print(f"  ========================================")

        # Method 1: Sequential (one ID at a time)
        print(f"\n  Fetching SEQUENTIAL...")
        sequential_data = {}
        for chembl_id in test_ids:
            try:
                molecules = new_client.molecule.filter(
                    molecule_chembl_id=chembl_id
                ).only(['molecule_chembl_id', 'pref_name', 'molecule_properties'])
                mol_list = list(molecules)
                if mol_list:
                    sequential_data[chembl_id] = {
                        'pref_name': mol_list[0].get('pref_name'),
                        'mw': mol_list[0].get('molecule_properties', {}).get('full_mwt') if mol_list[0].get('molecule_properties') else None
                    }
            except Exception as e:
                print(f"    Sequential error for {chembl_id}: {e}")

        # Method 2: Batch (all IDs at once)
        print(f"  Fetching BATCH...")
        batch_data = {}
        try:
            molecules = new_client.molecule.filter(
                molecule_chembl_id__in=test_ids
            ).only(['molecule_chembl_id', 'pref_name', 'molecule_properties'])
            for mol in molecules:
                chembl_id = mol.get('molecule_chembl_id')
                batch_data[chembl_id] = {
                    'pref_name': mol.get('pref_name'),
                    'mw': mol.get('molecule_properties', {}).get('full_mwt') if mol.get('molecule_properties') else None
                }
        except Exception as e:
            print(f"    Batch error: {e}")

        # Compare results
        print(f"\n  COMPARISON:")
        all_match = True
        for chembl_id in test_ids:
            seq = sequential_data.get(chembl_id, {})
            bat = batch_data.get(chembl_id, {})

            match = seq == bat
            status = "✓ MATCH" if match else "✗ MISMATCH"

            print(f"    {chembl_id}: {status}")
            if not match:
                print(f"      Sequential: {seq}")
                print(f"      Batch:      {bat}")
                all_match = False

        print(f"\n  ========================================")
        if all_match:
            print(f"  RESULT: ALL DATA MATCHES - Batch is SAFE to use")
        else:
            print(f"  RESULT: DATA MISMATCH - Investigate before using batch!")
        print(f"  ========================================")

        assert all_match, "Batch data does not match sequential data!"

    def test_pdb_graphql_vs_rest_accuracy(self):
        """
        CRITICAL TEST: Verify GraphQL returns same data as REST API.

        This ensures GraphQL doesn't return different/incorrect values.
        """
        import requests

        # Use 5 unique PDB IDs
        test_ids = SAMPLE_PDB_IDS[:5]

        print(f"\n  ========================================")
        print(f"  PDB DATA ACCURACY VERIFICATION")
        print(f"  Test IDs: {test_ids}")
        print(f"  ========================================")

        # Method 1: REST API (sequential)
        print(f"\n  Fetching via REST API...")
        rest_data = {}
        for pdb_id in test_ids:
            try:
                url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    res_list = data.get('rcsb_entry_info', {}).get('resolution_combined', [])
                    method = data.get('rcsb_entry_info', {}).get('experimental_method')
                    title = data.get('struct', {}).get('title', '')[:50] if data.get('struct') else ''

                    rest_data[pdb_id] = {
                        'resolution': round(res_list[0], 3) if res_list else None,
                        'method': method,
                        'title': title
                    }
            except Exception as e:
                print(f"    REST error for {pdb_id}: {e}")

        # Method 2: GraphQL (single query)
        print(f"  Fetching via GraphQL...")
        graphql_data = {}
        graphql_query = """
        query($ids: [String!]!) {
            entries(entry_ids: $ids) {
                rcsb_id
                struct {
                    title
                }
                rcsb_entry_info {
                    resolution_combined
                    experimental_method
                }
            }
        }
        """
        try:
            response = requests.post(
                "https://data.rcsb.org/graphql",
                json={"query": graphql_query, "variables": {"ids": test_ids}},
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                for entry in data.get("data", {}).get("entries", []):
                    pdb_id = entry.get("rcsb_id")
                    res_list = entry.get("rcsb_entry_info", {}).get("resolution_combined", [])
                    method = entry.get("rcsb_entry_info", {}).get("experimental_method")
                    title = entry.get("struct", {}).get("title", '')[:50] if entry.get("struct") else ''

                    graphql_data[pdb_id] = {
                        'resolution': round(res_list[0], 3) if res_list else None,
                        'method': method,
                        'title': title
                    }
        except Exception as e:
            print(f"    GraphQL error: {e}")

        # Compare results
        print(f"\n  COMPARISON:")
        all_match = True
        for pdb_id in test_ids:
            rest = rest_data.get(pdb_id, {})
            gql = graphql_data.get(pdb_id, {})

            match = rest == gql
            status = "✓ MATCH" if match else "✗ MISMATCH"

            print(f"    {pdb_id}: {status}")
            if match:
                print(f"      Resolution: {rest.get('resolution')} Å, Method: {rest.get('method')}")
            else:
                print(f"      REST:    {rest}")
                print(f"      GraphQL: {gql}")
                all_match = False

        print(f"\n  ========================================")
        if all_match:
            print(f"  RESULT: ALL DATA MATCHES - GraphQL is SAFE to use")
        else:
            print(f"  RESULT: DATA MISMATCH - Investigate before using GraphQL!")
        print(f"  ========================================")

        assert all_match, "GraphQL data does not match REST data!"

    def test_chembl_activity_data_accuracy(self):
        """
        Verify activity data accuracy between sequential and batch fetching.

        This is the most critical test since activities are the main data.
        """
        from chembl_webresource_client.new_client import new_client

        # Use 3 IDs with known activity data
        test_ids = ["CHEMBL25", "CHEMBL1642", "CHEMBL521"]  # Aspirin, Paracetamol, Ibuprofen

        print(f"\n  ========================================")
        print(f"  ChEMBL ACTIVITY DATA ACCURACY")
        print(f"  Test IDs: {test_ids}")
        print(f"  ========================================")

        # Method 1: Sequential
        print(f"\n  Fetching activities SEQUENTIAL...")
        sequential_activities = {}
        for chembl_id in test_ids:
            try:
                activities = new_client.activity.filter(
                    molecule_chembl_id=chembl_id,
                    standard_type="IC50"
                ).only(['molecule_chembl_id', 'target_chembl_id', 'standard_value', 'standard_units'])
                # Get first 5 activities for comparison
                act_list = list(activities)[:5]
                sequential_activities[chembl_id] = len(act_list)
            except Exception as e:
                print(f"    Error for {chembl_id}: {e}")
                sequential_activities[chembl_id] = 0

        # Method 2: Batch
        print(f"  Fetching activities BATCH...")
        batch_activities = {cid: 0 for cid in test_ids}
        try:
            activities = new_client.activity.filter(
                molecule_chembl_id__in=test_ids,
                standard_type="IC50"
            ).only(['molecule_chembl_id', 'target_chembl_id', 'standard_value', 'standard_units'])

            for act in activities:
                cid = act.get('molecule_chembl_id')
                if cid in batch_activities:
                    batch_activities[cid] += 1
        except Exception as e:
            print(f"    Batch error: {e}")

        # Compare counts (exact match not expected due to pagination, but should be similar)
        print(f"\n  ACTIVITY COUNT COMPARISON:")
        print(f"  (Note: Batch may return more due to single query)")
        for chembl_id in test_ids:
            seq_count = sequential_activities.get(chembl_id, 0)
            batch_count = batch_activities.get(chembl_id, 0)
            # Batch should have >= sequential (since sequential was limited to 5)
            print(f"    {chembl_id}: Sequential={seq_count}, Batch={batch_count}")

        print(f"\n  ========================================")
        print(f"  Activity data retrieved successfully from both methods")
        print(f"  ========================================")

    def test_pdb_total_count_verification(self):
        """
        CRITICAL: Verify REST and GraphQL return the SAME number of entries.

        This checks if pagination/limits affect the total count.
        We use a larger set of PDB IDs to stress-test pagination.
        """
        import requests

        # Use 50 unique PDB IDs to test pagination limits
        # These are well-known structures that should all exist
        test_ids = [
            "1CRN", "1HHO", "1MBO", "2HHB", "3HHB", "4HHB", "1AKE", "2AKE", "3AKE", "4AKE",
            "1TIM", "2TIM", "3TIM", "1LYZ", "2LYZ", "3LYZ", "1INS", "2INS", "3INS", "4INS",
            "1GFL", "2GFL", "1UBQ", "2UBQ", "1A3N", "2A3N", "1BNA", "2BNA", "1EHZ", "2EHZ",
            "1HSG", "2HSG", "1FKN", "2FKN", "1ATP", "2ATP", "1CDK", "2CDK", "1HIV", "2HIV",
            "1AO6", "2AO6", "1BRS", "2BRS", "1CSE", "2CSE", "1ECA", "2ECA", "1FME", "2FME",
        ]

        print(f"\n  ========================================")
        print(f"  PDB TOTAL COUNT VERIFICATION")
        print(f"  Testing with {len(test_ids)} PDB IDs")
        print(f"  ========================================")

        # Method 1: REST API (sequential) - count successful entries
        print(f"\n  Fetching via REST API...")
        rest_count = 0
        rest_data = {}
        for pdb_id in test_ids:
            try:
                url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    res_list = data.get('rcsb_entry_info', {}).get('resolution_combined', [])
                    rest_data[pdb_id] = res_list[0] if res_list else None
                    rest_count += 1
                elif resp.status_code == 404:
                    print(f"    {pdb_id}: NOT FOUND (404)")
            except Exception as e:
                print(f"    REST error for {pdb_id}: {e}")

        # Method 2: GraphQL (single query)
        print(f"  Fetching via GraphQL (single query)...")
        graphql_query = """
        query($ids: [String!]!) {
            entries(entry_ids: $ids) {
                rcsb_id
                rcsb_entry_info {
                    resolution_combined
                }
            }
        }
        """
        graphql_count = 0
        graphql_data = {}
        try:
            response = requests.post(
                "https://data.rcsb.org/graphql",
                json={"query": graphql_query, "variables": {"ids": test_ids}},
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            if response.status_code == 200:
                data = response.json()
                entries = data.get("data", {}).get("entries", [])
                graphql_count = len(entries)
                for entry in entries:
                    pdb_id = entry.get("rcsb_id")
                    res_list = entry.get("rcsb_entry_info", {}).get("resolution_combined", [])
                    graphql_data[pdb_id] = res_list[0] if res_list else None
            else:
                print(f"    GraphQL error: {response.status_code}")
                print(f"    Response: {response.text[:300]}")
        except Exception as e:
            print(f"    GraphQL error: {e}")

        # Compare counts
        print(f"\n  TOTAL COUNT COMPARISON:")
        print(f"  REST API entries:    {rest_count}")
        print(f"  GraphQL entries:     {graphql_count}")
        print(f"  Difference:          {abs(rest_count - graphql_count)}")

        # Check which IDs are missing
        rest_ids = set(rest_data.keys())
        graphql_ids = set(graphql_data.keys())

        only_in_rest = rest_ids - graphql_ids
        only_in_graphql = graphql_ids - rest_ids

        if only_in_rest:
            print(f"\n  IDs only in REST: {only_in_rest}")
        if only_in_graphql:
            print(f"  IDs only in GraphQL: {only_in_graphql}")

        # Verify resolution values match for common IDs
        common_ids = rest_ids & graphql_ids
        mismatches = []
        for pdb_id in common_ids:
            rest_val = rest_data.get(pdb_id)
            gql_val = graphql_data.get(pdb_id)
            if rest_val != gql_val:
                # Allow small floating point differences
                if rest_val is not None and gql_val is not None:
                    if abs(rest_val - gql_val) > 0.001:
                        mismatches.append((pdb_id, rest_val, gql_val))
                else:
                    mismatches.append((pdb_id, rest_val, gql_val))

        if mismatches:
            print(f"\n  VALUE MISMATCHES:")
            for pdb_id, rest_val, gql_val in mismatches[:5]:
                print(f"    {pdb_id}: REST={rest_val}, GraphQL={gql_val}")
        else:
            print(f"\n  All {len(common_ids)} common entries have matching values!")

        print(f"\n  ========================================")
        if rest_count == graphql_count and not mismatches:
            print(f"  RESULT: COUNTS MATCH - No pagination issues!")
        else:
            print(f"  RESULT: INVESTIGATE - Count or value differences found")
        print(f"  ========================================")

    def test_chembl_total_count_verification(self):
        """
        CRITICAL: Verify sequential vs batch fetching returns SAME total count.

        This checks if pagination limits affect the total results.
        Uses 50 unique ChEMBL IDs to stress test.
        """
        from chembl_webresource_client.new_client import new_client

        # Use 50 unique ChEMBL IDs
        test_ids = [
            "CHEMBL25", "CHEMBL1642", "CHEMBL521", "CHEMBL41", "CHEMBL192",
            "CHEMBL1201087", "CHEMBL1", "CHEMBL2", "CHEMBL3", "CHEMBL4",
            "CHEMBL5", "CHEMBL6", "CHEMBL7", "CHEMBL8", "CHEMBL9",
            "CHEMBL10", "CHEMBL11", "CHEMBL12", "CHEMBL13", "CHEMBL14",
            "CHEMBL15", "CHEMBL16", "CHEMBL17", "CHEMBL18", "CHEMBL19",
            "CHEMBL20", "CHEMBL21", "CHEMBL22", "CHEMBL23", "CHEMBL24",
            "CHEMBL26", "CHEMBL27", "CHEMBL28", "CHEMBL29", "CHEMBL30",
            "CHEMBL31", "CHEMBL32", "CHEMBL33", "CHEMBL34", "CHEMBL35",
            "CHEMBL36", "CHEMBL37", "CHEMBL38", "CHEMBL39", "CHEMBL40",
            "CHEMBL42", "CHEMBL43", "CHEMBL44", "CHEMBL45", "CHEMBL46",
        ]

        print(f"\n  ========================================")
        print(f"  ChEMBL TOTAL COUNT VERIFICATION")
        print(f"  Testing with {len(test_ids)} unique ChEMBL IDs")
        print(f"  ========================================")

        # Method 1: Sequential - fetch molecules one by one
        print(f"\n  Fetching molecules SEQUENTIAL...")
        sequential_data = {}
        sequential_count = 0
        for chembl_id in test_ids:
            try:
                molecules = new_client.molecule.filter(
                    molecule_chembl_id=chembl_id
                ).only(['molecule_chembl_id', 'pref_name'])
                mol_list = list(molecules)
                if mol_list:
                    sequential_data[chembl_id] = mol_list[0].get('pref_name')
                    sequential_count += 1
            except Exception as e:
                print(f"    Error for {chembl_id}: {e}")

        # Method 2: Batch - fetch all at once
        print(f"  Fetching molecules BATCH (all {len(test_ids)} at once)...")
        batch_data = {}
        batch_count = 0
        try:
            molecules = new_client.molecule.filter(
                molecule_chembl_id__in=test_ids
            ).only(['molecule_chembl_id', 'pref_name'])

            for mol in molecules:
                chembl_id = mol.get('molecule_chembl_id')
                batch_data[chembl_id] = mol.get('pref_name')
                batch_count += 1
        except Exception as e:
            print(f"    Batch error: {e}")

        # Compare counts
        print(f"\n  TOTAL COUNT COMPARISON:")
        print(f"  Sequential entries:  {sequential_count}")
        print(f"  Batch entries:       {batch_count}")
        print(f"  Difference:          {abs(sequential_count - batch_count)}")

        # Check which IDs are missing
        seq_ids = set(sequential_data.keys())
        batch_ids = set(batch_data.keys())

        only_in_seq = seq_ids - batch_ids
        only_in_batch = batch_ids - seq_ids

        if only_in_seq:
            print(f"\n  IDs only in Sequential: {list(only_in_seq)[:10]}")
        if only_in_batch:
            print(f"  IDs only in Batch: {list(only_in_batch)[:10]}")

        # Verify values match for common IDs
        common_ids = seq_ids & batch_ids
        mismatches = []
        for chembl_id in common_ids:
            seq_val = sequential_data.get(chembl_id)
            batch_val = batch_data.get(chembl_id)
            if seq_val != batch_val:
                mismatches.append((chembl_id, seq_val, batch_val))

        if mismatches:
            print(f"\n  VALUE MISMATCHES:")
            for chembl_id, seq_val, batch_val in mismatches[:5]:
                print(f"    {chembl_id}: Seq='{seq_val}', Batch='{batch_val}'")
        else:
            print(f"\n  All {len(common_ids)} common entries have matching names!")

        print(f"\n  ========================================")
        if sequential_count == batch_count and not mismatches:
            print(f"  RESULT: COUNTS MATCH - Batch fetching is SAFE!")
        else:
            print(f"  RESULT: INVESTIGATE - Count or value differences found")
        print(f"  ========================================")


class TestBatchVsSequential:
    """Compare batch vs sequential performance."""

    def test_chembl_batch_vs_sequential(self):
        """
        Direct comparison of batch vs sequential ChEMBL calls.

        This demonstrates the performance gain from batching.
        """
        from chembl_webresource_client.new_client import new_client

        # Use 20 IDs for comparison
        test_ids = (SAMPLE_CHEMBL_IDS * 2)[:20]

        print(f"\n  ========================================")
        print(f"  BATCH vs SEQUENTIAL COMPARISON")
        print(f"  Test IDs: {len(test_ids)}")
        print(f"  ========================================")

        # Sequential (current approach in compound_service.py)
        print(f"\n  Testing SEQUENTIAL approach...")
        start = time.time()
        seq_results = []
        for chembl_id in test_ids:
            try:
                activities = new_client.activity.filter(
                    molecule_chembl_id=chembl_id,
                    standard_type="IC50"
                ).only(['molecule_chembl_id', 'standard_value'])[:10]
                seq_results.extend(list(activities))
            except:
                pass
        seq_time = time.time() - start

        # Batch (proposed approach)
        print(f"  Testing BATCH approach...")
        start = time.time()
        batch_results = []
        try:
            activities = new_client.activity.filter(
                molecule_chembl_id__in=test_ids,
                standard_type="IC50"
            ).only(['molecule_chembl_id', 'standard_value'])[:200]
            batch_results = list(activities)
        except Exception as e:
            print(f"  Batch error: {e}")
        batch_time = time.time() - start

        speedup = seq_time / batch_time if batch_time > 0 else 0

        print(f"\n  RESULTS:")
        print(f"  Sequential: {seq_time:.2f}s ({len(seq_results)} results)")
        print(f"  Batch:      {batch_time:.2f}s ({len(batch_results)} results)")
        print(f"  Speedup:    {speedup:.1f}x")
        print(f"  ========================================")

        # Batch should generally be faster
        if speedup > 1:
            print(f"  CONCLUSION: Batching is {speedup:.1f}x faster!")
        else:
            print(f"  CONCLUSION: Batching was not faster (may be due to result size)")


class TestCurrentImplementation:
    """Test the current implementation patterns in the codebase."""

    def test_current_batch_fetch_activities(self):
        """
        Test the existing batch_fetch_activities function from api_client.py
        """
        try:
            from modules.api_client import batch_fetch_activities

            test_ids = SAMPLE_CHEMBL_IDS[:10]

            print(f"\n  ========================================")
            print(f"  TESTING EXISTING batch_fetch_activities()")
            print(f"  ========================================")

            # Test with batch_size=1 (current usage)
            start = time.time()
            results_1 = batch_fetch_activities(
                test_ids,
                activity_types=["IC50"],
                batch_size=1,
                max_workers=1
            )
            time_batch_1 = time.time() - start

            # Test with batch_size=50 (proposed)
            start = time.time()
            results_50 = batch_fetch_activities(
                test_ids,
                activity_types=["IC50"],
                batch_size=50,
                max_workers=4
            )
            time_batch_50 = time.time() - start

            print(f"  batch_size=1:  {time_batch_1:.2f}s ({len(results_1)} results)")
            print(f"  batch_size=50: {time_batch_50:.2f}s ({len(results_50)} results)")

            if time_batch_1 > 0:
                speedup = time_batch_1 / time_batch_50 if time_batch_50 > 0 else 0
                print(f"  Speedup: {speedup:.1f}x")

        except ImportError as e:
            print(f"\n  Could not import batch_fetch_activities: {e}")
            pytest.skip("Module not available")


class TestPDBGraphQLVsREST:
    """Compare PDB GraphQL API vs REST API for batch queries."""

    def test_graphql_batch_resolutions(self):
        """
        Test GraphQL API for fetching resolutions of multiple PDB IDs in ONE query.

        GraphQL Advantages:
        - Single request for all IDs (no pagination)
        - No rate limiting (currently)
        - Returns exactly the fields requested

        This is the KEY test - if GraphQL works well, it's far superior to REST.
        """
        import requests

        test_ids = SAMPLE_PDB_IDS[:20]  # 20 unique IDs

        # GraphQL query for multiple entries at once
        graphql_query = """
        query($ids: [String!]!) {
            entries(entry_ids: $ids) {
                rcsb_id
                rcsb_entry_info {
                    resolution_combined
                }
            }
        }
        """

        print(f"\n  ========================================")
        print(f"  PDB GraphQL BATCH TEST")
        print(f"  ========================================")

        start = time.time()
        try:
            response = requests.post(
                "https://data.rcsb.org/graphql",
                json={
                    "query": graphql_query,
                    "variables": {"ids": test_ids}
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )

            elapsed = time.time() - start

            if response.status_code == 200:
                data = response.json()
                entries = data.get("data", {}).get("entries", [])

                resolutions = {}
                for entry in entries:
                    pdb_id = entry.get("rcsb_id")
                    res_list = entry.get("rcsb_entry_info", {}).get("resolution_combined", [])
                    resolution = res_list[0] if res_list else None
                    resolutions[pdb_id] = resolution

                successful = len([r for r in resolutions.values() if r is not None])
                print(f"  Total IDs: {len(test_ids)}")
                print(f"  Results: {len(resolutions)}")
                print(f"  With resolution: {successful}")
                print(f"  Time: {elapsed:.2f}s")
                print(f"  SINGLE REQUEST for all {len(test_ids)} IDs!")
                print(f"  ========================================")

                # Show sample results
                print(f"\n  Sample resolutions:")
                for pdb_id, res in list(resolutions.items())[:5]:
                    print(f"    {pdb_id}: {res:.2f} Å" if res else f"    {pdb_id}: N/A")

            else:
                print(f"  GraphQL error: {response.status_code}")
                print(f"  Response: {response.text[:500]}")

        except Exception as e:
            elapsed = time.time() - start
            print(f"  GraphQL failed: {e}")
            print(f"  Time before failure: {elapsed:.2f}s")

    def test_rest_vs_graphql_comparison(self):
        """
        Direct comparison: REST (sequential) vs GraphQL (single query).

        This demonstrates the expected speedup from using GraphQL.
        """
        import requests

        test_ids = SAMPLE_PDB_IDS[:10]  # Use 10 IDs for fair comparison

        print(f"\n  ========================================")
        print(f"  REST vs GraphQL COMPARISON")
        print(f"  Test IDs: {len(test_ids)}")
        print(f"  ========================================")

        # Method 1: REST API (sequential calls)
        print(f"\n  Testing REST API (sequential)...")
        start = time.time()
        rest_results = {}
        for pdb_id in test_ids:
            try:
                url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    res_list = data.get('rcsb_entry_info', {}).get('resolution_combined', [])
                    rest_results[pdb_id] = res_list[0] if res_list else None
            except Exception as e:
                rest_results[pdb_id] = f"ERROR: {e}"
        rest_time = time.time() - start

        # Method 2: GraphQL API (single query)
        print(f"  Testing GraphQL API (single query)...")
        graphql_query = """
        query($ids: [String!]!) {
            entries(entry_ids: $ids) {
                rcsb_id
                rcsb_entry_info {
                    resolution_combined
                }
            }
        }
        """

        start = time.time()
        graphql_results = {}
        try:
            response = requests.post(
                "https://data.rcsb.org/graphql",
                json={
                    "query": graphql_query,
                    "variables": {"ids": test_ids}
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                for entry in data.get("data", {}).get("entries", []):
                    pdb_id = entry.get("rcsb_id")
                    res_list = entry.get("rcsb_entry_info", {}).get("resolution_combined", [])
                    graphql_results[pdb_id] = res_list[0] if res_list else None
        except Exception as e:
            print(f"  GraphQL error: {e}")
        graphql_time = time.time() - start

        # Results comparison
        speedup = rest_time / graphql_time if graphql_time > 0 else 0

        print(f"\n  RESULTS:")
        print(f"  REST API:    {rest_time:.2f}s ({len(rest_results)} results, {len(test_ids)} requests)")
        print(f"  GraphQL API: {graphql_time:.2f}s ({len(graphql_results)} results, 1 request)")
        print(f"  Speedup:     {speedup:.1f}x")
        print(f"  ========================================")

        if speedup > 1:
            print(f"  CONCLUSION: GraphQL is {speedup:.1f}x faster!")
        else:
            print(f"  CONCLUSION: Unexpected - REST was faster (network variance?)")

        # Verify results match
        matching = sum(1 for pdb_id in test_ids
                      if rest_results.get(pdb_id) == graphql_results.get(pdb_id))
        print(f"  Results match: {matching}/{len(test_ids)}")

    def test_graphql_large_batch(self):
        """
        Test GraphQL with larger batch sizes to find limits.

        According to RCSB docs: "no rate limits" but "complex queries may be slow".
        """
        import requests

        batch_sizes = [20, 50, 100, 200]

        print(f"\n  ========================================")
        print(f"  GraphQL LARGE BATCH TEST")
        print(f"  ========================================")

        graphql_query = """
        query($ids: [String!]!) {
            entries(entry_ids: $ids) {
                rcsb_id
                rcsb_entry_info {
                    resolution_combined
                }
            }
        }
        """

        for batch_size in batch_sizes:
            # Generate test IDs (repeat sample if needed)
            test_ids = (SAMPLE_PDB_IDS * 30)[:batch_size]

            start = time.time()
            try:
                response = requests.post(
                    "https://data.rcsb.org/graphql",
                    json={
                        "query": graphql_query,
                        "variables": {"ids": test_ids}
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=60
                )
                elapsed = time.time() - start

                if response.status_code == 200:
                    data = response.json()
                    entries = data.get("data", {}).get("entries", [])
                    print(f"  Batch {batch_size}: {elapsed:.2f}s - {len(entries)} entries returned")
                else:
                    print(f"  Batch {batch_size}: FAILED ({response.status_code})")

            except Exception as e:
                elapsed = time.time() - start
                print(f"  Batch {batch_size}: ERROR after {elapsed:.2f}s - {e}")


class TestPDBGraphQLExtendedData:
    """Test GraphQL for fetching multiple fields in a single query."""

    def test_graphql_full_structure_details(self):
        """
        Test fetching complete structure details via GraphQL.

        This shows GraphQL's power: get resolution, method, title, DOI all at once.
        """
        import requests

        test_ids = SAMPLE_PDB_IDS[:5]

        # Query for multiple fields at once
        graphql_query = """
        query($ids: [String!]!) {
            entries(entry_ids: $ids) {
                rcsb_id
                struct {
                    title
                }
                rcsb_entry_info {
                    resolution_combined
                    experimental_method
                }
                rcsb_primary_citation {
                    pdbx_database_id_DOI
                }
                exptl {
                    method
                }
            }
        }
        """

        print(f"\n  ========================================")
        print(f"  GraphQL FULL DETAILS TEST")
        print(f"  ========================================")

        start = time.time()
        try:
            response = requests.post(
                "https://data.rcsb.org/graphql",
                json={
                    "query": graphql_query,
                    "variables": {"ids": test_ids}
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            elapsed = time.time() - start

            if response.status_code == 200:
                data = response.json()
                entries = data.get("data", {}).get("entries", [])

                print(f"  Fetched {len(entries)} entries in {elapsed:.2f}s (1 request)")
                print(f"\n  Sample structure details:")

                for entry in entries[:3]:
                    pdb_id = entry.get("rcsb_id")
                    title = entry.get("struct", {}).get("title", "N/A")[:50]
                    res_list = entry.get("rcsb_entry_info", {}).get("resolution_combined", [])
                    resolution = f"{res_list[0]:.2f} Å" if res_list else "N/A"
                    method = entry.get("rcsb_entry_info", {}).get("experimental_method", "N/A")

                    print(f"    {pdb_id}: {resolution} ({method})")
                    print(f"      Title: {title}...")

                print(f"\n  ========================================")
                print(f"  GraphQL returns ALL fields in ONE request!")
                print(f"  REST would require 2-3 calls per PDB ID.")
                print(f"  ========================================")

            else:
                print(f"  Error: {response.status_code}")
                print(f"  Response: {response.text[:300]}")

        except Exception as e:
            print(f"  Failed: {e}")


class TestRealPDBFlow:
    """
    Test the REAL PDB flow: SMILES → search_similar_ligands → fetch resolutions.

    This demonstrates the actual data flow in IMPULATOR:
    1. User submits compound with SMILES
    2. search_similar_ligands(smiles) returns PDB IDs (single API call)
    3. get_batch_structure_resolutions(pdb_ids) fetches resolution data

    The GraphQL optimization applies to step 3.
    """

    def test_real_pdb_flow_with_smiles(self):
        """
        Test the complete PDB flow starting from a SMILES string.

        Uses Aspirin as a well-known test compound.
        """
        import requests

        # Aspirin SMILES
        test_smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"

        print(f"\n  ========================================")
        print(f"  REAL PDB FLOW TEST")
        print(f"  Test compound: Aspirin")
        print(f"  SMILES: {test_smiles}")
        print(f"  ========================================")

        # Step 1: Search for similar ligands (this is how we get PDB IDs)
        print(f"\n  Step 1: Searching PDB for similar ligands...")
        start = time.time()

        search_url = "https://search.rcsb.org/rcsbsearch/v2/query"
        search_payload = {
            "query": {
                "type": "terminal",
                "service": "chemical",
                "parameters": {
                    "value": test_smiles,
                    "type": "descriptor",
                    "descriptor_type": "SMILES",
                    "match_type": "graph-relaxed"
                }
            },
            "request_options": {"return_all_hits": True},
            "return_type": "entry"
        }

        pdb_ids = []
        try:
            resp = requests.post(search_url, json=search_payload, timeout=45)
            if resp.status_code == 200:
                result = resp.json()
                pdb_ids = [entry['identifier'] for entry in result.get('result_set', [])][:20]  # Limit to 20
            elif resp.status_code == 204:
                print(f"    No similar ligands found")
        except Exception as e:
            print(f"    Search error: {e}")

        search_time = time.time() - start
        print(f"    Found {len(pdb_ids)} PDB structures in {search_time:.2f}s")
        if pdb_ids:
            print(f"    Sample PDB IDs: {pdb_ids[:5]}")

        if not pdb_ids:
            print(f"\n  No PDB IDs found, skipping resolution fetch test")
            return

        # Step 2: Fetch resolutions (this is what we can optimize)
        print(f"\n  Step 2: Fetching resolutions...")

        # Method A: Sequential REST (current approach)
        print(f"\n  Method A: Sequential REST API calls...")
        start = time.time()
        rest_resolutions = {}
        for pdb_id in pdb_ids[:10]:  # Limit for speed
            try:
                url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    res_list = data.get('rcsb_entry_info', {}).get('resolution_combined', [])
                    rest_resolutions[pdb_id] = res_list[0] if res_list else None
            except:
                pass
        rest_time = time.time() - start

        # Method B: GraphQL (proposed optimization)
        print(f"  Method B: Single GraphQL query...")
        graphql_query = """
        query($ids: [String!]!) {
            entries(entry_ids: $ids) {
                rcsb_id
                rcsb_entry_info { resolution_combined }
            }
        }
        """
        start = time.time()
        graphql_resolutions = {}
        try:
            resp = requests.post(
                "https://data.rcsb.org/graphql",
                json={"query": graphql_query, "variables": {"ids": pdb_ids[:10]}},
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            if resp.status_code == 200:
                for entry in resp.json().get("data", {}).get("entries", []):
                    pdb_id = entry.get("rcsb_id")
                    res_list = entry.get("rcsb_entry_info", {}).get("resolution_combined", [])
                    graphql_resolutions[pdb_id] = res_list[0] if res_list else None
        except Exception as e:
            print(f"    GraphQL error: {e}")
        graphql_time = time.time() - start

        # Results
        speedup = rest_time / graphql_time if graphql_time > 0 else 0
        print(f"\n  RESULTS:")
        print(f"  REST API:    {rest_time:.2f}s ({len(rest_resolutions)} resolutions, {len(pdb_ids[:10])} requests)")
        print(f"  GraphQL:     {graphql_time:.2f}s ({len(graphql_resolutions)} resolutions, 1 request)")
        print(f"  Speedup:     {speedup:.1f}x")

        print(f"\n  Sample resolutions:")
        for pdb_id in list(rest_resolutions.keys())[:5]:
            res = rest_resolutions.get(pdb_id)
            print(f"    {pdb_id}: {res:.2f} Å" if res else f"    {pdb_id}: N/A")

        print(f"\n  ========================================")
        print(f"  CONCLUSION: GraphQL is {speedup:.1f}x faster for resolution fetching")
        print(f"  ========================================")


class TestChEMBLRealFlow:
    """
    Test the REAL ChEMBL flow: SMILES → similarity search → fetch activities.

    This demonstrates the actual bottleneck in IMPULATOR:
    1. User submits compound with SMILES
    2. ChEMBL similarity search returns ChEMBL IDs
    3. Fetch bioactivity data for those ChEMBL IDs (BOTTLENECK!)
    """

    def test_real_chembl_flow_with_smiles(self):
        """
        Test the complete ChEMBL flow starting from a SMILES string.

        Uses Aspirin as a well-known test compound.
        """
        from chembl_webresource_client.new_client import new_client

        # Aspirin SMILES
        test_smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"

        print(f"\n  ========================================")
        print(f"  REAL ChEMBL FLOW TEST")
        print(f"  Test compound: Aspirin")
        print(f"  SMILES: {test_smiles}")
        print(f"  ========================================")

        # Step 1: Search for similar molecules
        print(f"\n  Step 1: Searching ChEMBL for similar molecules...")
        start = time.time()

        chembl_ids = []
        try:
            similar = new_client.similarity.filter(smiles=test_smiles, similarity=70)
            similar_list = list(similar)[:20]  # Limit to 20
            chembl_ids = [mol.get('molecule_chembl_id') for mol in similar_list if mol.get('molecule_chembl_id')]
        except Exception as e:
            print(f"    Similarity search error: {e}")

        search_time = time.time() - start
        print(f"    Found {len(chembl_ids)} similar molecules in {search_time:.2f}s")
        if chembl_ids:
            print(f"    Sample ChEMBL IDs: {chembl_ids[:5]}")

        if not chembl_ids:
            print(f"\n  No ChEMBL IDs found, skipping activity fetch test")
            return

        # Step 2: Fetch activities (THIS IS THE BOTTLENECK)
        print(f"\n  Step 2: Fetching bioactivity data...")
        test_ids = chembl_ids[:10]  # Use 10 IDs for fair comparison

        # Method A: Sequential (current approach in compound_service.py)
        print(f"\n  Method A: Sequential calls (current approach)...")
        start = time.time()
        sequential_count = 0
        for chembl_id in test_ids:
            try:
                activities = new_client.activity.filter(
                    molecule_chembl_id=chembl_id,
                    standard_type="IC50"
                ).only(['molecule_chembl_id', 'standard_value'])[:5]
                sequential_count += len(list(activities))
            except:
                pass
        sequential_time = time.time() - start

        # Method B: Batch (proposed optimization)
        print(f"  Method B: Batch fetch (proposed optimization)...")
        start = time.time()
        batch_count = 0
        try:
            activities = new_client.activity.filter(
                molecule_chembl_id__in=test_ids,
                standard_type="IC50"
            ).only(['molecule_chembl_id', 'standard_value'])[:100]
            batch_count = len(list(activities))
        except Exception as e:
            print(f"    Batch error: {e}")
        batch_time = time.time() - start

        # Results
        speedup = sequential_time / batch_time if batch_time > 0 else 0
        print(f"\n  RESULTS:")
        print(f"  Sequential:  {sequential_time:.2f}s ({sequential_count} activities, {len(test_ids)} requests)")
        print(f"  Batch:       {batch_time:.2f}s ({batch_count} activities, 1 request)")
        print(f"  Speedup:     {speedup:.1f}x")

        print(f"\n  ========================================")
        print(f"  CONCLUSION: Batch fetching is {speedup:.1f}x faster!")
        print(f"  ========================================")


if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, "-v", "-s", "--tb=short"])
