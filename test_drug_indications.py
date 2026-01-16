"""
Test script to verify ChEMBL drug_indication API data availability.

Run this script standalone to check what data we can get:
- MESH ID (links to https://id.nlm.nih.gov/mesh/{mesh_id}.html)
- MESH Heading (disease name)
- EFO ID (links to https://www.ebi.ac.uk/ols4/ontologies/efo/classes?short_form={efo_id})
- EFO Terms
- Max Phase for Indication
- ChEMBL ID
- Clinical Trials references

Usage: python test_drug_indications.py
"""

import json
from pprint import pprint

def test_drug_indication_api():
    """Test the ChEMBL drug_indication endpoint."""
    print("=" * 60)
    print("Testing ChEMBL Drug Indication API")
    print("=" * 60)

    try:
        from chembl_webresource_client.new_client import new_client
        drug_indication = new_client.drug_indication
        print("✅ ChEMBL client imported successfully")
    except ImportError:
        print("❌ chembl_webresource_client not installed")
        print("   Run: pip install chembl_webresource_client")
        return

    # Test with a known drug that has indications (CHEMBL50 is Atorvastatin)
    test_chembl_ids = [
        'CHEMBL50',      # Atorvastatin (cholesterol drug)
        'CHEMBL1201631', # Pembrolizumab (cancer drug)
        'CHEMBL941',     # Metformin (diabetes drug)
    ]

    for chembl_id in test_chembl_ids:
        print(f"\n{'=' * 60}")
        print(f"Testing: {chembl_id}")
        print("=" * 60)

        try:
            # Fetch all indications for this compound
            indications = drug_indication.filter(molecule_chembl_id=chembl_id)
            indication_list = list(indications)

            print(f"Found {len(indication_list)} indications")

            if indication_list:
                # Show first indication with ALL available fields
                print("\n📋 First indication (ALL FIELDS):")
                print("-" * 40)
                first = indication_list[0]
                for key, value in sorted(first.items()):
                    print(f"  {key}: {value}")

                # Check specifically for clinical trial references
                print("\n🔍 Checking for Clinical Trial References:")
                print("-" * 40)

                # Look for any field that might contain clinical trial info
                trial_fields = ['ref_id', 'ref_type', 'ref_url', 'reference',
                               'clinical_trial', 'nct', 'trial', 'document']

                found_trial_fields = []
                for field in trial_fields:
                    if field in first:
                        found_trial_fields.append(field)
                        print(f"  ✅ Found '{field}': {first[field]}")

                if not found_trial_fields:
                    print("  ⚠️  No obvious clinical trial fields found in drug_indication")
                    print("     Need to check 'document' or other endpoints for trial refs")

                # Build URLs for MESH and EFO
                print("\n🔗 URL Construction Test:")
                print("-" * 40)

                mesh_id = first.get('mesh_id', '')
                efo_id = first.get('efo_id', '')

                if mesh_id:
                    mesh_url = f"https://id.nlm.nih.gov/mesh/{mesh_id}.html"
                    print(f"  MESH URL: {mesh_url}")
                else:
                    print("  MESH ID: Not available")

                if efo_id:
                    # EFO IDs are like "EFO:0001645", need to convert to "EFO_0001645"
                    efo_short = efo_id.replace(':', '_')
                    efo_url = f"https://www.ebi.ac.uk/ols4/ontologies/efo/classes?short_form={efo_short}"
                    print(f"  EFO URL: {efo_url}")
                else:
                    print("  EFO ID: Not available")

                # Show summary table
                print("\n📊 Sample Indications Table:")
                print("-" * 100)
                print(f"{'#':<3} {'MESH ID':<12} {'MESH Heading':<30} {'EFO ID':<15} {'Max Phase':<10}")
                print("-" * 100)

                for i, ind in enumerate(indication_list[:5], 1):
                    mesh_id = ind.get('mesh_id', 'N/A')
                    mesh_heading = ind.get('mesh_heading', 'N/A')[:28]
                    efo_id = ind.get('efo_id', 'N/A')
                    max_phase = ind.get('max_phase_for_ind', 'N/A')
                    print(f"{i:<3} {mesh_id:<12} {mesh_heading:<30} {efo_id:<15} {max_phase:<10}")

                if len(indication_list) > 5:
                    print(f"... and {len(indication_list) - 5} more indications")

        except Exception as e:
            print(f"❌ Error: {str(e)}")


def test_indication_refs():
    """
    Test if we can get clinical trial references from ChEMBL.
    The indication_refs endpoint might have this data.
    """
    print("\n" + "=" * 60)
    print("Testing ChEMBL indication_refs (for clinical trials)")
    print("=" * 60)

    try:
        from chembl_webresource_client.new_client import new_client

        # Check if indication_refs exists
        if hasattr(new_client, 'indication_refs'):
            indication_refs = new_client.indication_refs
            print("✅ indication_refs endpoint exists")

            # Try to get refs for a known drug
            refs = indication_refs.filter(molecule_chembl_id='CHEMBL50')
            ref_list = list(refs)[:5]

            if ref_list:
                print(f"Found {len(ref_list)} references")
                print("\n📋 First reference (ALL FIELDS):")
                for key, value in sorted(ref_list[0].items()):
                    print(f"  {key}: {value}")
        else:
            print("⚠️  indication_refs endpoint not directly available")

        # Try drug_indication with full fields
        print("\n🔍 Checking drug_indication for ref fields...")
        drug_indication = new_client.drug_indication

        # Get indication with all possible fields
        indications = drug_indication.filter(molecule_chembl_id='CHEMBL50')

        # Don't filter fields - get everything
        ind_list = list(indications)[:1]

        if ind_list:
            print("\nAll available fields in drug_indication:")
            for key in sorted(ind_list[0].keys()):
                print(f"  - {key}")

    except Exception as e:
        print(f"❌ Error: {str(e)}")


def test_document_endpoint():
    """
    Test if we can get clinical trial refs from document endpoint.
    Clinical trial references might be stored as documents.
    """
    print("\n" + "=" * 60)
    print("Testing ChEMBL document endpoint (for clinical trials)")
    print("=" * 60)

    try:
        from chembl_webresource_client.new_client import new_client

        # Get document endpoint
        document = new_client.document

        # Search for documents with clinical trial source
        # Clinical trial documents have doc_type = 'CLINICAL_TRIAL'
        print("\n🔍 Searching for clinical trial documents...")

        # Filter by doc_type
        ct_docs = document.filter(doc_type='CLINICAL_TRIAL')
        ct_list = list(ct_docs)[:5]

        if ct_list:
            print(f"✅ Found clinical trial documents!")
            print("\n📋 Sample clinical trial document:")
            for key, value in sorted(ct_list[0].items()):
                print(f"  {key}: {value}")

            # Check if there's an NCT ID or clinicaltrials.gov link
            first = ct_list[0]
            if 'src_id' in first:
                nct_id = first.get('src_id', '')
                if nct_id.startswith('NCT'):
                    ct_url = f"https://clinicaltrials.gov/study/{nct_id}"
                    print(f"\n🔗 Clinical Trial URL: {ct_url}")
        else:
            print("⚠️  No clinical trial documents found with this filter")

        # Also try getting documents for a specific compound
        print("\n🔍 Getting documents for CHEMBL50 (Atorvastatin)...")

        # Get activities to find document IDs
        activity = new_client.activity
        activities = activity.filter(
            molecule_chembl_id='CHEMBL50',
        ).only('document_chembl_id')

        doc_ids = set()
        for act in list(activities)[:100]:
            if act.get('document_chembl_id'):
                doc_ids.add(act['document_chembl_id'])

        print(f"Found {len(doc_ids)} unique documents")

        # Check first few documents for clinical trial type
        ct_count = 0
        for doc_id in list(doc_ids)[:20]:
            doc_data = document.get(doc_id)
            if doc_data and doc_data.get('doc_type') == 'CLINICAL_TRIAL':
                ct_count += 1
                if ct_count == 1:
                    print("\n📋 Clinical trial document found:")
                    for key, value in sorted(doc_data.items()):
                        print(f"  {key}: {value}")

        print(f"\n✅ Found {ct_count} clinical trial documents out of {min(20, len(doc_ids))} checked")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()


def test_all_available_resources():
    """List all available resources in chembl_webresource_client."""
    print("\n" + "=" * 60)
    print("Available ChEMBL API Resources")
    print("=" * 60)

    try:
        from chembl_webresource_client.new_client import new_client

        # List all attributes that are resources
        resources = []
        for attr in dir(new_client):
            if not attr.startswith('_'):
                obj = getattr(new_client, attr)
                if hasattr(obj, 'filter'):
                    resources.append(attr)

        print(f"\nFound {len(resources)} API resources:")
        for r in sorted(resources):
            print(f"  - {r}")

        # Check for indication-related resources
        print("\n🔍 Indication-related resources:")
        for r in resources:
            if 'ind' in r.lower() or 'drug' in r.lower() or 'trial' in r.lower():
                print(f"  ✅ {r}")

    except Exception as e:
        print(f"❌ Error: {str(e)}")


if __name__ == '__main__':
    # Run all tests
    test_all_available_resources()
    test_drug_indication_api()
    test_indication_refs()
    test_document_endpoint()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("\nRun this script to see what data is available from ChEMBL.")
    print("Based on results, we'll implement the Drug Indications tab.")
