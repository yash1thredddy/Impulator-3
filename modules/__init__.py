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
    extract_classification_data,
    process_single_compound,
    process_compounds_parallel,
    process_compound,
    load_results
)

# Legacy wrapper for backward compatibility with old code
def calculate_efficiency_metrics(pActivity, psa, molecular_weight, npol, heavy_atoms):
    """
    Backward compatibility wrapper for calculate_efficiency_metrics.
    In v2, this functionality is in efficiency_metrics module, but data_processor handles it internally.
    """
    try:
        from modules.efficiency_metrics import calculate_all_efficiency_metrics
        metrics = calculate_all_efficiency_metrics(pActivity, psa, molecular_weight, npol, heavy_atoms)
        return metrics['SEI'], metrics['BEI'], metrics['NSEI'], metrics['NBEI']
    except Exception:
        # Fallback to simple calculation if module not available
        sei = pActivity / (psa / 100) if psa and psa > 0 else float('nan')
        bei = pActivity / (molecular_weight / 1000) if molecular_weight and molecular_weight > 0 else float('nan')
        nsei = pActivity / npol if npol and npol > 0 else float('nan')
        nbei = pActivity / heavy_atoms if heavy_atoms and heavy_atoms > 0 else float('nan')
        return sei, bei, nsei, nbei

from modules.utils import (
    validate_smiles,
    validate_compound_name,
    validate_csv_file,
    get_available_compounds,
    zip_results,
    zip_compound_results,
    format_smiles_for_display,
    delete_compound
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