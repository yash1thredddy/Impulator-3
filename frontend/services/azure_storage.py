"""
Azure Blob Storage client for frontend direct access.

Frontend reads directly from Azure (same credentials as backend).
Backend writes, frontend reads - CQRS pattern.

Local caching:
- Results are cached locally in data/results/
- Only downloads from Azure if not cached locally
- Reduces Azure API calls significantly
"""

import os
import io
import json
import zipfile
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime, timezone

import pandas as pd

from frontend.utils import sanitize_compound_name

logger = logging.getLogger(__name__)

# Lazy import Azure SDK
_blob_service_client = None

# Local cache directory - use absolute path relative to this module
# This ensures frontend and backend share the same data directory
_MODULE_DIR = Path(__file__).parent.parent.parent  # Impulator/
LOCAL_CACHE_DIR = Path(os.getenv("DATA_DIR", str(_MODULE_DIR / "data"))) / "results"
LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Maximum number of cached compounds (LRU eviction)
MAX_CACHE_ITEMS = int(os.getenv("MAX_CACHE_ITEMS", "1000"))


def _get_connection_string() -> Optional[str]:
    """Get Azure connection string from environment."""
    return os.getenv("AZURE_CONNECTION_STRING", "")


def _get_container_name() -> str:
    """Get Azure container name from environment."""
    return os.getenv("AZURE_CONTAINER", "impulator")


def is_azure_configured() -> bool:
    """Check if Azure is configured."""
    return bool(_get_connection_string())


def _get_blob_service():
    """Lazy initialization of Azure Blob service client."""
    global _blob_service_client

    conn_str = _get_connection_string()
    if not conn_str:
        return None

    if _blob_service_client is None:
        try:
            from azure.storage.blob import BlobServiceClient
            _blob_service_client = BlobServiceClient.from_connection_string(conn_str)
            logger.info("Frontend Azure Blob client initialized")
        except ImportError:
            logger.warning("azure-storage-blob not installed")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Azure client: {e}")
            return None

    return _blob_service_client


def _get_container_client():
    """Get Azure container client."""
    service = _get_blob_service()
    if service is None:
        return None

    try:
        return service.get_container_client(_get_container_name())
    except Exception as e:
        logger.error(f"Failed to get container client: {e}")
        return None


def list_local_results() -> List[Dict[str, Any]]:
    """
    List all locally cached result files.

    Returns:
        List of compound info dictionaries
    """
    results = []
    try:
        for zip_path in LOCAL_CACHE_DIR.glob("*.zip"):
            compound_name = zip_path.stem  # filename without extension
            stat = zip_path.stat()
            results.append({
                "compound_name": compound_name,
                "blob_name": f"results/{compound_name}.zip",
                "size": stat.st_size,
                "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "source": "local",
            })
        logger.debug(f"Found {len(results)} results in local cache")
    except Exception as e:
        logger.error(f"Failed to list local results: {e}")
    return results


def list_results(use_local_cache: bool = True) -> List[Dict[str, Any]]:
    """
    List all result files, checking local cache first.

    Args:
        use_local_cache: If True, return local results without checking Azure

    Returns:
        List of compound info dictionaries with:
        - compound_name: str
        - blob_name: str
        - size: int
        - last_modified: datetime
        - source: "local" or "azure"
    """
    # If local cache has results and we're not forcing Azure check
    local_results = list_local_results()
    if use_local_cache and local_results:
        logger.debug("Using local cache for result listing")
        return local_results

    # Check Azure for authoritative list
    if not is_azure_configured():
        logger.warning("Azure not configured, using local cache only")
        return local_results

    container = _get_container_client()
    if container is None:
        return local_results

    try:
        results = []
        blobs = container.list_blobs(name_starts_with="results/")

        for blob in blobs:
            if blob.name.endswith(".zip"):
                # Extract compound name from path: results/compound_name.zip
                compound_name = blob.name.replace("results/", "").replace(".zip", "")
                results.append({
                    "compound_name": compound_name,
                    "blob_name": blob.name,
                    "size": blob.size,
                    "last_modified": blob.last_modified,
                    "source": "azure",
                })

        logger.info(f"Found {len(results)} results in Azure")
        return results

    except Exception as e:
        logger.error(f"Failed to list results from Azure: {e}")
        # Fallback to local cache
        return local_results


def _get_local_cache_path(compound_name: str) -> Path:
    """Get local cache path for a compound."""
    safe_name = sanitize_compound_name(compound_name)
    return LOCAL_CACHE_DIR / f"{safe_name}.zip"


def _is_cached_locally(compound_name: str) -> bool:
    """Check if compound result is cached locally."""
    cache_path = _get_local_cache_path(compound_name)
    return cache_path.exists() and cache_path.stat().st_size > 0


def _read_from_local_cache(compound_name: str) -> Optional[bytes]:
    """Read result from local cache.

    Updates modification time on read (LRU behavior).
    """
    cache_path = _get_local_cache_path(compound_name)
    if cache_path.exists():
        try:
            data = cache_path.read_bytes()
            # Touch file to update mtime (LRU: recently accessed stays)
            cache_path.touch()
            return data
        except Exception as e:
            logger.warning(f"Failed to read from cache: {e}")
    return None


def _write_to_local_cache(compound_name: str, data: bytes) -> bool:
    """Write result to local cache."""
    cache_path = _get_local_cache_path(compound_name)
    try:
        cache_path.write_bytes(data)
        logger.info(f"Cached {compound_name} locally ({len(data)} bytes)")
        # Evict oldest files if cache exceeds limit
        _evict_oldest_from_cache()
        return True
    except Exception as e:
        logger.warning(f"Failed to write to cache: {e}")
        return False


def _evict_oldest_from_cache() -> int:
    """
    Evict oldest files from cache if it exceeds MAX_CACHE_ITEMS.

    Uses LRU strategy based on file modification time.

    Returns:
        Number of files evicted
    """
    try:
        # Get all cached ZIP files with their modification times
        cached_files = []
        for zip_path in LOCAL_CACHE_DIR.glob("*.zip"):
            try:
                stat = zip_path.stat()
                cached_files.append((zip_path, stat.st_mtime))
            except OSError:
                continue

        # Check if eviction is needed
        if len(cached_files) <= MAX_CACHE_ITEMS:
            return 0

        # Sort by modification time (oldest first)
        cached_files.sort(key=lambda x: x[1])

        # Calculate how many to evict
        evict_count = len(cached_files) - MAX_CACHE_ITEMS
        evicted = 0

        for zip_path, _ in cached_files[:evict_count]:
            try:
                zip_path.unlink()
                evicted += 1
                logger.debug(f"Evicted {zip_path.stem} from cache")
            except OSError as e:
                logger.warning(f"Failed to evict {zip_path}: {e}")

        if evicted > 0:
            logger.info(f"Evicted {evicted} oldest files from cache (limit: {MAX_CACHE_ITEMS})")

        return evicted

    except Exception as e:
        logger.error(f"Cache eviction failed: {e}")
        return 0


def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics.

    Returns:
        Dict with cache size, count, and limit info
    """
    try:
        total_size = 0
        count = 0
        oldest_mtime = None
        newest_mtime = None

        for zip_path in LOCAL_CACHE_DIR.glob("*.zip"):
            try:
                stat = zip_path.stat()
                total_size += stat.st_size
                count += 1
                if oldest_mtime is None or stat.st_mtime < oldest_mtime:
                    oldest_mtime = stat.st_mtime
                if newest_mtime is None or stat.st_mtime > newest_mtime:
                    newest_mtime = stat.st_mtime
            except OSError:
                continue

        return {
            "count": count,
            "max_items": MAX_CACHE_ITEMS,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "oldest": datetime.fromtimestamp(oldest_mtime, tz=timezone.utc) if oldest_mtime else None,
            "newest": datetime.fromtimestamp(newest_mtime, tz=timezone.utc) if newest_mtime else None,
            "cache_dir": str(LOCAL_CACHE_DIR),
        }
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {"error": str(e)}


def download_result(compound_name: str, force_refresh: bool = False) -> Optional[bytes]:
    """
    Download a result ZIP file, using local cache when available.

    Args:
        compound_name: Name of the compound
        force_refresh: If True, skip cache and download from Azure

    Returns:
        ZIP file bytes, or None if not found
    """
    # Check local cache first (unless force refresh)
    if not force_refresh and _is_cached_locally(compound_name):
        logger.debug(f"Using cached result for {compound_name}")
        return _read_from_local_cache(compound_name)

    # Download from Azure
    if not is_azure_configured():
        # Fallback: try local cache even without Azure
        return _read_from_local_cache(compound_name)

    container = _get_container_client()
    if container is None:
        return _read_from_local_cache(compound_name)

    # Sanitize compound name (consistent with backend)
    safe_name = sanitize_compound_name(compound_name)
    blob_name = f"results/{safe_name}.zip"

    try:
        blob_client = container.get_blob_client(blob_name)

        if not blob_client.exists():
            logger.warning(f"Result {blob_name} not found in Azure")
            return None

        download_stream = blob_client.download_blob()
        data = download_stream.readall()
        logger.info(f"Downloaded {compound_name} from Azure ({len(data)} bytes)")

        # Cache locally for future use
        _write_to_local_cache(compound_name, data)

        return data

    except Exception as e:
        logger.error(f"Failed to download result: {e}")
        # Try local cache as fallback
        return _read_from_local_cache(compound_name)


def load_result_dataframe(compound_name: str, filename: str = "similar_compounds.csv") -> Optional[pd.DataFrame]:
    """
    Load a specific CSV from a result ZIP file.

    Args:
        compound_name: Name of the compound
        filename: CSV filename within the ZIP (default: similar_compounds.csv)

    Returns:
        DataFrame or None if not found
    """
    zip_data = download_result(compound_name)
    if zip_data is None:
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
            if filename in zf.namelist():
                with zf.open(filename) as f:
                    return pd.read_csv(f)
            else:
                logger.warning(f"{filename} not found in {compound_name}.zip")
                return None

    except Exception as e:
        logger.error(f"Failed to extract {filename}: {e}")
        return None


def load_result_json(compound_name: str, filename: str = "summary.json") -> Optional[Dict]:
    """
    Load a specific JSON from a result ZIP file.

    Args:
        compound_name: Name of the compound
        filename: JSON filename within the ZIP

    Returns:
        Dict or None if not found
    """
    zip_data = download_result(compound_name)
    if zip_data is None:
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
            if filename in zf.namelist():
                with zf.open(filename) as f:
                    return json.load(f)
            else:
                logger.warning(f"{filename} not found in {compound_name}.zip")
                return None

    except Exception as e:
        logger.error(f"Failed to extract {filename}: {e}")
        return None


def get_result_files(compound_name: str) -> List[str]:
    """
    List all files in a result ZIP.

    Args:
        compound_name: Name of the compound

    Returns:
        List of filenames in the ZIP
    """
    zip_data = download_result(compound_name)
    if zip_data is None:
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
            return zf.namelist()

    except Exception as e:
        logger.error(f"Failed to list ZIP contents: {e}")
        return []


@lru_cache(maxsize=50)
def get_cached_result(compound_name: str) -> Optional[Dict]:
    """
    Get cached result summary for a compound.

    Uses LRU cache to avoid repeated Azure downloads.

    Args:
        compound_name: Name of the compound

    Returns:
        Result summary dict or None
    """
    return load_result_json(compound_name, "summary.json")


def clear_cache():
    """Clear the result cache."""
    get_cached_result.cache_clear()
    logger.info("Azure result cache cleared")


def delete_from_cache(compound_name: str) -> bool:
    """
    Delete a compound from the local cache.

    Called when a compound is deleted from the backend.

    Args:
        compound_name: Name of the compound to delete

    Returns:
        True if deleted, False if not found or error
    """
    cache_path = _get_local_cache_path(compound_name)
    try:
        if cache_path.exists():
            cache_path.unlink()
            logger.info(f"Deleted {compound_name} from local cache")
            # Also clear from LRU cache
            get_cached_result.cache_clear()
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to delete from cache: {e}")
        return False


def delete_from_azure(compound_name: str) -> bool:
    """
    Delete a compound result from Azure Blob Storage.

    This allows deletion even when backend is unavailable.

    Args:
        compound_name: Name of the compound to delete

    Returns:
        True if deleted, False on error
    """
    container = _get_container_client()
    if container is None:
        logger.warning("Azure not configured, cannot delete from Azure")
        return False

    # Sanitize name (consistent with backend)
    safe_name = sanitize_compound_name(compound_name)
    blob_name = f"results/{safe_name}.zip"

    try:
        blob_client = container.get_blob_client(blob_name)
        blob_client.delete_blob()
        logger.info(f"Deleted {compound_name} from Azure: {blob_name}")
        return True
    except Exception as e:
        # May fail if blob doesn't exist - that's OK
        logger.warning(f"Failed to delete from Azure (may not exist): {e}")
        return False


def delete_compound(compound_name: str) -> bool:
    """
    Delete a compound from all storage locations.

    Deletes from:
    - Azure Blob Storage
    - Local cache

    Note: Does NOT delete from backend database (use backend API for that).

    Args:
        compound_name: Name of the compound to delete

    Returns:
        True if deleted from at least one location
    """
    azure_deleted = delete_from_azure(compound_name)
    cache_deleted = delete_from_cache(compound_name)

    if azure_deleted or cache_deleted:
        logger.info(f"Deleted compound {compound_name}: azure={azure_deleted}, cache={cache_deleted}")
        return True

    logger.warning(f"Compound {compound_name} not found in any storage")
    return False
