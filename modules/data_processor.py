"""
Data processing and calculation functions for compound analysis.
"""
import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import numpy as np
from rdkit import Chem
from rdkit.Chem import QED, Descriptors, Crippen
import streamlit as st

from config import RESULTS_DIR, ACTIVITY_TYPES, MAX_WORKERS
from modules.api_client import (
    get_molecule_data, 
    get_classification, 
    get_chembl_ids,
    batch_fetch_activities,
    fetch_compound_activities
)
from modules.utils import validate_compound_name, validate_smiles

# Configure logging
logger = logging.getLogger(__name__)

def extract_properties(smiles: str) -> Tuple[float, float, float]:
    """
    Extract molecular properties from SMILES.
    
    Args:
        smiles: SMILES string
    
    Returns:
        Tuple[float, float, float]: HBD, HBA, heavy atoms
    """
    if smiles == 'N/A':
        return np.nan, np.nan, np.nan
    
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return np.nan, np.nan, np.nan
            
        hbd = Chem.rdMolDescriptors.CalcNumHBD(mol)
        hba = Chem.rdMolDescriptors.CalcNumHBA(mol)
        heavy_atoms = mol.GetNumHeavyAtoms()
        
        return hbd, hba, heavy_atoms
    except Exception as e:
        logger.error(f"Error extracting properties: {str(e)}")
        return np.nan, np.nan, np.nan

def calculate_efficiency_metrics(
    pActivity: float, 
    psa: float, 
    molecular_weight: float, 
    npol: float, 
    heavy_atoms: float
) -> Tuple[float, float, float, float]:
    """
    Calculate efficiency metrics with validation.
    
    Args:
        pActivity: pActivity value
        psa: Polar surface area
        molecular_weight: Molecular weight
        npol: NPOL value
        heavy_atoms: Number of heavy atoms
    
    Returns:
        Tuple[float, float, float, float]: SEI, BEI, NSEI, nBEI
    """
    try:
        sei = pActivity / (psa / 100) if psa and not np.isnan(pActivity) and psa > 0 else np.nan
        bei = pActivity / (molecular_weight / 1000) if molecular_weight and not np.isnan(pActivity) and molecular_weight > 0 else np.nan
        nsei = pActivity / npol if npol and not np.isnan(pActivity) and npol > 0 else np.nan
        nbei = (npol * nsei + np.log10(heavy_atoms)) if npol and nsei and heavy_atoms and not np.isnan(nsei) and heavy_atoms > 0 else np.nan
        
        return sei, bei, nsei, nbei
    except Exception as e:
        logger.error(f"Error calculating efficiency metrics: {str(e)}")
        return np.nan, np.nan, np.nan, np.nan

def extract_classification_data(classification_result: Optional[Dict]) -> Dict[str, str]:
    """
    Extract classification fields with safe access.
    
    Args:
        classification_result: Classification data from API
    
    Returns:
        Dict[str, str]: Extracted classification data
    """
    if classification_result is None:
        return {
            'Kingdom': '',
            'Superclass': '',
            'Class': '',
            'Subclass': ''
        }
    
    try:
        return {
            'Kingdom': classification_result.get('kingdom', {}).get('name', '') if classification_result.get('kingdom') else '',
            'Superclass': classification_result.get('superclass', {}).get('name', '') if classification_result.get('superclass') else '',
            'Class': classification_result.get('class', {}).get('name', '') if classification_result.get('class') else '',
            'Subclass': classification_result.get('subclass', {}).get('name', '') if classification_result.get('subclass') else ''
        }
    except Exception as e:
        logger.error(f"Error extracting classification data: {str(e)}")
        return {
            'Kingdom': '',
            'Superclass': '',
            'Class': '',
            'Subclass': ''
        }

def process_single_compound(
    chembl_id: str, 
    activity_types: List[str] = ACTIVITY_TYPES
) -> List[Dict]:
    """
    Process a single compound with its activities and properties.
    
    Args:
        chembl_id: ChEMBL ID to process
        activity_types: List of activity types to fetch
    
    Returns:
        List[Dict]: List of processed compound data
    """
    try:
        # Get molecule data
        mol_data = get_molecule_data(chembl_id)
        if not mol_data:
            logger.warning(f"No molecule data found for {chembl_id}")
            return []
            
        # Extract properties
        molecular_properties = mol_data.get('molecule_properties', {})
        molecular_weight = float(molecular_properties.get('full_mwt', np.nan))
        psa = float(molecular_properties.get('psa', np.nan))
        
        smiles = mol_data.get('molecule_structures', {}).get('canonical_smiles', 'N/A')
        molecule_name = mol_data.get('pref_name', 'Unknown Name')

        # Extract molecular properties
        hbd, hba, heavy_atoms = extract_properties(smiles)
        npol = hbd + hba if not (np.isnan(hbd) or np.isnan(hba)) else np.nan

        # Generate InChIKey and get classification
        inchi_key = None
        if smiles != 'N/A':
            try:
                mol = Chem.MolFromSmiles(smiles)
                if mol:
                    inchi_key = Chem.MolToInchiKey(mol)
            except Exception as e:
                logger.error(f"Error generating InChIKey for {chembl_id}: {str(e)}")

        # Get classification data
        classification_data = {}
        if inchi_key:
            classification_result = get_classification(inchi_key)
            classification_data = extract_classification_data(classification_result)
        else:
            classification_data = extract_classification_data(None)

        # Fetch activities
        bioactivities = fetch_compound_activities(chembl_id, activity_types)
        
        # Process activities
        results = []
        for act in bioactivities:
            if all(key in act for key in ['standard_value', 'standard_units', 'standard_type']):
                if act['standard_value'] and act['standard_units'] == 'nM':
                    value = float(act['standard_value'])
                    pActivity = -np.log10(value * 1e-9)
                    
                    # Calculate efficiency metrics
                    sei, bei, nsei, nbei = calculate_efficiency_metrics(
                        pActivity, psa, molecular_weight, npol, heavy_atoms
                    )

                    # Calculate QED
                    qed = QED.qed(Chem.MolFromSmiles(smiles)) if smiles != 'N/A' else np.nan

                    results.append({
                        'ChEMBL ID': chembl_id,
                        'Molecule Name': molecule_name,
                        'SMILES': smiles,
                        'Molecular Weight': molecular_weight,
                        'TPSA': psa,
                        'Activity Type': act.get('standard_type', 'Unknown'),
                        'Activity (nM)': value,
                        'pActivity': pActivity,
                        'Target ChEMBL ID': act.get('target_chembl_id', ''),
                        'SEI': sei,
                        'BEI': bei,
                        'QED': qed,
                        'HBD': hbd,
                        'HBA': hba,
                        'Heavy Atoms': heavy_atoms,
                        'NPOL': npol,
                        'NSEI': nsei,
                        'nBEI': nbei,
                        'Kingdom': classification_data.get('Kingdom', ''),
                        'Superclass': classification_data.get('Superclass', ''),
                        'Class': classification_data.get('Class', ''),
                        'Subclass': classification_data.get('Subclass', '')
                    })

        # If no activity data, add basic compound info
        if not results:
            qed = QED.qed(Chem.MolFromSmiles(smiles)) if smiles != 'N/A' else np.nan
            results.append({
                'ChEMBL ID': chembl_id,
                'Molecule Name': molecule_name,
                'SMILES': smiles,
                'Molecular Weight': molecular_weight,
                'TPSA': psa,
                'Activity Type': 'Unknown',
                'Activity (nM)': np.nan,
                'pActivity': np.nan,
                'Target ChEMBL ID': '',
                'SEI': np.nan,
                'BEI': np.nan,
                'QED': qed,
                'HBD': hbd,
                'HBA': hba,
                'Heavy Atoms': heavy_atoms,
                'NPOL': npol,
                'NSEI': np.nan,
                'nBEI': np.nan,
                'Kingdom': classification_data.get('Kingdom', ''),
                'Superclass': classification_data.get('Superclass', ''),
                'Class': classification_data.get('Class', ''),
                'Subclass': classification_data.get('Subclass', '')
            })

        return results

    except Exception as e:
        logger.error(f"Error processing ChEMBL ID {chembl_id}: {str(e)}")
        return []


def process_compounds_parallel(
    chembl_ids_list: List[Dict[str, str]], 
    activity_types: List[str] = ACTIVITY_TYPES,
    max_workers: int = MAX_WORKERS
) -> List[Dict]:
    """
    Process multiple compounds in parallel to improve performance.
    
    Args:
        chembl_ids_list: List of dictionaries containing ChEMBL IDs
        activity_types: List of activity types to fetch
        max_workers: Maximum number of concurrent workers
    
    Returns:
        List[Dict]: Processed compound data
    """
    if not chembl_ids_list:
        return []
    
    all_results = []
    
    # Show progress bar
    progress_msg = st.empty()
    progress_bar = st.progress(0)
    progress_msg.text(f"Processing {len(chembl_ids_list)} compounds...")
    
    # Process compounds one at a time to avoid threading issues
    for i, chembl_id_dict in enumerate(chembl_ids_list):
        try:
            chembl_id = chembl_id_dict['ChEMBL ID']
            compound_results = process_single_compound(chembl_id, activity_types)
            all_results.extend(compound_results)
            
            # Update progress
            progress = (i + 1) / len(chembl_ids_list)
            progress_bar.progress(progress)
            progress_msg.text(f"Processed {i + 1}/{len(chembl_ids_list)} compounds ({int(progress * 100)}%)")
        except Exception as e:
            logger.error(f"Error processing compound {i}: {str(e)}")
    
    progress_msg.text(f"Completed! Processed {len(chembl_ids_list)} compounds.")
    return all_results
def process_compound(
    compound_name: str,
    smiles: str,
    similarity_threshold: int = 80,
    activity_types: List[str] = ACTIVITY_TYPES
) -> Optional[pd.DataFrame]:
    """
    Process a single compound with improved error handling and progress tracking.
    
    Args:
        compound_name: Name of the compound
        smiles: SMILES string
        similarity_threshold: Similarity threshold for search
        activity_types: List of activity types to process
    
    Returns:
        Optional[pd.DataFrame]: Results dataframe or None if error
    """
    try:
        # Update session state for tracking
        if 'processing_compound' in st.session_state:
            st.session_state.processing_compound = compound_name
        if 'processing_progress' in st.session_state:
            st.session_state.processing_progress = 0
        
        # Validate inputs
        if not validate_compound_name(compound_name):
            raise ValueError("Invalid compound name")
        if not validate_smiles(smiles):
            raise ValueError("Invalid SMILES string")
        if not activity_types:
            raise ValueError("No activity types selected")
        
        compound_folder = os.path.join(RESULTS_DIR, compound_name.replace(' ', '_'))
        
        # Create directory structure
        for folder in [compound_folder,
                      os.path.join(compound_folder, "SEI"),
                      os.path.join(compound_folder, "BEI"),
                      os.path.join(compound_folder, "Activity"),
                      os.path.join(compound_folder, "Structures")]:
            os.makedirs(folder, exist_ok=True)
            logger.info(f"Created directory: {folder}")
        
        # Fetch ChEMBL IDs
        with st.spinner("Searching for similar compounds..."):
            chembl_ids = get_chembl_ids(smiles, similarity_threshold)
            
            if not chembl_ids:
                st.warning("No similar compounds found")
                # Reset processing state
                if 'processing_compound' in st.session_state:
                    st.session_state.processing_compound = None
                return None
            
            # Save ChEMBL IDs
            chembl_ids_df = pd.DataFrame(chembl_ids)
            chembl_ids_filename = os.path.join(compound_folder,
                                             f"{compound_name}_chembl_ids.csv")
            chembl_ids_df.to_csv(chembl_ids_filename, index=False)
            
            # Update progress
            if 'processing_progress' in st.session_state:
                st.session_state.processing_progress = 0.2
        
        # Process compounds with progress tracking
        with st.spinner(f"Processing compounds with activity types: {', '.join(activity_types)}..."):
            st.info(f"Selected activity types: {', '.join(activity_types)}")
            
            # Process compounds in parallel for better performance
            all_results = process_compounds_parallel(chembl_ids, activity_types)
            
            # Update progress
            if 'processing_progress' in st.session_state:
                st.session_state.processing_progress = 0.7
        
        # Create and save results DataFrame
        df_results = pd.DataFrame(all_results)
        df_results.replace("No data", np.nan, inplace=True)
        
        # Save metadata
        metadata = {
            'compound_name': compound_name,
            'similarity_threshold': similarity_threshold,
            'activity_types': ','.join(activity_types),
            'processing_date': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Create a metadata file to store processing parameters
        metadata_filename = os.path.join(compound_folder, f"{compound_name}_metadata.json")
        with open(metadata_filename, 'w') as f:
            json.dump(metadata, f, indent=4)
        
        # Save complete results
        results_filename = os.path.join(compound_folder,
                                      f"{compound_name}_complete_results.csv")
        df_results.to_csv(results_filename, index=False)
        
        # Update progress
        if 'processing_progress' in st.session_state:
            st.session_state.processing_progress = 0.9
        
        # EXPLICIT PLOT GENERATION - Added to ensure plots are generated
        with st.spinner("Generating visualizations..."):
            try:
                # Import visualization module here to avoid circular imports
                from modules.visualization import plot_all_visualizations
                logger.info(f"Starting plot generation for {compound_name}")
                plot_all_visualizations(df_results, compound_folder)
                logger.info(f"Plot generation completed for {compound_name}")
                st.success("Visualizations generated successfully")
            except Exception as e:
                logger.error(f"Error generating plots: {str(e)}")
                st.warning(f"Error generating plots: {str(e)}")
        
        # Update progress
        if 'processing_progress' in st.session_state:
            st.session_state.processing_progress = 1.0
        
        # Set flags for notification if they exist in session state
        if 'last_processed_compound' in st.session_state:
            st.session_state.last_processed_compound = compound_name
        if 'show_new_compound_alert' in st.session_state:
            st.session_state.show_new_compound_alert = True
        
        # Reset processing state
        if 'processing_compound' in st.session_state:
            st.session_state.processing_compound = None
        if 'processing_progress' in st.session_state:
            st.session_state.processing_progress = 0
        
        return df_results
    
    except Exception as e:
        logger.error(f"Error processing compound {compound_name}: {str(e)}")
        st.error(f"Error processing compound: {str(e)}")
        
        # Reset processing state on error
        if 'processing_compound' in st.session_state:
            st.session_state.processing_compound = None
        if 'processing_progress' in st.session_state:
            st.session_state.processing_progress = 0
        
        return None
def load_results(compound_name: str) -> Optional[pd.DataFrame]:
    """
    Load CSV results for the selected compound with error handling.
    
    Args:
        compound_name: Name of the compound
    
    Returns:
        Optional[pd.DataFrame]: Results dataframe or None if error
    """
    try:
        compound_name = compound_name.replace(" ", "_")
        file_path = os.path.join(RESULTS_DIR, compound_name, 
                                f"{compound_name}_complete_results.csv")
        
        if not os.path.exists(file_path):
            st.warning(f"⚠️ No results found for {compound_name}. CSV file is missing.")
            return None
        
        df = pd.read_csv(file_path)
        if df.empty:
            st.warning(f"⚠️ The results file for {compound_name} is empty.")
            return None
        
        return df
    
    except Exception as e:
        logger.error(f"Error loading results for {compound_name}: {str(e)}")
        st.error(f"Error loading results: {str(e)}")
        return None