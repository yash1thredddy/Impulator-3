"""
Configuration settings and constants for the IMPULATOR application.
"""
import os
from pathlib import Path

# Directory Configuration
BASE_DIR = Path(__file__).parent
RESULTS_DIR = os.path.join(BASE_DIR, "analysis_results")

# Create directories if they don't exist
os.makedirs(RESULTS_DIR, exist_ok=True)

# Environment Detection
def get_deployment_environment() -> str:
    """
    Detect the deployment environment.

    Returns:
        str: 'hf_spaces', 'streamlit_cloud', 'docker', or 'local'
    """
    # Hugging Face Spaces
    if os.environ.get('SPACE_ID') or os.environ.get('SPACE_AUTHOR_NAME'):
        return 'hf_spaces'

    # Streamlit Cloud
    if os.environ.get('STREAMLIT_SHARING_MODE') or os.path.exists('/mount/src'):
        return 'streamlit_cloud'

    # Docker
    if os.path.exists('/.dockerenv'):
        return 'docker'

    # Local
    return 'local'

# API and Processing Constants
ACTIVITY_TYPES = ["IC50", "EC50", "Ki", "Kd", "AC50", "GI50", "MIC"]
MAX_CSV_SIZE_MB = 10

# API Batch Processing Settings (environment-aware)
MAX_BATCH_SIZE = 950  # Maximum number of items per batch

# Adjust MAX_WORKERS based on environment
DEPLOYMENT_ENV = get_deployment_environment()
if DEPLOYMENT_ENV == 'hf_spaces':
    MAX_WORKERS = 8  # HF Spaces has 2 vCPU, 16 GB RAM - can handle more workers
elif DEPLOYMENT_ENV == 'streamlit_cloud':
    MAX_WORKERS = 3  # Streamlit Cloud has limited resources (1 GB RAM)
elif DEPLOYMENT_ENV == 'docker':
    MAX_WORKERS = 5  # Standard Docker deployment
else:
    MAX_WORKERS = 5  # Local development

# API Retry Configuration
MAX_RETRIES = 3
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]
RETRY_BACKOFF_FACTOR = 1
API_TIMEOUT = 30  # Timeout in seconds

# Logging Configuration
LOG_LEVEL = "INFO"
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Cache Configuration
CACHE_SIZE = 128  # LRU cache size for API responses

# Visualization Settings
PLOTLY_THEME = "plotly_white"  # Default Plotly theme
PLOT_HEIGHT = 600  # Default plot height in pixels
PLOT_WIDTH = 900   # Default plot width in pixels
COLOR_SCALES = {
    "sequential": "Viridis",
    "diverging": "RdBu",
    "categorical": "Dark24"
}

# Molecule Rendering Settings
MOLECULE_2D_SIZE = (400, 400)  # Size of 2D molecule images
MOLECULE_3D_STYLE = "stick"    # Default 3D visualization style ('stick', 'line', 'cross', 'sphere')
MOLECULE_COLORS = {
    "C": "#808080",  # Carbon
    "O": "#FF0000",  # Oxygen
    "N": "#0000FF",  # Nitrogen
    "S": "#FFFF00",  # Sulfur
    "F": "#00FF00",  # Fluorine
    "P": "#FFA500",  # Phosphorus
    "Cl": "#00FFFF", # Chlorine
    "Br": "#A52A2A", # Bromine
    "I": "#800080"   # Iodine
}

# O[Q/P/L]A Scoring Configuration
USE_PDB_EVIDENCE = True  # Enable PDB Structural Evidence (Component 4)
SHOW_PDB_PROGRESS = True  # Show progress indicators during PDB queries
PDB_API_DELAY = 0.1  # Delay between PDB API calls (seconds) to avoid rate limiting