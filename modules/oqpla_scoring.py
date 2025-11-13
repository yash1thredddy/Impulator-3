"""
O[Q/P/L]A Scoring Module - Overall Quality/Promise/Likelihood Assessment

This module implements the O[Q/P/L]A multi-criteria scoring system for IMPs 2.0.

**Phase 1 Components**:
1. Efficiency Outlier Score (40%)
2. Development Angle Score (10%)
3. Distance to Best-in-Class Score (15%)

**Phase 2 Components (WITH PDB INTEGRATION)**:
4. PDB Structural Evidence Score (15%) ✅ IMPLEMENTED
5. Target Prediction Confidence Score (10%) - DEFERRED
6. Analog Support Score (10%) - FUTURE

When PDB is enabled, weights are renormalized to:
- Component 1: 40% → 50.0% (0.40/0.80)
- Component 2: 10% → 12.5% (0.10/0.80)
- Component 3: 15% → 18.75% (0.15/0.80)
- Component 4: 15% → 18.75% (0.15/0.80)

Final score includes QED multiplier for drug-likeness.
"""

import numpy as np
import pandas as pd
from typing import Dict, List
import logging
import streamlit as st

logger = logging.getLogger(__name__)


def calculate_efficiency_outlier_score(
    df: pd.DataFrame,
    metrics: List[str] = None
) -> pd.Series:
    """
    Component 1: Efficiency Outlier Score (40% weight).

    Quantifies how exceptional the compound's efficiency metrics are compared
    to the cohort using Z-score normalization.

    Method:
    1. Calculate Z-scores for each efficiency metric
    2. Normalize Z-scores to [0, 1] (Z-scores > 3 capped at 1.0)
    3. Average across all four metrics

    Args:
        df: DataFrame with efficiency metrics (SEI, BEI, NSEI, NBEI)
        metrics: List of metrics to use (default: ['SEI', 'BEI', 'NSEI', 'NBEI'])

    Returns:
        pd.Series: Efficiency scores (0-1) for each compound

    Interpretation:
        - 0.0-0.3: Below average (not an IMP)
        - 0.3-0.5: Average (borderline)
        - 0.5-0.7: Above average (potential IMP)
        - 0.7-0.9: Exceptional (strong IMP candidate)
        - 0.9-1.0: Extreme outlier (validate - possible artifact)
    """
    if metrics is None:
        metrics = ['SEI', 'BEI', 'NSEI', 'NBEI']

    # Validate metrics exist
    missing_metrics = [m for m in metrics if m not in df.columns]
    if missing_metrics:
        raise ValueError(f"Missing efficiency metrics: {missing_metrics}")

    # Calculate Z-scores and normalize
    normalized_scores = []

    for metric in metrics:
        # Calculate Z-score
        z_score = (df[metric] - df[metric].mean()) / df[metric].std()

        # Normalize to [0, 1]: Z/3 and clip
        normalized = (z_score / 3.0).clip(0, 1)

        normalized_scores.append(normalized)

    # Average across all metrics
    efficiency_score = pd.concat(normalized_scores, axis=1).mean(axis=1)

    return efficiency_score


def calculate_angle_score(angles: pd.Series, optimal_angle: float = 45.0) -> pd.Series:
    """
    Component 2: Development Angle Score (10% weight).

    Assesses if the compound has a balanced development trajectory in efficiency space.

    An angle of 45° represents optimal balance between surface efficiency (SEI/NSEI)
    and binding efficiency (BEI/NBEI).

    Method:
    Score = 1 - |angle - 45°| / 45°

    Args:
        angles: Series of angles (in degrees) from efficiency plane
        optimal_angle: Target angle (default: 45°)

    Returns:
        pd.Series: Angle scores (0-1) for each compound

    Interpretation:
        - 0.89-1.0 (40-50°): Excellent - balanced size and polarity
        - 0.67-0.89 (30-40° or 50-60°): Good - moderate balance
        - 0.44-0.67 (20-30° or 60-70°): Fair - unbalanced
        - 0.0-0.44 (<20° or >70°): Poor - highly unbalanced
            - <20°: Too hydrophobic
            - >70°: Too polar
    """
    # Calculate deviation from optimal angle
    angle_deviation = (angles - optimal_angle).abs()

    # Score based on deviation
    score = 1 - (angle_deviation / optimal_angle)

    # Clip to [0, 1]
    return score.clip(0, 1)


def calculate_distance_to_best_score(
    df: pd.DataFrame,
    modulus_column: str = 'Modulus_SEI_BEI'
) -> pd.Series:
    """
    Component 3: Distance to Best-in-Class Score (15% weight).

    Measures how close each compound is to the best-performing compound (highest modulus)
    in the cohort.

    Method:
    Score = compound_modulus / best_modulus

    Args:
        df: DataFrame with modulus values
        modulus_column: Name of modulus column (default: 'Modulus_SEI_BEI')

    Returns:
        pd.Series: Distance scores (0-1) for each compound

    Interpretation:
        - 0.9-1.0: Compound IS the best or very close (top tier)
        - 0.7-0.9: Competitive with best (second tier)
        - 0.5-0.7: Moderate distance from best (third tier)
        - <0.5: Far from best (lower tier)
    """
    if modulus_column not in df.columns:
        raise ValueError(f"Modulus column '{modulus_column}' not found in DataFrame")

    # Find best (maximum) modulus
    best_modulus = df[modulus_column].max()

    if np.isnan(best_modulus) or best_modulus == 0:
        logger.warning("Best modulus is NaN or zero. Returning all zeros.")
        return pd.Series([0.0] * len(df), index=df.index)

    # Calculate ratio
    distance_score = df[modulus_column] / best_modulus

    return distance_score


def calculate_oqpla_phase1(
    df: pd.DataFrame,
    use_normalized_weights: bool = True
) -> pd.DataFrame:
    """
    Calculate O[Q/P/L]A score using Phase 1 components (1-3) only.

    Phase 1 components account for 65% of total weight. When use_normalized_weights=True,
    these are normalized to 100% for Phase 1 implementation.

    Normalized weights:
    - Component 1: 40% → 61.5% (0.40/0.65)
    - Component 2: 10% → 15.4% (0.10/0.65)
    - Component 3: 15% → 23.1% (0.15/0.65)

    Args:
        df: DataFrame with efficiency metrics and plane geometry
        use_normalized_weights: If True, normalize Phase 1 weights to 100%

    Returns:
        pd.DataFrame: Input DataFrame with added O[Q/P/L]A columns:
            - Efficiency_Score: Component 1 (0-1)
            - Angle_Score: Component 2 (0-1)
            - Distance_Score: Component 3 (0-1)
            - OQPLA_Base_Score: Weighted sum before QED multiplier
            - OQPLA_Final_Score: Final score with QED multiplier

    Example:
        >>> df_with_oqpla = calculate_oqpla_phase1(df)
        >>> high_priority = df_with_oqpla[df_with_oqpla['OQPLA_Final_Score'] > 0.7]
    """
    df = df.copy()

    # Validate required columns
    required_columns = ['SEI', 'BEI', 'NSEI', 'NBEI', 'Angle_SEI_BEI', 'Modulus_SEI_BEI', 'QED']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    # Calculate Component 1: Efficiency Outlier Score
    df['Efficiency_Score'] = calculate_efficiency_outlier_score(df)

    # Calculate Component 2: Development Angle Score
    df['Angle_Score'] = calculate_angle_score(df['Angle_SEI_BEI'])

    # Calculate Component 3: Distance to Best Score
    df['Distance_Score'] = calculate_distance_to_best_score(df)

    # Calculate weighted sum
    if use_normalized_weights:
        # Normalize to 100% (Phase 1 only)
        total_phase1_weight = 0.40 + 0.10 + 0.15  # = 0.65
        w1 = 0.40 / total_phase1_weight  # = 0.615
        w2 = 0.10 / total_phase1_weight  # = 0.154
        w3 = 0.15 / total_phase1_weight  # = 0.231
    else:
        # Use original weights (will result in max score < 1.0)
        w1, w2, w3 = 0.40, 0.10, 0.15

    df['OQPLA_Base_Score'] = (
        w1 * df['Efficiency_Score'] +
        w2 * df['Angle_Score'] +
        w3 * df['Distance_Score']
    )

    # Apply QED multiplier
    # Formula: 0.5 + 0.5 × QED
    # This ensures compounds with QED=0 still get 50% credit
    df['QED_Multiplier'] = 0.5 + 0.5 * df['QED']
    df['OQPLA_Final_Score'] = df['OQPLA_Base_Score'] * df['QED_Multiplier']

    return df


def calculate_oqpla_phase2(
    df: pd.DataFrame,
    use_pdb: bool = True,
    show_progress: bool = True
) -> pd.DataFrame:
    """
    Calculate O[Q/P/L]A score using Phase 2 components (1-4).

    Phase 2 includes PDB Structural Evidence (Component 4).
    Weights with PDB enabled (total = 80%):
    - Component 1: 40% → 50.0% (0.40/0.80)
    - Component 2: 10% → 12.5% (0.10/0.80)
    - Component 3: 15% → 18.75% (0.15/0.80)
    - Component 4: 15% → 18.75% (0.15/0.80)

    Args:
        df: DataFrame with efficiency metrics, plane geometry, and SMILES
        use_pdb: If True, query PDB for structural evidence
        show_progress: If True, show Streamlit progress indicators

    Returns:
        pd.DataFrame: Input DataFrame with added O[Q/P/L]A columns:
            - Efficiency_Score: Component 1 (0-1)
            - Angle_Score: Component 2 (0-1)
            - Distance_Score: Component 3 (0-1)
            - PDB_Score: Component 4 (0-1)
            - PDB_Num_Structures, PDB_High/Medium/Poor_Quality, etc.
            - OQPLA_Base_Score: Weighted sum before QED multiplier
            - OQPLA_Final_Score: Final score with QED multiplier

    Example:
        >>> df_with_oqpla = calculate_oqpla_phase2(df, use_pdb=True)
        >>> high_priority = df_with_oqpla[df_with_oqpla['OQPLA_Final_Score'] > 0.7]
    """
    df = df.copy()

    # Validate required columns
    required_columns = ['SEI', 'BEI', 'NSEI', 'NBEI', 'Angle_SEI_BEI', 'Modulus_SEI_BEI', 'QED', 'SMILES']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    # Calculate Component 1: Efficiency Outlier Score
    df['Efficiency_Score'] = calculate_efficiency_outlier_score(df)

    # Calculate Component 2: Development Angle Score
    df['Angle_Score'] = calculate_angle_score(df['Angle_SEI_BEI'])

    # Calculate Component 3: Distance to Best Score
    df['Distance_Score'] = calculate_distance_to_best_score(df)

    # Calculate Component 4: PDB Structural Evidence
    df = calculate_pdb_evidence_score(df, use_pdb=use_pdb, show_progress=show_progress)

    # Calculate weighted sum (Phase 2 with PDB)
    total_phase2_weight = 0.40 + 0.10 + 0.15 + 0.15  # = 0.80
    w1 = 0.40 / total_phase2_weight  # = 0.500
    w2 = 0.10 / total_phase2_weight  # = 0.125
    w3 = 0.15 / total_phase2_weight  # = 0.1875
    w4 = 0.15 / total_phase2_weight  # = 0.1875

    df['OQPLA_Base_Score'] = (
        w1 * df['Efficiency_Score'] +
        w2 * df['Angle_Score'] +
        w3 * df['Distance_Score'] +
        w4 * df['PDB_Score']
    )

    # Apply QED multiplier
    df['QED_Multiplier'] = 0.5 + 0.5 * df['QED']
    df['OQPLA_Final_Score'] = df['OQPLA_Base_Score'] * df['QED_Multiplier']

    # Calculate component contributions (for transparency)
    df['Efficiency_Contribution'] = w1 * df['Efficiency_Score'] * df['QED_Multiplier']
    df['Angle_Contribution'] = w2 * df['Angle_Score'] * df['QED_Multiplier']
    df['Distance_Contribution'] = w3 * df['Distance_Score'] * df['QED_Multiplier']
    df['PDB_Contribution'] = w4 * df['PDB_Score'] * df['QED_Multiplier']

    # Calculate QED impact
    df['QED_Impact'] = df['OQPLA_Final_Score'] - df['OQPLA_Base_Score']

    return df


def interpret_oqpla_score(score: float) -> Dict[str, str]:
    """
    Interpret O[Q/P/L]A score and provide classification + recommendation.

    Args:
        score: O[Q/P/L]A final score (0-1)

    Returns:
        Dict[str, str]: Classification, interpretation, and action recommendation

    Example:
        >>> result = interpret_oqpla_score(0.75)
        >>> print(result['classification'])  # "Strong IMP"
        >>> print(result['action'])  # "Priority 2: Validate within 1 month"
    """
    if np.isnan(score):
        return {
            'classification': 'Invalid',
            'interpretation': 'No score calculated',
            'action': 'Check data quality',
            'priority': None
        }

    if 0.9 <= score <= 1.0:
        return {
            'classification': 'Exceptional IMP',
            'interpretation': 'Highest confidence - multiple validation streams confirm',
            'action': 'Priority 1: Immediate experimental validation',
            'priority': 1
        }
    elif 0.7 <= score < 0.9:
        return {
            'classification': 'Strong IMP',
            'interpretation': 'High confidence - most validation criteria met',
            'action': 'Priority 2: Validate within 1 month',
            'priority': 2
        }
    elif 0.5 <= score < 0.7:
        return {
            'classification': 'Moderate IMP',
            'interpretation': 'Potential lead - some validation, needs more evidence',
            'action': 'Priority 3: Monitor and gather more data',
            'priority': 3
        }
    elif 0.3 <= score < 0.5:
        return {
            'classification': 'Weak IMP',
            'interpretation': 'Low confidence - outlier but lacking validation',
            'action': 'Priority 4: Deprioritize unless novel scaffold',
            'priority': 4
        }
    else:  # 0.0 <= score < 0.3
        return {
            'classification': 'Not IMP',
            'interpretation': 'Likely artifact or not druggable',
            'action': 'Exclude: Do not pursue',
            'priority': None
        }


def add_oqpla_interpretation(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add human-readable O[Q/P/L]A interpretation columns to DataFrame.

    Args:
        df: DataFrame with OQPLA_Final_Score column

    Returns:
        pd.DataFrame: Input DataFrame with added columns:
            - OQPLA_Classification: e.g., "Strong IMP"
            - OQPLA_Interpretation: Detailed interpretation
            - OQPLA_Action: Recommended action
            - OQPLA_Priority: Priority level (1-4 or None)

    Example:
        >>> df = add_oqpla_interpretation(df)
        >>> priority_1 = df[df['OQPLA_Priority'] == 1]
    """
    df = df.copy()

    if 'OQPLA_Final_Score' not in df.columns:
        raise ValueError("OQPLA_Final_Score column not found. Run calculate_oqpla_phase1() first.")

    # Apply interpretation to each row
    interpretations = df['OQPLA_Final_Score'].apply(interpret_oqpla_score)

    df['OQPLA_Classification'] = interpretations.apply(lambda x: x['classification'])
    df['OQPLA_Interpretation'] = interpretations.apply(lambda x: x['interpretation'])
    df['OQPLA_Action'] = interpretations.apply(lambda x: x['action'])
    df['OQPLA_Priority'] = interpretations.apply(lambda x: x['priority'])

    return df


def get_oqpla_summary(df: pd.DataFrame) -> Dict:
    """
    Generate summary statistics about O[Q/P/L]A scores in the dataset.

    Args:
        df: DataFrame with O[Q/P/L]A scores and classifications

    Returns:
        Dict: Summary information

    Example:
        >>> summary = get_oqpla_summary(df)
        >>> print(f"Exceptional IMPs: {summary['exceptional_imps']}")
        >>> print(f"Mean O[Q/P/L]A score: {summary['mean_score']:.3f}")
    """
    if 'OQPLA_Final_Score' not in df.columns:
        return {'error': 'No O[Q/P/L]A scores found'}

    scores = df['OQPLA_Final_Score'].dropna()

    summary = {
        'total_compounds': len(df),
        'scored_compounds': len(scores),
        'mean_score': float(scores.mean()) if len(scores) > 0 else np.nan,
        'median_score': float(scores.median()) if len(scores) > 0 else np.nan,
        'std_score': float(scores.std()) if len(scores) > 0 else np.nan,
        'min_score': float(scores.min()) if len(scores) > 0 else np.nan,
        'max_score': float(scores.max()) if len(scores) > 0 else np.nan
    }

    # Count by classification
    if 'OQPLA_Classification' in df.columns:
        classification_counts = df['OQPLA_Classification'].value_counts().to_dict()
        summary['classification_counts'] = classification_counts

        summary['exceptional_imps'] = classification_counts.get('Exceptional IMP', 0)
        summary['strong_imps'] = classification_counts.get('Strong IMP', 0)
        summary['moderate_imps'] = classification_counts.get('Moderate IMP', 0)
        summary['weak_imps'] = classification_counts.get('Weak IMP', 0)
        summary['not_imps'] = classification_counts.get('Not IMP', 0)

    # Count by priority
    if 'OQPLA_Priority' in df.columns:
        priority_counts = df['OQPLA_Priority'].value_counts().sort_index().to_dict()
        summary['priority_counts'] = priority_counts

    return summary


def calculate_component_contributions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate how much each O[Q/P/L]A component contributes to the final score.

    Useful for sensitivity analysis and understanding which factors drive the score.

    Args:
        df: DataFrame with O[Q/P/L]A component scores

    Returns:
        pd.DataFrame: DataFrame with contribution columns

    Example:
        >>> df = calculate_component_contributions(df)
        >>> print(df[['Efficiency_Contribution', 'Angle_Contribution', 'Distance_Contribution']])
    """
    df = df.copy()

    required_columns = ['Efficiency_Score', 'Angle_Score', 'Distance_Score', 'QED_Multiplier']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    # Calculate weights (normalized for Phase 1)
    total_phase1_weight = 0.65
    w1 = 0.40 / total_phase1_weight  # 0.615
    w2 = 0.10 / total_phase1_weight  # 0.154
    w3 = 0.15 / total_phase1_weight  # 0.231

    # Calculate contributions
    df['Efficiency_Contribution'] = w1 * df['Efficiency_Score'] * df['QED_Multiplier']
    df['Angle_Contribution'] = w2 * df['Angle_Score'] * df['QED_Multiplier']
    df['Distance_Contribution'] = w3 * df['Distance_Score'] * df['QED_Multiplier']

    # Calculate QED impact (penalty)
    df['QED_Impact'] = df['OQPLA_Final_Score'] - df['OQPLA_Base_Score']

    return df


# Component 4: PDB Evidence - IMPLEMENTED
def calculate_pdb_evidence_score(
    df: pd.DataFrame,
    use_pdb: bool = False,
    show_progress: bool = True
) -> pd.DataFrame:
    """
    Component 4: PDB Structural Evidence Score (15% weight).

    Query RCSB PDB for experimental structures of the compound or close analogs.
    Score based on number and quality of structures found.

    Resolution Quality Classes:
    - ⭐⭐⭐ (Best): Resolution < 2.0 Å (multiplier 1.0)
    - ⭐⭐ (Medium): Resolution 2.0-3.0 Å (multiplier 0.75)
    - ⭐ (Poor): Resolution > 3.0 Å (multiplier 0.5)

    Scoring:
        Base score = min(num_structures / 5.0, 1.0)
        Quality-adjusted score = weighted by resolution quality
        Final score = average of base and quality-weighted

    Args:
        df: DataFrame with SMILES column
        use_pdb: If True, query PDB API; if False, return zeros
        show_progress: If True, show Streamlit progress indicators

    Returns:
        DataFrame with added columns:
        - PDB_Score: Final PDB evidence score (0-1)
        - PDB_Num_Structures: Total structures found
        - PDB_High_Quality: Count of high-quality structures (< 2.0 Å)
        - PDB_Medium_Quality: Count of medium-quality structures (2.0-3.0 Å)
        - PDB_Poor_Quality: Count of poor-quality structures (> 3.0 Å)
        - PDB_IDs: Comma-separated list of PDB IDs
        - PDB_Best_Resolution: Best (lowest) resolution found

    Note:
        This queries the RCSB PDB API which may be slow for large datasets.
        Enable only when needed for high-priority compounds.
    """
    df = df.copy()

    if not use_pdb:
        logger.info("PDB Evidence Score disabled. Returning zeros.")
        df['PDB_Score'] = 0.0
        df['PDB_Num_Structures'] = 0
        df['PDB_High_Quality'] = 0
        df['PDB_Medium_Quality'] = 0
        df['PDB_Poor_Quality'] = 0
        df['PDB_IDs'] = ""
        df['PDB_Best_Resolution'] = np.nan
        return df

    # Import PDB client
    try:
        from modules.pdb_client import get_pdb_evidence_score
    except ImportError:
        logger.error("PDB client module not found. Returning zeros.")
        df['PDB_Score'] = 0.0
        df['PDB_Num_Structures'] = 0
        df['PDB_High_Quality'] = 0
        df['PDB_Medium_Quality'] = 0
        df['PDB_Poor_Quality'] = 0
        df['PDB_IDs'] = ""
        df['PDB_Best_Resolution'] = np.nan
        return df

    logger.info(f"Querying RCSB PDB for {len(df)} unique compounds...")

    # Get unique SMILES to avoid duplicate queries
    unique_smiles = df['SMILES'].dropna().unique()

    if show_progress:
        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text(f"Querying PDB for {len(unique_smiles)} unique compound(s)...")

    # Query PDB for each unique SMILES
    pdb_results = {}
    for i, smiles in enumerate(unique_smiles):
        try:
            result = get_pdb_evidence_score(smiles, similarity_threshold=0.9)
            pdb_results[smiles] = result

            if show_progress:
                progress = (i + 1) / len(unique_smiles)
                progress_bar.progress(progress)
                status_text.text(f"Processed {i+1}/{len(unique_smiles)} compounds "
                               f"({result['num_structures']} structures found)")

        except Exception as e:
            logger.error(f"Error querying PDB for SMILES {smiles[:50]}: {str(e)}")
            pdb_results[smiles] = {
                'pdb_score': 0.0,
                'num_structures': 0,
                'num_high_quality': 0,
                'num_medium_quality': 0,
                'num_poor_quality': 0,
                'pdb_ids': [],
                'resolutions': []
            }

    if show_progress:
        progress_bar.empty()
        status_text.empty()

    # Map results back to dataframe
    df['PDB_Score'] = df['SMILES'].map(lambda s: pdb_results.get(s, {}).get('pdb_score', 0.0))
    df['PDB_Num_Structures'] = df['SMILES'].map(lambda s: pdb_results.get(s, {}).get('num_structures', 0))
    df['PDB_High_Quality'] = df['SMILES'].map(lambda s: pdb_results.get(s, {}).get('num_high_quality', 0))
    df['PDB_Medium_Quality'] = df['SMILES'].map(lambda s: pdb_results.get(s, {}).get('num_medium_quality', 0))
    df['PDB_Poor_Quality'] = df['SMILES'].map(lambda s: pdb_results.get(s, {}).get('num_poor_quality', 0))

    # Format PDB IDs as comma-separated string (show all IDs)
    df['PDB_IDs'] = df['SMILES'].map(
        lambda s: ",".join(pdb_results.get(s, {}).get('pdb_ids', []))  # All IDs
    )

    # Best resolution (lowest value)
    df['PDB_Best_Resolution'] = df['SMILES'].map(
        lambda s: min([r for r in pdb_results.get(s, {}).get('resolutions', []) if r is not None], default=np.nan)
    )

    total_structures = sum([result['num_structures'] for result in pdb_results.values()])
    logger.info(f"PDB query complete. Found {total_structures} total structures across {len(unique_smiles)} unique compounds.")

    # Store PDB results for later compound-level summary export
    df._pdb_results_cache = pdb_results  # Cache for export

    return df


def create_pdb_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create compound-level PDB summary from bioactivity dataframe.

    This function extracts unique compounds and their PDB evidence,
    avoiding duplication across bioactivity rows.

    Args:
        df: Bioactivity dataframe with PDB columns

    Returns:
        pd.DataFrame: Compound-level PDB summary with columns:
            - ChEMBL_ID
            - Molecule_Name
            - SMILES
            - PDB_Score
            - PDB_Num_Structures
            - PDB_High_Quality
            - PDB_Medium_Quality
            - PDB_Poor_Quality
            - PDB_IDs
            - PDB_Best_Resolution
    """
    # Get unique compounds (one row per compound)
    compound_cols = ['ChEMBL_ID', 'Molecule_Name', 'SMILES']
    pdb_cols = [
        'PDB_Score', 'PDB_Num_Structures',
        'PDB_High_Quality', 'PDB_Medium_Quality', 'PDB_Poor_Quality',
        'PDB_IDs', 'PDB_Best_Resolution'
    ]

    # Check if PDB columns exist
    if 'PDB_Score' not in df.columns:
        logger.warning("PDB columns not found in dataframe. Cannot create PDB summary.")
        return pd.DataFrame()

    # Get unique compounds with PDB data
    summary_df = df[compound_cols + pdb_cols].drop_duplicates(subset=['SMILES']).copy()

    # Sort by PDB_Score descending
    summary_df = summary_df.sort_values('PDB_Score', ascending=False).reset_index(drop=True)

    # Add quality percentage columns
    summary_df['PDB_High_Quality_Pct'] = (
        summary_df['PDB_High_Quality'] / summary_df['PDB_Num_Structures'] * 100
    ).fillna(0).round(1)

    summary_df['PDB_Medium_Quality_Pct'] = (
        summary_df['PDB_Medium_Quality'] / summary_df['PDB_Num_Structures'] * 100
    ).fillna(0).round(1)

    summary_df['PDB_Poor_Quality_Pct'] = (
        summary_df['PDB_Poor_Quality'] / summary_df['PDB_Num_Structures'] * 100
    ).fillna(0).round(1)

    logger.info(f"Created PDB summary for {len(summary_df)} unique compounds.")

    return summary_df


# Future: Component 6 (Analog Support) - Phase 4
def calculate_analog_support_score(df: pd.DataFrame) -> pd.Series:
    """
    Component 6: Analog Support Score (10% weight) [PHASE 4].

    PLACEHOLDER for future implementation.

    Will find similar compounds with activity to validate SAR.

    Returns:
        pd.Series: Placeholder (all zeros)
    """
    logger.info("Analog Support Score (Component 6) not yet implemented. Returning zeros.")
    return pd.Series([0.0] * len(df), index=df.index)
