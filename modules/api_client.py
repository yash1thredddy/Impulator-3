"""
ChEMBL API client with optimized batch processing and caching.
Decoupled from Streamlit for backend use.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from functools import lru_cache, wraps
from typing import Dict, List, Optional, Callable, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logger = logging.getLogger(__name__)

# Configuration constants
CACHE_SIZE = 2000
MAX_BATCH_SIZE = 50
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 0.5
RETRY_STATUS_CODES = [500, 502, 503, 504]
API_TIMEOUT = 30  # seconds for HTTP requests
CHEMBL_API_TIMEOUT = 60  # seconds for ChEMBL client operations (can be slower)
MAX_WORKERS = 4
ACTIVITY_TYPES = ["IC50", "Ki", "Kd", "EC50"]

# Thread pool for timeout wrapper (reused across calls)
_timeout_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chembl_timeout")


def with_timeout(timeout_seconds: int = CHEMBL_API_TIMEOUT):
    """
    Decorator to add timeout to functions (especially ChEMBL library calls).

    The ChEMBL client library doesn't support native timeouts, so we use
    ThreadPoolExecutor to enforce a timeout.

    Args:
        timeout_seconds: Maximum seconds to wait before timing out
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            future = _timeout_executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                logger.error(f"Timeout ({timeout_seconds}s) exceeded for {func.__name__}")
                # Return appropriate default based on return type hints
                return None
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                return None
        return wrapper
    return decorator

# Progress callback type
ProgressCallback = Callable[[float, str], None]

# Lazy import for ChEMBL client
_chembl_client = None


def _get_chembl_client():
    """Lazy initialization of ChEMBL client."""
    global _chembl_client
    if _chembl_client is None:
        try:
            from chembl_webresource_client.new_client import new_client
            _chembl_client = {
                'similarity': new_client.similarity,
                'molecule': new_client.molecule,
                'activity': new_client.activity,
                'target': new_client.target,
                'drug_indication': new_client.drug_indication,
            }
            logger.info(f"ChEMBL client initialized with endpoints: {list(_chembl_client.keys())}")
        except ImportError:
            logger.warning("chembl_webresource_client not installed")
            _chembl_client = {}
    return _chembl_client


# Configure retry strategy
retry_strategy = Retry(
    total=MAX_RETRIES,
    backoff_factor=RETRY_BACKOFF_FACTOR,
    status_forcelist=RETRY_STATUS_CODES,
)


def get_session():
    """Create and return a requests session with retry configuration."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# Create session
session = get_session()


def _fetch_molecule_data_with_timeout(chembl_id: str) -> Optional[Dict]:
    """Internal function to fetch molecule data with timeout."""
    client = _get_chembl_client()
    if 'molecule' not in client:
        return None
    return client['molecule'].get(chembl_id)


@lru_cache(maxsize=CACHE_SIZE)
def get_molecule_data(chembl_id: str) -> Optional[Dict]:
    """
    Fetch molecule data from ChEMBL API with caching and timeout.

    Args:
        chembl_id: ChEMBL ID to fetch

    Returns:
        Optional[Dict]: Molecule data or None if error
    """
    try:
        # Use ThreadPoolExecutor for timeout since ChEMBL client doesn't support it
        future = _timeout_executor.submit(_fetch_molecule_data_with_timeout, chembl_id)
        return future.result(timeout=CHEMBL_API_TIMEOUT)
    except FuturesTimeoutError:
        logger.error(f"Timeout fetching molecule data for {chembl_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching molecule data for {chembl_id}: {str(e)}")
        return None


@lru_cache(maxsize=CACHE_SIZE)
def get_classification(inchikey: str) -> Optional[Dict]:
    """
    Get classification data from ClassyFire API with caching.

    Args:
        inchikey: InChIKey for the molecule

    Returns:
        Optional[Dict]: Classification data or None if error
    """
    try:
        url = f'http://classyfire.wishartlab.com/entities/{inchikey}.json'
        response = session.get(url, timeout=API_TIMEOUT)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Error getting classification for {inchikey}: {str(e)}")
        return None


def _fetch_target_name_with_timeout(target_chembl_id: str) -> Optional[str]:
    """Internal function to fetch target name with timeout."""
    client = _get_chembl_client()
    if 'target' not in client:
        return None
    target_data = client['target'].get(target_chembl_id)
    if target_data:
        return target_data.get('pref_name', target_chembl_id)
    return None


@lru_cache(maxsize=CACHE_SIZE)
def get_target_name(target_chembl_id: str) -> Optional[str]:
    """
    Fetch target name from ChEMBL API with caching and timeout.

    Args:
        target_chembl_id: ChEMBL Target ID

    Returns:
        Optional[str]: Target preferred name or None if error
    """
    if not target_chembl_id:
        return None

    try:
        future = _timeout_executor.submit(_fetch_target_name_with_timeout, target_chembl_id)
        return future.result(timeout=CHEMBL_API_TIMEOUT)
    except FuturesTimeoutError:
        logger.error(f"Timeout fetching target name for {target_chembl_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching target name for {target_chembl_id}: {str(e)}")
        return None


def _fetch_drug_indications_with_timeout(chembl_id: str) -> tuple:
    """Internal function to fetch drug indications with timeout."""
    client = _get_chembl_client()
    if 'drug_indication' not in client:
        logger.warning("drug_indication endpoint not available")
        return ()

    indications = client['drug_indication'].filter(molecule_chembl_id=chembl_id)
    indication_list = list(indications)

    results = []
    for ind in indication_list:
        # Extract clinical trial URL from indication_refs
        clinical_trials_url = ''
        clinical_trials_ids = ''
        indication_refs = ind.get('indication_refs', [])

        if indication_refs:
            for ref in indication_refs:
                if ref.get('ref_type') == 'ClinicalTrials':
                    clinical_trials_url = ref.get('ref_url', '')
                    clinical_trials_ids = ref.get('ref_id', '')
                    break

        results.append({
            'ChEMBL_ID': chembl_id,
            'MESH_ID': ind.get('mesh_id', ''),
            'MESH_Heading': ind.get('mesh_heading', ''),
            'EFO_ID': ind.get('efo_id', ''),
            'EFO_Term': ind.get('efo_term', ''),
            'Max_Phase': ind.get('max_phase_for_ind', 0),
            'Clinical_Trials_URL': clinical_trials_url,
            'Clinical_Trials_IDs': clinical_trials_ids,
        })

    return tuple(results)


@lru_cache(maxsize=CACHE_SIZE)
def get_drug_indications(chembl_id: str) -> tuple:
    """
    Fetch drug indications for a ChEMBL ID with caching and timeout.

    Returns indication data including MESH, EFO, and clinical trial references.

    Args:
        chembl_id: ChEMBL molecule ID

    Returns:
        tuple: Tuple of indication dictionaries (for caching compatibility)
    """
    if not chembl_id:
        return ()

    try:
        future = _timeout_executor.submit(_fetch_drug_indications_with_timeout, chembl_id)
        return future.result(timeout=CHEMBL_API_TIMEOUT)
    except FuturesTimeoutError:
        logger.error(f"Timeout fetching drug indications for {chembl_id}")
        return ()
    except Exception as e:
        logger.error(f"Error fetching drug indications for {chembl_id}: {str(e)}")
        return ()


def _similarity_search_with_timeout(smiles: str, similarity_threshold: int) -> List[Dict[str, str]]:
    """Internal function to perform similarity search with timeout."""
    client = _get_chembl_client()
    if 'similarity' not in client:
        logger.error("ChEMBL client not available for similarity search")
        return []

    results = client['similarity'].filter(
        smiles=smiles,
        similarity=similarity_threshold
    ).only(['molecule_chembl_id'])

    # Convert to list to actually fetch the data
    result_list = list(results)
    return [{"ChEMBL ID": result['molecule_chembl_id']} for result in result_list]


# Longer timeout for similarity searches (can be slow)
SIMILARITY_SEARCH_TIMEOUT = 90  # seconds


def get_chembl_ids(smiles: str, similarity_threshold: int = 90, max_retries: int = 3) -> List[Dict[str, str]]:
    """
    Perform similarity search with error handling, retries, and timeout.

    Args:
        smiles: SMILES string to search
        similarity_threshold: Similarity threshold (0-100)
        max_retries: Maximum number of retry attempts

    Returns:
        List[Dict[str, str]]: List of ChEMBL IDs
    """
    for attempt in range(max_retries):
        try:
            # Use ThreadPoolExecutor for timeout
            future = _timeout_executor.submit(
                _similarity_search_with_timeout, smiles, similarity_threshold
            )
            return future.result(timeout=SIMILARITY_SEARCH_TIMEOUT)

        except FuturesTimeoutError:
            logger.warning(f"Similarity search timeout (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
            continue
        except IndexError as e:
            # Handle "tuple index out of range" from chembl client
            logger.warning(f"ChEMBL API IndexError (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))  # Exponential backoff
            continue
        except Exception as e:
            logger.error(f"Error in similarity search (attempt {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))
            continue

    logger.error(f"Similarity search failed after {max_retries} attempts")
    return []


def _fetch_activity_batch(batch_params: Dict[str, Any], max_retries: int = 2) -> List[Dict]:
    """
    Helper function to fetch a batch of activities with retry logic.

    Args:
        batch_params: Dictionary containing batch parameters
        max_retries: Maximum retry attempts

    Returns:
        List[Dict]: List of activity data
    """
    chembl_ids = batch_params['chembl_ids']
    activity_type = batch_params['activity_type']

    for attempt in range(max_retries):
        try:
            client = _get_chembl_client()
            if 'activity' not in client:
                return []

            activities = client['activity'].filter(
                molecule_chembl_id__in=chembl_ids,
                standard_type=activity_type
            ).only('molecule_chembl_id', 'standard_value',
                  'standard_units', 'standard_type',
                  'target_chembl_id')

            return list(activities)

        except IndexError as e:
            # Handle "tuple index out of range" from chembl client
            logger.warning(f"Activity fetch IndexError for {chembl_ids[:2]} (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            continue
        except Exception as e:
            logger.error(f"Error fetching activities for batch {chembl_ids[:2]} (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            continue

    return []


def batch_fetch_activities(
    chembl_ids: List[str],
    activity_types: List[str] = None,
    batch_size: int = MAX_BATCH_SIZE,
    max_workers: int = MAX_WORKERS,
    progress_callback: Optional[ProgressCallback] = None
) -> List[Dict]:
    """
    Fetch activities in parallel batches with optimized performance.

    Args:
        chembl_ids: List of ChEMBL IDs
        activity_types: List of activity types to fetch
        batch_size: Size of each batch
        max_workers: Maximum number of concurrent workers
        progress_callback: Optional callback for progress updates (progress: 0-1, message: str)

    Returns:
        List[Dict]: List of activity data
    """
    if activity_types is None:
        activity_types = ACTIVITY_TYPES

    if not chembl_ids:
        return []

    if batch_size > MAX_BATCH_SIZE:
        logger.warning(f"Batch size {batch_size} exceeds maximum {MAX_BATCH_SIZE}. Using maximum value.")
        batch_size = MAX_BATCH_SIZE

    all_activities = []

    # Create batches for parallel processing
    batches = []
    for i in range(0, len(chembl_ids), batch_size):
        batch = chembl_ids[i:i + batch_size]
        for activity_type in activity_types:
            batches.append({
                'chembl_ids': batch,
                'activity_type': activity_type
            })

    total_batches = len(batches)

    if progress_callback:
        progress_callback(0.0, f"Fetching activity data for {len(chembl_ids)} compounds across {len(activity_types)} activity types...")

    # Process batches in parallel
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_activity_batch, batch): i for i, batch in enumerate(batches)}

        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_results = future.result()
                all_activities.extend(batch_results)

                # Update progress
                completed += 1
                progress = completed / total_batches
                if progress_callback:
                    progress_callback(progress, f"Processed {completed}/{total_batches} batches ({int(progress * 100)}%)")
            except Exception as e:
                logger.error(f"Error processing batch {batch_idx}: {str(e)}")

    if progress_callback:
        progress_callback(1.0, f"Completed! Fetched {len(all_activities)} activity data points.")

    return all_activities


def fetch_compound_activities(
    chembl_id: str,
    activity_types: List[str] = None
) -> List[Dict]:
    """
    Fetch activities for a single compound.

    Args:
        chembl_id: ChEMBL ID to fetch
        activity_types: List of activity types to fetch

    Returns:
        List[Dict]: List of activity data
    """
    if activity_types is None:
        activity_types = ACTIVITY_TYPES

    all_activities = []
    client = _get_chembl_client()

    if 'activity' not in client:
        logger.error("ChEMBL client not available")
        return []

    for activity_type in activity_types:
        try:
            activities = client['activity'].filter(
                molecule_chembl_id=chembl_id,
                standard_type=activity_type
            ).only('standard_value', 'standard_units', 'standard_type',
                   'target_chembl_id', 'target_pref_name')

            all_activities.extend(list(activities))
        except Exception as e:
            logger.error(f"Error fetching {activity_type} for {chembl_id}: {str(e)}")

    return all_activities


# Cache clearing utilities
def clear_caches():
    """Clear all LRU caches."""
    get_molecule_data.cache_clear()
    get_classification.cache_clear()
    get_target_name.cache_clear()
    get_drug_indications.cache_clear()
    logger.info("All API client caches cleared")


def get_cache_info() -> Dict[str, Any]:
    """Get cache statistics."""
    return {
        'molecule_data': get_molecule_data.cache_info()._asdict(),
        'classification': get_classification.cache_info()._asdict(),
        'target_name': get_target_name.cache_info()._asdict(),
        'drug_indications': get_drug_indications.cache_info()._asdict(),
    }


def shutdown_api_client():
    """
    Shutdown the API client and cleanup resources.

    Call this during application shutdown to properly cleanup
    the timeout executor thread pool.
    """
    global _timeout_executor
    try:
        _timeout_executor.shutdown(wait=False, cancel_futures=True)
        logger.info("API client timeout executor shutdown complete")
    except Exception as e:
        logger.warning(f"Error during API client shutdown: {e}")


# Register shutdown handler
import atexit
atexit.register(shutdown_api_client)
