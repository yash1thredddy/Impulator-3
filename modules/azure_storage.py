"""
Azure Blob Storage Manager for IMPULATOR
Handles ZIP-based storage of compound analysis results in Azure Blob Storage.

Each compound's results are stored as a single ZIP file containing:
- CSV files (complete, imp, non-imp)
- Visualizations (PNG/HTML)
- All analysis outputs

This approach minimizes storage operations and reduces costs.
"""

import os
import tempfile
import zipfile
import logging
from pathlib import Path
from typing import List, Optional
import streamlit as st
import pandas as pd

logger = logging.getLogger(__name__)

# Environment detection
def is_cloud_deployment() -> bool:
    """
    Detect if running on any cloud platform (HF Spaces or Streamlit Cloud).
    Returns True if Azure Blob Storage should be enabled.
    """
    # Hugging Face Spaces detection
    if os.environ.get('SPACE_ID'):
        logger.info("✅ Detected Hugging Face Spaces (SPACE_ID found)")
        return True

    if os.environ.get('SPACE_AUTHOR_NAME'):
        logger.info("✅ Detected Hugging Face Spaces (SPACE_AUTHOR_NAME found)")
        return True

    # Streamlit Cloud detection
    if os.environ.get('STREAMLIT_SHARING_MODE'):
        logger.info("✅ Detected Streamlit Cloud (STREAMLIT_SHARING_MODE found)")
        return True

    if os.path.exists('/mount/src'):
        logger.info("✅ Detected Streamlit Cloud (mount point found)")
        return True

    # Manual override for testing
    if os.environ.get('FORCE_AZURE_MODE', '').lower() == 'true':
        logger.info("✅ Azure mode forced (FORCE_AZURE_MODE=true)")
        return True

    logger.info("ℹ️ Running locally - Azure Blob Storage disabled")
    return False


class AzureStorageManager:
    """
    Manages compound results storage in Azure Blob Storage.
    Uses ZIP compression to store each compound's folder as a single blob.
    """

    def __init__(self):
        """Initialize Azure Blob Storage client."""
        self.enabled = is_cloud_deployment()
        self.container_name = "impulator-results"
        self.blob_service_client = None
        self.container_client = None

        if self.enabled:
            self._initialize_azure_client()
        else:
            logger.info("Azure Storage disabled (running locally)")

    def _initialize_azure_client(self):
        """Initialize Azure Blob Storage client with credentials."""
        try:
            from azure.storage.blob import BlobServiceClient

            # Priority 1: Environment variable (HF Spaces uses this)
            connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')

            # Priority 2: Streamlit secrets (Streamlit Cloud uses this)
            account_name = None
            account_key = None
            if not connection_string and hasattr(st, 'secrets'):
                if 'azure' in st.secrets:
                    connection_string = st.secrets['azure'].get('connection_string')
                    account_name = st.secrets['azure'].get('account_name')
                    account_key = st.secrets['azure'].get('account_key')

            if not connection_string and not (account_name and account_key):
                logger.error("❌ Azure credentials not found in environment or secrets")
                self.enabled = False
                return

            # Prefer connection string, fall back to account name + key
            if connection_string:
                self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            elif account_name and account_key:
                account_url = f"https://{account_name}.blob.core.windows.net"
                from azure.storage.blob import BlobServiceClient
                from azure.core.credentials import AzureNamedKeyCredential
                credential = AzureNamedKeyCredential(account_name, account_key)
                self.blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
            else:
                logger.error("Invalid Azure credentials in secrets")
                self.enabled = False
                return

            # Get or create container
            self.container_client = self.blob_service_client.get_container_client(self.container_name)

            # Create container if it doesn't exist
            if not self.container_client.exists():
                logger.info(f"Creating Azure container: {self.container_name}")
                self.container_client.create_container()

            logger.info("✅ Azure Blob Storage initialized successfully")

        except ImportError:
            logger.error("azure-storage-blob package not installed")
            self.enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize Azure Storage: {e}")
            self.enabled = False

    def _create_zip_from_folder(self, folder_path: str, zip_path: str) -> bool:
        """
        Create a ZIP file from a folder.

        Args:
            folder_path: Path to folder to zip
            zip_path: Path where ZIP file will be created

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                folder = Path(folder_path)

                # Add all files in the folder
                for file_path in folder.rglob('*'):
                    if file_path.is_file():
                        # Store relative path in ZIP
                        arcname = file_path.relative_to(folder)
                        zipf.write(file_path, arcname)

            logger.info(f"Created ZIP: {zip_path} ({os.path.getsize(zip_path) / 1024:.2f} KB)")
            return True

        except Exception as e:
            logger.error(f"Failed to create ZIP: {e}")
            return False

    def _extract_zip_to_folder(self, zip_path: str, extract_to: str) -> bool:
        """
        Extract a ZIP file to a folder.

        Args:
            zip_path: Path to ZIP file
            extract_to: Path where contents will be extracted

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            os.makedirs(extract_to, exist_ok=True)

            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(extract_to)

            logger.info(f"Extracted ZIP to: {extract_to}")
            return True

        except Exception as e:
            logger.error(f"Failed to extract ZIP: {e}")
            return False

    def upload_compound_zip(self, compound_name: str, folder_path: str) -> bool:
        """
        Upload a compound's results folder as a ZIP file to Azure Blob Storage.

        Args:
            compound_name: Name of the compound
            folder_path: Local path to compound's results folder

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            logger.info(f"Azure Storage disabled - skipping upload for {compound_name}")
            return False

        temp_zip = None
        try:
            # Create temporary ZIP file path
            temp_zip = os.path.join(tempfile.gettempdir(), f"{compound_name}.zip")

            # ZIP the folder
            if not self._create_zip_from_folder(folder_path, temp_zip):
                return False

            # Upload to Azure
            blob_name = f"{compound_name}.zip"
            blob_client = self.container_client.get_blob_client(blob_name)

            with open(temp_zip, 'rb') as data:
                blob_client.upload_blob(data, overwrite=True)

            logger.info(f"✅ Uploaded {compound_name} to Azure Blob Storage")
            return True

        except Exception as e:
            logger.error(f"Failed to upload {compound_name} to Azure: {e}")
            return False
        finally:
            # Clean up temp ZIP
            if temp_zip and os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to remove temp file {temp_zip}: {cleanup_error}")

    def download_compound_zip(self, compound_name: str, extract_to: str) -> bool:
        """
        Download a compound's ZIP file from Azure and extract it.

        Args:
            compound_name: Name of the compound
            extract_to: Local path where contents will be extracted

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            logger.info(f"Azure Storage disabled - skipping download for {compound_name}")
            return False

        temp_zip = None
        try:
            blob_name = f"{compound_name}.zip"
            blob_client = self.container_client.get_blob_client(blob_name)

            # Download to temp ZIP
            temp_zip = os.path.join(tempfile.gettempdir(), f"{compound_name}_download.zip")

            with open(temp_zip, 'wb') as download_file:
                download_file.write(blob_client.download_blob().readall())

            logger.info(f"Downloaded {compound_name} from Azure Blob Storage")

            # Extract ZIP
            success = self._extract_zip_to_folder(temp_zip, extract_to)
            return success

        except Exception as e:
            logger.error(f"Failed to download {compound_name} from Azure: {e}")
            return False
        finally:
            # Clean up temp ZIP
            if temp_zip and os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to remove temp file {temp_zip}: {cleanup_error}")

    def list_compounds(self) -> List[str]:
        """
        List all compounds stored in Azure Blob Storage.

        Returns:
            List of compound names (without .zip extension)
        """
        if not self.enabled:
            return []

        try:
            blob_list = self.container_client.list_blobs()
            compounds = []

            for blob in blob_list:
                if blob.name.endswith('.zip'):
                    # Remove .zip extension
                    compound_name = blob.name[:-4]
                    compounds.append(compound_name)

            logger.info(f"Found {len(compounds)} compounds in Azure Blob Storage")
            return compounds

        except Exception as e:
            logger.error(f"Failed to list compounds from Azure: {e}")
            return []

    def delete_compound(self, compound_name: str) -> bool:
        """
        Delete a compound's ZIP file from Azure Blob Storage.

        Args:
            compound_name: Name of the compound to delete

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            logger.info(f"Azure Storage disabled - skipping delete for {compound_name}")
            return False

        try:
            blob_name = f"{compound_name}.zip"
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_client.delete_blob()

            logger.info(f"✅ Deleted {compound_name} from Azure Blob Storage")
            return True

        except Exception as e:
            logger.error(f"Failed to delete {compound_name} from Azure: {e}")
            return False

    def compound_exists(self, compound_name: str) -> bool:
        """
        Check if a compound exists in Azure Blob Storage.

        Args:
            compound_name: Name of the compound

        Returns:
            bool: True if exists, False otherwise
        """
        if not self.enabled:
            return False

        try:
            blob_name = f"{compound_name}.zip"
            blob_client = self.container_client.get_blob_client(blob_name)
            return blob_client.exists()

        except Exception as e:
            logger.error(f"Failed to check existence of {compound_name}: {e}")
            return False

    def upload_metadata_csv(self, metadata_df: pd.DataFrame) -> bool:
        """
        Upload metadata CSV to Azure (separate from compound ZIPs).

        Args:
            metadata_df: DataFrame containing all compounds metadata

        Returns:
            bool: True if successful
        """
        if not self.enabled:
            return False

        try:
            import io

            # Convert DataFrame to CSV bytes
            csv_buffer = io.BytesIO()
            metadata_df.to_csv(csv_buffer, index=False)
            csv_buffer.seek(0)

            # Upload to Azure
            blob_name = "compounds_metadata.csv"
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_client.upload_blob(csv_buffer, overwrite=True)

            logger.info(f"✅ Uploaded metadata CSV ({len(metadata_df)} compounds, {len(csv_buffer.getvalue())} bytes)")
            return True

        except Exception as e:
            logger.error(f"Failed to upload metadata CSV: {e}")
            return False

    def download_metadata_csv(self) -> Optional[pd.DataFrame]:
        """
        Download only metadata CSV (fast, ~100KB for 100 compounds).

        Returns:
            DataFrame with metadata or None
        """
        if not self.enabled:
            return None

        try:
            import io

            blob_name = "compounds_metadata.csv"
            blob_client = self.container_client.get_blob_client(blob_name)

            if not blob_client.exists():
                logger.info("No metadata CSV found in Azure")
                return None

            # Download CSV
            csv_bytes = blob_client.download_blob().readall()
            metadata_df = pd.read_csv(io.BytesIO(csv_bytes))

            logger.info(f"✅ Downloaded metadata for {len(metadata_df)} compounds ({len(csv_bytes)} bytes)")
            return metadata_df

        except Exception as e:
            logger.error(f"Failed to download metadata CSV: {e}")
            return None


# Singleton instance
_azure_storage = None

def get_azure_storage() -> AzureStorageManager:
    """Get singleton instance of AzureStorageManager."""
    global _azure_storage
    if _azure_storage is None:
        _azure_storage = AzureStorageManager()
    return _azure_storage
