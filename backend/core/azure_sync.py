"""
Azure Blob Storage sync utilities.
Handles database backup/restore and result uploads.
Azure Blob serves as the single source of truth for data persistence.
"""
import gzip
import os
import re
import shutil
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


class AzureSyncRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler that uploads rotated log files to Azure Blob storage.

    When a log file is full and rotates, the old file is compressed and
    uploaded to Azure before being replaced. This ensures logs are preserved
    even if the container crashes.
    """

    def doRollover(self):
        """
        Override to upload the rotated file to Azure before rotation.
        """
        # Get the file that's about to be rotated (current log file)
        if self.stream:
            self.stream.close()
            self.stream = None

        # Upload current log to Azure before rotation
        if self.baseFilename and Path(self.baseFilename).exists():
            self._upload_to_azure(self.baseFilename)

        # Call parent rollover (handles file rotation)
        super().doRollover()

    def _upload_to_azure(self, filepath: str) -> bool:
        """Compress and upload a log file to Azure."""
        try:
            # Check if Azure is configured (avoid circular import)
            if not settings.AZURE_CONNECTION_STRING:
                return False

            path = Path(filepath)
            if not path.exists() or path.stat().st_size == 0:
                return False

            # Create compressed version
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            gz_name = f"backend_{timestamp}.log.gz"
            gz_path = path.parent / gz_name

            with open(path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    f_out.writelines(f_in)

            # Upload to Azure
            blob_name = f"logs/{gz_name}"
            blob = _get_blob_client(blob_name)
            if blob is None:
                gz_path.unlink(missing_ok=True)
                return False

            with open(gz_path, 'rb') as f:
                blob.upload_blob(f, overwrite=True)

            # Cleanup local compressed file
            gz_path.unlink(missing_ok=True)

            # Use print since logger might cause recursion
            print(f"[AzureSync] Uploaded rotated log to Azure: {blob_name}")

            # Cleanup old archives (keep last 20)
            _cleanup_old_log_archives(keep_count=20)

            return True

        except Exception as e:
            print(f"[AzureSync] Failed to upload log to Azure: {e}")
            return False


def _sanitize_compound_name(name: str) -> str:
    """
    Sanitize compound name for filesystem and Azure storage.

    Internal function - use backend.core.sanitize_compound_name for external use.
    Duplicated here to avoid circular imports.
    """
    safe = name.replace(' ', '_').replace('/', '_').replace('\\', '_')
    safe = re.sub(r'[^a-zA-Z0-9\-_]', '_', safe)
    safe = re.sub(r'_+', '_', safe)
    safe = safe.strip('_')
    return safe if safe else 'unnamed_compound'

# Lazy import to avoid startup failures if azure not installed
_blob_service_client = None


def _get_blob_service():
    """Lazy initialization of Azure Blob service client."""
    global _blob_service_client

    if not settings.AZURE_CONNECTION_STRING:
        return None

    if _blob_service_client is None:
        try:
            from azure.storage.blob import BlobServiceClient
            _blob_service_client = BlobServiceClient.from_connection_string(
                settings.AZURE_CONNECTION_STRING
            )
            logger.info("Azure Blob service client initialized")
        except ImportError:
            logger.warning("azure-storage-blob not installed, Azure sync disabled")
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
        container = service.get_container_client(settings.AZURE_CONTAINER)
        # Create container if it doesn't exist
        if not container.exists():
            container.create_container()
            logger.info(f"Created Azure container: {settings.AZURE_CONTAINER}")
        return container
    except Exception as e:
        logger.error(f"Failed to get container client: {e}")
        return None


def _get_blob_client(blob_name: str):
    """Get Azure Blob client for a specific blob."""
    container = _get_container_client()
    if container is None:
        return None

    return container.get_blob_client(blob_name)


def is_azure_configured() -> bool:
    """Check if Azure Blob storage is configured."""
    return bool(settings.AZURE_CONNECTION_STRING)


def download_db_from_azure() -> bool:
    """
    Download SQLite database from Azure on container startup.
    This restores state from the single source of truth.

    Returns:
        True if download successful or Azure not configured
    """
    if not is_azure_configured():
        logger.info("Azure not configured, using local database")
        return True

    blob = _get_blob_client("impulator.db")
    if blob is None:
        return False

    db_path = Path(settings.DATA_DIR) / "impulator.db"

    try:
        # Ensure data directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        if blob.exists():
            with open(db_path, "wb") as f:
                download_stream = blob.download_blob()
                f.write(download_stream.readall())
            logger.info(f"Downloaded SQLite from Azure ({db_path})")
            return True
        else:
            logger.info("No existing database in Azure, starting fresh")
            return True

    except Exception as e:
        logger.error(f"Failed to download database from Azure: {e}")
        return False


def sync_db_to_azure() -> bool:
    """
    Upload SQLite database to Azure immediately.
    Called after every job completion to ensure no data loss.

    Returns:
        True if sync successful or Azure not configured
    """
    if not is_azure_configured():
        return True

    blob = _get_blob_client("impulator.db")
    if blob is None:
        return False

    db_path = Path(settings.DATA_DIR) / "impulator.db"
    temp_path = Path(settings.DATA_DIR) / "impulator.db.tmp"

    try:
        if not db_path.exists():
            logger.warning("Database file not found, skipping sync")
            return False

        # Copy to temp file to avoid locking issues
        shutil.copy2(db_path, temp_path)

        with open(temp_path, "rb") as f:
            blob.upload_blob(f, overwrite=True)

        # Cleanup temp file
        temp_path.unlink(missing_ok=True)

        logger.info("Synced SQLite to Azure")
        return True

    except Exception as e:
        logger.error(f"Failed to sync database to Azure: {e}")
        # Cleanup temp file on error
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return False


def upload_result_to_azure(local_path: str, compound_name: str) -> bool:
    """
    Upload result ZIP file to Azure Blob storage with verification.

    Args:
        local_path: Path to the local ZIP file
        compound_name: Name of the compound (used for blob name)

    Returns:
        True if upload successful and verified, or Azure not configured
    """
    if not is_azure_configured():
        return True

    # Sanitize compound name for blob path
    safe_name = _sanitize_compound_name(compound_name)
    blob_name = f"results/{safe_name}.zip"

    blob = _get_blob_client(blob_name)
    if blob is None:
        return False

    try:
        # Get local file size for verification
        local_path_obj = Path(local_path)
        if not local_path_obj.exists():
            logger.error(f"Local file not found: {local_path}")
            return False

        local_size = local_path_obj.stat().st_size

        # Upload the file
        with open(local_path, "rb") as f:
            blob.upload_blob(f, overwrite=True)

        # Verify upload by checking blob properties
        blob_properties = blob.get_blob_properties()
        uploaded_size = blob_properties.size

        if uploaded_size != local_size:
            logger.error(
                f"Upload verification failed for {compound_name}: "
                f"local size={local_size}, uploaded size={uploaded_size}"
            )
            return False

        logger.info(f"Uploaded and verified {compound_name}.zip to Azure ({blob_name}, {uploaded_size} bytes)")
        return True

    except Exception as e:
        logger.error(f"Failed to upload result to Azure: {e}")
        return False


def download_result_from_azure(compound_name: str, local_path: str) -> bool:
    """
    Download result ZIP file from Azure Blob storage.

    Args:
        compound_name: Name of the compound
        local_path: Where to save the downloaded file

    Returns:
        True if download successful
    """
    if not is_azure_configured():
        return False

    safe_name = _sanitize_compound_name(compound_name)
    blob_name = f"results/{safe_name}.zip"

    blob = _get_blob_client(blob_name)
    if blob is None:
        return False

    try:
        # Security: Validate path to prevent path traversal attacks
        resolved_path = Path(local_path).resolve()
        allowed_dirs = [
            Path(settings.RESULTS_DIR).resolve(),
            Path(settings.DATA_DIR).resolve(),
            Path("/tmp").resolve() if not os.name == 'nt' else Path(os.environ.get('TEMP', 'C:\\Temp')).resolve(),
        ]

        path_is_safe = any(
            str(resolved_path).startswith(str(allowed_dir))
            for allowed_dir in allowed_dirs
        )

        if not path_is_safe:
            logger.error(f"Path traversal attempt blocked: {local_path}")
            # Audit log for security monitoring
            try:
                from backend.core.audit import log_path_traversal_blocked
                log_path_traversal_blocked(local_path)
            except ImportError:
                pass  # Audit module may not be available during startup
            return False

        if not blob.exists():
            logger.warning(f"Result {blob_name} not found in Azure")
            return False

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)

        with open(local_path, "wb") as f:
            download_stream = blob.download_blob()
            f.write(download_stream.readall())

        logger.info(f"Downloaded {compound_name}.zip from Azure")
        return True

    except Exception as e:
        logger.error(f"Failed to download result from Azure: {e}")
        return False


def list_results_in_azure() -> list:
    """
    List all result files in Azure Blob storage.

    Returns:
        List of compound names with results
    """
    if not is_azure_configured():
        return []

    container = _get_container_client()
    if container is None:
        return []

    try:
        blobs = container.list_blobs(name_starts_with="results/")
        results = []
        for blob in blobs:
            # Extract compound name from path: results/compound_name.zip
            name = blob.name.replace("results/", "").replace(".zip", "")
            results.append(name)
        return results

    except Exception as e:
        logger.error(f"Failed to list results from Azure: {e}")
        return []


def delete_result_from_azure(compound_name: str) -> bool:
    """
    Delete a result ZIP file from Azure Blob storage.

    Args:
        compound_name: Name of the compound to delete

    Returns:
        True if deletion successful
    """
    if not is_azure_configured():
        return True

    safe_name = _sanitize_compound_name(compound_name)
    blob_name = f"results/{safe_name}.zip"

    blob = _get_blob_client(blob_name)
    if blob is None:
        return False

    try:
        if blob.exists():
            blob.delete_blob()
            logger.info(f"Deleted {compound_name}.zip from Azure")
        return True

    except Exception as e:
        logger.error(f"Failed to delete result from Azure: {e}")
        return False


def sync_compound_table_from_azure() -> int:
    """
    Sync local Compound table with Azure Blob storage.

    Ensures that every result ZIP in Azure has a corresponding entry
    in the local Compound table. This maintains consistency after
    database restoration or if local DB gets out of sync.

    Uses batch processing for efficiency:
    - Fetches all existing compounds in a single query
    - Batch inserts new compounds in groups of 100
    - Commits per batch to avoid large transactions

    Returns:
        Number of compound entries added
    """
    if not is_azure_configured():
        return 0

    # Get list of all results in Azure
    azure_compounds = list_results_in_azure()
    if not azure_compounds:
        return 0

    added_count = 0
    BATCH_SIZE = 100

    try:
        # Import here to avoid circular imports
        from backend.core.database import get_db_session
        from backend.models.database import Compound

        with get_db_session() as db:
            # Batch query: get all existing compound names in one query
            existing_compounds = db.query(Compound.compound_name).all()
            existing_names = {row[0] for row in existing_compounds}

            # Find compounds that need to be added
            new_compounds = [name for name in azure_compounds if name not in existing_names]

            if not new_compounds:
                logger.info("Compound table already in sync with Azure")
                return 0

            # Batch insert new compounds
            for i in range(0, len(new_compounds), BATCH_SIZE):
                batch = new_compounds[i:i + BATCH_SIZE]
                for compound_name in batch:
                    compound = Compound(
                        compound_name=compound_name,
                        storage_path=f"results/{_sanitize_compound_name(compound_name)}.zip",
                    )
                    db.add(compound)
                    added_count += 1

                # Commit after each batch
                db.commit()
                logger.info(f"Synced batch {i // BATCH_SIZE + 1}: {len(batch)} compounds")

            logger.info(f"Synced {added_count} compound entries from Azure")

    except Exception as e:
        logger.error(f"Failed to sync compound table from Azure: {e}")

    return added_count


def check_result_exists_in_azure(compound_name: str) -> bool:
    """
    Check if a compound result exists in Azure Blob storage.

    Args:
        compound_name: Name of the compound

    Returns:
        True if result exists in Azure
    """
    if not is_azure_configured():
        return False

    safe_name = _sanitize_compound_name(compound_name)
    blob_name = f"results/{safe_name}.zip"

    blob = _get_blob_client(blob_name)
    if blob is None:
        return False

    try:
        return blob.exists()
    except Exception as e:
        logger.error(f"Failed to check if result exists in Azure: {e}")
        return False


def sync_logs_to_azure() -> bool:
    """
    Upload current (non-rotated) log file to Azure on shutdown.

    Only uploads the main backend.log file since rotated logs (.log.1, .log.2)
    are already uploaded by AzureSyncRotatingFileHandler during rotation.

    Returns:
        True if sync successful or Azure not configured
    """
    if not is_azure_configured():
        return True

    log_file = Path(settings.DATA_DIR) / "logs" / "backend.log"
    if not log_file.exists() or log_file.stat().st_size == 0:
        logger.info("No current log to sync to Azure")
        return True

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    gz_name = f"backend_{timestamp}_shutdown.log.gz"
    gz_path = log_file.parent / gz_name

    try:
        # Compress current log
        with open(log_file, 'rb') as f_in:
            with gzip.open(gz_path, 'wb') as f_out:
                f_out.writelines(f_in)

        # Upload to Azure
        blob_name = f"logs/{gz_name}"
        blob = _get_blob_client(blob_name)
        if blob is None:
            gz_path.unlink(missing_ok=True)
            return False

        with open(gz_path, 'rb') as f:
            blob.upload_blob(f, overwrite=True)

        logger.info(f"Uploaded current log to Azure: {blob_name}")

        # Cleanup local compressed file
        gz_path.unlink(missing_ok=True)

        # Cleanup old log archives in Azure (keep last 20)
        _cleanup_old_log_archives(keep_count=20)

        return True

    except Exception as e:
        logger.error(f"Failed to sync logs to Azure: {e}")
        if gz_path.exists():
            gz_path.unlink(missing_ok=True)
        return False


def _cleanup_old_log_archives(keep_count: int = 10) -> None:
    """
    Remove old log archives from Azure, keeping only the most recent ones.

    Args:
        keep_count: Number of recent archives to keep
    """
    container = _get_container_client()
    if container is None:
        return

    try:
        blobs = list(container.list_blobs(name_starts_with="logs/"))
        if len(blobs) <= keep_count:
            return

        # Sort by name (timestamp-based, so alphabetical = chronological)
        blobs.sort(key=lambda b: b.name, reverse=True)

        # Delete older archives
        for blob in blobs[keep_count:]:
            try:
                container.delete_blob(blob.name)
                logger.info(f"Deleted old log archive: {blob.name}")
            except Exception as e:
                logger.warning(f"Failed to delete old log archive {blob.name}: {e}")

    except Exception as e:
        logger.warning(f"Failed to cleanup old log archives: {e}")
