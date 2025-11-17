"""
Compound management module for handling storage, retrieval, and processing.
"""
import os
import json
import shutil
import logging
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import seaborn as sns
# Add these import statements near the top of compound_manager.py, with the other imports
import plotly.express as px
import plotly.graph_objects as go
from config import RESULTS_DIR, ACTIVITY_TYPES
from modules.data_processor import process_compound, load_results
from modules.utils import validate_compound_name, validate_smiles, validate_inchi, inchi_to_smiles, sanitize_compound_name

# Configure logging
logger = logging.getLogger(__name__)

def check_existing_compound(
    compound_name: str, 
    smiles: str, 
    similarity_threshold: int, 
    activity_types: List[str] = ACTIVITY_TYPES
) -> Optional[str]:
    """
    Check if the compound already exists and prompt the user for action.
    
    Args:
        compound_name: Name of the compound
        smiles: SMILES string
        similarity_threshold: Similarity threshold
        activity_types: List of activity types to process
    
    Returns:
        Optional[str]: Validated compound name or None if operation cancelled
    """
    compound_folder = os.path.join(RESULTS_DIR, compound_name.replace(' ', '_'))

    if os.path.exists(compound_folder):
        st.warning(f"⚠️ Compound **'{compound_name}'** already exists!")

        # Initialize session state variables if not set
        if "compound_action" not in st.session_state:
            st.session_state.compound_action = None
        if "new_compound_name" not in st.session_state:
            st.session_state.new_compound_name = ""
        if "confirm_choice" not in st.session_state:
            st.session_state.confirm_choice = False
        if "processing_triggered" not in st.session_state:
            st.session_state.processing_triggered = False

        # Create a form to prevent immediate updates
        with st.form("compound_confirmation_form", clear_on_submit=False):
            action = st.radio(
                "**What would you like to do?**",
                ["❌ Replace existing compound", "✏️ Enter a new compound name"],
                index=None,
                key="compound_action_radio"
            )

            # If "Enter a new compound name" is selected, show input box
            if action == "✏️ Enter a new compound name":
                new_name = st.text_input("Enter a new compound name:", key="new_name_input")
                st.session_state.new_compound_name = new_name  

            # Submit button for confirmation
            confirm = st.form_submit_button("✅ Confirm Selection")

            if confirm:
                if action:
                    st.session_state.compound_action = action
                    st.session_state.confirm_choice = True  
                    st.session_state.processing_triggered = False  
                    st.success("✔ Selection confirmed. Processing will proceed.")
                    st.experimental_rerun()  
                else:
                    st.error("Please select an option before confirming.")

        # Proceed with processing only after confirmation
        if st.session_state.confirm_choice and not st.session_state.processing_triggered:
            st.session_state.processing_triggered = True  

            if st.session_state.compound_action == "✏️ Enter a new compound name":
                new_compound_name = st.session_state.new_compound_name
                if new_compound_name:
                    if validate_compound_name(new_compound_name):
                        st.success(f"✔ Processing with new name: **'{new_compound_name}'**")
                        return new_compound_name
                    else:
                        st.error("Invalid compound name. Please use alphanumeric characters.")
                        return None
                else:
                    st.error("Please enter a new compound name before confirming.")
                    return None

            elif st.session_state.compound_action == "❌ Replace existing compound":
                shutil.rmtree(compound_folder)  
                st.success(f"✅ Replacing compound **'{compound_name}'** with new parameters.")
                return compound_name

        return None

    return compound_name  # If compound doesn't exist, return the original name

def process_and_store(
    compound_name: str,
    structure_input: str = None,
    input_format: str = "smiles",
    smiles: str = None,  # Keep for backward compatibility
    similarity_threshold: int = 90,
    activity_types: List[str] = ACTIVITY_TYPES
) -> bool:
    """
    Process a compound and store results with improved validation.
    Supports both SMILES and InChI input formats.
    
    Args:
        compound_name: Name of the compound
        structure_input: Chemical structure input (SMILES or InChI)
        input_format: Format of structure_input ("smiles" or "inchi")
        smiles: SMILES string (for backward compatibility)
        similarity_threshold: Similarity threshold for search
        activity_types: List of activity types to process
    
    Returns:
        bool: True if processing successful, False otherwise
    """
    try:
        # Handle backward compatibility - if smiles is provided, use it
        if smiles is not None and structure_input is None:
            structure_input = smiles
            input_format = "smiles"
        
        # Validate inputs
        if not validate_compound_name(compound_name):
            st.error("Invalid compound name. Please use alphanumeric characters and avoid special characters.")
            return False
        
        if not structure_input:
            st.error("No chemical structure provided.")
            return False
        
        # Handle different input formats and convert to SMILES if needed
        final_smiles = None
        if input_format.lower() == "smiles":
            from modules.utils import validate_smiles
            if not validate_smiles(structure_input):
                st.error("Invalid SMILES string. Please check the input format.")
                return False
            final_smiles = structure_input
        elif input_format.lower() == "inchi":
            from modules.utils import validate_inchi, inchi_to_smiles
            if not validate_inchi(structure_input):
                st.error("Invalid InChI string. Please check the input format.")
                return False
            
            # Convert InChI to SMILES
            with st.spinner("Converting InChI to SMILES..."):
                final_smiles = inchi_to_smiles(structure_input)
                if final_smiles is None:
                    st.error("Failed to convert InChI to SMILES. Please check the InChI format.")
                    return False
                st.success(f"Successfully converted InChI to SMILES: {final_smiles}")
        else:
            st.error(f"Unsupported input format: {input_format}")
            return False
        
        if not activity_types:
            st.error("No activity types selected. Please select at least one activity type.")
            return False
        
        # Check for existing compound (use final_smiles for consistency)
        validated_compound_name = check_existing_compound(compound_name, final_smiles, similarity_threshold, activity_types)
        if validated_compound_name is None:
            return False
        
        # Process compound with progress tracking
        with st.spinner(f"Processing compound {validated_compound_name}..."):
            results = process_compound(
                validated_compound_name, 
                final_smiles, 
                similarity_threshold, 
                activity_types
            )
            
            if results is not None:
                st.success(f"Successfully processed {validated_compound_name}")
                if 'processing_complete' in st.session_state:
                    st.session_state.processing_complete = True
                return True
            else:
                st.error(f"Failed to process {validated_compound_name}")
                if 'processing_complete' in st.session_state:
                    st.session_state.processing_complete = False
                return False
    
    except Exception as e:
        logger.error(f"Error in process_and_store: {str(e)}")
        st.error(f"An error occurred: {str(e)}")
        if 'processing_complete' in st.session_state:
            st.session_state.processing_complete = False
        return False

def process_csv_batch(
    df: pd.DataFrame,
    similarity_threshold: int = 90,
    activity_types: List[str] = ACTIVITY_TYPES
) -> Tuple[int, int]:
    """
    Process a batch of compounds from a CSV file.
    
    Args:
        df: DataFrame containing compounds to process
        similarity_threshold: Similarity threshold for search
        activity_types: List of activity types to process
    
    Returns:
        Tuple[int, int]: Number of successful and failed compounds
    """
    if df is None or df.empty:
        st.error("No data to process")
        return 0, 0
    
    success_count = 0
    fail_count = 0
    
    # Create progress tracking
    progress_text = st.empty()
    progress_bar = st.progress(0)
    
    for idx, row in df.iterrows():
        try:
            # Get original compound name and sanitize it for filesystem
            original_name = str(row['compound_name']).strip()
            compound_name = sanitize_compound_name(original_name)

            # Log if name was changed
            if original_name != compound_name:
                logger.info(f"Sanitized compound name: '{original_name}' -> '{compound_name}'")

            # Determine structure input and format
            structure_input = None
            input_format = None

            if 'smiles' in df.columns and pd.notna(row['smiles']):
                structure_input = str(row['smiles']).strip()
                input_format = "smiles"
            elif 'inchi' in df.columns and pd.notna(row['inchi']):
                structure_input = str(row['inchi']).strip()
                input_format = "inchi"
            else:
                logger.error(f"No valid structure data found for compound {compound_name} at row {idx+1}")
                fail_count += 1
                continue

            progress_text.text(f"Processing compound {idx+1}/{len(df)}: {compound_name} ({input_format.upper()})")

            # Process the compound with sanitized name
            result = process_and_store(
                compound_name=compound_name,
                structure_input=structure_input,
                input_format=input_format,
                similarity_threshold=similarity_threshold,
                activity_types=activity_types
            )
            
            if result:
                success_count += 1
            else:
                fail_count += 1
            
            # Update progress
            progress = (idx + 1) / len(df)
            progress_bar.progress(progress)
            
        except Exception as e:
            logger.error(f"Error processing row {idx}: {str(e)}")
            fail_count += 1
    
    progress_text.text("Processing completed!")
    return success_count, fail_count

def display_compound_summary(
    df_results: pd.DataFrame, 
    compound_name: str, 
    similarity_threshold: Optional[int] = None
) -> None:
    """
    Display comprehensive summary statistics for the processed compound.
    
    Args:
        df_results: DataFrame containing the compound analysis results
        compound_name: Name of the processed compound
        similarity_threshold: The similarity threshold used in the search (optional)
    """
    # Try to load metadata from file if similarity_threshold is not provided
    if similarity_threshold is None:
        try:
            metadata_file = os.path.join(RESULTS_DIR, compound_name, f"{compound_name}_metadata.json")
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    similarity_threshold = metadata.get('similarity_threshold', 90)
                    processing_date = metadata.get('processing_date', 'Unknown')
                    activity_types_used = metadata.get('activity_types', '').split(',')
            else:
                similarity_threshold = st.session_state.get('last_similarity_threshold', 90)
                processing_date = 'Unknown'
                activity_types_used = []
        except Exception as e:
            logger.error(f"Error loading metadata: {str(e)}")
            similarity_threshold = st.session_state.get('last_similarity_threshold', 90)
            processing_date = 'Unknown'
            activity_types_used = []
    else:
        processing_date = 'Unknown'
        activity_types_used = []
        
    if df_results is None or df_results.empty:
        st.warning("No results available to summarize.")
        return
    
    st.subheader("📊 Compound Analysis Summary")
    
    # Create expandable sections for better organization
    with st.expander("🧪 Compound Information", expanded=True):
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown(f"**Compound Name:** {compound_name}")
            st.markdown(f"**Similarity Threshold:** {similarity_threshold}%")
            
            # Get unique SMILES (should be one for the input compound)
            original_smiles = df_results['SMILES'].iloc[0] if 'SMILES' in df_results.columns else "N/A"
            st.markdown(f"**Input SMILES:** ```{original_smiles}```")
            
        with col2:
            # Get unique ChEMBL IDs and count
            unique_chembl_ids = df_results['ChEMBL_ID'].unique()
            st.markdown(f"**Similar Compounds Found:** {len(unique_chembl_ids)}")
            
            # Display unique ChEMBL IDs
            chembl_ids_str = ", ".join(unique_chembl_ids[:5])
            if len(unique_chembl_ids) > 5:
                chembl_ids_str += f" and {len(unique_chembl_ids) - 5} more..."
            st.markdown(f"**ChEMBL IDs:** {chembl_ids_str}")
            
            # Display processing date if available
            if processing_date != 'Unknown':
                st.markdown(f"**Processing Date:** {processing_date}")
                
            # Display activity types used if available
            if activity_types_used:
                types_str = ", ".join(activity_types_used)
                st.markdown(f"**Activity Types Processed:** {types_str}")
    
    # Classification summary
    with st.expander("🔍 Classification Details", expanded=True):
        if any(col in df_results.columns for col in ['Kingdom', 'Superclass', 'Class', 'Subclass']):
            # Create a classification summary for each unique ChEMBL ID
            # Include both ClassyFire and NPClassifier fields
            class_cols = [
                'ChEMBL_ID',
                'Molecule_Name',
                # ClassyFire fields
                'Kingdom',
                'Superclass',
                'Class',
                'Subclass',
                'Direct_Parent',
                'Molecular_Framework',
                'Description',
                'ChEMONT_ID_Class',
                'ChEMONT_ID_Subclass',
                # NPClassifier fields
                'NP_Pathway',
                'NP_Superclass',
                'NP_Class',
                'NP_isglycoside'
            ]
            avail_cols = [col for col in class_cols if col in df_results.columns]

            if len(avail_cols) > 2:  # More than just ChEMBL_ID and Molecule_Name
                # Get unique classifications per ChEMBL ID
                class_summary = df_results[avail_cols].drop_duplicates().reset_index(drop=True)

                # Add section headers if we have both ClassyFire and NPClassifier
                st.markdown("##### Complete Chemical Classification")
                st.markdown("*Showing ClassyFire and NPClassifier taxonomy for all similar compounds*")
                st.dataframe(class_summary, use_container_width=True)

                # Show summary statistics
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**ClassyFire Coverage:**")
                    if 'Kingdom' in avail_cols:
                        kingdom_coverage = (df_results['Kingdom'].notna().sum() / len(df_results) * 100)
                        st.write(f"- Kingdom: {kingdom_coverage:.1f}% of compounds")
                    if 'Superclass' in avail_cols:
                        superclass_coverage = (df_results['Superclass'].notna().sum() / len(df_results) * 100)
                        st.write(f"- Superclass: {superclass_coverage:.1f}% of compounds")

                with col2:
                    st.markdown("**NPClassifier Coverage:**")
                    if 'NP_Pathway' in avail_cols:
                        np_coverage = (df_results['NP_Pathway'].notna().sum() / len(df_results) * 100)
                        st.write(f"- Pathway: {np_coverage:.1f}% of compounds")
                    if 'NP_Superclass' in avail_cols:
                        np_super_coverage = (df_results['NP_Superclass'].notna().sum() / len(df_results) * 100)
                        st.write(f"- Superclass: {np_super_coverage:.1f}% of compounds")
            else:
                st.info("No classification data available for these compounds.")
        else:
            st.info("No classification data available for these compounds.")
    
    # Activity summary
    with st.expander("📈 Activity Analysis", expanded=True):
        if 'Activity_Type' in df_results.columns and 'Activity_nM' in df_results.columns:
            # Count of each activity type
            activity_counts = df_results['Activity_Type'].value_counts().reset_index()
            activity_counts.columns = ['Activity_Type', 'Count']
            
            # Calculate percentage
            total_activities = activity_counts['Count'].sum()
            activity_counts['Percentage'] = (activity_counts['Count'] / total_activities * 100).round(2)
            
            col1, col2 = st.columns([2, 3])
            
            with col1:
                st.markdown("##### Activity Distribution")
                st.dataframe(activity_counts, use_container_width=True)
            
            with col2:
                # Create a Plotly pie chart
                fig = px.pie(
                    activity_counts,
                    values='Count',
                    names='Activity_Type',
                    title='Activity Type Distribution',
                    color_discrete_sequence=px.colors.qualitative.Set3,
                    hole=0.3  # Makes it a donut chart which looks more modern
                )
                
                fig.update_traces(
                    textposition='inside',
                    textinfo='percent+label',
                    hoverinfo='label+percent+value'
                )
                
                fig.update_layout(
                    autosize=True,
                    margin=dict(l=0, r=0, t=30, b=0)
                )
                
                # Display the chart (rendered on-demand, not saved to disk)
                st.plotly_chart(fig, use_container_width=True)
            
            # Statistical summary for activities
            st.markdown("##### Activity Statistics by Type (nM)")

            # Create a statistical summary table by activity type
            stats_summary = []
            for activity_type in df_results['Activity_Type'].unique():
                if activity_type != 'Unknown':
                    subset = df_results[df_results['Activity_Type'] == activity_type]
                    activity_values = subset['Activity_nM'].dropna()
                    
                    if not activity_values.empty:
                        stats_summary.append({
                            'Activity_Type': activity_type,
                            'Count': len(activity_values),
                            'Min': activity_values.min(),
                            'Max': activity_values.max(),
                            'Mean': activity_values.mean(),
                            'Median': activity_values.median(),
                            'Std Dev': activity_values.std()
                        })
            
            if stats_summary:
                stats_df = pd.DataFrame(stats_summary)
                # Format number columns to 2 decimal places
                for col in ['Min', 'Max', 'Mean', 'Median', 'Std Dev']:
                    if col in stats_df.columns:
                        stats_df[col] = stats_df[col].round(2)
                
                st.dataframe(stats_df, use_container_width=True)
    
    # Efficiency metrics summary
    with st.expander("🎯 Efficiency Metrics", expanded=True):
        efficiency_metrics = ['SEI', 'BEI', 'NSEI', 'NBEI']
        avail_metrics = [metric for metric in efficiency_metrics if metric in df_results.columns]
        
        if avail_metrics:
            # Statistical summary for efficiency metrics
            stats_summary = []
            for metric in avail_metrics:
                metric_values = df_results[metric].dropna()
                
                if not metric_values.empty:
                    stats_summary.append({
                        'Metric': metric,
                        'Count': len(metric_values),
                        'Min': metric_values.min(),
                        'Max': metric_values.max(),
                        'Mean': metric_values.mean(),
                        'Median': metric_values.median(),
                        'Std Dev': metric_values.std()
                    })
            
            if stats_summary:
                stats_df = pd.DataFrame(stats_summary)
                # Format number columns to 3 decimal places
                for col in ['Min', 'Max', 'Mean', 'Median', 'Std Dev']:
                    if col in stats_df.columns:
                        stats_df[col] = stats_df[col].round(3)
                
                st.dataframe(stats_df, use_container_width=True)
            
            # Create boxplots for efficiency metrics using Plotly
            st.markdown("##### Efficiency Metrics Distribution")
            
            # Create a Plotly boxplot for each metric
            # Replace the boxplot section in display_compound_summary with this code:

            # Create a single boxplot for all efficiency metrics using Plotly
            st.markdown("##### Efficiency Metrics Distribution")

            # Prepare data for a single combined boxplot

            # Prepare data for a single combined boxplot
            boxplot_data = pd.DataFrame()
            for metric in avail_metrics:
                metric_values = df_results[metric].dropna()
                if not metric_values.empty:
                    # Create a dataframe for this metric
                    metric_df = pd.DataFrame({
                        'Metric': [metric] * len(metric_values),
                        'Value': metric_values
                    })
                    # Append to the combined dataframe
                    boxplot_data = pd.concat([boxplot_data, metric_df], ignore_index=True)

            if not boxplot_data.empty:
                # Create a single boxplot with all metrics and only show outlier points
                box_fig = px.box(
                    boxplot_data,
                    x='Metric',  # Metrics on x-axis
                    y='Value',   # Values on y-axis
                    color='Metric',  # Color by metric
                    title="Efficiency Metrics Distribution",
                    labels={'Value': 'Value', 'Metric': 'Efficiency Metric'},
                    height=500,
                    width=800,
                    points='outliers',  # Only show outlier points
                    color_discrete_sequence=px.colors.qualitative.Set1  # Use distinct colors
                )
                
                # Customize the boxplot appearance
                box_fig.update_layout(
                    template='plotly_white',
                    xaxis_tickangle=-45,
                    legend_title_text='Compound'
                )
                
                
                # Customize the appearance of the outlier points
                box_fig.update_traces(
                    marker=dict(
                        size=8,       # Make outlier points slightly larger
                        opacity=0.9,  # Make points more visible
                        line=dict(width=1, color='DarkSlateGrey')  # Add thin border to points
                    ),
                    boxpoints='outliers'  # Ensure only outliers are shown
                )
                
                # Display the boxplot (rendered on-demand, not saved to disk)
                st.plotly_chart(box_fig, use_container_width=True)
                        
            if 'Target_ChEMBL_ID' in df_results.columns:
                st.markdown("##### Efficiency Metrics by Target")

                # Group by target and calculate statistics
                target_metrics = []

                for target in df_results['Target_ChEMBL_ID'].dropna().unique():
                    target_data = df_results[df_results['Target_ChEMBL_ID'] == target]

                    # Create a single row per target with all metrics
                    target_row = {'Target_ChEMBL_ID': target}

                    # Add target name if available
                    if 'Target_Name' in df_results.columns:
                        target_name = target_data['Target_Name'].iloc[0] if not target_data.empty else 'N/A'
                        target_row['Target_Name'] = target_name
                    
                    # Calculate count, mean and median for each metric
                    for metric in avail_metrics:
                        metric_values = target_data[metric].dropna()
                        
                        if not metric_values.empty:
                            target_row[f'{metric} Count'] = len(metric_values)
                            target_row[f'{metric} Mean'] = round(metric_values.mean(), 3)
                            target_row[f'{metric} Median'] = round(metric_values.median(), 3)
                        else:
                            target_row[f'{metric} Count'] = 0
                            target_row[f'{metric} Mean'] = None
                            target_row[f'{metric} Median'] = None
                    
                    target_metrics.append(target_row)
                
                if target_metrics:
                    # Create dataframe with one row per target
                    target_df = pd.DataFrame(target_metrics)
                    
                    # Display the table with one row per target
                    st.dataframe(target_df, use_container_width=True)
                    
                    # Add explanation
                    st.info("""
                    **Understanding Efficiency Metrics by Target:**
                    
                    This table shows efficiency metrics calculated for each target in the dataset.
                    
                    - **SEI (Surface Efficiency Index):** Measures activity relative to polar surface area
                    - **BEI (Binding Efficiency Index):** Measures activity relative to molecular weight
                    - **NSEI (Normalized Surface Efficiency Index):** SEI normalized by the number of polar atoms
                    - **nBEI (Normalized Binding Efficiency Index):** BEI normalized considering heavy atoms
                    
                    Higher values indicate more efficient compounds for that target.
                    """)

    # Outlier Analysis
    with st.expander("🎯 Outlier Detection & IMP Analysis", expanded=True):
        outlier_cols = ['Is_SEI_Outlier', 'Is_BEI_Outlier', 'Is_NSEI_Outlier', 'Is_NBEI_Outlier',
                       'Is_Efficiency_Outlier', 'Outlier_Count']

        if any(col in df_results.columns for col in outlier_cols):
            st.markdown("##### Efficiency Outliers")
            st.markdown("*Compounds with exceptional efficiency metrics (IQR method)*")

            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                if 'Is_SEI_Outlier' in df_results.columns:
                    sei_outliers = df_results['Is_SEI_Outlier'].sum()
                    st.metric("SEI Outliers", sei_outliers)

            with col2:
                if 'Is_BEI_Outlier' in df_results.columns:
                    bei_outliers = df_results['Is_BEI_Outlier'].sum()
                    st.metric("BEI Outliers", bei_outliers)

            with col3:
                if 'Is_NSEI_Outlier' in df_results.columns:
                    nsei_outliers = df_results['Is_NSEI_Outlier'].sum()
                    st.metric("NSEI Outliers", nsei_outliers)

            with col4:
                if 'Is_NBEI_Outlier' in df_results.columns:
                    nbei_outliers = df_results['Is_NBEI_Outlier'].sum()
                    st.metric("NBEI Outliers", nbei_outliers)

            # Show compounds that are outliers in multiple metrics
            if 'Outlier_Count' in df_results.columns:
                st.markdown("---")
                st.markdown("##### Multi-Metric Outliers")

                multi_outliers = df_results[df_results['Outlier_Count'] >= 2].copy()

                if not multi_outliers.empty:
                    # Count by outlier count
                    outlier_dist = multi_outliers['Outlier_Count'].value_counts().sort_index(ascending=False)

                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.markdown("**Distribution:**")
                        for count, num_compounds in outlier_dist.items():
                            st.write(f"- {num_compounds} compound(s) outlier in {count} metrics")

                    with col2:
                        # Show top outliers
                        display_cols = ['ChEMBL_ID', 'Molecule_Name', 'Outlier_Count']
                        if 'Is_SEI_Outlier' in multi_outliers.columns:
                            display_cols.append('Is_SEI_Outlier')
                        if 'Is_BEI_Outlier' in multi_outliers.columns:
                            display_cols.append('Is_BEI_Outlier')
                        if 'Is_NSEI_Outlier' in multi_outliers.columns:
                            display_cols.append('Is_NSEI_Outlier')
                        if 'Is_NBEI_Outlier' in multi_outliers.columns:
                            display_cols.append('Is_NBEI_Outlier')

                        avail_display_cols = [col for col in display_cols if col in multi_outliers.columns]

                        top_outliers = multi_outliers.nlargest(10, 'Outlier_Count')[avail_display_cols]
                        st.dataframe(top_outliers, use_container_width=True)
                else:
                    st.info("No compounds are outliers in 2 or more metrics.")

        # O[Q/P/L]A Scoring
        if 'OQPLA_Final_Score' in df_results.columns:
            st.markdown("---")

            # Determine which phase based on PDB columns
            has_pdb = 'PDB_Score' in df_results.columns
            phase_label = "Phase 2: Components 1-4" if has_pdb else "Phase 1: Components 1-3"

            st.markdown(f"##### O[Q/P/L]A Scoring ({phase_label})")
            st.markdown("*Outlier-based Quality, Promiscuity, Lipophilicity Assessment" + (" + PDB Evidence*" if has_pdb else "*"))

            # Score distribution
            col1, col2, col3 = st.columns(3)

            with col1:
                avg_score = df_results['OQPLA_Final_Score'].mean()
                st.metric("Average O[Q/P/L]A Score", f"{avg_score:.3f}")

            with col2:
                max_score = df_results['OQPLA_Final_Score'].max()
                st.metric("Maximum Score", f"{max_score:.3f}")

            with col3:
                if 'OQPLA_Classification' in df_results.columns:
                    top_class = df_results['OQPLA_Classification'].mode().iloc[0] if not df_results['OQPLA_Classification'].empty else 'N/A'
                    st.metric("Most Common Class", top_class)

            # Classification distribution
            if 'OQPLA_Classification' in df_results.columns:
                st.markdown("**Classification Distribution:**")
                class_counts = df_results['OQPLA_Classification'].value_counts()

                # Create a simple bar chart or table
                class_df = pd.DataFrame({
                    'Classification': class_counts.index,
                    'Count': class_counts.values,
                    'Percentage': (class_counts.values / len(df_results) * 100).round(1)
                })
                st.dataframe(class_df, use_container_width=True)

        # PDB Structural Evidence (Component 4) - Load from separate PDB summary file
        if 'PDB_Score' in df_results.columns:
            # Build compound folder path
            compound_folder = os.path.join(RESULTS_DIR, compound_name.replace(' ', '_'))

            # Try to load PDB summary CSV
            pdb_summary_path = os.path.join(compound_folder, f"{compound_name}_pdb_summary.csv")

            if os.path.exists(pdb_summary_path):
                try:
                    pdb_summary_df = pd.read_csv(pdb_summary_path)

                    st.markdown("---")
                    st.markdown("##### PDB Structural Evidence (Component 4)")
                    st.markdown("*Experimental crystal structures from RCSB Protein Data Bank (Compound-Level Summary)*")

                    # Summary metrics - now using unique compounds
                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        avg_pdb_score = pdb_summary_df['PDB_Score'].mean()
                        st.metric("Average PDB Score", f"{avg_pdb_score:.3f}")

                    with col2:
                        total_structures = pdb_summary_df['PDB_Num_Structures'].sum()
                        st.metric("Total Structures", int(total_structures))

                    with col3:
                        high_quality = pdb_summary_df['PDB_High_Quality'].sum()
                        st.metric("High Quality (⭐⭐⭐)", int(high_quality))

                    with col4:
                        compounds_with_pdb = (pdb_summary_df['PDB_Num_Structures'] > 0).sum()
                        pct_with_pdb = (compounds_with_pdb / len(pdb_summary_df) * 100)
                        st.metric("% with PDB Data", f"{pct_with_pdb:.1f}%")

                    st.caption(f"📊 Summary across **{len(pdb_summary_df)} unique compounds**")

                    # Quality distribution
                    st.markdown("**Structure Quality Distribution:**")
                    quality_data = {
                        'Quality Tier': ['⭐⭐⭐ High (< 2.0 Å)', '⭐⭐ Medium (2.0-3.0 Å)', '⭐ Poor (> 3.0 Å)'],
                        'Count': [
                            int(pdb_summary_df['PDB_High_Quality'].sum()),
                            int(pdb_summary_df['PDB_Medium_Quality'].sum()),
                            int(pdb_summary_df['PDB_Poor_Quality'].sum())
                        ],
                        'Avg %': [
                            f"{pdb_summary_df['PDB_High_Quality_Pct'].mean():.1f}%",
                            f"{pdb_summary_df['PDB_Medium_Quality_Pct'].mean():.1f}%",
                            f"{pdb_summary_df['PDB_Poor_Quality_Pct'].mean():.1f}%"
                        ]
                    }
                    quality_df = pd.DataFrame(quality_data)
                    st.dataframe(quality_df, use_container_width=True, hide_index=True)

                    # Top compounds with PDB evidence
                    top_pdb = pdb_summary_df[pdb_summary_df['PDB_Num_Structures'] > 0].head(10)

                    if not top_pdb.empty:
                        st.markdown("**Top Compounds with PDB Evidence:**")
                        display_cols = ['ChEMBL_ID', 'Molecule_Name', 'PDB_Score',
                                       'PDB_Num_Structures', 'PDB_High_Quality',
                                       'PDB_Best_Resolution', 'PDB_IDs']

                        avail_cols = [col for col in display_cols if col in top_pdb.columns]
                        st.dataframe(top_pdb[avail_cols], use_container_width=True, hide_index=True)

                        st.info("💡 **Tip**: Higher PDB scores indicate more experimental validation. "
                               "Compounds with ⭐⭐⭐ structures (< 2.0 Å resolution) have the strongest structural evidence. "
                               f"View the complete PDB summary in `{compound_name}_pdb_summary.csv`")

                        # Display detailed PDB structures table if available
                        pdb_details_path = os.path.join(compound_folder, f"{compound_name}_pdb_structures_detailed.csv")
                        if os.path.exists(pdb_details_path):
                            try:
                                pdb_details_df = pd.read_csv(pdb_details_path)

                                st.markdown("**Detailed PDB Structures:**")
                                st.markdown("*Sorted by quality (⭐⭐⭐ first) and resolution (best first)*")

                                # Prepare display dataframe
                                display_df = pdb_details_df.copy()

                                # Truncate long titles for better display
                                if 'Title' in display_df.columns:
                                    display_df['Title'] = display_df['Title'].apply(
                                        lambda x: (x[:60] + '...') if isinstance(x, str) and len(x) > 60 else x
                                    )

                                # Make URL clickable by converting to markdown link format
                                if 'URL' in display_df.columns and 'PDB_ID' in display_df.columns:
                                    display_df['PDB_Link'] = display_df.apply(
                                        lambda row: f'<a href="{row["URL"]}" target="_blank">{row["PDB_ID"]}</a>',
                                        axis=1
                                    )
                                    # Remove original PDB_ID and URL columns, reorder with link first
                                    cols_to_display = ['PDB_Link'] + [col for col in display_df.columns
                                                                      if col not in ['PDB_Link', 'PDB_ID', 'URL', 'SMILES']]
                                    display_df = display_df[cols_to_display]

                                # Display the dataframe with HTML links
                                st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)

                                st.caption(f"📊 **{len(pdb_details_df)} total PDB structures** sorted by quality (⭐⭐⭐ → ⭐⭐ → ⭐) "
                                         "and resolution (best first). Click PDB_Link to view structure at RCSB PDB.")

                            except Exception as e:
                                logger.error(f"Error loading detailed PDB structures: {str(e)}")
                                st.caption("⚠️ Detailed PDB structures file exists but could not be loaded.")
                    else:
                        st.info("No PDB structures found for compounds in this dataset.")

                except Exception as e:
                    st.warning(f"⚠️ Could not load PDB summary: {str(e)}")
            else:
                st.info("🔬 PDB evidence was used in O[Q/P/L]A scoring, but detailed summary file not found.")

        # IMP Candidate Classification
        if 'Is_IMP_Candidate' in df_results.columns:
            st.markdown("---")
            st.markdown("##### IMP Candidate Identification")
            st.markdown("*Invalid Metabolic Panaceas - Compounds with exceptional but potentially non-specific activity*")

            imp_candidates = df_results[df_results['Is_IMP_Candidate'] == True]

            col1, col2 = st.columns(2)

            with col1:
                st.metric("IMP Candidates", len(imp_candidates))
                st.metric("Total Compounds", len(df_results))
                st.metric("% IMP", f"{len(imp_candidates)/len(df_results)*100:.1f}%")

            with col2:
                if 'IMP_Confidence' in df_results.columns and not imp_candidates.empty:
                    st.markdown("**Confidence Distribution:**")
                    conf_counts = imp_candidates['IMP_Confidence'].value_counts()
                    for conf, count in conf_counts.items():
                        st.write(f"- {conf}: {count} compound(s)")

            # Show top IMP candidates
            if not imp_candidates.empty:
                st.markdown("**Top IMP Candidates:**")
                display_imp_cols = ['ChEMBL_ID', 'Molecule_Name', 'OQPLA_Final_Score',
                                   'Outlier_Count', 'IMP_Confidence']
                avail_imp_cols = [col for col in display_imp_cols if col in imp_candidates.columns]

                top_imps = imp_candidates.nlargest(10, 'OQPLA_Final_Score')[avail_imp_cols]
                st.dataframe(top_imps, use_container_width=True)
            else:
                st.success("✅ No IMP candidates detected - all compounds show specific activity profiles!")

            # Display IMP Report if available
            compound_folder = os.path.join(RESULTS_DIR, compound_name.replace(' ', '_'))
            imp_report_path = os.path.join(compound_folder, f"{compound_name}_imp_report.txt")
            if os.path.exists(imp_report_path):
                st.markdown("---")
                st.markdown("**📄 IMP Analysis Report:**")
                try:
                    with open(imp_report_path, 'r') as f:
                        report_content = f.read()

                    # Display in an expander to save space
                    with st.expander("View Complete IMP Report", expanded=False):
                        st.text(report_content)

                    st.caption(f"Full report saved to: `{compound_name}_imp_report.txt`")
                except Exception as e:
                    st.warning(f"Could not load IMP report: {str(e)}")

    # Target information
    if 'Target_ChEMBL_ID' in df_results.columns:
        with st.expander("🎚️ Target Analysis", expanded=True):
            unique_targets = df_results['Target_ChEMBL_ID'].dropna().unique()

            if len(unique_targets) > 0:
                st.markdown("##### Target Distribution")

                # Create target count table
                target_counts = df_results['Target_ChEMBL_ID'].value_counts().reset_index()
                target_counts.columns = ['Target_ChEMBL_ID', 'Count']
                target_counts['Percentage'] = (target_counts['Count'] / target_counts['Count'].sum() * 100).round(2)

                # Add target names if available
                if 'Target_Name' in df_results.columns:
                    target_names = df_results[['Target_ChEMBL_ID', 'Target_Name']].drop_duplicates()
                    target_counts = target_counts.merge(target_names, on='Target_ChEMBL_ID', how='left')
                    # Reorder columns to show name after ID
                    cols = ['Target_ChEMBL_ID', 'Target_Name', 'Count', 'Percentage']
                    target_counts = target_counts[cols]

                st.dataframe(target_counts, use_container_width=True)
    
    # Physicochemical properties
    with st.expander("⚗️ Physicochemical Properties", expanded=True):
        phys_props = ['Molecular_Weight', 'TPSA', 'QED', 'HBD', 'HBA', 'Heavy_Atoms', 'NPOL']
        avail_props = [prop for prop in phys_props if prop in df_results.columns]
        
        if avail_props:
            # Statistical summary for physicochemical properties
            props_summary = []
            for prop in avail_props:
                prop_values = df_results[prop].dropna()
                
                if not prop_values.empty:
                    props_summary.append({
                        'Property': prop,
                        'Count': len(prop_values),
                        'Min': prop_values.min(),
                        'Max': prop_values.max(),
                        'Mean': prop_values.mean(),
                        'Median': prop_values.median(),
                        'Std Dev': prop_values.std()
                    })
            
            if props_summary:
                props_df = pd.DataFrame(props_summary)
                # Format number columns to 2 decimal places
                for col in ['Min', 'Max', 'Mean', 'Median', 'Std Dev']:
                    if col in props_df.columns:
                        props_df[col] = props_df[col].round(2)
                
                st.dataframe(props_df, use_container_width=True)