"""
Background upload worker for Azure Blob Storage.
Runs independently of Streamlit, monitors for new compounds and uploads them automatically.
"""

import os
import time
import threading
import logging
import shutil
from queue import Queue
from typing import Dict
from pathlib import Path

logger = logging.getLogger(__name__)

# Global upload queue
_upload_queue = Queue()
_worker_thread = None
_worker_running = False


class UploadWorker:
    """Background worker that continuously monitors and uploads compounds to Azure."""

    def __init__(self):
        """Initialize the upload worker."""
        self.queue = _upload_queue
        self.running = False
        self.thread = None

    def start(self):
        """Start the background worker thread."""
        if self.running:
            logger.info("Upload worker already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="AzureUploadWorker")
        self.thread.start()
        logger.info("🚀 Background upload worker started")

    def stop(self):
        """Stop the background worker thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("🛑 Background upload worker stopped")

    def queue_upload(self, compound_name: str, compound_folder: str, metadata: Dict):
        """
        Queue a compound for upload.

        Args:
            compound_name: Name of the compound
            compound_folder: Path to compound's local folder
            metadata: Dict containing compound metadata
        """
        upload_task = {
            'compound_name': compound_name,
            'compound_folder': compound_folder,
            'metadata': metadata,
            'queued_at': time.time()
        }

        self.queue.put(upload_task)
        logger.info(f"📥 Queued {compound_name} for upload (queue size: {self.queue.qsize()})")

    def _worker_loop(self):
        """Main worker loop that processes upload queue."""
        logger.info("Worker loop started, waiting for upload tasks...")

        while self.running:
            try:
                # Wait for upload task (timeout to check if still running)
                try:
                    task = self.queue.get(timeout=1.0)
                except Exception:
                    # Timeout or queue error, continue checking if still running
                    continue

                compound_name = task['compound_name']
                compound_folder = task['compound_folder']
                metadata = task['metadata']

                logger.info(f"🔄 Processing upload for {compound_name}")

                # Perform upload
                success = self._upload_compound(compound_name, compound_folder, metadata)

                if success:
                    logger.info(f"✅ Successfully uploaded {compound_name}")
                else:
                    logger.warning(f"⚠️ Failed to upload {compound_name}, keeping local copy")

                self.queue.task_done()

            except Exception as e:
                logger.error(f"❌ Worker error: {e}", exc_info=True)
                time.sleep(1)  # Prevent tight loop on errors

        logger.info("Worker loop exited")

    def _upload_compound(self, compound_name: str, compound_folder: str, metadata: Dict) -> bool:
        """
        Upload compound and metadata to Azure.

        Args:
            compound_name: Name of the compound
            compound_folder: Path to compound's local folder
            metadata: Dict containing compound metadata

        Returns:
            bool: True if successful
        """
        try:
            from modules.azure_storage import get_azure_storage
            from modules.metadata_manager import save_metadata_to_azure, save_metadata_to_local

            azure_storage = get_azure_storage()

            if not azure_storage.enabled:
                logger.info("Azure not enabled, saving metadata locally only")
                # Save metadata to local CSV even if Azure is disabled
                save_metadata_to_local(metadata)
                return False

            # Check if folder exists
            if not os.path.exists(compound_folder):
                logger.warning(f"Compound folder not found: {compound_folder}")
                return False

            # Upload compound ZIP
            logger.info(f"Uploading ZIP for {compound_name}...")
            upload_success = azure_storage.upload_compound_zip(compound_name, compound_folder)

            if not upload_success:
                return False

            # Upload metadata to Azure
            logger.info(f"Uploading metadata for {compound_name}...")
            metadata_success = save_metadata_to_azure(metadata)

            if metadata_success:
                # Clear metadata cache so Azure metadata shows immediately
                try:
                    from modules.metadata_manager import get_all_compounds_metadata
                    get_all_compounds_metadata.clear()
                except Exception as e:
                    logger.warning(f"Failed to clear metadata cache: {e}")

                # Clean up local files (save ephemeral storage space)
                logger.info(f"Cleaning up local folder for {compound_name}...")
                shutil.rmtree(compound_folder)
                logger.info(f"🧹 Removed local folder: {compound_folder}")
            else:
                # If Azure metadata upload failed, save locally
                logger.warning("Azure metadata upload failed, saving locally")
                save_metadata_to_local(metadata)

            return upload_success and metadata_success

        except Exception as e:
            logger.error(f"Error uploading {compound_name}: {e}", exc_info=True)
            # Save metadata locally as fallback
            try:
                from modules.metadata_manager import save_metadata_to_local
                save_metadata_to_local(metadata)
            except Exception as fallback_error:
                logger.error(f"Failed to save metadata locally as fallback: {fallback_error}")
            return False


# Singleton instance
_worker_instance = None


def get_upload_worker() -> UploadWorker:
    """Get singleton instance of UploadWorker."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = UploadWorker()
    return _worker_instance


def start_upload_worker():
    """Start the global upload worker (call once at app startup)."""
    worker = get_upload_worker()
    worker.start()


def queue_compound_upload(compound_name: str, compound_folder: str, metadata: Dict):
    """
    Queue a compound for background upload.

    Args:
        compound_name: Name of the compound
        compound_folder: Path to compound's local folder
        metadata: Dict containing compound metadata
    """
    worker = get_upload_worker()
    worker.queue_upload(compound_name, compound_folder, metadata)
