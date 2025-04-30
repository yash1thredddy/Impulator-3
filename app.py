import os
import logging
import streamlit as st
import pandas as pd

from config import RESULTS_DIR, ACTIVITY_TYPES
from modules.utils import get_available_compounds, validate_csv_file, zip_results, zip_compound_results
from modules.compound_manager import process_and_store, display_compound_summary, process_csv_batch
from modules.data_processor import load_results
from modules.visualization import show_interactive_plots, show_molecular_structures
from modules.molecule_viewer import molecule_viewer_app
from modules.api_client import batch_fetch_activities

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
        "molecule_viewer_tab": "3D"  # Default tab for molecule viewer
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

def analyze_activity_cliffs(df_results):
    """
    Analyze activity cliffs in the dataset - pairs of molecules with similar structures 
    but significantly different activities.
    
    Args:
        df_results: DataFrame containing the compound analysis results
    """
    if df_results is None or df_results.empty:
        return
    
    # Check if we have necessary data
    if not all(col in df_results.columns for col in ['ChEMBL ID', 'pActivity', 'Molecular Weight']):
        return
    
    st.subheader("⛰️ Activity Cliff Analysis")
    st.markdown("""
    Activity cliffs are pairs of compounds with similar structures but significantly different activities.
    They represent opportunities for understanding structure-activity relationships.
    """)
    
    # Filter out invalid data
    valid_data = df_results.dropna(subset=['ChEMBL ID', 'pActivity']).copy()
    
    if valid_data.empty or len(valid_data['ChEMBL ID'].unique()) < 2:
        st.info("Insufficient data for activity cliff analysis. Need at least two compounds with activity data.")
        return
    
    # Group by ChEMBL ID and get the mean activity
    activity_by_compound = valid_data.groupby('ChEMBL ID')['pActivity'].mean().reset_index()
    
    # Calculate activity differences between all pairs
    compounds = activity_by_compound['ChEMBL ID'].tolist()
    activities = activity_by_compound['pActivity'].tolist()
    
    pairs = []
    for i in range(len(compounds)):
        for j in range(i+1, len(compounds)):
            activity_diff = abs(activities[i] - activities[j])
            
            # Get a representative SMILES for each compound
            smiles_i = valid_data[valid_data['ChEMBL ID'] == compounds[i]]['SMILES'].iloc[0]
            smiles_j = valid_data[valid_data['ChEMBL ID'] == compounds[j]]['SMILES'].iloc[0]
            
            # Get molecular weights for reference
            mw_i = valid_data[valid_data['ChEMBL ID'] == compounds[i]]['Molecular Weight'].iloc[0]
            mw_j = valid_data[valid_data['ChEMBL ID'] == compounds[j]]['Molecular Weight'].iloc[0]
            
            # Add to pairs list
            pairs.append({
                'Compound 1': compounds[i],
                'Compound 2': compounds[j],
                'Activity 1': activities[i],
                'Activity 2': activities[j],
                'Activity Difference': activity_diff,
                'MW 1': mw_i,
                'MW 2': mw_j,
                'MW Difference': abs(mw_i - mw_j),
                'SMILES 1': smiles_i,
                'SMILES 2': smiles_j
            })
    
    if not pairs:
        st.info("No valid pairs found for activity cliff analysis.")
        return
    
    # Convert to DataFrame and sort by activity difference
    pairs_df = pd.DataFrame(pairs)
    pairs_df = pairs_df.sort_values(by='Activity Difference', ascending=False)
    
    # Define significant activity cliffs (difference > 1 log unit)
    activity_cliff_threshold = 1.0
    significant_cliffs = pairs_df[pairs_df['Activity Difference'] > activity_cliff_threshold]
    
    # Display summary
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Compound Pairs", len(pairs_df))
    with col2:
        st.metric("Significant Activity Cliffs", len(significant_cliffs))
    
    # Explain the threshold
    st.markdown(f"""
    **Significant activity cliffs** are defined as compound pairs with:
    - Activity difference > {activity_cliff_threshold} log units
    - Similar molecular scaffolds
    """)
    
    # Show the cliffs in a table
    if not significant_cliffs.empty:
        st.markdown("##### Significant Activity Cliffs")
        # Format the dataframe for display
        display_df = significant_cliffs[['Compound 1', 'Compound 2', 'Activity 1', 'Activity 2', 
                                       'Activity Difference', 'MW 1', 'MW 2', 'MW Difference']].copy()
        # Round numeric columns
        for col in ['Activity 1', 'Activity 2', 'Activity Difference', 'MW 1', 'MW 2', 'MW Difference']:
            display_df[col] = display_df[col].round(2)
        
        st.dataframe(display_df, use_container_width=True)
    else:
        st.info("No significant activity cliffs were found in the dataset.")

def display_home_view():
    """Display the home/landing page with compound search and listing."""
    st.title("🔬 IMPULATOR - Compound Library")
    
    # Top controls for searching and adding new compounds
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Search input
        search_query = st.text_input(
            "Search compounds:",
            value=st.session_state.compound_search_query,
            placeholder="Enter compound name...",
            key="compound_search"
        )
        st.session_state.compound_search_query = search_query
    
    with col2:
        # Button to add new compounds
        if st.button("➕ Analyze New Compound", key="add_new_compound", use_container_width=True):
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
    
    
    # Create a grid of compounds - 3 columns
    cols = st.columns(3)
    for i, compound in enumerate(filtered_compounds):
        with cols[i % 3]:
            # Create a card-like container for each compound
            with st.container(border=True):
                st.markdown(f"### {compound}")
                
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
                                    img = Draw.MolToImage(mol, size=(250, 150))
                                    
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
                            if 'Molecular Weight' in df.columns:
                                avg_mw = df['Molecular Weight'].mean()
                                st.markdown(f"**MW:** {avg_mw:.2f}")
                        
                        with col2:
                            # Count unique ChEMBL IDs
                            if 'ChEMBL ID' in df.columns:
                                unique_chembl = df['ChEMBL ID'].nunique()
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

def display_compound_details_view():
    """Display detailed view for a selected compound."""
    # Navigation controls
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Back", key="back_to_home"):
            st.session_state.current_view = "home"
            st.rerun()
    
    with col2:
        st.title(f"🔬 {st.session_state.selected_compound}")
    
    selected_compound = st.session_state.selected_compound
    # Use the directory name directly without modifying it
    compound_folder = os.path.join(RESULTS_DIR, selected_compound)
    
    # Load compound data
    df_results = load_results(selected_compound)
    
    if df_results is None or df_results.empty:
        st.warning("No data available for this compound.")
        return
    
    # Create tabs for different sections
    tabs = st.tabs([
        "📊 Summary", 
        "📈 Interactive Plots", 
        "🧪 Molecules", 
        "📋 Data Table",
        "⚙️ Debug"
    ])
    
    # Summary tab
    with tabs[0]:
        display_compound_summary(
            df_results=df_results, 
            compound_name=selected_compound,
            similarity_threshold=st.session_state.last_similarity_threshold
        )
        
        # Activity cliff analysis
        st.markdown("---")
        analyze_activity_cliffs(df_results)
    
    # Interactive plots tab
    with tabs[1]:
        # Create subtabs for different plot categories
        plot_tabs = st.tabs([
            "SEI vs BEI", 
            "Activity Plots", 
            "SEI Visualizations", 
            "BEI Visualizations"
        ])
        
        with plot_tabs[0]:
            show_interactive_plots(compound_folder, "scatter")
        
        with plot_tabs[1]:
            show_interactive_plots(compound_folder, "activity")
        
        with plot_tabs[2]:
            show_interactive_plots(compound_folder, "sei")
        
        with plot_tabs[3]:
            show_interactive_plots(compound_folder, "bei")
    
    # Molecule viewer tab
    with tabs[2]:
        st.sidebar.header("Molecule Visualization Settings")
        molecule_viewer_app(compound_folder)
    
    # Data table tab
    with tabs[3]:
        st.subheader("📋 Complete Results Table")
        st.dataframe(df_results, use_container_width=True)
        
        # Download options
        col1, col2 = st.columns(2)
        
        # CSV download option
        with col1:
            csv_file = df_results.to_csv(index=False)
            st.download_button(
                "📥 Download CSV", 
                csv_file, 
                file_name=f"{selected_compound}_results.csv", 
                mime="text/csv"
            )
        
        # Zip download option for this compound
        with col2:
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
        plot_cols = ['SEI', 'BEI', 'NSEI', 'nBEI', 'pActivity', 'Activity (nM)']
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
    
    # Input method selection
    input_method = st.radio("Input Method", ["Manual", "CSV Upload"], horizontal=True)
    
    # Configuration settings
    st.subheader("Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        similarity_threshold = st.slider("Similarity Threshold", 0, 100, 80)
        st.session_state.last_similarity_threshold = similarity_threshold
    
    with col2:
        # Activity type selection with improved UI
        st.write("**Activity Types**")
        st.caption("Select which activity types to process. Choosing fewer types may speed up processing.")
        
        # Use multiselect for activity types
        selected_activity_types = st.multiselect(
            "Select Activity Types",
            options=ACTIVITY_TYPES,
            default=st.session_state.selected_activity_types
        )
        
        # Update session state with selected activity types
        if selected_activity_types:
            st.session_state.selected_activity_types = selected_activity_types
        else:
            st.warning("⚠️ Please select at least one activity type")
    
    # Manual input processing
    if input_method == "Manual":
        st.subheader("Enter Compound Information")
        compound_name = st.text_input("Compound Name")
        smiles = st.text_area("SMILES String")
        
        if st.button("Process Compound", key="process_single_compound", type="primary"):
            if not selected_activity_types:
                st.error("Please select at least one activity type to process.")
                return
            
            with st.spinner("Processing compound..."):
                process_result = process_and_store(
                    compound_name=compound_name,
                    smiles=smiles,
                    similarity_threshold=similarity_threshold,
                    activity_types=selected_activity_types
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
        st.info("CSV file should contain 'compound_name' and 'smiles' columns.")
        
        uploaded_file = st.file_uploader("Upload CSV", type=['csv'])
        
        if uploaded_file:
            valid, df = validate_csv_file(uploaded_file)
            
            if valid and df is not None:
                st.write("Preview of uploaded data:")
                st.write(df.head())
                
                if st.button("Process CSV", key="process_csv_batch", type="primary"):
                    if not selected_activity_types:
                        st.error("Please select at least one activity type to process.")
                        return
                    
                    with st.spinner("Processing compounds... Please wait."):
                        success, fail = process_csv_batch(
                            df=df,
                            similarity_threshold=similarity_threshold,
                            activity_types=selected_activity_types
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