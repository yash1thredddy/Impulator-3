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

# API and Processing Constants
ACTIVITY_TYPES = ["IC50", "EC50", "Ki", "Kd", "AC50", "GI50", "MIC"]
MAX_CSV_SIZE_MB = 10

# API Batch Processing Settings
MAX_BATCH_SIZE = 950  # Maximum number of items per batch
MAX_WORKERS = 5      # Number of concurrent workers for API requests

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