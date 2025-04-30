"""
Utility functions for validation and helper operations.
"""
import os
import logging
import zipfile
import time
from typing import List, Dict, Optional, Union, Any
from typing import List, Dict, Optional, Tuple, Any, Union
import pandas as pd
import numpy as np
from rdkit import Chem
import streamlit as st

from config import RESULTS_DIR, MAX_CSV_SIZE_MB

# Configure logging
logger = logging.getLogger(__name__)

def validate_smiles(smiles: str) -> bool:
    """
    Validate SMILES string using RDKit.
    
    Args:
        smiles: SMILES string to validate
    
    Returns:
        bool: True if valid, False otherwise
    """
    if not isinstance(smiles, str):
        return False
    
    try:
        mol = Chem.MolFromSmiles(smiles)
        return mol is not None
    except:
        return False

def validate_compound_name(name: str) -> bool:
    """
    Validate compound name.
    
    Args:
        name: Compound name to validate
    
    Returns:
        bool: True if valid, False otherwise
    """
    if not isinstance(name, str):
        return False
    
    # Check length
    if len(name) < 1 or len(name) > 100:
        return False
    
    # Check for invalid characters
    invalid_chars = '<>:"/\\|?*'
    if any(char in name for char in invalid_chars):
        return False
    
    return True

def validate_csv_file(uploaded_file) -> Tuple[bool, Optional[pd.DataFrame]]:
    """
    Validate uploaded CSV file.
    
    Args:
        uploaded_file: Uploaded file object
    
    Returns:
        Tuple[bool, Optional[pd.DataFrame]]: Validation result and DataFrame if valid
    """
    try:
        # Reset file pointer
        uploaded_file.seek(0)
        
        # Check file size
        file_size_mb = uploaded_file.size / (1024 * 1024)
        if file_size_mb > MAX_CSV_SIZE_MB:
            st.error(f"File size exceeds maximum limit of {MAX_CSV_SIZE_MB}MB")
            return False, None

        # Try reading the CSV
        df = pd.read_csv(uploaded_file)
        
        # Show available columns
        st.write("Available columns:", list(df.columns))
        
        # Check required data is present
        if not any(col in df.columns for col in ['compound_name', 'compound']):
            st.error("CSV must contain either 'compound_name' or 'compound' column")
            return False, None
            
        if 'smiles' not in df.columns:
            st.error("CSV must contain 'smiles' column")
            return False, None

        # If we have 'compound' but not 'compound_name', use 'compound'
        if 'compound' in df.columns and 'compound_name' not in df.columns:
            df['compound_name'] = df['compound']

        # Validate data
        invalid_names = []
        invalid_smiles = []
        for idx, row in df.iterrows():
            compound_name = row.get('compound_name', row.get('compound', ''))
            if not validate_compound_name(str(compound_name).strip()):
                invalid_names.append(compound_name)
            if not validate_smiles(str(row['smiles']).strip()):
                invalid_smiles.append(idx + 1)
        
        if invalid_names:
            st.error(f"Invalid compound names found: {', '.join(map(str, invalid_names[:5]))}")
            return False, None
        if invalid_smiles:
            st.error(f"Invalid SMILES strings found in rows: {invalid_smiles[:5]}")
            return False, None
        
        return True, df
    
    except Exception as e:
        st.error(f"Error validating CSV file: {str(e)}")
        logger.error(f"Error validating CSV file: {str(e)}")
        return False, None

def get_available_compounds() -> List[str]:
    """
    Get list of available processed compounds.
    
    Returns:
        List[str]: List of compound names
    """
    try:
        if not os.path.exists(RESULTS_DIR):
            return []
            
        compounds = sorted([d for d in os.listdir(RESULTS_DIR) 
                          if os.path.isdir(os.path.join(RESULTS_DIR, d))])
        logger.info(f"Found compounds: {compounds}")
        return compounds
    except Exception as e:
        logger.error(f"Error getting available compounds: {str(e)}")
        return []

def zip_results() -> Optional[str]:
    """
    Create a zip file of all results with progress tracking.
    
    Returns:
        Optional[str]: Path to zip file or None if error
    """
    try:
        zip_filename = "processed_results.zip"
        compounds = get_available_compounds()
        
        if not compounds:
            st.warning("No results available to download.")
            return None
        
        with st.spinner("Creating ZIP file..."):
            progress_bar = st.progress(0)
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for idx, compound in enumerate(compounds):
                    compound_folder = os.path.join(RESULTS_DIR, compound)
                    for root, _, files in os.walk(compound_folder):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path, 
                                     os.path.relpath(file_path, RESULTS_DIR))
                    progress_bar.progress((idx + 1) / len(compounds))
            
            return zip_filename if os.path.exists(zip_filename) else None
    
    except Exception as e:
        logger.error(f"Error creating ZIP file: {str(e)}")
        st.error(f"Error creating download file: {str(e)}")
        return None
    
def zip_compound_results(compound_name: str) -> Optional[str]:
    """
    Create a zip file for a specific compound's results.
    
    Args:
        compound_name: Name of the compound to zip
    
    Returns:
        Optional[str]: Path to zip file or None if error
    """
    try:
        zip_filename = f"{compound_name}_results.zip"
        compound_folder = os.path.join(RESULTS_DIR, compound_name)
        
        if not os.path.exists(compound_folder):
            st.warning(f"No results available for {compound_name}.")
            return None
        
        with st.spinner(f"Creating ZIP file for {compound_name}..."):
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(compound_folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zipf.write(file_path, 
                                os.path.relpath(file_path, RESULTS_DIR))
            
            return zip_filename if os.path.exists(zip_filename) else None
    
    except Exception as e:
        logger.error(f"Error creating ZIP file for {compound_name}: {str(e)}")
        st.error(f"Error creating download file: {str(e)}")
        return None

def format_smiles_for_display(smiles: str, max_length: int = 40) -> str:
    """
    Format SMILES string for display by truncating if necessary.
    
    Args:
        smiles: SMILES string
        max_length: Maximum displayed length
        
    Returns:
        str: Formatted SMILES string
    """
    if not smiles or smiles == 'N/A':
        return 'N/A'
    
    if len(smiles) > max_length:
        return f"{smiles[:max_length]}..."
    
    return smiles