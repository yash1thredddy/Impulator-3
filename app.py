import os
import logging
import streamlit as st
import pandas as pd
import json
from config import RESULTS_DIR, ACTIVITY_TYPES
from modules.utils import get_available_compounds, validate_csv_file, zip_results, zip_compound_results
from modules.compound_manager import process_and_store, display_compound_summary, process_csv_batch
from modules.data_processor import load_results
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
        "last_similarity_threshold": 80,  # Default similarity threshold
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
    """Display the home/landing page with compound search and listing."""
    
    
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
            label_visibility="collapsed"  # Hides the label
        )
        st.session_state.compound_search_query = search_query

    with button_col:
        if st.button("➕ New Compound", key="add_new_compound", use_container_width=True):
            st.session_state.current_view = "analyze"
            st.rerun()
    
    # Get available compounds
    compounds_list = get_available_compounds()
    
    if not compounds_list:
        st.info("No compounds have been analyzed yet. Click 'Analyze New Compound' to get started.")
        return
    
    # Filter compounds based on search query
    if search_query:
        filtered_compounds = [c for c in compounds_list if search_query.lower() in c.lower()]
    else:
        filtered_compounds = compounds_list
    
    if not filtered_compounds:
        st.warning(f"No compounds found matching '{search_query}'")
        return
    
    # Display compounds in a grid
    st.subheader(f"Available Compounds ({len(filtered_compounds)})")
    
    # Add styling for consistent cards
    st.markdown("""
    <style>
    .compound-card {
        height: 1px !important;  /* Set an appropriate fixed height */
        overflow: hidden;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Create a grid of compounds - 4 columns
    cols = st.columns(4)
    for i, compound in enumerate(filtered_compounds):
        with cols[i % 4]:
            # Create a single container for the entire card with a border
            with st.container(border=True):
                # Compound name centered
                st.markdown(f"<h4 style='text-align: center; margin: 5px 0;'>{compound}</h4>", unsafe_allow_html=True)
                
                # Try to get some basic info about the compound
                try:
                    df = load_results(compound)
                    if df is not None and not df.empty:
                        # Get SMILES if available
                        smiles = None
                        if 'SMILES' in df.columns:
                            smiles = df['SMILES'].iloc[0]
                            
                            # Display the molecular structure using RDKit and HTML
                            try:
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
                                        f'<img src="data:image/png;base64,{img_str}" alt="{compound}" />'
                                        f'</div>',
                                        unsafe_allow_html=True
                                    )
                                else:
                                    st.warning("Could not render molecule from SMILES")
                            except Exception as e:
                                logger.error(f"Error rendering molecule: {str(e)}")
                                # Fall back to displaying SMILES as text
                                if smiles:
                                    # Truncate if too long
                                    if len(smiles) > 30:
                                        display_smiles = smiles[:27] + "..."
                                    else:
                                        display_smiles = smiles
                                    st.markdown(f"**SMILES:** `{display_smiles}`")
                        
                        # Display other compound info
                        col1, col2 = st.columns(2)
                        with col1:
                            # Try to load metadata to get similarity threshold
                            try:
                                metadata_file = os.path.join(RESULTS_DIR, compound, f"{compound}_metadata.json")
                                if os.path.exists(metadata_file):
                                    with open(metadata_file, 'r') as f:
                                        metadata = json.load(f)
                                        sim_threshold = metadata.get('similarity_threshold', 80)
                                        st.markdown(f"**Sim Threshold:** {sim_threshold}%")
                                else:
                                    st.markdown("**Sim Threshold:** N/A")
                            except Exception as e:
                                logger.error(f"Error loading metadata: {str(e)}")
                                st.markdown("**Sim Threshold:** N/A")
                        
                        with col2:
                            # Count unique ChEMBL IDs
                            if 'ChEMBL_ID' in df.columns:
                                unique_chembl = df['ChEMBL_ID'].nunique()
                                st.markdown(f"**Similar:** {unique_chembl}")
                    else:
                        # Show warning about missing data directly in the card
                        st.warning(f"No results found for {compound}. CSV file is missing.")
                except Exception as e:
                    logger.error(f"Error loading compound info: {str(e)}")
                    st.error(f"Error loading data: {str(e)}")
                
                # Button to view compound details
                if st.button(f"View Details", key=f"view_{compound}", type="primary", use_container_width=True):
                    st.session_state.selected_compound = compound
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
        # Create subtabs for different plot categories
        plot_tabs = st.tabs([
            "📊 Quick Plots",
            "🎨 Custom Builder",
            "Activity Plots",
            "SEI Visualizations",
            "BEI Visualizations"
        ])

        # Quick plots tab - Default scatter plots
        with plot_tabs[0]:
            st.markdown("### Quick Access Plots")
            st.markdown("*Pre-configured efficiency metric visualizations with customization*")

            # Add quick buttons for common plots
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### Efficiency Scatter Plots")
                if st.button("📈 SEI vs BEI", key="quick_sei_bei", use_container_width=True):
                    st.session_state.quick_plot = "sei_bei"
                if st.button("📈 NSEI vs NBEI", key="quick_nsei_nbei", use_container_width=True):
                    st.session_state.quick_plot = "nsei_nbei"

            with col2:
                st.markdown("#### Metric Distributions")
                if st.button("📊 Efficiency Boxplots", key="quick_boxplots", use_container_width=True):
                    st.session_state.quick_plot = "boxplots"
                if st.button("📊 Activity Distribution", key="quick_activity", use_container_width=True):
                    st.session_state.quick_plot = "activity"

            # Show the selected quick plot with customization
            if 'quick_plot' in st.session_state:
                st.markdown("---")

                # Import the enhanced static plot viewer
                from modules.visualization import show_static_plot_with_controls

                if st.session_state.quick_plot == "sei_bei":
                    show_static_plot_with_controls(df_results, "SEI", "BEI", compound_folder)
                elif st.session_state.quick_plot == "nsei_nbei":
                    show_static_plot_with_controls(df_results, "NSEI", "NBEI", compound_folder)
                elif st.session_state.quick_plot == "boxplots":
                    show_interactive_plots(compound_folder, "sei")
                elif st.session_state.quick_plot == "activity":
                    show_interactive_plots(compound_folder, "activity")

        # Custom visualization builder tab
        with plot_tabs[1]:
            from modules.custom_viz_builder import custom_visualization_builder
            custom_visualization_builder(df_results, selected_compound)

        with plot_tabs[2]:
            show_interactive_plots(compound_folder, "activity")

        with plot_tabs[3]:
            show_interactive_plots(compound_folder, "sei")

        with plot_tabs[4]:
            show_interactive_plots(compound_folder, "bei")
    
    # Molecule viewer tab
    with tabs[2]:
        # Only show sidebar when in Molecules tab
        from modules.molecule_viewer import molecule_viewer_app, get_molecule_style_controls
        
        st.subheader("🧪 Molecule Viewer")
        style_settings = get_molecule_style_controls(show_sidebar=True)

        
        # Call the viewer with the style settings
        molecule_viewer_app(compound_folder, style_settings)
    
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
                'Is_SEI_Outlier', 'Is_BEI_Outlier', 'Is_NSEI_Outlier', 'Is_NBEI_Outlier',
                'Is_Modulus_Outlier', 'Outlier_Count', 'Is_Efficiency_Outlier',
                'Kingdom', 'Superclass', 'Class', 'Subclass', 'Direct_Parent', 'Molecular_Framework',
                'Description', 'ChEMONT_ID_Class', 'ChEMONT_ID_Subclass',
                'NP_Pathway', 'NP_Superclass', 'NP_Class', 'NP_isglycoside'
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
                'OQPLA_Classification', 'OQPLA_Interpretation', 'OQPLA_Action', 'OQPLA_Priority',
                'Efficiency_Contribution', 'Angle_Contribution', 'Distance_Contribution', 'PDB_Contribution',
                'QED_Impact',
                'Is_IMP_Candidate', 'IMP_Confidence'
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

        # Tab 3: PDB Evidence (compound-level)
        with data_tabs[2]:
            st.markdown("**PDB structural evidence (compound-level, no duplication)**")

            # Try to load PDB summary CSV
            compound_folder = os.path.join(RESULTS_DIR, selected_compound.replace(' ', '_'))
            pdb_summary_path = os.path.join(compound_folder, f"{selected_compound}_pdb_summary.csv")

            if os.path.exists(pdb_summary_path):
                try:
                    df_pdb = pd.read_csv(pdb_summary_path)

                    st.caption(f"🔬 Showing {len(df_pdb)} unique compounds with PDB evidence")
                    st.dataframe(df_pdb, use_container_width=True, height=500)

                    # Download button
                    csv_pdb = df_pdb.to_csv(index=False)
                    st.download_button(
                        "📥 Download PDB Evidence CSV",
                        csv_pdb,
                        file_name=f"{selected_compound}_pdb_summary.csv",
                        mime="text/csv"
                    )

                    st.info("💡 **Note**: This table shows one row per unique compound. PDB evidence is compound-specific, not target-specific.")

                except Exception as e:
                    st.error(f"Error loading PDB summary: {str(e)}")
            else:
                st.warning("PDB summary file not found. PDB integration may not be enabled or data not yet processed.")
                st.info("PDB evidence is stored in a separate file to avoid duplication across bioactivity rows.")

        # Tab 4: Complete Table (merged view)
        with data_tabs[3]:
            st.markdown("**Complete bioactivity data with all columns**")
            st.caption("⚠️ **Note**: This view shows bioactivity-level data. PDB details are not duplicated here - see 'PDB Evidence' tab for compound-level structural data.")

            st.caption(f"📊 Showing {len(df_results)} rows × {len(df_results.columns)} columns")
            st.dataframe(df_results, use_container_width=True, height=500)

            # Download button
            csv_complete = df_results.to_csv(index=False)
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
            # All-in-one CSV download (complete table)
            csv_file = df_results.to_csv(index=False)
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
        
        # Add regenerate plots button
        if st.button("🔄 Regenerate Plots"):
            with st.spinner("Regenerating plots..."):
                try:
                    # Import here to avoid circular imports
                    from modules.visualization import plot_all_visualizations
                    plot_all_visualizations(df_results, compound_folder)
                    st.success("✅ Plots regenerated successfully. Refresh the page to view them.")
                except Exception as e:
                    st.error(f"❌ Error regenerating plots: {str(e)}")

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
        similarity_threshold = st.slider("Similarity Threshold", 0, 100, 80)
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
            
            with st.spinner("Processing compound..."):
                process_result = process_and_store(
                    compound_name=compound_name,
                    structure_input=structure_input,
                    input_format=input_format,
                    similarity_threshold=similarity_threshold,
                    activity_types=selected_activities
                )
                
                if process_result:
                    st.success(f"Successfully processed {compound_name}")
                    # Offer to navigate to the compound details view
                    if st.button("View Results", key="view_new_results"):
                        st.session_state.selected_compound = compound_name
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
                st.progress(st.session_state.processing_progress)
        
        # Alert for newly processed compound
        if st.session_state.show_new_compound_alert:
            alert_container = st.container()
            with alert_container:
                new_compound = st.session_state.last_processed_compound
                st.success(f"✅ New compound processed: {new_compound}")
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("View Results Now"):
                        st.session_state.selected_compound = new_compound
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