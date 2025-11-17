"""
Data Processing and Calculation Functions for Compound Analysis - REFACTORED v2.0

This is the refactored version that uses the new modular architecture:
- efficiency_metrics.py: Calculate SEI, BEI, NSEI, NBEI
- efficiency_planes.py: Calculate plane geometry
- outlier_detection.py: Detect statistical outliers
- oqpla_scoring.py: Calculate O[Q/P/L]A scores
- imp_classifier.py: Classify IMPs

Changes from v1:
- Cleaner separation of concerns
- Uses dedicated modules for calculations
- Adds complete IMPs 2.0 pipeline
- Includes O[Q/P/L]A scoring and IMP classification
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np
from rdkit import Chem
from rdkit.Chem import QED, Descriptors
import streamlit as st

from config import RESULTS_DIR, ACTIVITY_TYPES, MAX_WORKERS
from modules.api_client import (
    get_molecule_data,
    get_classification,
    get_chembl_ids,
    fetch_compound_activities
)
from modules.utils import validate_compound_name, validate_smiles

# Import new modular components
from modules.efficiency_metrics import calculate_all_efficiency_metrics
from modules.efficiency_planes import calculate_all_plane_metrics
from modules.outlier_detection import (
    detect_efficiency_outliers,
    calculate_cohort_statistics,
    get_outlier_summary
)
from modules.oqpla_scoring import (
    calculate_oqpla_phase1,
    add_oqpla_interpretation,
    get_oqpla_summary
)
from modules.imp_classifier import (
    classify_imp_candidates,
    get_imp_summary,
    generate_imp_report
)

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

    This is the core function that fetches data and calculates basic metrics.
    Advanced metrics (planes, outliers, O[Q/P/L]A) are calculated later in the pipeline.

    Args:
        chembl_id: ChEMBL ID to process
        activity_types: List of activity types to fetch

    Returns:
        List[Dict]: List of processed compound data (one row per bioactivity)
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

                    # Calculate efficiency metrics using new module
                    efficiency_metrics = calculate_all_efficiency_metrics(
                        pActivity=pActivity,
                        psa=psa,
                        molecular_weight=molecular_weight,
                        npol=npol,
                        heavy_atoms=heavy_atoms
                    )

                    # Calculate QED (guard against invalid molecules)
                    mol_for_qed = Chem.MolFromSmiles(smiles) if smiles != 'N/A' else None
                    qed = QED.qed(mol_for_qed) if mol_for_qed is not None else np.nan

                    # Build result dictionary
                    result_dict = {
                        'ChEMBL_ID': chembl_id,
                        'Molecule_Name': molecule_name,
                        'SMILES': smiles,
                        'Molecular_Weight': molecular_weight,
                        'TPSA': psa,
                        'Activity_Type': act.get('standard_type', 'Unknown'),
                        'Activity_nM': value,
                        'pActivity': pActivity,
                        'Target_ChEMBL_ID': act.get('target_chembl_id', ''),
                        'QED': qed,
                        'HBD': hbd,
                        'HBA': hba,
                        'Heavy_Atoms': heavy_atoms,
                        'NPOL': npol,
                        # Add efficiency metrics
                        'SEI': efficiency_metrics['SEI'],
                        'BEI': efficiency_metrics['BEI'],
                        'NSEI': efficiency_metrics['NSEI'],
                        'NBEI': efficiency_metrics['NBEI'],  # CORRECTED FORMULA
                        'nBEI_viz': efficiency_metrics['nBEI_viz'],  # For visualization only
                        # Add classification
                        'Kingdom': classification_data.get('Kingdom', ''),
                        'Superclass': classification_data.get('Superclass', ''),
                        'Class': classification_data.get('Class', ''),
                        'Subclass': classification_data.get('Subclass', '')
                    }

                    results.append(result_dict)

        # If no activity data, add basic compound info
        if not results:
            mol_for_qed = Chem.MolFromSmiles(smiles) if smiles != 'N/A' else None
            qed = QED.qed(mol_for_qed) if mol_for_qed is not None else np.nan
            results.append({
                'ChEMBL_ID': chembl_id,
                'Molecule_Name': molecule_name,
                'SMILES': smiles,
                'Molecular_Weight': molecular_weight,
                'TPSA': psa,
                'Activity_Type': 'Unknown',
                'Activity_nM': np.nan,
                'pActivity': np.nan,
                'Target_ChEMBL_ID': '',
                'QED': qed,
                'HBD': hbd,
                'HBA': hba,
                'Heavy_Atoms': heavy_atoms,
                'NPOL': npol,
                'SEI': np.nan,
                'BEI': np.nan,
                'NSEI': np.nan,
                'NBEI': np.nan,
                'nBEI_viz': np.nan,
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
    Process multiple compounds sequentially with progress tracking.

    Args:
        chembl_ids_list: List of dictionaries containing ChEMBL IDs
        activity_types: List of activity types to fetch
        max_workers: Maximum number of concurrent workers (reserved for future use)

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

    # Process compounds one at a time
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


def calculate_advanced_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate advanced metrics using the new modular pipeline.

    Pipeline:
    1. Efficiency plane geometry (modulus, angle, slope)
    2. Outlier detection (IQR method)
    3. O[Q/P/L]A scoring (Phase 1: Components 1-3)
    4. IMP classification

    Args:
        df: DataFrame with basic efficiency metrics

    Returns:
        pd.DataFrame: DataFrame with all advanced metrics added
    """
    logger.info("Starting advanced metrics calculation pipeline...")

    # STEP 1: Calculate efficiency plane geometry
    logger.info("Calculating efficiency plane geometry...")
    for idx, row in df.iterrows():
        plane_metrics = calculate_all_plane_metrics(
            sei=float(row['SEI']),
            bei=float(row['BEI']),
            nsei=float(row['NSEI']),
            nbei=float(row['NBEI']),
            psa=float(row['TPSA']),
            molecular_weight=float(row['Molecular_Weight']),
            npol=float(row['NPOL']),
            heavy_atoms=float(row['Heavy_Atoms'])
        )
        # Add metrics to row
        for key, value in plane_metrics.items():
            if key not in df.columns:
                df[key] = np.nan
            df.at[idx, key] = value

    # STEP 2: Detect outliers
    logger.info("Detecting statistical outliers...")
    df = detect_efficiency_outliers(df, metrics=['SEI', 'BEI', 'NSEI', 'NBEI'])

    # STEP 3: Calculate O[Q/P/L]A scores
    logger.info("Calculating O[Q/P/L]A scores...")
    df = calculate_oqpla_phase1(df, use_normalized_weights=True)
    df = add_oqpla_interpretation(df)

    # STEP 4: Classify IMPs
    logger.info("Classifying IMP candidates...")
    df = classify_imp_candidates(df, min_outlier_count=2, use_oqpla=True)

    logger.info("Advanced metrics calculation complete!")
    return df


def process_compound(
    compound_name: str,
    smiles: str,
    similarity_threshold: int = 80,
    activity_types: List[str] = ACTIVITY_TYPES
) -> Optional[pd.DataFrame]:
    """
    Complete compound processing pipeline with IMPs 2.0 analysis.

    Pipeline:
    1. Validate inputs
    2. Search for similar compounds
    3. Fetch bioactivity data
    4. Calculate basic efficiency metrics
    5. Calculate advanced metrics (planes, outliers, O[Q/P/L]A, IMP classification)
    6. Save results and metadata
    7. Generate reports

    Args:
        compound_name: Name of the compound
        smiles: SMILES string
        similarity_threshold: Similarity threshold for search
        activity_types: List of activity types to process

    Returns:
        Optional[pd.DataFrame]: Complete results dataframe or None if error
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

        # Create directory structure (simplified - no plot subfolders)
        os.makedirs(compound_folder, exist_ok=True)
        logger.info(f"Created directory: {compound_folder}")

        # STEP 1: Fetch ChEMBL IDs
        with st.spinner("Searching for similar compounds..."):
            chembl_ids = get_chembl_ids(smiles, similarity_threshold)

            if not chembl_ids:
                st.warning("No similar compounds found")
                if 'processing_compound' in st.session_state:
                    st.session_state.processing_compound = None
                return None

            # Save ChEMBL IDs
            chembl_ids_df = pd.DataFrame(chembl_ids)
            chembl_ids_filename = os.path.join(compound_folder, f"{compound_name}_chembl_ids.csv")
            chembl_ids_df.to_csv(chembl_ids_filename, index=False)

            if 'processing_progress' in st.session_state:
                st.session_state.processing_progress = 0.2

        # STEP 2: Process compounds
        with st.spinner(f"Processing compounds with activity types: {', '.join(activity_types)}..."):
            st.info(f"Selected activity types: {', '.join(activity_types)}")
            all_results = process_compounds_parallel(chembl_ids, activity_types)

            if 'processing_progress' in st.session_state:
                st.session_state.processing_progress = 0.5

        # STEP 3: Create DataFrame
        df_results = pd.DataFrame(all_results)
        df_results.replace("No data", np.nan, inplace=True)

        if df_results.empty:
            st.warning("No bioactivity data found")
            return None

        # STEP 4: Calculate advanced metrics (planes, outliers, O[Q/P/L]A, IMP classification)
        with st.spinner("Calculating advanced metrics (efficiency planes, outliers, O[Q/P/L]A scores)..."):
            df_results = calculate_advanced_metrics(df_results)

            if 'processing_progress' in st.session_state:
                st.session_state.processing_progress = 0.8

        # STEP 5: Save results
        results_filename = os.path.join(compound_folder, f"{compound_name}_complete_results.csv")
        df_results.to_csv(results_filename, index=False)
        logger.info(f"Saved complete results to {results_filename}")

        # STEP 6: Save metadata with statistics
        cohort_stats = calculate_cohort_statistics(df_results)
        outlier_summary = get_outlier_summary(df_results)
        oqpla_summary = get_oqpla_summary(df_results)
        imp_summary = get_imp_summary(df_results)

        metadata = {
            'compound_name': compound_name,
            'query_smiles': smiles,
            'similarity_threshold': similarity_threshold,
            'activity_types': ','.join(activity_types),
            'processing_date': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_similar_compounds': len(chembl_ids),
            'total_bioactivity_rows': len(df_results),
            'cohort_statistics': cohort_stats,
            'outlier_summary': outlier_summary,
            'oqpla_summary': oqpla_summary,
            'imp_summary': imp_summary
        }

        metadata_filename = os.path.join(compound_folder, f"{compound_name}_metadata.json")
        with open(metadata_filename, 'w') as f:
            json.dump(metadata, f, indent=4)
        logger.info(f"Saved metadata to {metadata_filename}")

        # STEP 7: Generate IMP report
        report = generate_imp_report(df_results, compound_name)
        report_filename = os.path.join(compound_folder, f"{compound_name}_imp_report.txt")
        with open(report_filename, 'w') as f:
            f.write(report)
        logger.info(f"Saved IMP report to {report_filename}")

        # Display summary
        st.success(f"✅ Processing complete!")
        st.info(f"📊 Found {imp_summary['total_imp_candidates']} IMP candidates out of {imp_summary['total_compounds']} compounds")

        if imp_summary['total_imp_candidates'] > 0:
            st.info(f"🎯 High confidence: {imp_summary.get('high_confidence', 0)} | "
                   f"Medium: {imp_summary.get('medium_confidence', 0)} | "
                   f"Low: {imp_summary.get('low_confidence', 0)}")

        if 'processing_progress' in st.session_state:
            st.session_state.processing_progress = 1.0

        # Set flags for notification
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
