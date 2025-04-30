"""
Import all module components for easy access.
"""
from modules.api_client import (
    get_molecule_data,
    get_classification,
    get_chembl_ids,
    batch_fetch_activities,
    fetch_compound_activities
)

from modules.data_processor import (
    extract_properties,
    calculate_efficiency_metrics,
    extract_classification_data,
    process_single_compound,
    process_compounds_parallel,
    process_compound,
    load_results
)

from modules.utils import (
    validate_smiles,
    validate_compound_name,
    validate_csv_file,
    get_available_compounds,
    zip_results,
    zip_compound_results,
    format_smiles_for_display
)

from modules.visualization import (
    plot_all_visualizations,
    plot_efficiency_scatter_plots,
    plot_activity_visualizations,
    plot_property_visualizations,
    generate_molecular_structures,
    display_interactive_plot,
    show_interactive_plots,
    show_molecular_structures
)

from modules.compound_manager import (
    check_existing_compound,
    process_and_store,
    process_csv_batch,
    display_compound_summary
)

from modules.molecule_viewer import (
    generate_3d_coordinates,
    view_molecule_3d,
    view_molecule_from_smiles,
    get_molecule_style_controls,
    molecule_viewer_app
)