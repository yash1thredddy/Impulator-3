#!/usr/bin/env python3
"""
Rebuild metadata CSV from existing compound folders.
Run this to regenerate the metadata CSV if it's missing.
"""

import os
import sys
import pandas as pd
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

RESULTS_DIR = "analysis_results"

def extract_compound_metadata(compound_name: str, results_folder: str) -> dict:
    """Extract lightweight metadata from a processed compound."""
    metadata = {
        'compound_name': compound_name,
        'processed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_activities': 0,
        'num_outliers': 0,
        'qed': 0.0,
        'similarity_threshold': 90,
        'chembl_id': '',
        'smiles': ''
    }

    try:
        # Read metadata JSON file first (has similarity_threshold and outlier_summary)
        metadata_json_path = os.path.join(results_folder, f"{compound_name}_metadata.json")
        if os.path.exists(metadata_json_path):
            with open(metadata_json_path, 'r') as f:
                json_metadata = json.load(f)
                metadata['similarity_threshold'] = json_metadata.get('similarity_threshold', 90)

                # Get number of outliers from outlier_summary
                outlier_summary = json_metadata.get('outlier_summary', {})
                metadata['num_outliers'] = outlier_summary.get('efficiency_outliers', 0)

        # Read complete results CSV
        csv_path = os.path.join(results_folder, f"{compound_name}_complete_results.csv")

        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            metadata['total_activities'] = len(df)

            # Get ChEMBL ID, SMILES, and QED from first row
            if not df.empty:
                if 'ChEMBL_ID' in df.columns:
                    metadata['chembl_id'] = str(df['ChEMBL_ID'].iloc[0])
                if 'SMILES' in df.columns:
                    metadata['smiles'] = str(df['SMILES'].iloc[0])
                if 'QED' in df.columns:
                    qed_value = df['QED'].iloc[0]
                    # Handle NaN values
                    if pd.notna(qed_value):
                        metadata['qed'] = float(qed_value)

        print(f"✅ Extracted metadata for {compound_name}: {metadata['num_outliers']} outliers, QED={metadata['qed']:.2f}")

    except Exception as e:
        print(f"❌ Error extracting metadata for {compound_name}: {e}")

    return metadata


def rebuild_metadata_csv():
    """Rebuild the metadata CSV from existing compound folders."""
    if not os.path.exists(RESULTS_DIR):
        print(f"❌ Results directory not found: {RESULTS_DIR}")
        return

    metadata_list = []

    # Scan all compound folders
    for compound_name in os.listdir(RESULTS_DIR):
        compound_folder = os.path.join(RESULTS_DIR, compound_name)

        if os.path.isdir(compound_folder):
            print(f"\nProcessing {compound_name}...")
            metadata = extract_compound_metadata(compound_name, compound_folder)
            metadata_list.append(metadata)

    if metadata_list:
        # Create DataFrame
        metadata_df = pd.DataFrame(metadata_list)

        # Save to CSV
        metadata_csv_path = os.path.join(RESULTS_DIR, 'compounds_metadata.csv')
        metadata_df.to_csv(metadata_csv_path, index=False)

        print(f"\n{'='*60}")
        print(f"✅ Successfully rebuilt metadata CSV with {len(metadata_df)} compounds")
        print(f"📁 Saved to: {metadata_csv_path}")
        print(f"{'='*60}")
    else:
        print("\n❌ No compound folders found")


if __name__ == "__main__":
    print("Rebuilding metadata CSV...")
    print("="*60)
    rebuild_metadata_csv()
