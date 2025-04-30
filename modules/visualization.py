"""
Visualization functions for plotting and displaying compound data using Plotly for interactivity.
"""
import os
import glob
import logging
import json
from typing import List, Dict, Optional, Tuple, Any, Union

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from rdkit import Chem
from rdkit.Chem import Draw, AllChem

from config import RESULTS_DIR
from modules.api_client import get_molecule_data

# Configure logging
logger = logging.getLogger(__name__)

def plot_all_visualizations(df_results: pd.DataFrame, folder_name: str) -> None:
    """
    Generate all visualizations for a compound using Plotly.
    
    Args:
        df_results: DataFrame containing the compound analysis results
        folder_name: Directory to save visualizations
    """
    try:
        # Log initial state for debugging
        logger.info(f"Starting plot_all_visualizations for folder: {folder_name}")
        logger.info(f"DataFrame shape: {df_results.shape if df_results is not None else 'None'}")
        
        if df_results is None or df_results.empty:
            logger.warning("No data available for visualization")
            st.warning("No data available for visualization")
            return
        
        # Create subfolders
        sei_folder = os.path.join(folder_name, "SEI")
        bei_folder = os.path.join(folder_name, "BEI")
        activity_folder = os.path.join(folder_name, "Activity")
        structure_folder = os.path.join(folder_name, "Structures")
        
        for folder in [sei_folder, bei_folder, activity_folder, structure_folder]:
            os.makedirs(folder, exist_ok=True)
            logger.info(f"Created folder: {folder}")

        # Generate all plot types with individual try-except blocks
        try:
            logger.info("Generating efficiency scatter plots")
            plot_efficiency_scatter_plots(df_results, folder_name)
        except Exception as e:
            logger.error(f"Error generating efficiency scatter plots: {str(e)}")
            st.warning(f"Error generating efficiency plots: {str(e)}")
            
        try:
            logger.info("Generating activity visualizations")
            plot_activity_visualizations(df_results, activity_folder)
        except Exception as e:
            logger.error(f"Error generating activity visualizations: {str(e)}")
            st.warning(f"Error generating activity plots: {str(e)}")
            
        try:
            logger.info("Generating property visualizations")
            plot_property_visualizations(df_results, sei_folder, bei_folder)
        except Exception as e:
            logger.error(f"Error generating property visualizations: {str(e)}")
            st.warning(f"Error generating property plots: {str(e)}")
            
        try:
            logger.info("Generating molecular structures")
            generate_molecular_structures(df_results, structure_folder)
        except Exception as e:
            logger.error(f"Error generating molecular structures: {str(e)}")
            st.warning(f"Error generating molecular structures: {str(e)}")
            
        # List generated files for debugging
        for folder in [folder_name, sei_folder, bei_folder, activity_folder, structure_folder]:
            if os.path.exists(folder):
                files = os.listdir(folder)
                logger.info(f"Files in {folder}: {files}")
            else:
                logger.warning(f"Folder does not exist: {folder}")
        
        logger.info(f"All visualizations generation completed for {folder_name}")
    
    except Exception as e:
        logger.error(f"Error in plot_all_visualizations: {str(e)}")
        st.error(f"Error generating visualizations: {str(e)}")

def plot_efficiency_scatter_plots(df_results: pd.DataFrame, folder_name: str) -> None:
    """
    Generate interactive efficiency index scatter plots with Plotly.
    
    Args:
        df_results: DataFrame containing the compound analysis results
        folder_name: Directory to save visualizations
    """
    try:
        # Check for required columns
        required_cols = ['SEI', 'BEI', 'ChEMBL ID', 'Molecule Name']
        missing_cols = [col for col in required_cols if col not in df_results.columns]
        if missing_cols:
            logger.warning(f"Missing required columns for efficiency plots: {missing_cols}")
            logger.info(f"Available columns: {list(df_results.columns)}")
            return
        
        # Filter out rows with NaN values in key columns
        valid_data = df_results.dropna(subset=['SEI', 'BEI']).copy()
        
        if valid_data.empty:
            logger.warning("No valid data points for efficiency plots after dropping NaN values")
            return
            
        logger.info(f"Creating efficiency plots with {len(valid_data)} valid data points")
        
        # SEI vs BEI scatter plot
        sei_bei_fig = px.scatter(
            valid_data, 
            x='SEI', 
            y='BEI',
            color='ChEMBL ID',  # Use ChEMBL ID for color coding
            hover_name='Molecule Name',
            hover_data=['Activity Type', 'Activity (nM)', 'Target ChEMBL ID'],
            title='Surface Efficiency Index (SEI) vs Binding Efficiency Index (BEI)',
            labels={'SEI': 'Surface Efficiency Index', 'BEI': 'Binding Efficiency Index'},
            width=900,
            height=700
        )
        
        # Add trendlines for each compound - only if there are multiple points
        for chembl_id in valid_data['ChEMBL ID'].unique():
            df_subset = valid_data[valid_data['ChEMBL ID'] == chembl_id]
            if len(df_subset) > 1:  # Only add trendline if there are multiple points
                sei_bei_fig.add_trace(
                    go.Scatter(
                        x=df_subset['SEI'],
                        y=df_subset['BEI'],
                        mode='lines',
                        showlegend=False,
                        opacity=0.4,
                        hoverinfo='none'
                    )
                )
        
        # Remove legend as requested for SEI vs BEI plot
        sei_bei_fig.update_layout(
            template='plotly_white',
            showlegend=False  # Remove legend
        )
        
        # Save as HTML and JSON for interactive viewing
        try:
            html_path = os.path.join(folder_name, 'sei_vs_bei_scatter_plot.html')
            sei_bei_fig.write_html(html_path)
            logger.info(f"Saved HTML to {html_path}")
            
            json_path = os.path.join(folder_name, 'sei_vs_bei_scatter_plot.json')
            sei_bei_fig_json = sei_bei_fig.to_json()
            with open(json_path, 'w') as f:
                f.write(sei_bei_fig_json)
            logger.info(f"Saved JSON to {json_path}")
        except Exception as e:
            logger.error(f"Error saving SEI vs BEI plot files: {str(e)}")
        
        # Check for NSEI and nBEI columns
        nsei_nbei_cols = ['NSEI', 'nBEI']
        if not all(col in df_results.columns for col in nsei_nbei_cols):
            logger.warning(f"Missing columns for NSEI vs nBEI plot: {[col for col in nsei_nbei_cols if col not in df_results.columns]}")
            return
            
        # Filter out rows with NaN values in NSEI/nBEI columns
        valid_nsei_nbei = df_results.dropna(subset=['NSEI', 'nBEI']).copy()
        
        if valid_nsei_nbei.empty:
            logger.warning("No valid data points for NSEI vs nBEI plot after dropping NaN values")
            return
            
        logger.info(f"Creating NSEI vs nBEI plot with {len(valid_nsei_nbei)} valid data points")
        
        # NSEI vs nBEI scatter plot
        nsei_nbei_fig = px.scatter(
            valid_nsei_nbei, 
            x='NSEI', 
            y='nBEI',
            color='ChEMBL ID',  # Use ChEMBL ID for color coding
            hover_name='Molecule Name',
            hover_data=['Activity Type', 'Activity (nM)', 'Target ChEMBL ID'],
            title='Normalized Surface Efficiency Index (NSEI) vs Normalized Binding Efficiency Index (nBEI)',
            labels={'NSEI': 'Normalized SEI', 'nBEI': 'Normalized BEI'},
            width=900,
            height=700
        )
        
        # Add trendlines for each compound - only if there are multiple points
        for chembl_id in valid_nsei_nbei['ChEMBL ID'].unique():
            df_subset = valid_nsei_nbei[valid_nsei_nbei['ChEMBL ID'] == chembl_id]
            if len(df_subset) > 1:  # Only add trendline if there are multiple points
                nsei_nbei_fig.add_trace(
                    go.Scatter(
                        x=df_subset['NSEI'],
                        y=df_subset['nBEI'],
                        mode='lines',
                        showlegend=False,
                        opacity=0.4,
                        hoverinfo='none'
                    )
                )
        
        # Remove legend as requested for NSEI vs nBEI plot
        nsei_nbei_fig.update_layout(
            template='plotly_white',
            showlegend=False  # Remove legend
        )
        
        # Save as HTML and JSON
        try:
            html_path = os.path.join(folder_name, 'nsei_vs_nbei_scatter_plot.html')
            nsei_nbei_fig.write_html(html_path)
            logger.info(f"Saved HTML to {html_path}")
            
            json_path = os.path.join(folder_name, 'nsei_vs_nbei_scatter_plot.json')
            nsei_nbei_fig_json = nsei_nbei_fig.to_json()
            with open(json_path, 'w') as f:
                f.write(nsei_nbei_fig_json)
            logger.info(f"Saved JSON to {json_path}")
        except Exception as e:
            logger.error(f"Error saving NSEI vs nBEI plot files: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error generating efficiency scatter plots: {str(e)}", exc_info=True)
        
        
def plot_activity_visualizations(df_results: pd.DataFrame, activity_folder: str) -> None:
    """
    Generate activity-related interactive visualizations with Plotly.
    
    Args:
        df_results: DataFrame containing the compound analysis results
        activity_folder: Directory to save activity visualizations
    """
    try:
        # Skip if required columns are missing
        if 'Activity Type' not in df_results.columns or 'pActivity' not in df_results.columns:
            logger.warning("Activity columns missing, skipping activity visualizations")
            return
        
        # 1. Activity Distribution box plot
        activity_box_fig = px.box(
            df_results, 
            x='Activity Type', 
            y='pActivity',
            color='Activity Type',
            points='all',
            hover_data=['ChEMBL ID', 'Molecule Name'],
            title='Activity Distribution by Type',
            labels={'pActivity': 'pActivity (-log10[M])', 'Activity Type': 'Activity Type'},
            height=600
        )
        
        activity_box_fig.update_layout(
            template='plotly_white',
            xaxis_title='Activity Type',
            yaxis_title='pActivity (-log10[M])'
        )
        
        activity_box_fig.write_html(os.path.join(activity_folder, 'activity_distribution.html'))
        activity_box_fig_json = activity_box_fig.to_json()
        with open(os.path.join(activity_folder, 'activity_distribution.json'), 'w') as f:
            f.write(activity_box_fig_json)
        
        # 2. Add PSAoMW vs QED plot (new plot)
        if all(col in df_results.columns for col in ['TPSA', 'Molecular Weight', 'QED']):
            # Create PSAoMW column
            df_plot = df_results.copy()
            df_plot['PSAoMW'] = df_plot['TPSA'] / df_plot['Molecular Weight']
            
            # Create the plot
            psaomw_qed_fig = px.scatter(
                df_plot.dropna(subset=['PSAoMW', 'QED']),
                x='QED',
                y='PSAoMW',
                color='Activity Type',
                hover_name='ChEMBL ID',
                hover_data=['Molecule Name', 'Activity (nM)', 'TPSA', 'Molecular Weight'],
                title='PSA/MW vs Drug-likeness (QED)',
                labels={'PSAoMW': 'PSA/MW Ratio', 'QED': 'QED (Drug-likeness)'},
                height=600
            )
            
            psaomw_qed_fig.update_layout(
                template='plotly_white'
            )
            
            psaomw_qed_fig.write_html(os.path.join(activity_folder, 'PSAoMW_vs_QED.html'))
            psaomw_qed_fig_json = psaomw_qed_fig.to_json()
            with open(os.path.join(activity_folder, 'PSAoMW_vs_QED.json'), 'w') as f:
                f.write(psaomw_qed_fig_json)
    
    except Exception as e:
        logger.error(f"Error generating activity visualizations: {str(e)}")

# Fix for the plot_property_visualizations function in visualization.py

def plot_property_visualizations(df_results: pd.DataFrame, sei_folder: str, bei_folder: str) -> None:
    """
    Generate SEI and BEI interactive visualizations with Plotly.
    
    Args:
        df_results: DataFrame containing the compound analysis results
        sei_folder: Directory to save SEI visualizations
        bei_folder: Directory to save BEI visualizations
    """
    try:
        # Create display name for legend - use Molecule Name if available, ChEMBL ID if not
        df_results['DisplayName'] = df_results.apply(
            lambda row: row['Molecule Name'] if pd.notna(row['Molecule Name']) and row['Molecule Name'] != 'Unknown Name' 
            else row['ChEMBL ID'], 
            axis=1
        )
        
        # Function to create clustered box plots - with proper unique data points
        def create_clustered_boxplots(df, metrics, folder, title_prefix):
            """
            Create box plots grouped in clusters of 5 compounds
            
            Args:
                df: DataFrame with data
                metrics: List of metrics to create plots for (e.g. ['SEI', 'NSEI'])
                folder: Output folder
                title_prefix: Prefix for plot titles
            """
            # Get unique compounds
            unique_chembl_ids = df['ChEMBL ID'].unique()
            
            # Skip if no compounds
            if len(unique_chembl_ids) == 0:
                return
            
            # Create clusters of 5 compounds
            cluster_size = 5
            compound_clusters = [unique_chembl_ids[i:i+cluster_size] for i in range(0, len(unique_chembl_ids), cluster_size)]
            
            # Process each metric
            for metric in metrics:
                # Skip if the metric is not in the data
                if metric not in df.columns:
                    logger.warning(f"Metric {metric} not found in DataFrame")
                    continue
                
                # Get valid data for this metric
                valid_data = df.dropna(subset=[metric]).copy()
                if valid_data.empty:
                    logger.warning(f"No valid data for {metric}")
                    continue
                
                metric_title = {
                    'SEI': 'Surface Efficiency Index',
                    'NSEI': 'Normalized Surface Efficiency Index',
                    'BEI': 'Binding Efficiency Index',
                    'nBEI': 'Normalized Binding Efficiency Index'
                }.get(metric, metric)
                
                # Create a box plot for each cluster
                for i, cluster in enumerate(compound_clusters):
                    # Filter data for this cluster
                    cluster_data = valid_data[valid_data['ChEMBL ID'].isin(cluster)]
                    
                    # Skip if no data for this cluster
                    if cluster_data.empty:
                        continue
                    
                    # Process each unique ChEMBL ID to avoid duplicates
                    plot_data = []
                    for chembl_id in cluster:
                        compound_data = cluster_data[cluster_data['ChEMBL ID'] == chembl_id]
                        if not compound_data.empty:
                            # Use the first occurrence for display name
                            display_name = compound_data['DisplayName'].iloc[0]
                            
                            # Add each data point with needed metadata
                            for _, row in compound_data.iterrows():
                                plot_data.append({
                                    'ChEMBL ID': chembl_id,
                                    'DisplayName': display_name,
                                    'Value': row[metric],
                                    'Metric': metric,
                                    'Molecule Name': row['Molecule Name'],
                                    'Activity Type': row.get('Activity Type', 'Unknown'),
                                    'Activity (nM)': row.get('Activity (nM)', float('nan'))
                                })
                    
                    # Skip if no valid data for plotting
                    if not plot_data:
                        continue
                    
                    # Convert to DataFrame
                    plot_df = pd.DataFrame(plot_data)
                    
                    # Create boxplot
                    fig = px.box(
                        plot_df,
                        x='ChEMBL ID',
                        y='Value',
                        color='ChEMBL ID',
                        points='all',
                        hover_data=['Molecule Name', 'Activity Type', 'Activity (nM)'],
                        title=f'{metric_title} Distribution (Group {i+1} of {len(compound_clusters)})',
                        labels={'Value': metric, 'ChEMBL ID': 'Compound'},
                        height=600
                    )
                    
                    # Update the legend to use DisplayName
                    for trace in fig.data:
                        chembl_id = trace.name
                        display_names = plot_df[plot_df['ChEMBL ID'] == chembl_id]['DisplayName'].unique()
                        if len(display_names) > 0:
                            trace.name = display_names[0]
                    
                    fig.update_layout(
                        template='plotly_white',
                        xaxis_tickangle=-45,
                        legend_title_text='Compound'
                    )
                    
                    # Add navigation info
                    if len(compound_clusters) > 1:
                        prev_group = i - 1 if i > 0 else len(compound_clusters) - 1
                        next_group = i + 1 if i < len(compound_clusters) - 1 else 0
                        nav_text = f"◀ Group {prev_group+1} | Group {next_group+1} ▶"
                        
                        fig.add_annotation(
                            text=nav_text,
                            xref="paper", yref="paper",
                            x=0.5, y=1.05,
                            showarrow=False,
                            font=dict(size=12)
                        )
                    
                    # Save files
                    metric_lower = metric.lower()
                    html_path = os.path.join(folder, f'{metric_lower}_boxplot_group{i+1}.html')
                    fig.write_html(html_path)
                    
                    json_path = os.path.join(folder, f'{metric_lower}_boxplot_group{i+1}.json')
                    fig_json = fig.to_json()
                    with open(json_path, 'w') as f:
                        f.write(fig_json)
        
        # Create SEI/NSEI boxplots
        if any(col in df_results.columns for col in ['SEI', 'NSEI']):
            create_clustered_boxplots(
                df_results, 
                ['SEI', 'NSEI'], 
                sei_folder, 
                'Surface Efficiency Index'
            )
        
        # Create BEI/nBEI boxplots
        if any(col in df_results.columns for col in ['BEI', 'nBEI']):
            create_clustered_boxplots(
                df_results, 
                ['BEI', 'nBEI'], 
                bei_folder, 
                'Binding Efficiency Index'
            )
    
    except Exception as e:
        logger.error(f"Error generating property visualizations: {str(e)}")
        st.error(f"Error in property visualizations: {str(e)}")

def generate_molecular_structures(df_results: pd.DataFrame, structure_folder: str) -> None:
    """
    Generate 2D and 3D molecular structure files for all compounds.
    
    Args:
        df_results: DataFrame containing the compound analysis results
        structure_folder: Directory to save structure files
    """
    try:
        # Get unique ChEMBL IDs and corresponding SMILES
        unique_chembl_data = df_results[['ChEMBL ID', 'SMILES', 'Molecule Name']].drop_duplicates().reset_index(drop=True)
        
        # Create a directory for 2D images and 3D models
        os.makedirs(os.path.join(structure_folder, '2D'), exist_ok=True)
        os.makedirs(os.path.join(structure_folder, '3D'), exist_ok=True)
        
        # Create structure information dictionary
        structure_info = []
        
        for _, row in unique_chembl_data.iterrows():
            chembl_id = row['ChEMBL ID']
            smiles = row['SMILES']
            mol_name = row['Molecule Name'] if pd.notna(row['Molecule Name']) else chembl_id
            
            if not pd.isna(smiles) and smiles != 'N/A':
                try:
                    # Generate 2D structure image
                    mol = Chem.MolFromSmiles(smiles)
                    if mol:
                        # Save 2D image
                        img_path = os.path.join(structure_folder, '2D', f"{chembl_id}.png")
                        img = Draw.MolToImage(mol, size=(400, 400))
                        img.save(img_path)
                        
                        # Create 3D structure for visualization
                        mol_3d = Chem.AddHs(mol)
                        AllChem.EmbedMolecule(mol_3d, randomSeed=42)
                        AllChem.MMFFOptimizeMolecule(mol_3d)
                        
                        # Save as PDB for 3D visualization
                        pdb_path = os.path.join(structure_folder, '3D', f"{chembl_id}.pdb")
                        pdb_block = Chem.MolToPDBBlock(mol_3d)
                        with open(pdb_path, 'w') as f:
                            f.write(pdb_block)
                        
                        # Create JSON with molecule data
                        json_path = os.path.join(structure_folder, f"{chembl_id}.json")
                        mol_props = {
                            'ChEMBL ID': chembl_id,
                            'Molecule Name': mol_name,
                            'SMILES': smiles,
                            'InChI': Chem.MolToInchi(mol) if mol else '',
                            'InChIKey': Chem.MolToInchiKey(mol) if mol else '',
                            'Formula': Chem.rdMolDescriptors.CalcMolFormula(mol) if mol else '',
                            'Exact Mass': Chem.rdMolDescriptors.CalcExactMolWt(mol) if mol else None,
                            '2D_Image': f"2D/{chembl_id}.png",
                            '3D_Model': f"3D/{chembl_id}.pdb"
                        }
                        
                        with open(json_path, 'w') as f:
                            json.dump(mol_props, f, indent=2)
                        
                        structure_info.append(mol_props)
                except Exception as e:
                    logger.error(f"Error generating structures for {chembl_id}: {str(e)}")
        
        # Create summary file
        with open(os.path.join(structure_folder, 'structure_info.json'), 'w') as f:
            json.dump(structure_info, f, indent=2)
    
    except Exception as e:
        logger.error(f"Error generating molecular structures: {str(e)}")

def display_interactive_plot(plot_path: str) -> None:
    """
    Display interactive Plotly plot in Streamlit.
    
    Args:
        plot_path: Path to the Plotly JSON file
    """
    try:
        logger.info(f"Loading plot from: {plot_path}")
        
        # Check if file exists and has content
        if not os.path.exists(plot_path):
            logger.error(f"Plot file does not exist: {plot_path}")
            st.error(f"Plot file does not exist: {plot_path}")
            return
            
        # Check file size
        file_size = os.path.getsize(plot_path)
        if file_size == 0:
            logger.error(f"Plot file is empty: {plot_path}")
            st.error(f"Plot file is empty: {plot_path}")
            return
            
        logger.info(f"Plot file size: {file_size} bytes")
        
        with open(plot_path, 'r') as f:
            fig_json = f.read()
            
            try:
                # Attempt to parse JSON
                plot_data = json.loads(fig_json)
                fig = go.Figure(plot_data)
                st.plotly_chart(fig, use_container_width=True)
                logger.info(f"Successfully displayed plot from {plot_path}")
                
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in plot file {plot_path}: {str(e)}")
                st.error(f"Invalid plot data. Try regenerating the plot.")
                # Show part of the JSON for debugging
                if len(fig_json) > 100:
                    logger.error(f"JSON content (first 100 chars): {fig_json[:100]}...")
                else:
                    logger.error(f"JSON content: {fig_json}")
                    
    except Exception as e:
        logger.error(f"Error displaying interactive plot: {str(e)}")
        st.error(f"Could not load plot: {str(e)}")
        st.info("Try regenerating the plot by reprocessing the compound.")

# In visualization.py, modify the show_interactive_plots function:

# Fix for the show_interactive_plots function to replace st.experimental_rerun
def show_interactive_plots(folder_path: str, plot_type: str) -> None:
    """
    Display interactive plots with navigation controls and error handling.
    Includes toggle functionality for SEI/NSEI and BEI/nBEI metrics.
    
    Args:
        folder_path: Path to folder containing plots
        plot_type: Type of plot to display
    """
    try:
        logger.info(f"Attempting to show {plot_type} plots from {folder_path}")
        
        # Check if the folder exists
        if not os.path.exists(folder_path):
            logger.warning(f"Plot folder does not exist: {folder_path}")
            st.warning(f"Plot folder does not exist: {folder_path}")
            return
        
        # Get plot files based on type
        if plot_type == "scatter":
            # Define the expected scatter plot files
            expected_files = [
                {"name": "SEI vs BEI", "path": os.path.join(folder_path, "sei_vs_bei_scatter_plot.json")},
                {"name": "NSEI vs nBEI", "path": os.path.join(folder_path, "nsei_vs_nbei_scatter_plot.json")}
            ]
            
            # Filter to only include files that actually exist
            plot_files = [f for f in expected_files if os.path.exists(f["path"])]
            state_key = "scatter_plot_index"
            
            # Display plots
            if plot_files:
                # Initialize state if not set
                if state_key not in st.session_state:
                    st.session_state[state_key] = 0
                
                # Ensure the index is within bounds
                if st.session_state[state_key] >= len(plot_files):
                    st.session_state[state_key] = 0
                
                # Plot selection
                selected_plot = st.selectbox(
                    "Select Plot:",
                    [p["name"] for p in plot_files],
                    index=st.session_state[state_key],
                    key=f"select_{plot_type}"
                )
                # Update index based on selection
                selected_idx = [p["name"] for p in plot_files].index(selected_plot)
                if st.session_state[state_key] != selected_idx:
                    st.session_state[state_key] = selected_idx
                
                # Display selected plot
                current_plot = plot_files[st.session_state[state_key]]
                if os.path.exists(current_plot["path"]):
                    display_interactive_plot(current_plot["path"])
                else:
                    st.warning(f"Plot file not found: {current_plot['path']}")
            else:
                st.info("No scatter plots are available.")
            
        elif plot_type == "activity":
            # Get all JSON files in the Activity folder
            activity_folder = os.path.join(folder_path, "Activity")
            
            if not os.path.exists(activity_folder):
                logger.warning(f"Activity folder does not exist: {activity_folder}")
                st.warning(f"Activity plots folder does not exist")
                return
                
            json_files = glob.glob(os.path.join(activity_folder, "*.json"))
            plot_files = [{"name": os.path.basename(f).replace(".json", ""), "path": f} for f in json_files]
            state_key = "activity_index"
            
            # Display plots
            if plot_files:
                # Initialize state if not set
                if state_key not in st.session_state:
                    st.session_state[state_key] = 0
                
                # Ensure the index is within bounds
                if st.session_state[state_key] >= len(plot_files):
                    st.session_state[state_key] = 0
                
                # Plot selection
                selected_plot = st.selectbox(
                    "Select Activity Plot:",
                    [p["name"] for p in plot_files],
                    index=st.session_state[state_key],
                    key=f"select_{plot_type}"
                )
                # Update index based on selection
                selected_idx = [p["name"] for p in plot_files].index(selected_plot)
                if st.session_state[state_key] != selected_idx:
                    st.session_state[state_key] = selected_idx
                
                # Display selected plot
                current_plot = plot_files[st.session_state[state_key]]
                if os.path.exists(current_plot["path"]):
                    display_interactive_plot(current_plot["path"])
                else:
                    st.warning(f"Plot file not found: {current_plot['path']}")
            else:
                st.info("No activity plots are available.")
            
        elif plot_type == "sei":
            sei_folder = os.path.join(folder_path, "SEI")
            
            if not os.path.exists(sei_folder):
                logger.warning(f"SEI folder does not exist: {sei_folder}")
                st.warning(f"SEI plots folder does not exist")
                return
            
            # Toggle between SEI and NSEI
            # Initialize toggle state if not set
            if "sei_metric_toggle" not in st.session_state:
                st.session_state.sei_metric_toggle = "SEI"
            
            # Toggle selection
            col1, col2 = st.columns([1, 3])
            with col1:
                selected_metric = st.radio(
                    "Select Metric:",
                    ["SEI", "NSEI"],
                    index=0 if st.session_state.sei_metric_toggle == "SEI" else 1,
                    key="sei_metric_selector"
                )
                st.session_state.sei_metric_toggle = selected_metric
            
            with col2:
                st.info(f"**{'Surface Efficiency Index' if selected_metric == 'SEI' else 'Normalized Surface Efficiency Index'}**: "
                        f"{'Measures activity relative to polar surface area' if selected_metric == 'SEI' else 'SEI normalized by the number of polar atoms'}")
            
            # Look for group-based boxplots matching the selected metric
            metric_lower = selected_metric.lower()
            group_files = glob.glob(os.path.join(sei_folder, f"{metric_lower}_boxplot_group*.json"))
            
            if group_files:
                # Sort them properly by group number
                def get_group_num(filename):
                    import re
                    match = re.search(r'group(\d+)', filename)
                    return int(match.group(1)) if match else 0
                
                group_files.sort(key=get_group_num)
                plot_files = [{"name": f"{selected_metric} Group {get_group_num(f)}", "path": f} for f in group_files]
                
                # Initialize index if not set
                if "sei_group_index" not in st.session_state:
                    st.session_state.sei_group_index = 0
                
                # Ensure the index is within bounds
                if st.session_state.sei_group_index >= len(plot_files):
                    st.session_state.sei_group_index = 0
                
                # Add navigation buttons for groups
                col1, col2, col3 = st.columns([1, 3, 1])
                
                # Define navigation callbacks
                def go_to_prev_sei_group():
                    st.session_state.sei_group_index = (st.session_state.sei_group_index - 1) % len(plot_files)
                
                def go_to_next_sei_group():
                    st.session_state.sei_group_index = (st.session_state.sei_group_index + 1) % len(plot_files)
                
                with col1:
                    st.button("◀ Previous Group", key="prev_sei_group", on_click=go_to_prev_sei_group)
                
                with col2:
                    group_idx = st.selectbox(
                        "Select Group:",
                        range(1, len(plot_files) + 1),
                        index=st.session_state.sei_group_index,
                        format_func=lambda x: f"Group {x}",
                        key="sei_group_selector"
                    )
                    # Update index based on selection (zero-based)
                    new_idx = group_idx - 1
                    if st.session_state.sei_group_index != new_idx:
                        st.session_state.sei_group_index = new_idx
                
                with col3:
                    st.button("Next Group ▶", key="next_sei_group", on_click=go_to_next_sei_group)
                
                # Display the current plot
                current_plot = plot_files[st.session_state.sei_group_index]
                if os.path.exists(current_plot["path"]):
                    display_interactive_plot(current_plot["path"])
                else:
                    st.warning(f"Plot file not found: {current_plot['path']}")
            else:
                # No group files found
                st.info(f"No {selected_metric} box plots available. This may happen if there's insufficient data.")
        
        elif plot_type == "bei":
            bei_folder = os.path.join(folder_path, "BEI")
            
            if not os.path.exists(bei_folder):
                logger.warning(f"BEI folder does not exist: {bei_folder}")
                st.warning(f"BEI plots folder does not exist")
                return
            
            # Toggle between BEI and nBEI
            # Initialize toggle state if not set
            if "bei_metric_toggle" not in st.session_state:
                st.session_state.bei_metric_toggle = "BEI"
            
            # Toggle selection
            col1, col2 = st.columns([1, 3])
            with col1:
                selected_metric = st.radio(
                    "Select Metric:",
                    ["BEI", "nBEI"],
                    index=0 if st.session_state.bei_metric_toggle == "BEI" else 1,
                    key="bei_metric_selector"
                )
                st.session_state.bei_metric_toggle = selected_metric
            
            with col2:
                st.info(f"**{'Binding Efficiency Index' if selected_metric == 'BEI' else 'Normalized Binding Efficiency Index'}**: "
                        f"{'Measures activity relative to molecular weight' if selected_metric == 'BEI' else 'BEI normalized considering heavy atoms'}")
            
            # Look for group-based boxplots matching the selected metric
            metric_lower = selected_metric.lower()
            group_files = glob.glob(os.path.join(bei_folder, f"{metric_lower}_boxplot_group*.json"))
            
            if group_files:
                # Sort them properly by group number
                def get_group_num(filename):
                    import re
                    match = re.search(r'group(\d+)', filename)
                    return int(match.group(1)) if match else 0
                
                group_files.sort(key=get_group_num)
                plot_files = [{"name": f"{selected_metric} Group {get_group_num(f)}", "path": f} for f in group_files]
                
                # Initialize index if not set
                if "bei_group_index" not in st.session_state:
                    st.session_state.bei_group_index = 0
                
                # Ensure the index is within bounds
                if st.session_state.bei_group_index >= len(plot_files):
                    st.session_state.bei_group_index = 0
                
                # Add navigation buttons for groups
                col1, col2, col3 = st.columns([1, 3, 1])
                
                # Define navigation callbacks
                def go_to_prev_bei_group():
                    st.session_state.bei_group_index = (st.session_state.bei_group_index - 1) % len(plot_files)
                
                def go_to_next_bei_group():
                    st.session_state.bei_group_index = (st.session_state.bei_group_index + 1) % len(plot_files)
                
                with col1:
                    st.button("◀ Previous Group", key="prev_bei_group", on_click=go_to_prev_bei_group)
                
                with col2:
                    group_idx = st.selectbox(
                        "Select Group:",
                        range(1, len(plot_files) + 1),
                        index=st.session_state.bei_group_index,
                        format_func=lambda x: f"Group {x}",
                        key="bei_group_selector"
                    )
                    # Update index based on selection (zero-based)
                    new_idx = group_idx - 1
                    if st.session_state.bei_group_index != new_idx:
                        st.session_state.bei_group_index = new_idx
                
                with col3:
                    st.button("Next Group ▶", key="next_bei_group", on_click=go_to_next_bei_group)
                
                # Display the current plot
                current_plot = plot_files[st.session_state.bei_group_index]
                if os.path.exists(current_plot["path"]):
                    display_interactive_plot(current_plot["path"])
                else:
                    st.warning(f"Plot file not found: {current_plot['path']}")
            else:
                # No group files found
                st.info(f"No {selected_metric} box plots available. This may happen if there's insufficient data.")
        
        else:
            logger.warning(f"Unknown plot type: {plot_type}")
            st.warning(f"Unknown plot type: {plot_type}")
    
    except Exception as e:
        logger.error(f"Error displaying {plot_type} plots: {str(e)}")
        st.error(f"Error displaying plots: {str(e)}")
        
# Update in show_molecular_structures function in visualization.py
def show_molecular_structures(compound_folder: str) -> None:
    """
    Display molecular structures with 2D/3D toggle option.
    
    Args:
        compound_folder: Path to compound folder
    """
    try:
        structure_folder = os.path.join(compound_folder, "Structures")
        structure_info_path = os.path.join(structure_folder, "structure_info.json")
        
        if not os.path.exists(structure_info_path):
            st.warning("No structure information available.")
            return
        
        with open(structure_info_path, 'r') as f:
            structure_info = json.load(f)
        
        if not structure_info:
            st.warning("No molecular structures available.")
            return
        
        # Create a dropdown to select molecules
        selected_molecule = st.selectbox(
            "Select Molecule:",
            options=[f"{mol['ChEMBL ID']} - {mol['Molecule Name']}" for mol in structure_info],
            key="analysis_molecule_selector"
        )
        
        # Get selected molecule info
        selected_idx = next((i for i, mol in enumerate(structure_info) 
                            if f"{mol['ChEMBL ID']} - {mol['Molecule Name']}" == selected_molecule), 0)
        mol_data = structure_info[selected_idx]
        
        # Display molecule info
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("Molecule Information")
            st.write(f"**ChEMBL ID:** {mol_data['ChEMBL ID']}")
            st.write(f"**Name:** {mol_data['Molecule Name']}")
            st.write(f"**Formula:** {mol_data['Formula']}")
            st.write(f"**Exact Mass:** {mol_data['Exact Mass']:.4f}")
            st.write(f"**SMILES:** `{mol_data['SMILES']}`")
            
            # Add download options with a unique key
            st.download_button(
                "Download Structure Data (JSON)",
                data=json.dumps(mol_data, indent=2),
                file_name=f"{mol_data['ChEMBL ID']}_structure.json",
                mime="application/json",
                key=f"analysis_download_{mol_data['ChEMBL ID']}"
            )
        
        with col2:
            # Create tabs for 2D and 3D visualization
            view_mode = st.radio("Select View Mode:", ["2D Structure", "3D Structure"], horizontal=True)
            
            if view_mode == "2D Structure":
                img_path = os.path.join(structure_folder, mol_data['2D_Image'])
                if os.path.exists(img_path):
                    # Updated to use_container_width instead of use_column_width
                    st.image(img_path, use_container_width=True)
                else:
                    st.warning("2D structure image not available.")
            else:  # 3D Structure
                pdb_path = os.path.join(structure_folder, mol_data['3D_Model'])
                if os.path.exists(pdb_path):
                    # Load PDB content for visualization
                    with open(pdb_path, 'r') as f:
                        pdb_block = f.read()
                    
                    # Use py3Dmol for visualization
                    st_3dmol_viewer(pdb_block)
                else:
                    st.warning("3D structure model not available.")
    
    except Exception as e:
        logger.error(f"Error displaying molecular structures: {str(e)}")
        st.error(f"Error displaying molecular structures: {str(e)}")

def st_3dmol_viewer(pdb_block: str) -> None:
    """
    Create a 3Dmol.js viewer in Streamlit using HTML.
    
    Args:
        pdb_block: PDB content as string
    """
    # Create HTML component for 3Dmol viewer
    html_content = f"""
    <script src="https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.0.1/3Dmol-min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.3/jquery.min.js"></script>
    <style>
        .mol-container {{
            width: 100%;
            height: 400px;
            position: relative;
        }}
    </style>
    <div id="3dmol-viewer" class="mol-container"></div>
    <script>
        let viewer = $3Dmol.createViewer($("#3dmol-viewer"), {{backgroundColor: "white"}});
        let pdbData = `{pdb_block}`;
        viewer.addModel(pdbData, "pdb");
        viewer.setStyle({{}}, {{stick: {{}}}});
        viewer.zoomTo();
        viewer.render();
    </script>
    """
    
    # Display HTML in Streamlit
    st.components.v1.html(html_content, height=450)