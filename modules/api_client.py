"""
ChEMBL API client with optimized batch processing and caching.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Dict, List, Optional, Union, Any

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from chembl_webresource_client.new_client import new_client
import streamlit as st

from config import (
    MAX_BATCH_SIZE, MAX_RETRIES, RETRY_STATUS_CODES,
    RETRY_BACKOFF_FACTOR, API_TIMEOUT, CACHE_SIZE,
    MAX_WORKERS, ACTIVITY_TYPES
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize ChEMBL client
similarity = new_client.similarity
molecule = new_client.molecule
activity = new_client.activity

# Configure retry strategy
retry_strategy = Retry(
    total=MAX_RETRIES,
    backoff_factor=RETRY_BACKOFF_FACTOR,
    status_forcelist=RETRY_STATUS_CODES,
)

# Setup session for API calls with retry
def get_session():
    """Create and return a requests session with retry configuration."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# Create session
session = get_session()

@lru_cache(maxsize=CACHE_SIZE)
def get_molecule_data(chembl_id: str) -> Optional[Dict]:
    """
    Fetch molecule data from ChEMBL API with caching.
    
    Args:
        chembl_id: ChEMBL ID to fetch
    
    Returns:
        Optional[Dict]: Molecule data or None if error
    """
    try:
        return molecule.get(chembl_id)
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

def get_chembl_ids(smiles: str, similarity_threshold: int = 80) -> List[Dict[str, str]]:
    """
    Perform similarity search with error handling.
    
    Args:
        smiles: SMILES string to search
        similarity_threshold: Similarity threshold (0-100)
    
    Returns:
        List[Dict[str, str]]: List of ChEMBL IDs
    """
    try:
        results = similarity.filter(
            smiles=smiles,
            similarity=similarity_threshold
        ).only(['molecule_chembl_id'])
        
        return [{"ChEMBL ID": result['molecule_chembl_id']} for result in results]
    except Exception as e:
        logger.error(f"Error in similarity search: {str(e)}")
        return []

def _fetch_activity_batch(batch_params: Dict[str, Any]) -> List[Dict]:
    """
    Helper function to fetch a batch of activities.
    
    Args:
        batch_params: Dictionary containing batch parameters
    
    Returns:
        List[Dict]: List of activity data
    """
    chembl_ids = batch_params['chembl_ids']
    activity_type = batch_params['activity_type']
    
    try:
        activities = activity.filter(
            molecule_chembl_id__in=chembl_ids,
            standard_type=activity_type
        ).only('molecule_chembl_id', 'standard_value',
              'standard_units', 'standard_type',
              'target_chembl_id')
        
        return list(activities)
    except Exception as e:
        logger.error(f"Error fetching activities for batch {chembl_ids[:2]}: {str(e)}")
        return []

def batch_fetch_activities(
    chembl_ids: List[str], 
    activity_types: List[str] = ACTIVITY_TYPES, 
    batch_size: int = MAX_BATCH_SIZE, 
    max_workers: int = MAX_WORKERS
) -> List[Dict]:
    """
    Fetch activities in parallel batches with optimized performance.
    
    Args:
        chembl_ids: List of ChEMBL IDs
        activity_types: List of activity types to fetch
        batch_size: Size of each batch
        max_workers: Maximum number of concurrent workers
    
    Returns:
        List[Dict]: List of activity data
    """
    if not chembl_ids:
        return []
    
    if batch_size > MAX_BATCH_SIZE:
        logger.warning(f"Batch size {batch_size} exceeds maximum {MAX_BATCH_SIZE}. Using maximum value.")
        batch_size = MAX_BATCH_SIZE
    
    all_activities = []
    total_batches = 0
    
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
    
    # Show progress
    progress_msg = st.empty()
    progress_bar = st.progress(0)
    progress_msg.text(f"Fetching activity data for {len(chembl_ids)} compounds across {len(activity_types)} activity types...")
    
    # Process batches in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_activity_batch, batch): i for i, batch in enumerate(batches)}
        
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_results = future.result()
                all_activities.extend(batch_results)
                
                # Update progress
                progress = (batch_idx + 1) / total_batches
                progress_bar.progress(progress)
                progress_msg.text(f"Processed {batch_idx + 1}/{total_batches} batches ({int(progress * 100)}%)")
            except Exception as e:
                logger.error(f"Error processing batch {batch_idx}: {str(e)}")
    
    progress_msg.text(f"Completed! Fetched {len(all_activities)} activity data points.")
    return all_activities

def fetch_compound_activities(
    chembl_id: str, 
    activity_types: List[str] = ACTIVITY_TYPES
) -> List[Dict]:
    """
    Fetch activities for a single compound.
    
    Args:
        chembl_id: ChEMBL ID to fetch
        activity_types: List of activity types to fetch
    
    Returns:
        List[Dict]: List of activity data
    """
    all_activities = []
    
    for activity_type in activity_types:
        try:
            activities = activity.filter(
                molecule_chembl_id=chembl_id,
                standard_type=activity_type
            ).only('standard_value', 'standard_units', 'standard_type', 'target_chembl_id')
            
            all_activities.extend(list(activities))
        except Exception as e:
            logger.error(f"Error fetching {activity_type} for {chembl_id}: {str(e)}")
    
    return all_activities