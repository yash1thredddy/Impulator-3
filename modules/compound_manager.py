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
from modules.utils import validate_compound_name, validate_smiles

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
    smiles: str,
    similarity_threshold: int = 80,
    activity_types: List[str] = ACTIVITY_TYPES
) -> bool:
    """
    Process a compound and store results with improved validation.
    
    Args:
        compound_name: Name of the compound
        smiles: SMILES string
        similarity_threshold: Similarity threshold for search
        activity_types: List of activity types to process
    
    Returns:
        bool: True if processing successful, False otherwise
    """
    try:
        # Validate inputs
        if not validate_compound_name(compound_name):
            st.error("Invalid compound name. Please use alphanumeric characters and avoid special characters.")
            return False
        
        if not validate_smiles(smiles):
            st.error("Invalid SMILES string. Please check the input format.")
            return False
        
        if not activity_types:
            st.error("No activity types selected. Please select at least one activity type.")
            return False
        
        # Check for existing compound
        validated_compound_name = check_existing_compound(compound_name, smiles, similarity_threshold, activity_types)
        if validated_compound_name is None:
            return False
        
        # Process compound with progress tracking
        with st.spinner(f"Processing compound {validated_compound_name}..."):
            results = process_compound(
                validated_compound_name, 
                smiles, 
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
    similarity_threshold: int = 80,
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
            compound_name = str(row['compound_name']).strip()
            smiles = str(row['smiles']).strip()
            
            progress_text.text(f"Processing compound {idx+1}/{len(df)}: {compound_name}")
            
            # Process the compound
            result = process_and_store(
                compound_name=compound_name,
                smiles=smiles,
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
                    similarity_threshold = metadata.get('similarity_threshold', 80)
                    processing_date = metadata.get('processing_date', 'Unknown')
                    activity_types_used = metadata.get('activity_types', '').split(',')
            else:
                similarity_threshold = st.session_state.get('last_similarity_threshold', 80)
                processing_date = 'Unknown'
                activity_types_used = []
        except Exception as e:
            logger.error(f"Error loading metadata: {str(e)}")
            similarity_threshold = st.session_state.get('last_similarity_threshold', 80)
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
            unique_chembl_ids = df_results['ChEMBL ID'].unique()
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
            class_cols = ['ChEMBL ID', 'Molecule Name', 'Kingdom', 'Superclass', 'Class', 'Subclass']
            avail_cols = [col for col in class_cols if col in df_results.columns]
            
            # Get unique classifications per ChEMBL ID
            class_summary = df_results[avail_cols].drop_duplicates().reset_index(drop=True)
            st.dataframe(class_summary, use_container_width=True)
    
    # Activity summary
    with st.expander("📈 Activity Analysis", expanded=True):
        if 'Activity Type' in df_results.columns and 'Activity (nM)' in df_results.columns:
            # Count of each activity type
            activity_counts = df_results['Activity Type'].value_counts().reset_index()
            activity_counts.columns = ['Activity Type', 'Count']
            
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
                    names='Activity Type',
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
                
                # Display the chart
                st.plotly_chart(fig, use_container_width=True)
                
                # Save the pie chart to the Activity folder
                try:
                    activity_folder = os.path.join(RESULTS_DIR, compound_name, "Activity")
                    os.makedirs(activity_folder, exist_ok=True)
                    
                    pie_json_path = os.path.join(activity_folder, "activity_distribution_pie.json")
                    fig_json = fig.to_json()
                    with open(pie_json_path, 'w') as f:
                        f.write(fig_json)
                except Exception as e:
                    logger.error(f"Error saving activity pie chart: {str(e)}")
            
            # Statistical summary for activities
            st.markdown("##### Activity Statistics by Type (nM)")
            
            # Create a statistical summary table by activity type
            stats_summary = []
            for activity_type in df_results['Activity Type'].unique():
                if activity_type != 'Unknown':
                    subset = df_results[df_results['Activity Type'] == activity_type]
                    activity_values = subset['Activity (nM)'].dropna()
                    
                    if not activity_values.empty:
                        stats_summary.append({
                            'Activity Type': activity_type,
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
        efficiency_metrics = ['SEI', 'BEI', 'NSEI', 'nBEI']
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
                fig.update_layout(
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
                
                # Display the boxplot
                st.plotly_chart(box_fig, use_container_width=True)
                
                # Save the boxplot
                try:
                    sei_folder = os.path.join(RESULTS_DIR, compound_name, "SEI")
                    os.makedirs(sei_folder, exist_ok=True)
                    
                    box_json_path = os.path.join(sei_folder, "efficiency_metrics_boxplot.json")
                    box_fig_json = box_fig.to_json()
                    with open(box_json_path, 'w') as f:
                        f.write(box_fig_json)
                except Exception as e:
                    logger.error(f"Error saving efficiency metrics boxplot: {str(e)}")
                        
            if 'Target ChEMBL ID' in df_results.columns:
                st.markdown("##### Efficiency Metrics by Target")
                
                # Group by target and calculate statistics
                target_metrics = []
                
                for target in df_results['Target ChEMBL ID'].dropna().unique():
                    target_data = df_results[df_results['Target ChEMBL ID'] == target]
                    
                    # Create a single row per target with all metrics
                    target_row = {'Target ChEMBL ID': target}
                    
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
    
    # Target information
    if 'Target ChEMBL ID' in df_results.columns:
        with st.expander("🎚️ Target Analysis", expanded=True):
            unique_targets = df_results['Target ChEMBL ID'].dropna().unique()
            
            if len(unique_targets) > 0:
                st.markdown("##### Target Distribution")
                
                # Create target count table
                target_counts = df_results['Target ChEMBL ID'].value_counts().reset_index()
                target_counts.columns = ['Target ChEMBL ID', 'Count']
                target_counts['Percentage'] = (target_counts['Count'] / target_counts['Count'].sum() * 100).round(2)
                
                st.dataframe(target_counts, use_container_width=True)
    
    # Physicochemical properties
    with st.expander("⚗️ Physicochemical Properties", expanded=True):
        phys_props = ['Molecular Weight', 'TPSA', 'HBD', 'HBA', 'NPOL', 'QED', 'Heavy Atoms']
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
                
            # Create correlation heatmap between properties and efficiency metrics
            correlation_cols = avail_props + [metric for metric in ['SEI', 'BEI', 'NSEI', 'nBEI', 'pActivity'] 
                                           if metric in df_results.columns]
            
            if len(correlation_cols) > 1:
                st.markdown("##### Correlation Between Properties and Efficiency Metrics")
                
                # Calculate correlation matrix
                corr_df = df_results[correlation_cols].corr().round(2)
                
                # Plot heatmap
                fig, ax = plt.subplots(figsize=(12, 10))
                mask = np.triu(np.ones_like(corr_df, dtype=bool))
                cmap = sns.diverging_palette(220, 10, as_cmap=True)
                
                sns.heatmap(corr_df, mask=mask, cmap=cmap, vmax=1, vmin=-1, center=0,
                           square=True, linewidths=.5, cbar_kws={"shrink": .5}, annot=True)
                
                plt.title('Correlation Heatmap')
                st.pyplot(fig)