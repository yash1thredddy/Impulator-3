import threading
import queue
import time
import logging
import os
import shutil
from typing import Optional
from modules.azure_storage import get_azure_storage
from config import RESULTS_DIR

logger = logging.getLogger(__name__)

# Global queue for upload tasks
upload_queue = queue.Queue()

def background_upload_worker():
    """
    Daemon worker that monitors the queue and uploads files to Azure.
    This runs independently of any specific user session.
    """
    logger.info("🚀 Background upload worker started")
    
    while True:
        try:
            # Get task from queue (blocking wait)
            task = upload_queue.get()
            
            if task is None:
                break  # Sentinel to stop worker
                
            compound_name, folder_path = task
            logger.info(f"🔄 Starting background upload for: {compound_name}")
            
            azure_storage = get_azure_storage()
            if azure_storage.enabled:
                success = azure_storage.upload_compound_zip(compound_name, folder_path)
                
                if success:
                    logger.info(f"✅ Background upload complete: {compound_name}")
                    # Clean up local files after successful upload
                    if os.path.exists(folder_path):
                        shutil.rmtree(folder_path)
                        logger.info(f"🧹 Cleaned up local folder: {folder_path}")
                else:
                    logger.error(f"❌ Background upload failed for {compound_name}")
            else:
                logger.warning("Azure storage not enabled, skipping background upload")
                
            upload_queue.task_done()
            
        except Exception as e:
            logger.error(f"💥 Error in background worker: {e}")

# Singleton thread reference
_worker_thread: Optional[threading.Thread] = None

def start_background_worker():
    """Start the background worker thread if not already running."""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=background_upload_worker, daemon=True)
        _worker_thread.start()
        logger.info("Background worker thread initialized")

def enqueue_upload(compound_name: str, folder_path: str):
    """Add a compound to the upload queue."""
    upload_queue.put((compound_name, folder_path))
    logger.info(f"Queued upload for {compound_name} (Queue size: {upload_queue.qsize()})")
