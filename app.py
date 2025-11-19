import os
import logging
import streamlit as st
import pandas as pd
import json
from config import RESULTS_DIR, ACTIVITY_TYPES
from modules.utils import get_available_compounds, validate_csv_file, zip_results, zip_compound_results
from modules.compound_manager import process_and_store, display_compound_summary, process_csv_batch
from modules.data_processor import load_results, get_compound_folder
from modules.visualization import show_interactive_plots, show_molecular_structures
#from modules.molecule_viewer import molecule_viewer_app
from modules.api_client import batch_fetch_activities

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
st.set_page_config(layout="wide")

# Start background upload worker (only once at app startup)
from modules.upload_worker import start_upload_worker
from modules.azure_storage import is_cloud_deployment

if is_cloud_deployment():
    start_upload_worker()
    logger.info("✅ Background upload worker initialized")
# Initialize session state
def init_session_state():
    """Initialize all session state variables."""
    state_vars = {
        "processing_complete": False,
        "compound_action": None,
        "new_compound_name": "",
        "confirm_choice": False,
        "error_state": None,
        "processing_progress": 0,
        "current_view": "home",  # Changed default to 'home' for landing page
        "selected_compound": None,
        "compound_search_query": "",
        "selected_plots": [],
        "batch_processing": False,
        "processing_compound": None,
        "compounds_to_process": [],
        "last_processed_compound": None,
        "show_new_compound_alert": False,
        "selected_activity_types": ACTIVITY_TYPES,  # Default to all activity types
        "last_similarity_threshold": 90,  # Default similarity threshold
        "molecule_viewer_tab": "3D",  # Default tab for molecule viewer
        "show_delete_confirmation": False,  # Add this new line
        "deletion_success": False  # Add this new line
    }
    
    for var, default in state_vars.items():
        if var not in st.session_state:
            st.session_state[var] = default

def reset_processing_state():
    """Reset all processing-related session state variables."""
    st.session_state.processing_complete = False
    st.session_state.compound_action = None
    st.session_state.confirm_choice = False
    st.session_state.error_state = None
    st.session_state.processing_progress = 0

def display_home_view():
    """Display the home/landing page with compound search and listing (using lightweight metadata)."""
    from modules.metadata_manager import get_all_compounds_metadata

    st.markdown("""
    <style>
    .app-title {
        font-size: 2.2rem;
        font-weight: 600;
        color: #4a86e8;
        margin-bottom: 1.5rem;
    }
    .subtitle {
        font-size: 1.3rem;
        font-weight: 400;
        color: #7c7c7c;
        margin-top: -1rem;
        margin-bottom: 2rem;
    }
    </style>
    <h1 class="app-title">🔬 IMPs Navigator</h1>
    <p class="subtitle">Compound Library & Analysis Tool for better Insights</p>
    """, unsafe_allow_html=True)

    # Top controls for searching and adding new compounds
    search_col, button_col = st.columns([4, 1])
    with search_col:
        search_query = st.text_input(
            "Search compounds:",
            value=st.session_state.compound_search_query,
            placeholder="Enter compound name...",
            key="compound_search",
            label_visibility="collapsed"
        )
        st.session_state.compound_search_query = search_query

    with button_col:
        if st.button("➕ New Compound", key="add_new_compound", use_container_width=True):
            st.session_state.current_view = "analyze"
            st.rerun()

    # Get metadata for all compounds (fast - only downloads metadata CSV ~100KB)
    metadata_df = get_all_compounds_metadata()

    if metadata_df is None or metadata_df.empty:
        st.info("No compounds have been analyzed yet. Click '➕ New Compound' to get started.")
        return

    # Filter compounds based on search query
    if search_query:
        filtered_df = metadata_df[metadata_df['compound_name'].str.lower().str.contains(search_query.lower())]
    else:
        filtered_df = metadata_df

    if filtered_df.empty:
        st.warning(f"No compounds found matching '{search_query}'")
        return

    # Display compounds in a grid
    st.subheader(f"Available Compounds ({len(filtered_df)})")

    # Add styling for consistent cards
    st.markdown("""
    <style>
    .compound-card {
        height: 1px !important;
        overflow: hidden;
    }
    </style>
    """, unsafe_allow_html=True)

    # Create a grid of compounds - 4 columns
    cols = st.columns(4)
    for i, row in enumerate(filtered_df.itertuples()):
        with cols[i % 4]:
            # Create a single container for the entire card with a border
            with st.container(border=True):
                # Compound name centered
                compound_name = row.compound_name
                st.markdown(f"<h4 style='text-align: center; margin: 5px 0;'>{compound_name}</h4>", unsafe_allow_html=True)

                # Display the molecular structure from SMILES
                try:
                    smiles = row.smiles if hasattr(row, 'smiles') and row.smiles else None

                    if smiles and smiles != '' and smiles != 'nan':
                        from rdkit import Chem
                        from rdkit.Chem import Draw
                        import base64
                        from io import BytesIO

                        # Generate the molecular image
                        mol = Chem.MolFromSmiles(smiles)
                        if mol:
                            img = Draw.MolToImage(mol, size=(350, 250))

                            # Convert image to base64 for HTML display
                            buffered = BytesIO()
                            img.save(buffered, format="PNG")
                            img_str = base64.b64encode(buffered.getvalue()).decode()

                            # Display the image in a centered container
                            st.markdown(
                                f'<div style="display: flex; justify-content: center; padding: 10px;">'
                                f'<img src="data:image/png;base64,{img_str}" alt="{compound_name}" />'
                                f'</div>',
                                unsafe_allow_html=True
                            )
                        else:
                            st.info("Structure not available")
                    else:
                        st.info("Structure not available")
                except Exception as e:
                    logger.error(f"Error rendering molecule for {compound_name}: {str(e)}")
                    st.info("Structure not available")

                # Display compound statistics from metadata
                # Row 1: ChEMBL ID
                if hasattr(row, 'chembl_id') and row.chembl_id and str(row.chembl_id) != 'nan':
                    st.markdown(f"<small style='color: #666;'>ChEMBL: {row.chembl_id}</small>", unsafe_allow_html=True)

                # Row 2: Total Activities and Outliers
                col1, col2 = st.columns(2)
                with col1:
                    total_activities = row.total_activities if hasattr(row, 'total_activities') else 0
                    st.markdown(f"**Activities:** {total_activities}")

                with col2:
                    num_outliers = row.num_outliers if hasattr(row, 'num_outliers') else 0
                    st.markdown(f"**Outliers:** {num_outliers}")

                # Row 3: QED and Similarity Threshold
                col1, col2 = st.columns(2)
                with col1:
                    qed = row.qed if hasattr(row, 'qed') else 0.0
                    st.markdown(f"**QED:** {qed:.2f}")

                with col2:
                    similarity_threshold = row.similarity_threshold if hasattr(row, 'similarity_threshold') else 90
                    st.markdown(f"**Similarity:** {similarity_threshold}%")

                # Button to view compound details
                if st.button(f"View Details", key=f"view_{compound_name}", type="primary", use_container_width=True):
                    st.session_state.selected_compound = compound_name
                    st.session_state.current_view = "compound_details"
                    st.rerun()
    
    # Download all results button at the bottom
    st.markdown("### Batch Operations")
    if st.button("📥 Download All Results (ZIP)", key="download_all"):
        with st.spinner("Creating ZIP of all results..."):
            zip_file = zip_results()
            if zip_file:
                with open(zip_file, "rb") as f:
                    st.download_button(
                        "📥 Download ZIP",
                        f,
                        file_name=zip_file,
                        mime="application/zip",
                        key="download_zip_button"
                    )
def display_delete_confirmation():
    """Display confirmation dialog for compound deletion."""
    st.markdown("### ❗ Confirm Deletion")
    st.warning(
        f"You are about to delete **{st.session_state.selected_compound}** and all associated data. "
        "This action cannot be undone."
    )
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("❌ Cancel", key="cancel_delete", use_container_width=True):
            st.session_state.show_delete_confirmation = False
            st.rerun()
    
    with col2:
        if st.button("🗑️ Delete Permanently", key="confirm_delete", use_container_width=True):
            with st.spinner(f"Deleting {st.session_state.selected_compound}..."):
                # Import here to avoid circular imports
                from modules.utils import delete_compound
                
                success = delete_compound(st.session_state.selected_compound)

                if success:
                    st.session_state.deletion_success = True
                    st.session_state.show_delete_confirmation = False
                    st.session_state.current_view = "home"
                    st.success(f"✅ {st.session_state.selected_compound} has been deleted successfully.")
                    st.session_state.selected_compound = None

                    # Clear any stale compound-related session state
                    if 'df_results' in st.session_state:
                        del st.session_state.df_results
                    if 'last_processed_compound' in st.session_state:
                        del st.session_state.last_processed_compound
                    if 'show_new_compound_alert' in st.session_state:
                        st.session_state.show_new_compound_alert = False
                else:
                    st.error(f"Failed to delete {st.session_state.selected_compound}. Please try again.")
                
                st.rerun()
                
def display_compound_details_view():
    """Display detailed view for a selected compound."""
    # Navigation controls
    # Add a delete button in the top navigation
    col1, col2, col3 = st.columns([1, 4, 1])
    with col1:
        if st.button("← Back", key="back_to_home"):
            st.session_state.current_view = "home"
            st.rerun()

    with col2:
        # Center the title using markdown with HTML
        st.markdown(f"<h1 style='text-align: center;'>🔬 {st.session_state.selected_compound}</h1>", unsafe_allow_html=True)

    with col3:
        if st.button("🗑️ Delete", key="delete_compound_btn", type="secondary", use_container_width=True):
            st.session_state.show_delete_confirmation = True
            st.rerun()

    # Add confirmation dialog if needed
    if 'show_delete_confirmation' not in st.session_state:
        st.session_state.show_delete_confirmation = False

    if st.session_state.show_delete_confirmation:
        display_delete_confirmation()
        
    selected_compound = st.session_state.selected_compound
    # Use the directory name directly without modifying it
    compound_folder = os.path.join(RESULTS_DIR, selected_compound)
    
    # Load compound data
    df_results = load_results(selected_compound)
    
    if df_results is None or df_results.empty:
        st.warning("No data available for this compound.")
        return
    #size 
    
    # Create tabs for different sections
    tabs = st.tabs([
        "📊 **Summary**", 
        "📈 **Interactive Plots**", 
        "🧪 **Molecules**", 
        "📋 **Data Table**",
        "⚙️ **Debug**"
    ])
    
    # Summary tab
    with tabs[0]:
        display_compound_summary(
            df_results=df_results,
            compound_name=selected_compound,
            similarity_threshold=st.session_state.last_similarity_threshold
        )
    
    # Interactive plots tab
    with tabs[1]:
        st.markdown("## 📊 Visualizations")
        st.info("💡 Expand sections below to generate plots on-demand with customizable parameters")

        # Initialize session state for cluster size
        if 'cluster_size' not in st.session_state:
            st.session_state.cluster_size = 5

        # Activity Distribution Expander
        with st.expander("📈 Activity Distribution", expanded=False):
            st.markdown("*Distribution of bioactivity values across different activity types*")

            if st.button("Generate Activity Distribution Plot", key="btn_activity"):
                import plotly.express as px

                # Check if required columns exist
                if 'Activity_Type' in df_results.columns and 'pActivity' in df_results.columns:
                    # Create activity distribution box plot
                    activity_box_fig = px.box(
                        df_results,
                        x='Activity_Type',
                        y='pActivity',
                        color='Activity_Type',
                        points='all',
                        hover_data=['ChEMBL_ID', 'Molecule_Name'],
                        title='Activity Distribution by Type',
                        labels={'pActivity': 'pActivity (-log10[M])', 'Activity_Type': 'Activity_Type'},
                        height=600
                    )

                    activity_box_fig.update_layout(
                        template='plotly_white',
                        xaxis_title='Activity_Type',
                        yaxis_title='pActivity (-log10[M])'
                    )

                    # Display the plot
                    st.plotly_chart(activity_box_fig, use_container_width=True)
                else:
                    st.warning("Activity data not available for this dataset")

        # Efficiency Scatter Plots Expander
        with st.expander("📊 Efficiency Scatter Plots", expanded=False):
            st.markdown("*Compare efficiency metrics (SEI vs BEI / NSEI vs NBEI)*")

            plot_type = st.radio(
                "Select Plot Type",
                ["SEI vs BEI", "NSEI vs NBEI"],
                key="scatter_plot_type",
                horizontal=True
            )

            if st.button("Generate Scatter Plot", key="btn_scatter"):
                from modules.visualization import show_static_plot_with_controls
                if plot_type == "SEI vs BEI":
                    show_static_plot_with_controls(df_results, "SEI", "BEI", compound_folder)
                else:
                    show_static_plot_with_controls(df_results, "NSEI", "NBEI", compound_folder)

        # Efficiency Boxplots Expander
        with st.expander("📦 Efficiency Boxplots (Grouped by Compound)", expanded=False):
            st.markdown("*Boxplots showing efficiency metric distributions grouped by compounds*")

            # Cluster size slider
            cluster_size = st.slider(
                "Compounds per group",
                min_value=3,
                max_value=20,
                value=st.session_state.cluster_size,
                step=1,
                key="boxplot_cluster_size",
                help="Adjust how many compounds are shown in each boxplot group"
            )
            st.session_state.cluster_size = cluster_size

            # Calculate number of groups
            num_unique_compounds = df_results['ChEMBL_ID'].nunique()
            num_groups = (num_unique_compounds + cluster_size - 1) // cluster_size  # Ceiling division
            st.caption(f"📊 Will create **{num_groups} groups** ({num_unique_compounds} compounds ÷ {cluster_size} per group)")

            # Create sub-tabs for SEI and BEI
            box_tabs = st.tabs(["SEI Metrics", "BEI Metrics"])

            with box_tabs[0]:
                st.markdown("**Surface Efficiency Index (SEI) Boxplots**")
                if st.button("Generate SEI Boxplots", key="btn_sei_box"):
                    import plotly.express as px

                    # Check if SEI or NSEI columns exist
                    sei_metrics = [col for col in ['SEI', 'NSEI'] if col in df_results.columns]

                    if not sei_metrics:
                        st.warning("SEI metrics not available for this dataset")
                    else:
                        # Get unique compounds and create clusters
                        unique_compounds = df_results['ChEMBL_ID'].unique().tolist()
                        compound_clusters = [unique_compounds[i:i + cluster_size]
                                           for i in range(0, len(unique_compounds), cluster_size)]

                        # Add DisplayName column if it doesn't exist
                        if 'DisplayName' not in df_results.columns:
                            df_results['DisplayName'] = df_results['ChEMBL_ID']

                        # Generate boxplots for each metric and cluster
                        for metric in sei_metrics:
                            st.markdown(f"#### {metric} Distribution")

                            # Filter valid data
                            valid_data = df_results[df_results[metric].notna()].copy()

                            if valid_data.empty:
                                st.warning(f"No valid data for {metric}")
                                continue

                            metric_title = {
                                'SEI': 'Surface Efficiency Index',
                                'NSEI': 'Normalized Surface Efficiency Index'
                            }.get(metric, metric)

                            # Create a box plot for each cluster
                            for i, cluster in enumerate(compound_clusters):
                                # Filter data for this cluster
                                cluster_data = valid_data[valid_data['ChEMBL_ID'].isin(cluster)]

                                if cluster_data.empty:
                                    continue

                                # Process each unique ChEMBL ID
                                plot_data = []
                                for chembl_id in cluster:
                                    compound_data = cluster_data[cluster_data['ChEMBL_ID'] == chembl_id]
                                    if not compound_data.empty:
                                        display_name = compound_data['DisplayName'].iloc[0]

                                        for _, row in compound_data.iterrows():
                                            plot_data.append({
                                                'ChEMBL_ID': chembl_id,
                                                'DisplayName': display_name,
                                                'Value': row[metric],
                                                'Metric': metric,
                                                'Molecule_Name': row['Molecule_Name'],
                                                'Activity_Type': row.get('Activity_Type', 'Unknown'),
                                                'Activity_nM': row.get('Activity_nM', float('nan'))
                                            })

                                if not plot_data:
                                    continue

                                # Convert to DataFrame
                                plot_df = pd.DataFrame(plot_data)

                                # Create boxplot
                                fig = px.box(
                                    plot_df,
                                    x='ChEMBL_ID',
                                    y='Value',
                                    color='ChEMBL_ID',
                                    points='all',
                                    hover_data=['Molecule_Name', 'Activity_Type', 'Activity_nM'],
                                    title=f'{metric_title} Distribution (Group {i+1} of {len(compound_clusters)})',
                                    labels={'Value': metric, 'ChEMBL_ID': 'Compound'},
                                    height=600
                                )

                                # Update legend to use DisplayName
                                for trace in fig.data:
                                    chembl_id = trace.name
                                    display_names = plot_df[plot_df['ChEMBL_ID'] == chembl_id]['DisplayName'].unique()
                                    if len(display_names) > 0:
                                        trace.name = display_names[0]

                                fig.update_layout(
                                    template='plotly_white',
                                    xaxis_tickangle=-45,
                                    legend_title_text='Compound'
                                )

                                # Display the plot
                                st.plotly_chart(fig, use_container_width=True)

            with box_tabs[1]:
                st.markdown("**Binding Efficiency Index (BEI) Boxplots**")
                if st.button("Generate BEI Boxplots", key="btn_bei_box"):
                    import plotly.express as px

                    # Check if BEI or nBEI columns exist
                    bei_metrics = [col for col in ['BEI', 'nBEI'] if col in df_results.columns]

                    if not bei_metrics:
                        st.warning("BEI metrics not available for this dataset")
                    else:
                        # Get unique compounds and create clusters
                        unique_compounds = df_results['ChEMBL_ID'].unique().tolist()
                        compound_clusters = [unique_compounds[i:i + cluster_size]
                                           for i in range(0, len(unique_compounds), cluster_size)]

                        # Add DisplayName column if it doesn't exist
                        if 'DisplayName' not in df_results.columns:
                            df_results['DisplayName'] = df_results['ChEMBL_ID']

                        # Generate boxplots for each metric and cluster
                        for metric in bei_metrics:
                            st.markdown(f"#### {metric} Distribution")

                            # Filter valid data
                            valid_data = df_results[df_results[metric].notna()].copy()

                            if valid_data.empty:
                                st.warning(f"No valid data for {metric}")
                                continue

                            metric_title = {
                                'BEI': 'Binding Efficiency Index',
                                'nBEI': 'Normalized Binding Efficiency Index'
                            }.get(metric, metric)

                            # Create a box plot for each cluster
                            for i, cluster in enumerate(compound_clusters):
                                # Filter data for this cluster
                                cluster_data = valid_data[valid_data['ChEMBL_ID'].isin(cluster)]

                                if cluster_data.empty:
                                    continue

                                # Process each unique ChEMBL ID
                                plot_data = []
                                for chembl_id in cluster:
                                    compound_data = cluster_data[cluster_data['ChEMBL_ID'] == chembl_id]
                                    if not compound_data.empty:
                                        display_name = compound_data['DisplayName'].iloc[0]

                                        for _, row in compound_data.iterrows():
                                            plot_data.append({
                                                'ChEMBL_ID': chembl_id,
                                                'DisplayName': display_name,
                                                'Value': row[metric],
                                                'Metric': metric,
                                                'Molecule_Name': row['Molecule_Name'],
                                                'Activity_Type': row.get('Activity_Type', 'Unknown'),
                                                'Activity_nM': row.get('Activity_nM', float('nan'))
                                            })

                                if not plot_data:
                                    continue

                                # Convert to DataFrame
                                plot_df = pd.DataFrame(plot_data)

                                # Create boxplot
                                fig = px.box(
                                    plot_df,
                                    x='ChEMBL_ID',
                                    y='Value',
                                    color='ChEMBL_ID',
                                    points='all',
                                    hover_data=['Molecule_Name', 'Activity_Type', 'Activity_nM'],
                                    title=f'{metric_title} Distribution (Group {i+1} of {len(compound_clusters)})',
                                    labels={'Value': metric, 'ChEMBL_ID': 'Compound'},
                                    height=600
                                )

                                # Update legend to use DisplayName
                                for trace in fig.data:
                                    chembl_id = trace.name
                                    display_names = plot_df[plot_df['ChEMBL_ID'] == chembl_id]['DisplayName'].unique()
                                    if len(display_names) > 0:
                                        trace.name = display_names[0]

                                fig.update_layout(
                                    template='plotly_white',
                                    xaxis_tickangle=-45,
                                    legend_title_text='Compound'
                                )

                                # Display the plot
                                st.plotly_chart(fig, use_container_width=True)

        # Molecular Properties Expander
        with st.expander("🧪 Molecular Properties (PSA/MW vs QED)", expanded=False):
            st.markdown("*Relationship between molecular properties and drug-likeness*")

            if st.button("Generate Property Plot", key="btn_properties"):
                import plotly.express as px

                # Check if required columns exist
                if all(col in df_results.columns for col in ['TPSA', 'Molecular_Weight', 'QED']):
                    # Create PSAoMW column
                    df_plot = df_results.copy()
                    df_plot['PSAoMW'] = df_plot['TPSA'] / df_plot['Molecular_Weight']

                    # Create the scatter plot
                    psaomw_qed_fig = px.scatter(
                        df_plot.dropna(subset=['PSAoMW', 'QED']),
                        x='QED',
                        y='PSAoMW',
                        color='Activity_Type',
                        hover_name='ChEMBL_ID',
                        hover_data=['Molecule_Name', 'Activity_nM', 'TPSA', 'Molecular_Weight'],
                        title='PSA/MW vs Drug-likeness (QED)',
                        labels={'PSAoMW': 'PSA/MW Ratio', 'QED': 'QED (Drug-likeness)'},
                        height=600
                    )

                    psaomw_qed_fig.update_layout(
                        template='plotly_white'
                    )

                    # Display the plot
                    st.plotly_chart(psaomw_qed_fig, use_container_width=True)
                else:
                    st.warning("Required molecular property data (TPSA, Molecular_Weight, QED) not available for this dataset")

        # Custom Visualization Builder Expander
        with st.expander("🎨 Custom Visualization Builder", expanded=False):
            st.markdown("*Build custom plots with your choice of metrics and styling*")
            from modules.custom_viz_builder import custom_visualization_builder
            custom_visualization_builder(df_results, selected_compound)
    
    # Molecule viewer tab
    with tabs[2]:
        # Only show sidebar when in Molecules tab
        from modules.molecule_viewer import molecule_viewer_app, get_molecule_style_controls

        st.subheader("🧪 Molecule Viewer")
        style_settings = get_molecule_style_controls(show_sidebar=True)


        # Call the viewer with the style settings and df_results for on-demand generation
        molecule_viewer_app(compound_folder, style_settings, df_results)
    
    # Data table tab with 4 sub-tabs
    with tabs[3]:
        st.subheader("📋 Data Tables")

        # Create sub-tabs for different data views
        data_tabs = st.tabs([
            "🧬 Data Analysis",
            "📊 Interpretation",
            "🔬 PDB Evidence",
            "📑 Complete Table"
        ])

        # Tab 1: Data Analysis (ChEMBL_ID to Subclass)
        with data_tabs[0]:
            st.markdown("**Core bioactivity and chemical classification data**")

            # Define columns for Data Analysis
            data_analysis_cols = [
                'ChEMBL_ID', 'Molecule_Name', 'SMILES',
                'Molecular_Weight', 'TPSA', 'HBD', 'HBA', 'Heavy_Atoms', 'NPOL', 'QED',
                'Activity_Type', 'Activity_nM', 'pActivity', 'Target_ChEMBL_ID', 'Target_Name',
                'SEI', 'BEI', 'NSEI', 'NBEI', 'nBEI_viz',
                'Modulus_SEI_BEI', 'Angle_SEI_BEI', 'Slope_SEI_BEI',
                'Modulus_NSEI_NBEI', 'Angle_NSEI_NBEI', 'Slope_NSEI_NBEI', 'Intercept_NSEI_NBEI',
                'SEI_Percentile', 'BEI_Percentile', 'NSEI_Percentile', 'NBEI_Percentile',
                'SEI_Zscore', 'BEI_Zscore', 'NSEI_Zscore', 'NBEI_Zscore',
                # Removed individual outlier flags (Is_SEI_Outlier, Is_BEI_Outlier, etc.) and Is_Efficiency_Outlier
                # Removed Is_Modulus_Outlier and Outlier_Count - interpretive flags handled in backend
                'Kingdom', 'Superclass', 'Class', 'Subclass', 'Direct_Parent', 'Molecular_Framework',
                'Description', 'ChEMONT_ID_Class', 'ChEMONT_ID_Subclass',
                'NP_Pathway', 'NP_Superclass', 'NP_Class'
                # Removed NP_isglycoside - interpretive flag not needed in UI
            ]

            available_cols = [col for col in data_analysis_cols if col in df_results.columns]
            df_data_analysis = df_results[available_cols].copy()

            st.caption(f"📊 Showing {len(df_data_analysis)} rows × {len(available_cols)} columns")
            st.dataframe(df_data_analysis, use_container_width=True, height=500)

            # Download button
            csv_data = df_data_analysis.to_csv(index=False)
            st.download_button(
                "📥 Download Data Analysis CSV",
                csv_data,
                file_name=f"{selected_compound}_data_analysis.csv",
                mime="text/csv"
            )

        # Tab 2: Interpretation (O[Q/P/L]A, IMP, etc.)
        with data_tabs[1]:
            st.markdown("**O[Q/P/L]A scoring, IMP classification, and interpretations**")

            # Define columns for Interpretation
            interpretation_cols = [
                'ChEMBL_ID', 'Molecule_Name',
                'Efficiency_Score', 'Angle_Score', 'Distance_Score', 'PDB_Score',
                'OQPLA_Base_Score', 'QED_Multiplier', 'OQPLA_Final_Score',
                'OQPLA_Classification', 'OQPLA_Priority',
                'Efficiency_Contribution', 'Angle_Contribution', 'Distance_Contribution', 'PDB_Contribution',
                'QED_Impact'
                # Removed Is_IMP_Candidate and IMP_Confidence - interpretive flags handled in backend
            ]

            available_cols = [col for col in interpretation_cols if col in df_results.columns]
            df_interpretation = df_results[available_cols].copy()

            st.caption(f"📊 Showing {len(df_interpretation)} rows × {len(available_cols)} columns")
            st.dataframe(df_interpretation, use_container_width=True, height=500)

            # Download button
            csv_interpretation = df_interpretation.to_csv(index=False)
            st.download_button(
                "📥 Download Interpretation CSV",
                csv_interpretation,
                file_name=f"{selected_compound}_interpretation.csv",
                mime="text/csv"
            )

        # Tab 3: PDB Evidence
        with data_tabs[2]:
            st.markdown("**PDB Structural Evidence**")

            # Load detailed PDB structures from local or Azure (using same logic as results loader)
            compound_name = selected_compound.replace(' ', '_')
            compound_folder = get_compound_folder(compound_name)

            if compound_folder:
                pdb_details_path = os.path.join(compound_folder, f"{compound_name}_pdb_structures_detailed.csv")
            else:
                pdb_details_path = None

            if pdb_details_path and os.path.exists(pdb_details_path):
                try:
                    pdb_details_df = pd.read_csv(pdb_details_path)

                    st.markdown("*Sorted by quality (⭐⭐⭐ first) and resolution (best first)*")

                    # Prepare display dataframe
                    display_df = pdb_details_df.copy()

                    # Truncate long titles for better display
                    if 'Title' in display_df.columns:
                        display_df['Title'] = display_df['Title'].apply(
                            lambda x: (x[:60] + '...') if isinstance(x, str) and len(x) > 60 else x
                        )

                    # Make URL clickable by converting to HTML link
                    if 'URL' in display_df.columns and 'PDB_ID' in display_df.columns:
                        display_df['PDB_Link'] = display_df.apply(
                            lambda row: f'<a href="{row["URL"]}" target="_blank">{row["PDB_ID"]}</a>',
                            axis=1
                        )
                        # Remove original PDB_ID, URL, SMILES columns
                        cols_to_display = ['PDB_Link'] + [col for col in display_df.columns
                                                          if col not in ['PDB_Link', 'PDB_ID', 'URL', 'SMILES']]
                        display_df = display_df[cols_to_display]

                    # Display the dataframe with HTML links enabled
                    st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)

                    st.caption(f"📊 **{len(pdb_details_df)} total PDB structures** sorted by quality and resolution. Click PDB_Link to view structure at RCSB PDB.")

                    # Download button for detailed structures
                    csv_pdb_details = pdb_details_df.to_csv(index=False)
                    st.download_button(
                        "📥 Download PDB Structures CSV",
                        csv_pdb_details,
                        file_name=f"{compound_name}_pdb_structures_detailed.csv",
                        mime="text/csv"
                    )

                except Exception as e:
                    st.error(f"Error loading PDB structures: {str(e)}")
            else:
                st.warning("PDB structures file not found. PDB integration may not be enabled or data not yet processed.")
                st.info("💡 PDB evidence shows experimental crystal structures from the RCSB Protein Data Bank that contain compounds similar to your query.")

        # Tab 4: Complete Table (merged view)
        with data_tabs[3]:
            st.markdown("**Complete bioactivity data with all columns**")
            st.caption("⚠️ **Note**: This view shows bioactivity-level data. PDB details are not duplicated here - see 'PDB Evidence' tab for compound-level structural data.")

            # Filter out interpretive flag columns (Is_* columns) for display
            # These are kept in CSV files for internal processing but not shown to users
            display_df = df_results.copy()
            cols_to_remove = [col for col in display_df.columns if col.startswith('Is_')]

            # Also remove other interpretive columns we decided to hide
            cols_to_remove.extend(['Outlier_Count', 'NP_isglycoside'])

            # Remove columns that exist in the dataframe
            cols_to_remove = [col for col in cols_to_remove if col in display_df.columns]
            display_df = display_df.drop(columns=cols_to_remove)

            st.caption(f"📊 Showing {len(display_df)} rows × {len(display_df.columns)} columns")
            st.dataframe(display_df, use_container_width=True, height=500)

            # Download button - provide filtered version without interpretive flags
            csv_complete = display_df.to_csv(index=False)
            st.download_button(
                "📥 Download Complete CSV",
                csv_complete,
                file_name=f"{selected_compound}_complete_results.csv",
                mime="text/csv"
            )

        # Global download options at bottom
        st.markdown("---")
        st.markdown("**📦 Download All Files:**")
        col1, col2 = st.columns(2)

        with col1:
            # All-in-one CSV download (complete table) - use filtered version without interpretive flags
            csv_file = display_df.to_csv(index=False)
            st.download_button(
                "📥 Download Complete Results CSV",
                csv_file,
                file_name=f"{selected_compound}_complete_results.csv",
                mime="text/csv"
            )

        with col2:
            # Zip download option for this compound
            if st.button(f"📥 Download All {selected_compound} Files (ZIP)"):
                with st.spinner(f"Preparing {selected_compound} files..."):
                    zip_file = zip_compound_results(selected_compound)
                    if zip_file:
                        with open(zip_file, "rb") as f:
                            st.download_button(
                                f"📥 Download {selected_compound} ZIP",
                                f,
                                file_name=zip_file,
                                mime="application/zip"
                            )
    
    # Debug tab
    with tabs[4]:
        st.subheader("🔍 Debug Information")
        
        # Check data columns and NaN counts
        st.write("### DataFrame Information")
        st.write(f"- Shape: {df_results.shape}")
        st.write(f"- Available columns: {df_results.columns.tolist()}")
        
        # Check for NaN values in key plotting columns
        st.write("### NaN Values in Key Columns")
        plot_cols = ['SEI', 'BEI', 'NSEI', 'NBEI', 'pActivity', 'Activity_nM']
        nan_data = []
        for col in plot_cols:
            if col in df_results.columns:
                nan_count = df_results[col].isna().sum()
                total_count = len(df_results)
                nan_percentage = (nan_count/total_count*100) if total_count > 0 else 0
                nan_data.append({
                    "Column": col,
                    "NaN Count": nan_count,
                    "Total Rows": total_count,
                    "NaN Percentage": f"{nan_percentage:.1f}%"
                })
        
        nan_df = pd.DataFrame(nan_data)
        st.write(nan_df)
        
        # High NaN percentage warning
        if any(df_results[col].isna().mean() > 0.8 for col in ['SEI', 'BEI'] if col in df_results.columns):
            st.warning("⚠️ Over 80% of SEI/BEI values are NaN, which may prevent plots from generating")
        
        # Directory structure check
        st.write("### Directory Structure")
        st.write(f"Compound folder: {compound_folder}")
        st.write(f"- Exists: {os.path.exists(compound_folder)}")
        
        for subfolder in ["SEI", "BEI", "Activity", "Structures"]:
            full_path = os.path.join(compound_folder, subfolder)
            exists = os.path.exists(full_path)
            st.write(f"{subfolder} folder: {full_path}")
            st.write(f"- Exists: {exists}")
            
            if exists:
                files = os.listdir(full_path)
                json_files = [f for f in files if f.endswith('.json')]
                st.write(f"- Contains {len(files)} files ({len(json_files)} JSON files)")
                if json_files:
                    st.write(f"- JSON files: {json_files}")

        # Plots are now generated on-demand in the Interactive Plots tab

def display_analyze_view():
    """Display the analyze new compound view."""
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Back", key="back_to_home_from_analyze"):
            st.session_state.current_view = "home"
            st.rerun()
    
    with col2:
        st.title("🔬 Analyze New Compound")
    
    # Input method selection - keep the original horizontal radio buttons
    st.subheader("Input Method")
    input_method = st.radio("Input Method", ["Manual", "CSV Upload"], horizontal=True)
    
    # Configuration settings - maintain the original layout
    st.subheader("Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        similarity_threshold = st.slider("Similarity Threshold", 0, 100, 90)
        st.session_state.last_similarity_threshold = similarity_threshold
    
    with col2:
        # Activity type selection with improved checkbox UI
        st.write("**Activity Types**")
        st.caption("Select which activity types to process. Choosing fewer types may speed up processing.")
        
        # Create columns for checkboxes to arrange them horizontally
        checkbox_cols = st.columns(4)  # 4 columns for the 7 activity types
        
        # Initialize session state for checkboxes if not already set
        if "activity_checkboxes" not in st.session_state:
            st.session_state.activity_checkboxes = {activity: activity in st.session_state.selected_activity_types 
                                                  for activity in ACTIVITY_TYPES}
        
        # Create the checkboxes
        selected_activities = []
        for i, activity in enumerate(ACTIVITY_TYPES):
            with checkbox_cols[i % 4]:
                is_checked = st.checkbox(
                    activity, 
                    value=st.session_state.activity_checkboxes.get(activity, True),
                    key=f"activity_{activity}"
                )
                st.session_state.activity_checkboxes[activity] = is_checked
                if is_checked:
                    selected_activities.append(activity)
        
        # Update session state with selected activity types
        if selected_activities:
            st.session_state.selected_activity_types = selected_activities
        else:
            st.warning("⚠️ Please select at least one activity type")
    
    # Manual input processing
    if input_method == "Manual":
        st.subheader("Enter Compound Information")
        compound_name = st.text_input("**Compound Name**")
        
        # Toggle between SMILES and InChI input
        input_type = st.radio(
            "**Chemical Structure Input Type**",
            ["SMILES", "InChI"],
            horizontal=True,
            help="Choose whether to input the compound structure as SMILES or InChI"
        )
        
        # Add info box explaining the formats
        with st.expander("ℹ️ About Chemical Structure Formats", expanded=False):
            st.markdown("""
            **SMILES (Simplified Molecular Input Line Entry System):**
            - A text-based notation for describing molecular structures
            - Example: `CCO` (ethanol), `CC(=O)O` (acetic acid)
            
            **InChI (International Chemical Identifier):**
            - A standardized identifier for chemical compounds
            - Example: `InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3` (ethanol)
            - More unique and standardized than SMILES
            
            When you select InChI, it will be automatically converted to SMILES for processing.
            """)
        
        if input_type == "SMILES":
            structure_input = st.text_area("**SMILES String**", height=80, 
                                          placeholder="Enter SMILES string (e.g., CCO for ethanol)")
        else:
            structure_input = st.text_area("**InChI String**", height=80,
                                          placeholder="Enter InChI string (e.g., InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3)")
        
        # Store the input type for processing
        input_format = input_type.lower()
        
        if st.button("Process Compound", key="process_single_compound", type="primary", use_container_width=False):
            if not selected_activities:
                st.error("Please select at least one activity type to process.")
                return
            
            # Validate inputs
            if not compound_name.strip():
                st.error("Please enter a compound name.")
                return

            if not structure_input.strip():
                st.error(f"Please enter a {input_type} string.")
                return

            # Sanitize compound name for filesystem safety
            from modules.utils import sanitize_compound_name
            original_name = compound_name.strip()
            sanitized_name = sanitize_compound_name(original_name)

            # Inform user if name was sanitized
            if original_name != sanitized_name:
                st.info(f"ℹ️ Compound name sanitized: '{original_name}' → '{sanitized_name}'")

            with st.spinner("Processing compound..."):
                process_result = process_and_store(
                    compound_name=sanitized_name,
                    structure_input=structure_input,
                    input_format=input_format,
                    similarity_threshold=similarity_threshold,
                    activity_types=selected_activities
                )

                if process_result:
                    st.success(f"Successfully processed {sanitized_name}")
                    # Offer to navigate to the compound details view
                    if st.button("View Results", key="view_new_results"):
                        st.session_state.selected_compound = sanitized_name
                        st.session_state.current_view = "compound_details"
                        st.rerun()
    
    # CSV upload processing
    elif input_method == "CSV Upload":
        st.subheader("Upload CSV File")
        st.info("CSV file should contain 'compound_name' and either 'smiles' or 'inchi' columns.")
        
        uploaded_file = st.file_uploader("Upload CSV", type=['csv'])
        
        if uploaded_file:
            valid, df = validate_csv_file(uploaded_file)
            
            if valid and df is not None:
                st.write("Preview of uploaded data:")
                st.dataframe(df.head())

                # Check for compound names that will be sanitized
                from modules.utils import sanitize_compound_name
                name_changes = []
                for idx, row in df.iterrows():
                    original_name = str(row['compound_name']).strip()
                    sanitized_name = sanitize_compound_name(original_name)
                    if original_name != sanitized_name:
                        name_changes.append({
                            'Row': idx + 1,
                            'Original Name': original_name,
                            'Sanitized Name': sanitized_name
                        })

                # Show warning if there are name changes
                if name_changes:
                    st.warning(f"⚠️ **{len(name_changes)} compound name(s) contain invalid characters and will be sanitized:**")
                    changes_df = pd.DataFrame(name_changes)
                    st.dataframe(changes_df, use_container_width=True)
                    st.info("📝 These names will be automatically cleaned to ensure compatibility with file systems.")

                if st.button("Process CSV", key="process_csv_batch", type="primary"):
                    if not selected_activities:
                        st.error("Please select at least one activity type to process.")
                        return
                    
                    with st.spinner("Processing compounds... Please wait."):
                        success, fail = process_csv_batch(
                            df=df,
                            similarity_threshold=similarity_threshold,
                            activity_types=selected_activities
                        )
                        
                        st.success(f"Processing completed: {success} successful, {fail} failed.")
                        
                        # Offer to navigate back to the home view
                        if st.button("Return to Home", key="back_to_home_after_batch"):
                            st.session_state.current_view = "home"
                            st.rerun()


def main():
    """Main application function with improved view routing."""
    try:
        # Initialize session state for all required variables
        
        init_session_state()
        
        # Global progress indicator (always visible when processing)
        if st.session_state.processing_compound:
            progress_container = st.container()
            with progress_container:
                st.info(f"⏳ Processing {st.session_state.processing_compound} in background...")
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("View Results Now"):
                        st.session_state.selected_compound = st.session_state.processing_compound
                        st.session_state.current_view = "compound_details"
                        st.session_state.show_new_compound_alert = False
                        st.rerun()
                with col2:
                    if st.button("Dismiss"):
                        st.session_state.show_new_compound_alert = False
                        st.rerun()
        
        # View routing based on current view state
        if st.session_state.current_view == "home":
            display_home_view()
        elif st.session_state.current_view == "compound_details":
            if st.session_state.selected_compound:
                display_compound_details_view()
            else:
                st.error("No compound selected. Returning to home.")
                st.session_state.current_view = "home"
                st.rerun()
        elif st.session_state.current_view == "analyze":
            display_analyze_view()
        else:
            st.error(f"Unknown view: {st.session_state.current_view}")
            st.session_state.current_view = "home"
            st.rerun()
    
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        st.error("An error occurred. Please try again or contact support.")
        reset_processing_state()

if __name__ == "__main__":
    main()
