# Future Integrations

> This document outlines planned integrations and how to implement them.

---

## 1. PubChem Integration

### Overview
PubChem is a free chemistry database with over 100 million compounds. Integration will provide:
- Additional compound data
- Bioactivity information
- Cross-referencing with ChEMBL

### API Details

**Base URL**: `https://pubchem.ncbi.nlm.nih.gov/rest/pug`

**Key Endpoints**:
```
GET /compound/smiles/{smiles}/cids/JSON
    → Get PubChem CID from SMILES

GET /compound/cid/{cid}/property/{properties}/JSON
    → Get compound properties

GET /compound/cid/{cid}/assaysummary/JSON
    → Get bioactivity assays

GET /compound/fastsimilarity_2d/smiles/{smiles}/cids/JSON
    → Similarity search
```

**Rate Limits**:
- 5 requests/second (no API key)
- 400 requests/minute burst

### Implementation Plan

#### Phase 1: Client Module

```python
# modules/pubchem_client.py
import requests
from typing import Optional, List, Dict
import time

class PubChemClient:
    """PubChem REST API client."""

    BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

    def __init__(self, rate_limit: float = 5.0):
        self.min_interval = 1.0 / rate_limit
        self.last_request = 0
        self.session = requests.Session()

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()

    def _request(self, endpoint: str, **params) -> Optional[dict]:
        """Make rate-limited request."""
        self._rate_limit()

        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                response.raise_for_status()
        except Exception as e:
            logger.error(f"PubChem request failed: {e}")
            return None

    def get_cid_from_smiles(self, smiles: str) -> Optional[int]:
        """Get PubChem CID from SMILES."""
        endpoint = f"/compound/smiles/{requests.utils.quote(smiles)}/cids/JSON"
        data = self._request(endpoint)
        if data and "IdentifierList" in data:
            cids = data["IdentifierList"].get("CID", [])
            return cids[0] if cids else None
        return None

    def get_compound_properties(
        self,
        cid: int,
        properties: List[str] = None
    ) -> Optional[dict]:
        """Get compound properties."""
        if properties is None:
            properties = [
                "MolecularWeight",
                "XLogP",
                "TPSA",
                "HBondDonorCount",
                "HBondAcceptorCount",
                "RotatableBondCount",
                "Complexity",
                "CanonicalSMILES",
                "InChI",
                "InChIKey"
            ]

        prop_string = ",".join(properties)
        endpoint = f"/compound/cid/{cid}/property/{prop_string}/JSON"
        data = self._request(endpoint)

        if data and "PropertyTable" in data:
            props = data["PropertyTable"].get("Properties", [])
            return props[0] if props else None
        return None

    def get_bioactivity_summary(self, cid: int) -> List[dict]:
        """Get bioactivity assay summary."""
        endpoint = f"/compound/cid/{cid}/assaysummary/JSON"
        data = self._request(endpoint)

        if data and "AssaySummaries" in data:
            return data["AssaySummaries"]
        return []

    def similarity_search(
        self,
        smiles: str,
        threshold: int = 90,
        max_records: int = 100
    ) -> List[int]:
        """Find similar compounds."""
        endpoint = f"/compound/fastsimilarity_2d/smiles/{requests.utils.quote(smiles)}/cids/JSON"
        params = {
            "Threshold": threshold,
            "MaxRecords": max_records
        }
        data = self._request(endpoint, **params)

        if data and "IdentifierList" in data:
            return data["IdentifierList"].get("CID", [])
        return []

    def get_synonyms(self, cid: int) -> List[str]:
        """Get compound synonyms/names."""
        endpoint = f"/compound/cid/{cid}/synonyms/JSON"
        data = self._request(endpoint)

        if data and "InformationList" in data:
            info = data["InformationList"].get("Information", [])
            if info:
                return info[0].get("Synonym", [])
        return []
```

#### Phase 2: Integration with Data Processor

```python
# modules/data_processor.py (additions)

from modules.pubchem_client import PubChemClient

pubchem = PubChemClient()

def enrich_with_pubchem(df: pd.DataFrame) -> pd.DataFrame:
    """Enrich compound data with PubChem information."""
    enriched_data = []

    for idx, row in df.iterrows():
        smiles = row.get('SMILES', row.get('Canonical_SMILES'))
        if not smiles:
            continue

        # Get PubChem CID
        cid = pubchem.get_cid_from_smiles(smiles)

        if cid:
            # Get properties
            props = pubchem.get_compound_properties(cid)

            enriched_data.append({
                'ChEMBL_ID': row.get('ChEMBL_ID'),
                'PubChem_CID': cid,
                'PubChem_XLogP': props.get('XLogP') if props else None,
                'PubChem_Complexity': props.get('Complexity') if props else None,
            })

    if enriched_data:
        enriched_df = pd.DataFrame(enriched_data)
        df = df.merge(enriched_df, on='ChEMBL_ID', how='left')

    return df
```

#### Phase 3: UI Integration

```python
# In app.py or compound details view
def display_pubchem_info(smiles: str):
    """Display PubChem information."""
    st.subheader("PubChem Data")

    cid = pubchem.get_cid_from_smiles(smiles)

    if cid:
        st.write(f"**PubChem CID**: [{cid}](https://pubchem.ncbi.nlm.nih.gov/compound/{cid})")

        props = pubchem.get_compound_properties(cid)
        if props:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("XLogP", props.get('XLogP', 'N/A'))
                st.metric("Complexity", props.get('Complexity', 'N/A'))
            with col2:
                st.metric("TPSA", props.get('TPSA', 'N/A'))
                st.metric("Rotatable Bonds", props.get('RotatableBondCount', 'N/A'))

        # Synonyms
        synonyms = pubchem.get_synonyms(cid)
        if synonyms:
            st.write("**Known Names**:", ", ".join(synonyms[:5]))
    else:
        st.info("Compound not found in PubChem")
```

---

## 2. UniProt Integration

### Overview
UniProt provides protein sequence and functional information. Integration will enhance target analysis.

### API Details

**Base URL**: `https://rest.uniprot.org`

**Key Endpoints**:
```
GET /uniprotkb/search?query={query}&format=json
    → Search proteins

GET /uniprotkb/{accession}?format=json
    → Get protein details
```

### Implementation Plan

```python
# modules/uniprot_client.py
import requests
from typing import Optional, List, Dict

class UniProtClient:
    """UniProt REST API client."""

    BASE_URL = "https://rest.uniprot.org"

    def search_protein(self, query: str, limit: int = 10) -> List[dict]:
        """Search for proteins."""
        url = f"{self.BASE_URL}/uniprotkb/search"
        params = {
            "query": query,
            "format": "json",
            "size": limit
        }
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return data.get("results", [])
        return []

    def get_protein(self, accession: str) -> Optional[dict]:
        """Get protein by UniProt accession."""
        url = f"{self.BASE_URL}/uniprotkb/{accession}"
        params = {"format": "json"}
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None

    def get_protein_by_gene(self, gene_name: str, organism: str = "human") -> Optional[dict]:
        """Get protein by gene name."""
        query = f"gene:{gene_name} AND organism_name:{organism}"
        results = self.search_protein(query, limit=1)
        return results[0] if results else None
```

---

## 3. ChemSpider Integration

### Overview
ChemSpider is a free chemical structure database with links to many data sources.

### API Details

**Base URL**: `https://api.rsc.org/compounds/v1`

**Requirements**: API key required (free registration)

### Implementation Plan

```python
# modules/chemspider_client.py
import requests
import os
from typing import Optional, List

class ChemSpiderClient:
    """ChemSpider API client."""

    BASE_URL = "https://api.rsc.org/compounds/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("CHEMSPIDER_API_KEY")
        self.headers = {"apikey": self.api_key}

    def search_by_smiles(self, smiles: str) -> Optional[int]:
        """Search for compound by SMILES."""
        url = f"{self.BASE_URL}/filter/smiles"
        data = {"smiles": smiles}
        response = requests.post(
            url, json=data, headers=self.headers, timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            query_id = result.get("queryId")
            # Poll for results...
            return self._get_filter_results(query_id)
        return None

    def get_compound(self, csid: int) -> Optional[dict]:
        """Get compound details by ChemSpider ID."""
        url = f"{self.BASE_URL}/{csid}/details"
        response = requests.get(url, headers=self.headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None
```

---

## 4. DrugBank Integration

### Overview
DrugBank contains detailed drug and drug target information.

**Note**: DrugBank requires licensing for commercial use. Academic use may be available.

### Data Points Available:
- Drug-target interactions
- Pharmacokinetics
- Drug-drug interactions
- Adverse effects

---

## 5. ZINC Database Integration

### Overview
ZINC contains commercially available compounds for virtual screening.

### Use Cases:
- Find purchasable analogs
- Check commercial availability
- Get vendor information

### Implementation Plan

```python
# modules/zinc_client.py
import requests
from typing import List, Dict

class ZINCClient:
    """ZINC database client."""

    BASE_URL = "https://zinc15.docking.org"

    def search_similar(self, smiles: str, threshold: float = 0.7) -> List[dict]:
        """Find similar commercially available compounds."""
        url = f"{self.BASE_URL}/substances/search/"
        params = {
            "smiles": smiles,
            "threshold": threshold,
            "output_format": "json"
        }
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
        return []

    def check_availability(self, zinc_id: str) -> Dict:
        """Check commercial availability."""
        url = f"{self.BASE_URL}/substances/{zinc_id}/vendors/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return {}
```

---

## 6. Enhanced Classification APIs

### Current APIs
- ClassyFire - Chemical taxonomy
- NPClassifier - Natural products

### Future Additions

#### LOTUS (Natural Products)
```python
# modules/lotus_client.py
class LOTUSClient:
    """LOTUS natural products database."""

    BASE_URL = "https://lotus.naturalproducts.net/api"

    def search_by_inchikey(self, inchikey: str) -> Optional[dict]:
        """Search LOTUS by InChIKey."""
        url = f"{self.BASE_URL}/structures/search/inchikey/{inchikey}"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None
```

#### ChEBI (Chemical Entities of Biological Interest)
```python
# modules/chebi_client.py
from zeep import Client  # SOAP client

class ChEBIClient:
    """ChEBI SOAP API client."""

    WSDL_URL = "https://www.ebi.ac.uk/webservices/chebi/2.0/webservice?wsdl"

    def __init__(self):
        self.client = Client(self.WSDL_URL)

    def get_entity(self, chebi_id: str) -> Optional[dict]:
        """Get ChEBI entity details."""
        try:
            result = self.client.service.getCompleteEntity(chebi_id)
            return result
        except Exception:
            return None
```

---

## 7. Structure-Based Integration

### RCSB PDB Enhancements

Current implementation queries for similar structures. Enhancements:

```python
# modules/pdb_client.py (enhancements)

class EnhancedPDBClient(PDBClient):
    """Enhanced PDB client with additional features."""

    def get_ligand_interactions(self, pdb_id: str, ligand_id: str) -> dict:
        """Get detailed ligand-protein interactions."""
        url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
        # Implementation...

    def get_binding_site_residues(self, pdb_id: str, ligand_id: str) -> List[dict]:
        """Get binding site residue information."""
        # Implementation...

    def get_resolution(self, pdb_id: str) -> Optional[float]:
        """Get structure resolution."""
        # Implementation...
```

### AlphaFold Integration

```python
# modules/alphafold_client.py
class AlphaFoldClient:
    """AlphaFold structure prediction database."""

    BASE_URL = "https://alphafold.ebi.ac.uk/api"

    def get_prediction(self, uniprot_id: str) -> Optional[dict]:
        """Get AlphaFold structure prediction."""
        url = f"{self.BASE_URL}/prediction/{uniprot_id}"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None

    def download_structure(self, uniprot_id: str, format: str = "pdb") -> Optional[str]:
        """Download predicted structure."""
        url = f"{self.BASE_URL}/files/{uniprot_id}-model_v4.{format}"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.text
        return None
```

---

## 8. Integration Architecture

### Unified API Client Interface

```python
# modules/base_client.py
from abc import ABC, abstractmethod
from typing import Optional, List, Dict

class ChemicalDataSource(ABC):
    """Abstract base class for chemical data sources."""

    @abstractmethod
    def search_by_smiles(self, smiles: str) -> List[Dict]:
        """Search compounds by SMILES."""
        pass

    @abstractmethod
    def get_compound(self, identifier: str) -> Optional[Dict]:
        """Get compound details by identifier."""
        pass

    @abstractmethod
    def get_activities(self, identifier: str) -> List[Dict]:
        """Get bioactivity data."""
        pass

# All clients implement this interface
class ChEMBLClient(ChemicalDataSource): ...
class PubChemClient(ChemicalDataSource): ...
class UniChemClient(ChemicalDataSource): ...
```

### Aggregator Service

```python
# modules/aggregator.py
class CompoundAggregator:
    """Aggregate data from multiple sources."""

    def __init__(self):
        self.sources = {
            'chembl': ChEMBLClient(),
            'pubchem': PubChemClient(),
            'pdb': PDBClient(),
        }

    def get_all_data(self, smiles: str) -> Dict:
        """Aggregate data from all sources."""
        results = {}

        for name, client in self.sources.items():
            try:
                data = client.search_by_smiles(smiles)
                results[name] = data
            except Exception as e:
                results[name] = {'error': str(e)}

        return results
```

---

## 9. Configuration for New APIs

### Environment Variables

```bash
# .env (add to .gitignore)

# Existing
AZURE_STORAGE_CONNECTION_STRING=...

# New API keys
CHEMSPIDER_API_KEY=...
DRUGBANK_API_KEY=...  # If licensed

# Feature flags
ENABLE_PUBCHEM=true
ENABLE_UNIPROT=true
ENABLE_ALPHAFOLD=true
```

### Config Module Update

```python
# config.py (additions)

# API Feature Flags
ENABLE_PUBCHEM = os.getenv("ENABLE_PUBCHEM", "true").lower() == "true"
ENABLE_UNIPROT = os.getenv("ENABLE_UNIPROT", "true").lower() == "true"
ENABLE_ALPHAFOLD = os.getenv("ENABLE_ALPHAFOLD", "false").lower() == "true"

# API Keys
CHEMSPIDER_API_KEY = os.getenv("CHEMSPIDER_API_KEY")

# Rate Limits (requests per second)
RATE_LIMITS = {
    'chembl': 10,
    'pubchem': 5,
    'pdb': 5,
    'uniprot': 10,
    'alphafold': 5,
}
```

---

## 10. Implementation Priority

| Integration | Priority | Effort | Value | Dependencies |
|-------------|----------|--------|-------|--------------|
| PubChem | High | Medium | High | None |
| UniProt | Medium | Low | Medium | None |
| AlphaFold | Medium | Low | High | UniProt |
| ChemSpider | Low | Medium | Medium | API Key |
| ZINC | Low | Low | Medium | None |
| DrugBank | Low | High | High | License |
| LOTUS | Low | Low | Low | None |
| ChEBI | Low | Medium | Low | None |

### Recommended Order:
1. **PubChem** - Free, comprehensive, high value
2. **UniProt** - Enhances target information
3. **AlphaFold** - Structural predictions
4. Others as needed

---

## 11. Testing Strategy for New Integrations

```python
# tests/integration/test_pubchem.py
import pytest
from modules.pubchem_client import PubChemClient

@pytest.fixture
def pubchem():
    return PubChemClient()

def test_get_cid_from_smiles(pubchem):
    # Aspirin
    cid = pubchem.get_cid_from_smiles("CC(=O)OC1=CC=CC=C1C(=O)O")
    assert cid == 2244

def test_get_compound_properties(pubchem):
    props = pubchem.get_compound_properties(2244)
    assert props is not None
    assert 'MolecularWeight' in props

def test_similarity_search(pubchem):
    # Aspirin analogs
    cids = pubchem.similarity_search("CC(=O)OC1=CC=CC=C1C(=O)O", threshold=90)
    assert len(cids) > 0
    assert 2244 in cids  # Aspirin itself

def test_invalid_smiles(pubchem):
    cid = pubchem.get_cid_from_smiles("not_a_smiles")
    assert cid is None
```
