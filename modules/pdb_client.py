"""
RCSB PDB Client Module
Provides integration with RCSB Protein Data Bank for structural evidence scoring.

Component 4 of O[Q/P/L]A scoring: PDB Structural Evidence Score (15% weight)
- Query PDB for compound or close analogs
- Extract resolution data (X-ray crystallography quality)
- Count structures with binding affinity data
- Score based on structural validation

Resolution Quality Classes:
- *** Best: < 2.0 Å (high confidence)
- ** Medium: 2.0-3.0 Å (moderate confidence)
- * Poor: > 3.0 Å (low confidence)
"""

import logging
import requests
from typing import Dict, List, Optional, Tuple
from functools import lru_cache
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from config import PDB_API_DELAY

logger = logging.getLogger(__name__)

# Try to import official RCSB API package
try:
    from rcsbapi.search import ChemSimilarityQuery
    from rcsbapi.data import DataQuery
    USE_OFFICIAL_API = True
except ImportError:
    USE_OFFICIAL_API = False
    logger.warning("rcsb-api package not installed. Install with: pip install rcsb-api")

# RCSB PDB API endpoints (fallback for manual queries)
SEARCH_API_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
DATA_API_URL = "https://data.rcsb.org/rest/v1/core"

# Configuration
DEFAULT_SIMILARITY_THRESHOLD = 0.9  # Not used with official API (fixed at graph-relaxed)
API_TIMEOUT = 30  # seconds (for REST API calls)
SIMILARITY_QUERY_TIMEOUT = 45  # seconds (for chemical similarity searches, can be slower)
CACHE_SIZE = 500
BATCH_SIZE = 50  # Number of PDB IDs to query in one batch for optimal performance


def get_session():
    """Create and return a requests session for PDB API calls."""
    session = requests.Session()
    session.headers.update({
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    })
    return session


session = get_session()


@lru_cache(maxsize=CACHE_SIZE)
def search_similar_ligands(
    smiles: str,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> List[str]:
    """
    Search RCSB PDB for ligands similar to the query compound.

    Args:
        smiles: SMILES string of query compound
        similarity_threshold: Tanimoto similarity threshold (0.0-1.0) [NOTE: Not used with official API]

    Returns:
        List of PDB IDs containing similar ligands

    Note:
        Uses graph-relaxed match type (structural similarity).
        Returns entries containing similar chemical components.
    """
    if not USE_OFFICIAL_API:
        logger.error("Official RCSB API package not available. Cannot perform chemical similarity search.")
        return []

    try:
        logger.info(f"Searching PDB for ligands similar to SMILES: {smiles[:50]}...")

        # Create chemical similarity query using official API
        query = ChemSimilarityQuery(
            value=smiles,
            query_type="descriptor",
            descriptor_type="SMILES",
            match_type="graph-relaxed"  # Structural similarity
        )

        # Execute query with timeout and retry logic for server errors
        max_retries = 2
        retry_delay = 2  # seconds

        for attempt in range(max_retries + 1):
            try:
                # Execute query with timeout using ThreadPoolExecutor
                # This prevents the query from hanging for 60+ seconds on server errors
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(lambda: list(query()))

                    try:
                        results = future.result(timeout=SIMILARITY_QUERY_TIMEOUT)
                    except FuturesTimeoutError:
                        logger.warning(f"PDB query timed out after {SIMILARITY_QUERY_TIMEOUT}s")
                        raise TimeoutError(f"Chemical similarity query exceeded {SIMILARITY_QUERY_TIMEOUT}s timeout")

                # Limit to top 100 results
                pdb_ids = results[:100]

                logger.info(f"Found {len(pdb_ids)} PDB entries with similar ligands")
                return pdb_ids

            except (TimeoutError, FuturesTimeoutError) as timeout_error:
                if attempt < max_retries:
                    logger.warning(f"PDB query attempt {attempt + 1} timed out (retrying in {retry_delay}s)")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"PDB query failed after {max_retries + 1} attempts due to timeout")
                    raise timeout_error

            except Exception as query_error:
                if attempt < max_retries:
                    logger.warning(f"PDB query attempt {attempt + 1} failed (retrying in {retry_delay}s): {str(query_error)}")
                    time.sleep(retry_delay)
                else:
                    # Final attempt failed
                    raise query_error

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error searching PDB for similar ligands: {error_msg}")
        logger.error(f"SMILES: {smiles}")

        # Check error type and provide helpful messages
        if "timeout" in error_msg.lower() or isinstance(e, (TimeoutError, FuturesTimeoutError)):
            logger.warning(f"PDB query timed out after {SIMILARITY_QUERY_TIMEOUT}s. This may indicate:")
            logger.warning("  - RCSB PDB server is experiencing high load")
            logger.warning("  - Complex chemical structure requiring more processing time")
            logger.warning("  - Network connectivity issues")
            logger.info("PDB evidence will not be available for this compound, but processing will continue.")
        elif "500" in error_msg or "Internal Server Error" in error_msg:
            logger.warning("RCSB PDB server returned HTTP 500. This is a temporary server issue, not a problem with your query.")
            logger.info("PDB evidence will not be available for this compound, but processing will continue.")
        elif "429" in error_msg or "rate limit" in error_msg.lower():
            logger.warning("RCSB PDB API rate limit reached. Consider adding delays between compound queries.")
            logger.info("PDB evidence will not be available for this compound, but processing will continue.")

        return []


@lru_cache(maxsize=CACHE_SIZE)
def get_structure_details(pdb_id: str) -> Dict[str, any]:
    """
    Retrieve detailed information for a PDB structure.

    Args:
        pdb_id: PDB identifier (e.g., "4HHB")

    Returns:
        Dictionary containing:
        - pdb_id: PDB code
        - title: Structure title/name
        - resolution: Resolution in Ångströms (Å)
        - doi: DOI of publication
        - uniprot_ids: List of UniProt accession IDs
        - url: Link to RCSB PDB structure page
        - experimental_method: Experimental method used
    """
    result = {
        'pdb_id': pdb_id,
        'title': None,
        'resolution': None,
        'doi': None,
        'uniprot_ids': [],
        'url': f"https://www.rcsb.org/structure/{pdb_id}",
        'experimental_method': None
    }

    try:
        # Fetch entry data
        url = f"{DATA_API_URL}/entry/{pdb_id}"
        response = session.get(url, timeout=API_TIMEOUT)

        if response.status_code == 200:
            data = response.json()

            # Extract title
            if 'struct' in data and 'title' in data['struct']:
                result['title'] = data['struct']['title']

            # Extract resolution
            if 'rcsb_entry_info' in data:
                if 'resolution_combined' in data['rcsb_entry_info']:
                    resolution_list = data['rcsb_entry_info']['resolution_combined']
                    if resolution_list and len(resolution_list) > 0:
                        result['resolution'] = float(resolution_list[0])

            # Extract experimental method
            if 'exptl' in data and len(data['exptl']) > 0:
                result['experimental_method'] = data['exptl'][0].get('method', None)

            # Extract DOI from primary citation
            if 'rcsb_primary_citation' in data:
                result['doi'] = data['rcsb_primary_citation'].get('pdbx_database_id_DOI', None)

        # Fetch polymer entity data for UniProt IDs
        # Try entity 1 (most structures have at least one polymer entity)
        try:
            entity_url = f"{DATA_API_URL}/polymer_entity/{pdb_id}/1"
            entity_response = session.get(entity_url, timeout=API_TIMEOUT)

            if entity_response.status_code == 200:
                entity_data = entity_response.json()

                # Extract UniProt IDs from database references
                if 'rcsb_polymer_entity_container_identifiers' in entity_data:
                    identifiers = entity_data['rcsb_polymer_entity_container_identifiers']
                    if 'reference_sequence_identifiers' in identifiers:
                        for ref in identifiers['reference_sequence_identifiers']:
                            if ref.get('database_name') == 'UniProt':
                                uniprot_id = ref.get('database_accession')
                                if uniprot_id and uniprot_id not in result['uniprot_ids']:
                                    result['uniprot_ids'].append(uniprot_id)

        except Exception as e:
            logger.debug(f"Could not fetch polymer entity for {pdb_id}: {str(e)}")

    except Exception as e:
        logger.error(f"Error retrieving details for {pdb_id}: {str(e)}")

    return result


def get_batch_structure_resolutions(pdb_ids: List[str]) -> Dict[str, Optional[float]]:
    """
    Retrieve resolutions for multiple PDB structures in a single batched query.

    This is MUCH more efficient than calling get_structure_resolution() in a loop.

    Args:
        pdb_ids: List of PDB identifiers (e.g., ["4HHB", "3WHM", "2CPK"])

    Returns:
        Dictionary mapping PDB ID to resolution (float or None if not available)
        Example: {"4HHB": 1.74, "3WHM": 2.10, "2CPK": None}

    Note:
        - Processes in batches of BATCH_SIZE (default 50) to avoid overloading API
        - Much faster than individual queries: 1 API call per 50 structures vs 50 calls
        - Uses official Data API for optimal performance
    """
    if not pdb_ids:
        return {}

    if not USE_OFFICIAL_API:
        logger.warning("Official RCSB API not available. Falling back to individual queries.")
        return {pdb_id: get_structure_resolution(pdb_id) for pdb_id in pdb_ids}

    resolutions = {}

    # Process in batches to avoid overwhelming the API
    for i in range(0, len(pdb_ids), BATCH_SIZE):
        batch = pdb_ids[i:i + BATCH_SIZE]

        try:
            logger.info(f"Fetching resolutions for batch of {len(batch)} structures (IDs {i+1}-{min(i+BATCH_SIZE, len(pdb_ids))} of {len(pdb_ids)})")

            # Use official Data API to query multiple entries at once
            data_query = DataQuery(
                input_type="entries",
                input_ids=batch,
                return_data_list=["rcsb_entry_info.resolution_combined"]
            )

            result = data_query.exec()

            # Parse results
            # Result format: {'data': {'entries': [{'rcsb_id': '...', 'rcsb_entry_info': {...}}]}}
            if result and 'data' in result and 'entries' in result['data']:
                for entry_data in result['data']['entries']:
                    pdb_id = entry_data.get('rcsb_id', '').upper()

                    # Extract resolution
                    if 'rcsb_entry_info' in entry_data:
                        if 'resolution_combined' in entry_data['rcsb_entry_info']:
                            resolution_list = entry_data['rcsb_entry_info']['resolution_combined']
                            if resolution_list and len(resolution_list) > 0:
                                resolutions[pdb_id] = float(resolution_list[0])
                                continue

                    # No resolution found
                    resolutions[pdb_id] = None

            # Add None for any IDs that weren't in the response
            for pdb_id in batch:
                if pdb_id.upper() not in resolutions:
                    resolutions[pdb_id.upper()] = None

        except Exception as e:
            logger.error(f"Error fetching batch resolutions: {str(e)}")
            # Fall back to None for this batch
            for pdb_id in batch:
                if pdb_id.upper() not in resolutions:
                    resolutions[pdb_id.upper()] = None

        # Small delay between batches to be respectful to API
        if i + BATCH_SIZE < len(pdb_ids):
            time.sleep(0.5)

    logger.info(f"Successfully fetched resolutions for {len([r for r in resolutions.values() if r is not None])}/{len(pdb_ids)} structures")
    return resolutions


@lru_cache(maxsize=CACHE_SIZE)
def get_structure_resolution(pdb_id: str) -> Optional[float]:
    """
    Retrieve X-ray crystallography resolution for a PDB structure.

    Args:
        pdb_id: PDB identifier (e.g., "4HHB")

    Returns:
        Resolution in Ångströms (Å), or None if not available

    Note:
        This is a lightweight function for backward compatibility.
        Use get_structure_details() for comprehensive information.
    """
    if USE_OFFICIAL_API:
        try:
            # Use official Data API
            data_query = DataQuery(
                input_type="entries",
                input_ids=[pdb_id],
                return_data_list=["rcsb_entry_info.resolution_combined"]
            )

            result = data_query.exec()

            # Result format: {'data': {'entries': [{'rcsb_id': '...', 'rcsb_entry_info': {...}}]}}
            if result and 'data' in result and 'entries' in result['data']:
                entries = result['data']['entries']
                if len(entries) > 0:
                    entry_data = entries[0]
                    if 'rcsb_entry_info' in entry_data:
                        if 'resolution_combined' in entry_data['rcsb_entry_info']:
                            resolution_list = entry_data['rcsb_entry_info']['resolution_combined']
                            if resolution_list and len(resolution_list) > 0:
                                return float(resolution_list[0])

            logger.debug(f"No resolution data found for {pdb_id}")
            return None

        except Exception as e:
            logger.error(f"Error retrieving resolution for {pdb_id}: {str(e)}")
            return None
    else:
        # Fallback to manual REST API query
        try:
            url = f"{DATA_API_URL}/entry/{pdb_id}"
            response = session.get(url, timeout=API_TIMEOUT)

            if response.status_code == 200:
                data = response.json()

                # Try rcsb_entry_info.resolution_combined
                if 'rcsb_entry_info' in data:
                    if 'resolution_combined' in data['rcsb_entry_info']:
                        resolution_list = data['rcsb_entry_info']['resolution_combined']
                        if resolution_list and len(resolution_list) > 0:
                            return float(resolution_list[0])

                logger.debug(f"No resolution data found for {pdb_id}")
                return None
            else:
                logger.warning(f"Failed to retrieve data for {pdb_id}: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error retrieving resolution for {pdb_id}: {str(e)}")
            return None


def classify_resolution_quality(resolution: float) -> Tuple[str, float]:
    """
    Classify resolution quality and return quality score.

    Args:
        resolution: Resolution in Ångströms (Å)

    Returns:
        Tuple of (quality_class, quality_multiplier)
        - quality_class: "***" (best), "**" (medium), "*" (poor)
        - quality_multiplier: 1.0, 0.75, or 0.5
    """
    if resolution < 2.0:
        return ("***", 1.0)  # Best quality
    elif resolution <= 3.0:
        return ("**", 0.75)  # Medium quality
    else:
        return ("*", 0.5)    # Poor quality


def get_pdb_evidence_score(
    smiles: str,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> Dict[str, any]:
    """
    Calculate PDB Structural Evidence Score (Component 4 of O[Q/P/L]A).

    Args:
        smiles: SMILES string of query compound
        similarity_threshold: Tanimoto similarity threshold (default 0.9)

    Returns:
        Dictionary containing:
        - pdb_score: Final score (0.0-1.0)
        - num_structures: Total number of similar structures found
        - num_high_quality: Number of high-quality structures (< 2.0 Å)
        - num_medium_quality: Number of medium-quality structures (2.0-3.0 Å)
        - num_poor_quality: Number of poor-quality structures (> 3.0 Å)
        - pdb_ids: List of PDB IDs found
        - resolutions: List of resolutions (in Å)
        - quality_classes: List of quality classifications

    Scoring Logic:
        Base score = min(num_structures_with_resolution / 5.0, 1.0)
        Quality-adjusted score = (sum of quality_multipliers) / (num_structures * max_multiplier)

    Example:
        5+ high-quality structures = score 1.0
        3 medium-quality structures = score ~0.45
        1 poor-quality structure = score ~0.10
    """
    logger.info(f"Calculating PDB evidence score for SMILES: {smiles[:50]}...")

    # Step 1: Search for similar ligands in PDB
    pdb_ids = search_similar_ligands(smiles, similarity_threshold)

    if not pdb_ids:
        logger.info("No similar structures found in PDB")
        return {
            'pdb_score': 0.0,
            'num_structures': 0,
            'num_high_quality': 0,
            'num_medium_quality': 0,
            'num_poor_quality': 0,
            'pdb_ids': [],
            'resolutions': [],
            'quality_classes': []
        }

    # Step 2: Retrieve resolution data for all structures in batches (OPTIMIZED!)
    # OLD: for loop with 100 individual API calls + 10 seconds of delays
    # NEW: batched query with 2-3 API calls total (50 IDs per batch)
    resolution_dict = get_batch_structure_resolutions(pdb_ids)

    resolutions = []
    quality_classes = []
    quality_multipliers = []

    for pdb_id in pdb_ids:
        resolution = resolution_dict.get(pdb_id.upper())

        if resolution is not None:
            resolutions.append(resolution)
            quality_class, quality_mult = classify_resolution_quality(resolution)
            quality_classes.append(quality_class)
            quality_multipliers.append(quality_mult)
        else:
            # No resolution data available for this structure
            resolutions.append(None)
            quality_classes.append("N/A")
            quality_multipliers.append(0.0)

    # Step 3: Calculate counts by quality
    num_high_quality = sum(1 for q in quality_classes if q == "***")
    num_medium_quality = sum(1 for q in quality_classes if q == "**")
    num_poor_quality = sum(1 for q in quality_classes if q == "*")
    num_with_resolution = num_high_quality + num_medium_quality + num_poor_quality

    # Step 4: Calculate PDB score
    if num_with_resolution == 0:
        pdb_score = 0.0
    else:
        # Base score: count-based (5+ structures = 1.0)
        base_score = min(num_with_resolution / 5.0, 1.0)

        # Quality adjustment: weighted by resolution quality
        quality_weighted_score = sum(quality_multipliers) / (num_with_resolution * 1.0)

        # Final score: average of base and quality-weighted
        pdb_score = (base_score + quality_weighted_score) / 2.0

    logger.info(f"PDB Evidence Score: {pdb_score:.3f} ({num_with_resolution} structures, "
                f"{num_high_quality} high, {num_medium_quality} medium, {num_poor_quality} poor)")

    return {
        'pdb_score': pdb_score,
        'num_structures': len(pdb_ids),
        'num_high_quality': num_high_quality,
        'num_medium_quality': num_medium_quality,
        'num_poor_quality': num_poor_quality,
        'pdb_ids': pdb_ids,
        'resolutions': resolutions,
        'quality_classes': quality_classes
    }


def get_detailed_pdb_structures(smiles: str) -> List[Dict[str, any]]:
    """
    Get detailed information for all PDB structures matching a compound.

    Args:
        smiles: SMILES string of query compound

    Returns:
        List of dictionaries, each containing:
        - pdb_id: PDB code
        - title: Structure title/name
        - resolution: Resolution in Ångströms
        - quality_class: Quality classification (***/**/*)
        - uniprot_ids: Comma-separated UniProt IDs
        - url: Link to RCSB PDB page
        - experimental_method: Experimental method used

    Note:
        Results are sorted by quality (*** first) and then by resolution (best first)
    """
    logger.info(f"Fetching detailed PDB structures for SMILES: {smiles[:50]}...")

    # Get basic PDB evidence
    pdb_result = get_pdb_evidence_score(smiles)

    if not pdb_result['pdb_ids']:
        return []

    detailed_structures = []

    for i, pdb_id in enumerate(pdb_result['pdb_ids']):
        try:
            # Get detailed information for this structure
            details = get_structure_details(pdb_id)

            # Add quality classification
            resolution = pdb_result['resolutions'][i]
            quality_class = pdb_result['quality_classes'][i]

            structure_info = {
                'PDB_ID': details['pdb_id'],
                'Title': details['title'] if details['title'] else 'N/A',
                'Resolution': resolution if resolution is not None else 999.0,  # Use high value for N/A to sort last
                'Quality': quality_class,
                'UniProt_IDs': ','.join(details['uniprot_ids']) if details['uniprot_ids'] else 'N/A',
                'Experimental_Method': details['experimental_method'] if details['experimental_method'] else 'N/A',
                'URL': details['url']
            }

            detailed_structures.append(structure_info)

            # Rate limiting using config
            time.sleep(PDB_API_DELAY)

        except Exception as e:
            logger.error(f"Error fetching details for {pdb_id}: {str(e)}")
            # Add minimal entry
            detailed_structures.append({
                'PDB_ID': pdb_id,
                'Title': 'Error fetching details',
                'Resolution': 999.0,  # Sort errors last
                'Quality': pdb_result['quality_classes'][i] if i < len(pdb_result['quality_classes']) else 'N/A',
                'UniProt_IDs': 'N/A',
                'Experimental_Method': 'N/A',
                'URL': f"https://www.rcsb.org/structure/{pdb_id}"
            })

    # Sort by quality (*** > ** > *) and then by resolution (lower is better)
    quality_order = {'***': 1, '**': 2, '*': 3, 'N/A': 4}
    detailed_structures.sort(key=lambda x: (quality_order.get(x['Quality'], 4), x['Resolution']))

    # Convert Resolution back to 'N/A' for display if it was 999.0
    for structure in detailed_structures:
        if structure['Resolution'] == 999.0:
            structure['Resolution'] = 'N/A'

    logger.info(f"Retrieved and sorted {len(detailed_structures)} PDB structures (best quality first)")
    return detailed_structures


def get_pdb_summary_for_compound(smiles: str) -> str:
    """
    Generate a human-readable summary of PDB evidence for a compound.

    Args:
        smiles: SMILES string of query compound

    Returns:
        Formatted string summarizing PDB evidence
    """
    result = get_pdb_evidence_score(smiles)

    if result['num_structures'] == 0:
        return "No experimental structures found in PDB for this compound or close analogs."

    summary_parts = []
    summary_parts.append(f"Found {result['num_structures']} similar structure(s) in PDB")
    summary_parts.append(f"PDB Evidence Score: {result['pdb_score']:.3f}/1.0")

    if result['num_high_quality'] > 0:
        summary_parts.append(f"- {result['num_high_quality']} high-quality (*** < 2.0 Å)")
    if result['num_medium_quality'] > 0:
        summary_parts.append(f"- {result['num_medium_quality']} medium-quality (** 2.0-3.0 Å)")
    if result['num_poor_quality'] > 0:
        summary_parts.append(f"- {result['num_poor_quality']} poor-quality (* > 3.0 Å)")

    # Show top 5 PDB IDs with resolution
    summary_parts.append("\nTop PDB Entries:")
    for i, (pdb_id, resolution, quality) in enumerate(zip(
        result['pdb_ids'][:5],
        result['resolutions'][:5],
        result['quality_classes'][:5]
    )):
        if resolution is not None:
            summary_parts.append(f"  {pdb_id}: {resolution:.2f} Å ({quality})")
        else:
            summary_parts.append(f"  {pdb_id}: Resolution N/A")

    return "\n".join(summary_parts)


# Example usage for testing
if __name__ == "__main__":
    # Test with a known compound (e.g., ATP)
    test_smiles = "C1=NC(=C2C(=N1)N(C=N2)C3C(C(C(O3)COP(=O)(O)OP(=O)(O)OP(=O)(O)O)O)O)N"

    print("Testing PDB Client Module")
    print("=" * 60)
    print(f"Query SMILES: {test_smiles}")
    print()

    summary = get_pdb_summary_for_compound(test_smiles)
    print(summary)
