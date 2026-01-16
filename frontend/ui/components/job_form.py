"""Job submission form component for IMPULATOR.

Provides the input form for submitting new compound analysis jobs.
"""

import html
import logging
from typing import Dict, List, Optional, Tuple

import streamlit as st

from frontend.services import get_api_client
from frontend.config.settings import config
from frontend.utils import SessionState, InputValidator, sanitize_compound_name
from frontend.ui.components.sidebar import start_polling

logger = logging.getLogger(__name__)


def render_job_form() -> Optional[str]:
    """Render the job submission form.

    Returns:
        Optional[str]: Job ID if submitted successfully, None otherwise
    """
    st.subheader("Compound Information")

    # Compound name input
    compound_name = st.text_input(
        "Compound Name",
        placeholder="e.g., Aspirin",
        help="Name to identify this compound in results"
    )

    # Input type selection
    input_type = st.radio(
        "Structure Input Type",
        ["SMILES", "InChI"],
        horizontal=True,
        help="Choose the format of your chemical structure input"
    )

    # Structure input
    if input_type == "SMILES":
        structure_input = st.text_area(
            "SMILES String",
            height=80,
            placeholder="e.g., CC(=O)OC1=CC=CC=C1C(=O)O (Aspirin)",
            help="Simplified Molecular Input Line Entry System notation"
        )
    else:
        structure_input = st.text_area(
            "InChI String",
            height=80,
            placeholder="e.g., InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)",
            help="International Chemical Identifier"
        )

    # Configuration section
    st.subheader("Analysis Configuration")

    col1, col2 = st.columns(2)

    with col1:
        similarity_threshold = st.slider(
            "Similarity Threshold (%)",
            min_value=50,
            max_value=100,
            value=config.DEFAULT_SIMILARITY_THRESHOLD,
            help="Minimum similarity for ChEMBL compound search"
        )

    with col2:
        st.markdown("**Activity Types**")
        selected_activities = render_activity_checkboxes()

    # Validation feedback
    validation_passed = True
    if compound_name and structure_input:
        if input_type == "SMILES":
            result = InputValidator.validate_smiles(structure_input)
        else:
            result = InputValidator.validate_inchi(structure_input)

        if not result.is_valid:
            st.error(f"Invalid {input_type}: {result.errors[0]}")
            validation_passed = False

    # Submit button
    st.divider()

    # Check if we're already processing
    is_processing = SessionState.is_processing()

    if st.button(
        "Submit Analysis Job",
        type="primary",
        disabled=is_processing,
        width='stretch'
    ):
        return _submit_job(
            compound_name=compound_name,
            structure_input=structure_input,
            input_type=input_type.lower(),
            similarity_threshold=similarity_threshold,
            activity_types=selected_activities
        )

    if is_processing:
        st.info("A job is currently being submitted...")

    return None


def render_activity_checkboxes(key_prefix: str = "single") -> List[str]:
    """Render activity type checkboxes and return selected types.

    Args:
        key_prefix: Prefix for widget keys to avoid duplicates (e.g., "single", "batch")
    """
    # Get default activity types from config
    default_types = list(config.DEFAULT_ACTIVITY_TYPES)

    # Initialize session state for checkboxes (use prefix to separate single vs batch)
    state_key = f'{key_prefix}_activity_checkboxes'
    if state_key not in st.session_state:
        st.session_state[state_key] = {
            activity: True for activity in default_types
        }

    selected = []
    cols = st.columns(2)

    for i, activity in enumerate(default_types):
        with cols[i % 2]:
            is_checked = st.checkbox(
                activity,
                value=st.session_state[state_key].get(activity, True),
                key=f"{key_prefix}_activity_cb_{activity}"
            )
            st.session_state[state_key][activity] = is_checked
            if is_checked:
                selected.append(activity)

    if not selected:
        st.warning("Select at least one activity type")

    return selected


def _submit_job(
    compound_name: str,
    structure_input: str,
    input_type: str,
    similarity_threshold: int,
    activity_types: List[str]
) -> Optional[str]:
    """Submit the job to the backend.

    Returns:
        Optional[str]: Job ID if successful, None otherwise
    """
    # Validate inputs
    if not compound_name or not compound_name.strip():
        st.error("Please enter a compound name")
        return None

    if not structure_input or not structure_input.strip():
        st.error(f"Please enter a {input_type.upper()} string")
        return None

    if not activity_types:
        st.error("Please select at least one activity type")
        return None

    # Sanitize compound name (consistent with backend)
    sanitized_name = _sanitize_and_limit_name(compound_name.strip())

    if sanitized_name != compound_name.strip():
        st.info(f"Compound name sanitized: '{compound_name}' -> '{sanitized_name}'")

    # Convert InChI to SMILES if needed (backend expects SMILES)
    smiles = structure_input.strip()
    if input_type == "inchi":
        with st.spinner("Converting InChI to SMILES..."):
            smiles = _inchi_to_smiles(structure_input.strip())
            if not smiles:
                st.error("Failed to convert InChI to SMILES")
                return None
            st.success(f"Converted to SMILES: {smiles[:50]}...")

    # Submit to backend
    SessionState.start_processing(sanitized_name)

    try:
        client = get_api_client()
        response = client.submit_job(
            compound_name=sanitized_name,
            smiles=smiles,
            similarity_threshold=similarity_threshold,
            activity_types=activity_types
        )

        if response.success:
            st.success(f"Job submitted! ID: {response.job_id}")
            SessionState.add_active_job(
                job_id=response.job_id,
                compound_name=sanitized_name,
                status="pending"
            )
            # Start polling for job updates
            start_polling()
            return response.job_id
        else:
            st.error(f"Failed to submit job: {response.error}")
            return None

    except Exception as e:
        logger.error(f"Error submitting job: {e}")
        st.error(f"Error: {e}")
        return None

    finally:
        SessionState.set('is_processing', False)


def _detect_column_mappings(df) -> Dict[str, Optional[str]]:
    """
    Detect likely column mappings based on column names.

    Returns dict with suggested original column name for each required field.
    Does NOT rename columns - just suggests mappings for dropdown pre-selection.

    Args:
        df: pandas DataFrame

    Returns:
        Dict like {'compound_name': 'Molecule', 'smiles': 'SMILES', 'inchi': None}
    """
    # Column name variants (lowercase -> field type)
    compound_name_variants = [
        'compound_name', 'compoundname', 'compound', 'name', 'molecule',
        'molecule_name', 'mol_name', 'molname', 'mol', 'title', 'id',
        'cdd num', 'cdd_num', 'cddnum',
    ]

    smiles_variants = [
        'smiles', 'canonical_smiles', 'canonicalsmiles', 'canonical smiles',
        'smi', 'structure', 'mol_smiles',
    ]

    inchi_variants = [
        'inchi', 'inchikey', 'inchi_key', 'standard_inchi', 'standardinchi',
    ]

    result = {'compound_name': None, 'smiles': None, 'inchi': None}

    for col in df.columns:
        col_lower = col.lower().strip()

        # Check compound name variants (first match wins)
        if result['compound_name'] is None and col_lower in compound_name_variants:
            result['compound_name'] = col

        # Check SMILES variants
        if result['smiles'] is None and col_lower in smiles_variants:
            result['smiles'] = col

        # Check InChI variants
        if result['inchi'] is None and col_lower in inchi_variants:
            result['inchi'] = col

    return result


def _render_column_mapping_ui(df) -> Optional[Dict[str, str]]:
    """
    Render dropdown selectors for column mapping.

    Shows dropdowns with auto-detected suggestions that users can override.

    Args:
        df: pandas DataFrame with CSV data

    Returns:
        Mapping dict if valid selection, None if incomplete
    """
    st.markdown("**Column Mapping**")
    st.caption("Select which columns to use (auto-detected, you can change)")

    columns = list(df.columns)
    columns_with_none = ["-- Select --"] + columns

    # Get auto-detected suggestions
    suggestions = _detect_column_mappings(df)

    # Calculate default index based on suggestion or existing selection
    def get_default_index(field_key: str, suggestion_key: str) -> int:
        # First check if widget already has a selection (from previous render)
        widget_key = f"csv_col_{field_key}_select"
        if widget_key in st.session_state:
            selected = st.session_state[widget_key]
            if selected in columns:
                return columns.index(selected) + 1
        # Otherwise use auto-detected suggestion
        suggested = suggestions.get(suggestion_key)
        if suggested and suggested in columns:
            return columns.index(suggested) + 1
        return 0

    col1, col2 = st.columns(2)

    with col1:
        # Compound Name dropdown (required)
        selected_name = st.selectbox(
            "Compound Name Column *",
            columns_with_none,
            index=get_default_index('name', 'compound_name'),
            key="csv_col_name_select",
            help="Column containing compound identifiers"
        )

    with col2:
        # SMILES dropdown
        selected_smiles = st.selectbox(
            "SMILES Column",
            columns_with_none,
            index=get_default_index('smiles', 'smiles'),
            key="csv_col_smiles_select",
            help="Column containing SMILES strings"
        )

    # InChI dropdown
    selected_inchi = st.selectbox(
        "InChI Column (optional if SMILES selected)",
        columns_with_none,
        index=get_default_index('inchi', 'inchi'),
        key="csv_col_inchi_select",
        help="Column containing InChI strings"
    )

    # Validate selections
    has_name = selected_name != "-- Select --"
    has_smiles = selected_smiles != "-- Select --"
    has_inchi = selected_inchi != "-- Select --"

    if not has_name:
        st.warning("Please select a Compound Name column")
        return None

    if not has_smiles and not has_inchi:
        st.warning("Please select either a SMILES or InChI column")
        return None

    # Build mapping
    mapping = {'compound_name': selected_name}
    if has_smiles:
        mapping['smiles'] = selected_smiles
    if has_inchi:
        mapping['inchi'] = selected_inchi

    return mapping


def _apply_column_mapping(df, mapping: Dict[str, str]):
    """
    Apply user-selected column mapping to dataframe.

    Creates a new dataframe with standardized column names.

    Args:
        df: Original DataFrame
        mapping: Dict mapping standard names to original column names

    Returns:
        New DataFrame with standardized columns
    """
    import pandas as pd

    result = pd.DataFrame()
    result['compound_name'] = df[mapping['compound_name']]

    if mapping.get('smiles'):
        result['smiles'] = df[mapping['smiles']]
    if mapping.get('inchi'):
        result['inchi'] = df[mapping['inchi']]

    return result


def _sanitize_and_limit_name(name: str) -> str:
    """Sanitize compound name for filesystem safety with length limit."""
    # Use shared sanitization function for consistency
    safe_name = sanitize_compound_name(name)
    # Limit length for display/filesystem
    return safe_name[:100] if len(safe_name) > 100 else safe_name


def _inchi_to_smiles(inchi: str) -> Optional[str]:
    """Convert InChI to SMILES using RDKit."""
    try:
        from rdkit import Chem
        mol = Chem.MolFromInchi(inchi)
        if mol:
            return Chem.MolToSmiles(mol)
        return None
    except Exception as e:
        logger.error(f"InChI to SMILES conversion failed: {e}")
        return None


def render_csv_upload_form() -> Optional[str]:
    """Render the CSV batch upload form with duplicate confirmation.

    Returns:
        Optional[str]: Batch job ID if submitted, None otherwise
    """
    st.subheader("Batch Upload")
    st.info("Upload a CSV file with compound names and SMILES/InChI structures")

    uploaded_file = st.file_uploader(
        "Choose CSV file",
        type=['csv'],
        help="CSV with any column names - you'll map them below"
    )

    if not uploaded_file:
        # Clear state when no file
        _clear_duplicate_check_state()
        _clear_column_mapping_state()
        return None

    # Check if file changed
    if SessionState.file_changed(uploaded_file):
        # Parse and validate CSV
        import pandas as pd
        try:
            df = pd.read_csv(uploaded_file)
            st.session_state['csv_preview'] = df
            # Clear state for new file
            _clear_duplicate_check_state()
            _clear_column_mapping_state()
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
            return None

    df = st.session_state.get('csv_preview')
    if df is None:
        return None

    # Interactive column mapping UI
    column_mapping = _render_column_mapping_ui(df)

    if column_mapping is None:
        # User hasn't selected required columns yet
        return None

    # Apply user's column mapping
    df_mapped = _apply_column_mapping(df, column_mapping)

    # Store mapped dataframe for submission
    st.session_state['csv_mapped'] = df_mapped
    has_smiles = 'smiles' in df_mapped.columns
    has_inchi = 'inchi' in df_mapped.columns

    # Preview mapped data
    st.write("Preview (mapped):")
    st.dataframe(df_mapped.head(5))
    st.caption(f"{len(df_mapped)} compounds in file")

    # Configuration
    st.subheader("Batch Configuration")

    similarity_threshold = st.slider(
        "Similarity Threshold (%)",
        min_value=50,
        max_value=100,
        value=config.DEFAULT_SIMILARITY_THRESHOLD,
        key="batch_similarity"
    )

    selected_activities = render_activity_checkboxes(key_prefix="batch")

    # Check for duplicates before showing submit
    duplicate_check_done = st.session_state.get('batch_duplicate_check_done', False)
    user_confirmed = st.session_state.get('batch_user_confirmed', False)

    if not duplicate_check_done:
        # Step 1: Check for duplicates first
        if st.button("Check & Submit Batch", type="primary", width='stretch'):
            compound_names = [
                _sanitize_and_limit_name(str(row.get('compound_name', '')).strip())
                for _, row in df_mapped.iterrows()
                if str(row.get('compound_name', '')).strip()
            ]

            if not compound_names:
                st.error("No valid compound names found in file")
                return None

            with st.spinner("Checking for existing compounds..."):
                api_client = get_api_client()
                result = api_client.check_duplicates(compound_names)

                if result.get("success"):
                    st.session_state['batch_duplicate_check_done'] = True
                    st.session_state['batch_existing'] = result.get('existing', [])
                    st.session_state['batch_processing'] = result.get('processing', [])
                    st.session_state['batch_new'] = result.get('new', [])
                    st.rerun()
                else:
                    st.error(f"Failed to check duplicates: {result.get('error', 'Unknown error')}")
                    return None

    else:
        # Step 2: Show duplicate confirmation dialog
        existing = st.session_state.get('batch_existing', [])
        processing = st.session_state.get('batch_processing', [])
        new_compounds = st.session_state.get('batch_new', [])

        # Show summary with colored boxes
        st.divider()
        st.markdown("### Duplicate Check Results")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("New Compounds", len(new_compounds))
        with col2:
            st.metric("Already Processed", len(existing))
        with col3:
            st.metric("Currently Processing", len(processing))

        # Show details if there are duplicates
        if existing or processing:
            st.warning("Some compounds will be skipped:")

            if existing:
                with st.expander(f"⏭️ Already processed ({len(existing)})", expanded=False):
                    safe_names = [html.escape(name) for name in existing[:20]]
                    st.markdown(", ".join(f"`{name}`" for name in safe_names))
                    if len(existing) > 20:
                        st.caption(f"...and {len(existing) - 20} more")

            if processing:
                with st.expander(f"⏳ Currently processing ({len(processing)})", expanded=False):
                    safe_names = [html.escape(name) for name in processing[:20]]
                    st.markdown(", ".join(f"`{name}`" for name in safe_names))
                    if len(processing) > 20:
                        st.caption(f"...and {len(processing) - 20} more")

        if not new_compounds:
            st.info("All compounds already exist or are being processed. Nothing new to submit.")
            if st.button("↩️ Upload Different File", width='stretch'):
                _clear_duplicate_check_state()
                st.session_state.pop('csv_preview', None)
                st.rerun()
            return None

        # Show new compounds that will be processed
        with st.expander(f"✅ Will be processed ({len(new_compounds)})", expanded=True):
            safe_new_names = [html.escape(name) for name in new_compounds[:30]]
            st.markdown(", ".join(f"`{name}`" for name in safe_new_names))
            if len(new_compounds) > 30:
                st.caption(f"...and {len(new_compounds) - 30} more")

        # Confirmation buttons
        st.divider()
        col1, col2 = st.columns(2)

        with col1:
            if st.button("✅ Confirm & Submit", type="primary", width='stretch'):
                st.session_state['batch_user_confirmed'] = True
                return _submit_batch(
                    df=df_mapped,
                    has_smiles=has_smiles,
                    similarity_threshold=similarity_threshold,
                    activity_types=selected_activities
                )

        with col2:
            if st.button("❌ Cancel", width='stretch'):
                _clear_duplicate_check_state()
                st.session_state.pop('csv_preview', None)
                st.rerun()

    return None


def _clear_duplicate_check_state():
    """Clear duplicate check related session state."""
    keys_to_clear = [
        'batch_duplicate_check_done',
        'batch_user_confirmed',
        'batch_existing',
        'batch_processing',
        'batch_new'
    ]
    for key in keys_to_clear:
        st.session_state.pop(key, None)


def _clear_column_mapping_state():
    """Clear column mapping related session state."""
    keys_to_clear = [
        'csv_col_name_select',
        'csv_col_smiles_select',
        'csv_col_inchi_select',
        'csv_mapped',
    ]
    for key in keys_to_clear:
        st.session_state.pop(key, None)


def _submit_batch(
    df,
    has_smiles: bool,
    similarity_threshold: int,
    activity_types: List[str]
) -> Optional[str]:
    """Submit batch of compounds to backend.

    Args:
        df: DataFrame with compound_name and smiles/inchi columns
        has_smiles: True if df has 'smiles' column, False if 'inchi'
        similarity_threshold: Similarity threshold for all compounds
        activity_types: Activity types for all compounds

    Returns:
        batch_id if successful, None otherwise
    """
    if df is None or df.empty:
        st.error("No compounds to submit")
        return None

    # Determine structure column
    structure_col = 'smiles' if has_smiles else 'inchi'

    # Build compounds list for batch submission
    compounds = []
    for _, row in df.iterrows():
        compound_name = str(row.get('compound_name', '')).strip()
        structure = str(row.get(structure_col, '')).strip()

        if not compound_name or not structure:
            continue

        # Sanitize compound name
        safe_name = _sanitize_and_limit_name(compound_name)

        # Convert InChI to SMILES if needed
        smiles = structure
        if not has_smiles:
            converted = _inchi_to_smiles(structure)
            if converted:
                smiles = converted
            else:
                logger.warning(f"Could not convert InChI for {compound_name}, skipping")
                continue

        compounds.append({
            "compound_name": safe_name,
            "smiles": smiles,
            "similarity_threshold": similarity_threshold,
            "activity_types": activity_types,
        })

    if not compounds:
        st.error("No valid compounds found in file")
        return None

    # Submit batch
    with st.spinner(f"Submitting {len(compounds)} compounds..."):
        try:
            api_client = get_api_client()
            result = api_client.submit_batch_job(compounds, skip_existing=True)

            if result.get("success"):
                batch_id = result.get("batch_id")
                jobs = result.get("jobs", [])
                skipped_existing = result.get("skipped_existing", [])
                skipped_processing = result.get("skipped_processing", [])

                # Show summary
                st.success(f"Batch submitted: {len(jobs)} jobs queued")

                if skipped_existing:
                    st.info(f"Skipped {len(skipped_existing)} already processed: {', '.join(skipped_existing[:5])}{'...' if len(skipped_existing) > 5 else ''}")

                if skipped_processing:
                    st.info(f"Skipped {len(skipped_processing)} currently processing: {', '.join(skipped_processing[:5])}{'...' if len(skipped_processing) > 5 else ''}")

                # Start polling for job updates
                start_polling()

                return batch_id
            else:
                st.error(f"Batch submission failed: {result.get('error', 'Unknown error')}")
                return None

        except Exception as e:
            logger.error(f"Batch submission error: {e}")
            st.error(f"Error submitting batch: {e}")
            return None
