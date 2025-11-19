import logging
import sys
import os
import time

# Add current dir to path
sys.path.append(os.getcwd())

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_pdb")

print("--- Starting PDB Connection Verification ---")

try:
    print("1. Importing modules.pdb_client...")
    from modules.pdb_client import search_similar_ligands
    print("   Import successful.")
except Exception as e:
    print(f"   ❌ Import failed: {e}")
    sys.exit(1)

try:
    print("\n2. Testing search_similar_ligands (Direct API)...")
    # Aspirin SMILES
    smiles = "CC(=O)Oc1ccccc1C(=O)O"
    print(f"   Querying for SMILES: {smiles}")
    
    start_time = time.time()
    results = search_similar_ligands(smiles)
    duration = time.time() - start_time
    
    if results:
        print(f"   ✅ Success! Found {len(results)} similar structures in {duration:.2f}s.")
        print(f"   Sample IDs: {results[:5]}")
    else:
        print(f"   ⚠️ No results found (but no crash). Duration: {duration:.2f}s.")

except Exception as e:
    print(f"   ❌ Search failed: {e}")
    import traceback
    traceback.print_exc()

print("\n--- Verification Complete ---")
