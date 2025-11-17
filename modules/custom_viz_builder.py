"""
Custom Visualization Builder Module
Allows users to create fully customizable plots with interactive controls.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


def get_numeric_columns(df: pd.DataFrame) -> List[str]:
    """Get list of numeric columns suitable for plotting."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    # Exclude index-like columns
    exclude = ['Unnamed: 0', 'index']
    return [col for col in numeric_cols if col not in exclude]


def get_categorical_columns(df: pd.DataFrame) -> List[str]:
    """Get list of categorical columns suitable for color/grouping."""
    categorical_cols = df.select_dtypes(include=['object', 'category', 'bool']).columns.tolist()
    # Add some numeric columns that should be treated as categorical (only if they exist)
    potential_categorical = ['Outlier_Count']
    categorical_cols.extend([col for col in potential_categorical if col in df.columns])
    return categorical_cols


def add_clustering(df: pd.DataFrame, x_col: str, y_col: str, n_clusters: int = 3) -> pd.DataFrame:
    """
    Add clustering labels to the dataframe.

    Args:
        df: Input dataframe
        x_col: Column to use for x-axis
        y_col: Column to use for y-axis
        n_clusters: Number of clusters

    Returns:
        DataFrame with added 'Cluster' column
    """
    try:
        # Get valid data (no NaN)
        valid_data = df[[x_col, y_col]].dropna()

        if len(valid_data) < n_clusters:
            logger.warning(f"Not enough data points ({len(valid_data)}) for {n_clusters} clusters")
            df['Cluster'] = 'No Clustering'
            return df

        # Perform K-means clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(valid_data)

        # Add cluster labels to dataframe
        df_copy = df.copy()
        df_copy['Cluster'] = 'No Data'
        df_copy.loc[valid_data.index, 'Cluster'] = [f'Cluster {i+1}' for i in cluster_labels]

        return df_copy

    except Exception as e:
        logger.error(f"Error in clustering: {str(e)}")
        df['Cluster'] = 'Error'
        return df


def custom_visualization_builder(df: pd.DataFrame, compound_name: str):
    """
    Interactive visualization builder with full user control.

    Args:
        df: DataFrame containing compound data
        compound_name: Name of the compound for saving plots
    """
    st.markdown("### 🎨 Custom Visualization Builder")
    st.markdown("*Create your own plots with full control over axes, colors, and clustering*")

    # Get available columns
    numeric_cols = get_numeric_columns(df)
    categorical_cols = get_categorical_columns(df)

    if len(numeric_cols) < 2:
        st.warning("Not enough numeric columns for visualization. Need at least 2 numeric columns.")
        return

    # Sidebar controls
    with st.expander("📊 Plot Configuration", expanded=True):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Plot Type")
            plot_type = st.selectbox(
                "Select visualization type:",
                ["Scatter Plot", "Box Plot", "Violin Plot", "Histogram", "3D Scatter"],
                key="custom_plot_type"
            )

        with col2:
            st.markdown("#### Data Filters")
            # Option to filter data
            apply_filter = st.checkbox("Apply data filters", value=False)

            if apply_filter:
                filter_col = st.selectbox("Filter by:", categorical_cols, key="filter_column")
                unique_vals = df[filter_col].unique()
                selected_vals = st.multiselect(
                    f"Select {filter_col} values:",
                    options=unique_vals,
                    default=list(unique_vals)[:5] if len(unique_vals) > 5 else list(unique_vals),
                    key="filter_values"
                )
                df = df[df[filter_col].isin(selected_vals)]

    # Plot-specific controls
    if plot_type == "Scatter Plot":
        create_custom_scatter(df, numeric_cols, categorical_cols, compound_name)

    elif plot_type == "3D Scatter":
        create_custom_3d_scatter(df, numeric_cols, categorical_cols, compound_name)

    elif plot_type == "Box Plot":
        create_custom_boxplot(df, numeric_cols, categorical_cols, compound_name)

    elif plot_type == "Violin Plot":
        create_custom_violin(df, numeric_cols, categorical_cols, compound_name)

    elif plot_type == "Histogram":
        create_custom_histogram(df, numeric_cols, categorical_cols, compound_name)


def create_custom_scatter(df: pd.DataFrame, numeric_cols: List[str],
                         categorical_cols: List[str], compound_name: str):
    """Create customizable scatter plot."""
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### X-Axis")
        x_col = st.selectbox("X-axis variable:", numeric_cols, index=0, key="scatter_x")

    with col2:
        st.markdown("#### Y-Axis")
        default_y = 1 if len(numeric_cols) > 1 else 0
        y_col = st.selectbox("Y-axis variable:", numeric_cols, index=default_y, key="scatter_y")

    with col3:
        st.markdown("#### Styling")
        color_by = st.selectbox("Color by:", ["None"] + categorical_cols, key="scatter_color")
        size_by = st.selectbox("Size by:", ["None"] + numeric_cols, key="scatter_size")

    # Advanced options
    with st.expander("🔧 Advanced Options"):
        col_adv1, col_adv2 = st.columns(2)

        with col_adv1:
            add_trendline = st.checkbox("Add trendline", value=False)
            trendline_type = None
            if add_trendline:
                trendline_type = st.selectbox(
                    "Trendline type:",
                    ["ols", "lowess"],
                    help="OLS = Linear regression, LOWESS = Locally weighted regression"
                )

        with col_adv2:
            enable_clustering = st.checkbox("Enable clustering", value=False)
            n_clusters = 3
            if enable_clustering:
                n_clusters = st.slider("Number of clusters:", 2, 10, 3)

    # Apply clustering if enabled
    if enable_clustering:
        df = add_clustering(df, x_col, y_col, n_clusters)
        if color_by == "None":
            color_by = "Cluster"

    # Create plot
    plot_df = df.dropna(subset=[x_col, y_col])

    if plot_df.empty:
        st.warning(f"No valid data for {x_col} vs {y_col}")
        return

    fig = px.scatter(
        plot_df,
        x=x_col,
        y=y_col,
        color=None if color_by == "None" else color_by,
        size=None if size_by == "None" else size_by,
        hover_data=['ChEMBL_ID', 'Molecule_Name'] if all(c in plot_df.columns for c in ['ChEMBL_ID', 'Molecule_Name']) else None,
        title=f'{y_col} vs {x_col}',
        trendline=trendline_type if add_trendline else None,
        height=600,
        width=900
    )

    fig.update_layout(template='plotly_white')
    st.plotly_chart(fig, use_container_width=True)

    # Download option
    if st.button("💾 Save this plot", key="save_scatter"):
        fig_json = fig.to_json()
        st.download_button(
            "Download as JSON",
            fig_json,
            file_name=f"{compound_name}_custom_scatter_{x_col}_vs_{y_col}.json",
            mime="application/json"
        )


def create_custom_3d_scatter(df: pd.DataFrame, numeric_cols: List[str],
                            categorical_cols: List[str], compound_name: str):
    """Create customizable 3D scatter plot."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        x_col = st.selectbox("X-axis:", numeric_cols, index=0, key="3d_x")
    with col2:
        y_col = st.selectbox("Y-axis:", numeric_cols, index=min(1, len(numeric_cols)-1), key="3d_y")
    with col3:
        z_col = st.selectbox("Z-axis:", numeric_cols, index=min(2, len(numeric_cols)-1), key="3d_z")
    with col4:
        color_by = st.selectbox("Color by:", ["None"] + categorical_cols, key="3d_color")

    plot_df = df.dropna(subset=[x_col, y_col, z_col])

    if plot_df.empty:
        st.warning("No valid data for 3D plot")
        return

    fig = px.scatter_3d(
        plot_df,
        x=x_col,
        y=y_col,
        z=z_col,
        color=None if color_by == "None" else color_by,
        hover_data=['ChEMBL_ID', 'Molecule_Name'] if all(c in plot_df.columns for c in ['ChEMBL_ID', 'Molecule_Name']) else None,
        title=f'3D Plot: {x_col} vs {y_col} vs {z_col}',
        height=700
    )

    fig.update_layout(template='plotly_white')
    st.plotly_chart(fig, use_container_width=True)


def create_custom_boxplot(df: pd.DataFrame, numeric_cols: List[str],
                         categorical_cols: List[str], compound_name: str):
    """Create customizable box plot."""
    col1, col2 = st.columns(2)

    with col1:
        y_col = st.selectbox("Value (Y-axis):", numeric_cols, key="box_y")
    with col2:
        x_col = st.selectbox("Group by (X-axis):", ["None"] + categorical_cols, key="box_x")

    show_points = st.checkbox("Show individual points", value=True)
    points_type = "all" if show_points else False

    plot_df = df.dropna(subset=[y_col])

    if plot_df.empty:
        st.warning(f"No valid data for {y_col}")
        return

    if x_col == "None":
        fig = px.box(plot_df, y=y_col, points=points_type, title=f'Distribution of {y_col}')
    else:
        fig = px.box(plot_df, x=x_col, y=y_col, points=points_type, title=f'{y_col} by {x_col}')

    fig.update_layout(template='plotly_white', height=600)
    st.plotly_chart(fig, use_container_width=True)


def create_custom_violin(df: pd.DataFrame, numeric_cols: List[str],
                        categorical_cols: List[str], compound_name: str):
    """Create customizable violin plot."""
    col1, col2 = st.columns(2)

    with col1:
        y_col = st.selectbox("Value (Y-axis):", numeric_cols, key="violin_y")
    with col2:
        x_col = st.selectbox("Group by (X-axis):", categorical_cols, key="violin_x")

    plot_df = df.dropna(subset=[y_col])

    if plot_df.empty:
        st.warning(f"No valid data for {y_col}")
        return

    fig = px.violin(plot_df, x=x_col, y=y_col, box=True, points="all",
                   title=f'{y_col} distribution by {x_col}')

    fig.update_layout(template='plotly_white', height=600)
    st.plotly_chart(fig, use_container_width=True)


def create_custom_histogram(df: pd.DataFrame, numeric_cols: List[str],
                           categorical_cols: List[str], compound_name: str):
    """Create customizable histogram."""
    col1, col2 = st.columns(2)

    with col1:
        x_col = st.selectbox("Variable:", numeric_cols, key="hist_x")
    with col2:
        color_by = st.selectbox("Color by:", ["None"] + categorical_cols, key="hist_color")

    n_bins = st.slider("Number of bins:", 10, 100, 30)

    plot_df = df.dropna(subset=[x_col])

    if plot_df.empty:
        st.warning(f"No valid data for {x_col}")
        return

    fig = px.histogram(
        plot_df,
        x=x_col,
        color=None if color_by == "None" else color_by,
        nbins=n_bins,
        title=f'Distribution of {x_col}',
        marginal="box"  # Add box plot on top
    )

    fig.update_layout(template='plotly_white', height=600)
    st.plotly_chart(fig, use_container_width=True)
