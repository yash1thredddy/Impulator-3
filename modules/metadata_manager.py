"""
Lightweight metadata management for compound listing.
Enables fast home page by downloading only metadata CSV instead of all compound ZIPs.
"""

import os
import pandas as pd
import logging
import streamlit as st
from typing import Dict, Optional
from datetime import datetime
from config import RESULTS_DIR

logger = logging.getLogger(__name__)


def extract_compound_metadata(compound_name: str, results_folder: str) -> Dict:
    """
    Extract lightweight metadata from a processed compound.

    Args:
        compound_name: Name of the compound
        results_folder: Path to compound's results folder

    Returns:
        Dict containing: name, date, counts, chembl_id, smiles, qed, outliers, similarity_threshold
    """
    import json

    metadata = {
        'compound_name': compound_name,
        'processed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_activities': 0,
        'num_outliers': 0,
        'qed': 0.0,
        'similarity_threshold': 90,
        'chembl_id': '',
        'smiles': ''
    }

    try:
        # Read metadata JSON file first (has similarity_threshold and outlier_summary)
        metadata_json_path = os.path.join(results_folder, f"{compound_name}_metadata.json")
        if os.path.exists(metadata_json_path):
            with open(metadata_json_path, 'r') as f:
                json_metadata = json.load(f)
                metadata['similarity_threshold'] = json_metadata.get('similarity_threshold', 90)

                # Get number of outliers from outlier_summary
                outlier_summary = json_metadata.get('outlier_summary', {})
                metadata['num_outliers'] = outlier_summary.get('efficiency_outliers', 0)

        # Read complete results CSV
        csv_path = os.path.join(results_folder, f"{compound_name}_complete_results.csv")

        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            metadata['total_activities'] = len(df)

            # Get ChEMBL ID, SMILES, and QED from first row
            if not df.empty:
                if 'ChEMBL_ID' in df.columns:
                    metadata['chembl_id'] = str(df['ChEMBL_ID'].iloc[0])
                if 'SMILES' in df.columns:
                    metadata['smiles'] = str(df['SMILES'].iloc[0])
                if 'QED' in df.columns:
                    qed_value = df['QED'].iloc[0]
                    # Handle NaN values
                    if pd.notna(qed_value):
                        metadata['qed'] = float(qed_value)

        logger.info(f"Extracted metadata for {compound_name}: {metadata['num_outliers']} outliers, QED={metadata['qed']:.2f}")

    except Exception as e:
        logger.error(f"Error extracting metadata for {compound_name}: {e}")

    return metadata


def save_metadata_to_azure(metadata: Dict) -> bool:
    """
    Append or update compound metadata in Azure metadata CSV.

    Args:
        metadata: Dict containing compound metadata

    Returns:
        bool: True if successful
    """
    try:
        from modules.azure_storage import get_azure_storage

        azure = get_azure_storage()
        if not azure.enabled:
            logger.info("Azure disabled, skipping metadata save")
            return False

        # Download existing metadata
        existing_df = azure.download_metadata_csv()

        # Create new row
        new_row = pd.DataFrame([metadata])

        if existing_df is not None and not existing_df.empty:
            # Remove old entry if exists (update case)
            existing_df = existing_df[existing_df['compound_name'] != metadata['compound_name']]
            # Append new row
            updated_df = pd.concat([existing_df, new_row], ignore_index=True)
        else:
            updated_df = new_row

        # Upload updated metadata
        success = azure.upload_metadata_csv(updated_df)

        if success:
            logger.info(f"✅ Saved metadata for {metadata['compound_name']} to Azure")

        return success

    except Exception as e:
        logger.error(f"Error saving metadata to Azure: {e}")
        return False


@st.cache_data(ttl=300)
def get_all_compounds_metadata() -> Optional[pd.DataFrame]:
    """
    Get metadata for all compounds (from Azure or local).
    Cached for 5 minutes to reduce Azure API calls.

    Returns:
        DataFrame with compound metadata or None
    """
    try:
        from modules.azure_storage import get_azure_storage

        azure = get_azure_storage()

        if azure.enabled:
            # Download lightweight metadata CSV (~100KB for 100 compounds)
            logger.info("Downloading metadata from Azure...")
            metadata_df = azure.download_metadata_csv()

            if metadata_df is not None:
                logger.info(f"✅ Loaded metadata for {len(metadata_df)} compounds from Azure")
                return metadata_df

        # Fallback to local metadata
        logger.info("Loading metadata from local storage...")
        return load_local_metadata()

    except Exception as e:
        logger.error(f"Error getting compounds metadata: {e}")
        return None


def save_metadata_to_local(metadata: Dict) -> bool:
    """
    Append or update compound metadata in local metadata CSV.

    Args:
        metadata: Dict containing compound metadata

    Returns:
        bool: True if successful
    """
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        metadata_csv_path = os.path.join(RESULTS_DIR, 'compounds_metadata.csv')

        # Load existing metadata
        if os.path.exists(metadata_csv_path):
            existing_df = pd.read_csv(metadata_csv_path)
            # Remove old entry if exists (update case)
            existing_df = existing_df[existing_df['compound_name'] != metadata['compound_name']]
        else:
            existing_df = pd.DataFrame()

        # Create new row
        new_row = pd.DataFrame([metadata])

        # Append new row
        if not existing_df.empty:
            updated_df = pd.concat([existing_df, new_row], ignore_index=True)
        else:
            updated_df = new_row

        # Save to CSV
        updated_df.to_csv(metadata_csv_path, index=False)
        logger.info(f"✅ Saved metadata for {metadata['compound_name']} to local CSV")
        return True

    except Exception as e:
        logger.error(f"Error saving metadata to local CSV: {e}")
        return False


def delete_metadata_from_azure(compound_name: str) -> bool:
    """
    Delete compound metadata entry from Azure metadata CSV.

    Args:
        compound_name: Name of the compound to delete

    Returns:
        bool: True if successful
    """
    try:
        from modules.azure_storage import get_azure_storage

        azure = get_azure_storage()
        if not azure.enabled:
            logger.info("Azure disabled, skipping metadata delete")
            return False

        # Download existing metadata
        existing_df = azure.download_metadata_csv()

        if existing_df is None or existing_df.empty:
            logger.info("No metadata found in Azure")
            return True

        # Remove the compound's entry
        updated_df = existing_df[existing_df['compound_name'] != compound_name]

        # Upload updated metadata
        success = azure.upload_metadata_csv(updated_df)

        if success:
            logger.info(f"✅ Deleted metadata for {compound_name} from Azure")

        return success

    except Exception as e:
        logger.error(f"Error deleting metadata from Azure: {e}")
        return False


def delete_metadata_from_local(compound_name: str) -> bool:
    """
    Delete compound metadata entry from local metadata CSV.

    Args:
        compound_name: Name of the compound to delete

    Returns:
        bool: True if successful
    """
    try:
        metadata_csv_path = os.path.join(RESULTS_DIR, 'compounds_metadata.csv')

        if not os.path.exists(metadata_csv_path):
            logger.info("No local metadata CSV found")
            return True

        # Load existing metadata
        existing_df = pd.read_csv(metadata_csv_path)

        # Remove the compound's entry
        updated_df = existing_df[existing_df['compound_name'] != compound_name]

        # Save updated CSV
        updated_df.to_csv(metadata_csv_path, index=False)
        logger.info(f"✅ Deleted metadata for {compound_name} from local CSV")
        return True

    except Exception as e:
        logger.error(f"Error deleting metadata from local CSV: {e}")
        return False


def load_local_metadata() -> Optional[pd.DataFrame]:
    """Load metadata from local CSV file or scan folders."""
    try:
        if not os.path.exists(RESULTS_DIR):
            return None

        metadata_csv_path = os.path.join(RESULTS_DIR, 'compounds_metadata.csv')

        # Try to load from CSV first (fast)
        if os.path.exists(metadata_csv_path):
            try:
                # Try UTF-8 first, then fallback to other encodings
                try:
                    metadata_df = pd.read_csv(metadata_csv_path, encoding='utf-8')
                except UnicodeDecodeError:
                    # Try with latin1 encoding as fallback
                    try:
                        metadata_df = pd.read_csv(metadata_csv_path, encoding='latin1')
                    except:
                        # Try with cp1252 (Windows encoding)
                        metadata_df = pd.read_csv(metadata_csv_path, encoding='cp1252')

                logger.info(f"✅ Loaded metadata for {len(metadata_df)} compounds from local CSV")
                return metadata_df
            except Exception as e:
                logger.warning(f"Failed to load local metadata CSV: {e}, deleting corrupt file and rebuilding...")
                # Delete corrupt CSV and rebuild
                try:
                    os.remove(metadata_csv_path)
                    logger.info("Deleted corrupt metadata CSV")
                except:
                    pass

        # Fallback: scan folders (slower but rebuilds metadata)
        metadata_list = []

        for compound_name in os.listdir(RESULTS_DIR):
            compound_folder = os.path.join(RESULTS_DIR, compound_name)

            if os.path.isdir(compound_folder):
                metadata = extract_compound_metadata(compound_name, compound_folder)
                metadata_list.append(metadata)

        if metadata_list:
            metadata_df = pd.DataFrame(metadata_list)
            # Save to CSV for next time
            metadata_df.to_csv(metadata_csv_path, index=False)
            logger.info(f"✅ Rebuilt local metadata CSV with {len(metadata_df)} compounds")
            return metadata_df

        return None

    except Exception as e:
        logger.error(f"Error loading local metadata: {e}")
        return None
