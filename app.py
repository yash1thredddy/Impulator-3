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
        "current_view": "main",
        "selected_plots": [],
        "batch_processing": False,
        "processing_compound": None,
        "compounds_to_process": [],
        "last_processed_compound": None,
        "show_new_compound_alert": False,
        "selected_activity_types": ACTIVITY_TYPES,  # Default to all activity types
        "last_similarity_threshold": 80  # Default similarity threshold
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

def main():
    """Main application function."""
    try:
        st.title("🔬 IMPULATOR")
        
        # Global progress indicator (always visible)
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
                        compounds_list = get_available_compounds()
                        if new_compound in compounds_list:
                            st.session_state.selected_compound = new_compound
                            st.session_state.show_new_compound_alert = False
                            st.experimental_rerun()
                with col2:
                    if st.button("Dismiss"):
                        st.session_state.show_new_compound_alert = False
                        st.experimental_rerun()
                        
        # Sidebar configuration
        st.sidebar.header("Compound Processing")
        
        # Input method selection
        input_method = st.sidebar.radio("Input Method", ["Manual", "CSV Upload"])
        similarity_threshold = st.sidebar.slider("Similarity Threshold", 0, 100, 80)
        st.session_state.last_similarity_threshold = similarity_threshold
        
        # Activity type selection
        st.sidebar.subheader("Activity Types")
        st.sidebar.info("Select which activity types to process. Choosing fewer types may speed up processing.")
        selected_activity_types = st.sidebar.multiselect(
            "Select Activity Types to Process",
            options=ACTIVITY_TYPES,
            default=st.session_state.selected_activity_types
        )
        
        # Update session state with selected activity types
        if selected_activity_types:
            st.session_state.selected_activity_types = selected_activity_types
        else:
            st.sidebar.warning("⚠️ Please select at least one activity type")
        
        # Manual input processing
        if input_method == "Manual":
            compound_name = st.sidebar.text_input("Compound Name")
            smiles = st.sidebar.text_area("SMILES String")
            
            if st.sidebar.button("Process Compound"):
                if not selected_activity_types:
                    st.error("Please select at least one activity type to process.")
                    return
                
                process_and_store(
                    compound_name=compound_name,
                    smiles=smiles,
                    similarity_threshold=similarity_threshold,
                    activity_types=selected_activity_types
                )
        
        # CSV upload processing
        elif input_method == "CSV Upload":
            uploaded_file = st.sidebar.file_uploader("Upload CSV", type=['csv'])
            
            if uploaded_file:
                valid, df = validate_csv_file(uploaded_file)
                
                if valid and df is not None:
                    st.write("Preview of uploaded data:")
                    st.write(df.head())
                    
                    if st.sidebar.button("Process CSV"):
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
        
        # Results display
        st.sidebar.header("Select Processed Compound")
        
        # Get available compounds
        compounds_list = get_available_compounds()
        
        if compounds_list:
            selected_compound = st.sidebar.selectbox(
                "Choose a compound", 
                compounds_list
            )
            compound_folder = os.path.join(RESULTS_DIR, selected_compound)
            
            # Display results
            st.subheader(f"Results for: {selected_compound}")
            df_results = load_results(selected_compound)
            
            if df_results is not None and not df_results.empty:
                # Display comprehensive summary before showing the data table
                display_compound_summary(
                    df_results=df_results, 
                    compound_name=selected_compound,
                    similarity_threshold=st.session_state.last_similarity_threshold
                )
                
                # Create divider for better separation
                st.markdown("---")
                
                # Perform activity cliff analysis
                analyze_activity_cliffs(df_results)
                
                # Create divider for better separation
                st.markdown("---")
                
                # Show full data table
                st.subheader("📋 Complete Results Table")
                st.dataframe(df_results)
                
                # Create two columns for download options
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
# Add this code inside the main function where you load and display results
# After loading df_results but before showing plots

                if df_results is not None and not df_results.empty:
                    # Add debugging option with expander to keep the UI clean
                    with st.expander("🔍 Debug Information (Expand for troubleshooting)"):
                        st.subheader("Data and Directory Diagnostics")
                        
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
                        
                        # Root directory plot files
                        st.write("### Plot Files in Root Directory")
                        plot_files = [f for f in os.listdir(compound_folder) if f.endswith('.json') or f.endswith('.html')]
                        if plot_files:
                            st.write(f"Plot files found: {plot_files}")
                        else:
                            st.write("No plot files found in root directory")
                        
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
                    
                # Display interactive plots with Plotly
                st.subheader("📊 Interactive Scatter Plots")
                show_interactive_plots(compound_folder, "scatter")
                
                st.subheader("📈 Activity Plots")
                show_interactive_plots(compound_folder, "activity")
                
                # Display efficiency metrics plots
                st.subheader("🔍 SEI Visualizations")
                show_interactive_plots(compound_folder, "sei")
                
                st.subheader("🔬 BEI Visualizations")
                show_interactive_plots(compound_folder, "bei")
                
                # Display advanced molecular structure viewer
                st.subheader("🧪 Molecular Structure Viewer")
                molecule_tab, analysis_tab = st.tabs(["Molecule Viewer", "Structure Analysis"])
                
                with molecule_tab:
                    molecule_viewer_app(compound_folder)
                
                with analysis_tab:
                    show_molecular_structures(compound_folder)
            
            # Download all results
            st.sidebar.markdown("---")
            if st.sidebar.button("📥 Prepare All Results (ZIP)"):
                with st.sidebar.spinner("Creating ZIP of all results..."):
                    zip_file = zip_results()
                    if zip_file:
                        with open(zip_file, "rb") as f:
                            st.sidebar.download_button(
                                "📥 Download All Results (ZIP)",
                                f,
                                file_name=zip_file,
                                mime="application/zip"
                            )
    
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        st.error("An error occurred. Please try again or contact support.")
        reset_processing_state()

if __name__ == "__main__":
    init_session_state()
    main()