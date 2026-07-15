# src/dashboard/app.py
"""
Interactive Streamlit dashboard for bearing health monitoring
"""
import os
import streamlit as st
import pandas as pd
import pickle
from sqlalchemy import create_engine
import plotly.graph_objects as go
import plotly.express as px

# Page config
st.set_page_config(
    page_title="Bearing Health Monitor",
    page_icon="⚙️",
    layout="wide"
)


# Load model
@st.cache_resource
def load_model():
    with open('models/lightgbm_v2_tuned.pkl', 'rb') as f:
        return pickle.load(f)


@st.cache_resource
def get_db_connection():
    # Env-first (was hardcoded with no override). Default preserved for local dev.
    return create_engine(os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/anudeep'))


model = load_model()
engine = get_db_connection()
features = pd.read_csv('data/processed/selected_features.csv')['feature'].tolist()

# Dashboard header
st.title("⚙️ Bearing Failure Prediction Dashboard")
st.markdown("**Prototype RUL monitoring dashboard | validation claims under correction**")
st.warning(
    "This dashboard uses the existing leaky-regime model artifact. "
    "Current source-of-truth validation is leakage-safe Phase 1, not the old 2.88h headline metric."
)

# Sidebar
st.sidebar.header("Configuration")
st.sidebar.info("💡 Only bearings 3 & 4 are shown (these are the only bearings that failed in the dataset)")
bearing_id = st.sidebar.selectbox("Select Bearing", [3, 4], index=0)
axis = st.sidebar.selectbox("Select Axis", ["x", "y"], index=0)


# Load data
@st.cache_data(ttl=60)
def load_bearing_data(bearing_id, axis):
    query = f"""
    SELECT timestamp, rms_mean, kurtosis_mean, rul_hours
    FROM features 
    WHERE bearing_id = {bearing_id} AND axis = '{axis}' AND failed = TRUE
    ORDER BY timestamp DESC 
    LIMIT 200
    """
    return pd.read_sql(query, engine)


df = load_bearing_data(bearing_id, axis)

if len(df) > 0:
    # Get latest row
    latest_idx = df['timestamp'].idxmax()
    latest = df.loc[latest_idx]
    current_rul = latest['rul_hours']

    # Predict using full feature set
    query_features = f"""
    SELECT * FROM features 
    WHERE bearing_id = {bearing_id} AND axis = '{axis}' AND timestamp = '{latest['timestamp']}'
    LIMIT 1
    """
    df_features = pd.read_sql(query_features, engine)

    if len(df_features) > 0:
        X = df_features[features].values
        pred_rul = float(model.predict(X)[0])
    else:
        pred_rul = None

    # Display metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Current RMS", f"{latest['rms_mean']:.4f}")
    with col2:
        st.metric("Current Kurtosis", f"{latest['kurtosis_mean']:.2f}")
    with col3:
        st.metric("Actual RUL", f"{current_rul:.1f} hours")
    with col4:
        if pred_rul:
            error = abs(pred_rul - current_rul)
            st.metric("Predicted RUL", f"{pred_rul:.1f} hours",
                      delta=f"{error:.1f}h error")
        else:
            st.metric("Predicted RUL", "N/A")

    # Risk indicator
    if pred_rul and pred_rul < 50:
        st.error("🚨 CRITICAL: Schedule emergency maintenance immediately!")
    elif pred_rul and pred_rul < 150:
        st.warning("⚠️ WARNING: Schedule maintenance within 3-5 days")
    else:
        st.success("✅ NORMAL: Bearing health is acceptable")

    # Plot degradation over time
    st.subheader("Degradation Trends (Last 200 Measurements)")

    # Sort by timestamp for proper plotting
    df_sorted = df.sort_values('timestamp')

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sorted['timestamp'],
        y=df_sorted['rms_mean'],
        mode='lines+markers',
        name='RMS',
        line=dict(color='blue', width=2),
        marker=dict(size=4)
    ))
    fig.add_trace(go.Scatter(
        x=df_sorted['timestamp'],
        y=df_sorted['kurtosis_mean'],
        mode='lines+markers',
        name='Kurtosis',
        yaxis='y2',
        line=dict(color='red', width=2),
        marker=dict(size=4)
    ))

    # FIXED: Use new Plotly API
    fig.update_layout(
        yaxis=dict(
            title=dict(text="RMS", font=dict(color='blue'))
        ),
        yaxis2=dict(
            title=dict(text="Kurtosis", font=dict(color='red')),
            overlaying='y',
            side='right'
        ),
        hovermode='x unified',
        height=400
    )
    st.plotly_chart(fig, use_container_width=True)

    # RUL prediction over time
    st.subheader("RUL Degradation Over Time")

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=df_sorted['timestamp'],
        y=df_sorted['rul_hours'],
        mode='lines+markers',
        name='Actual RUL',
        line=dict(color='green', width=2),
        marker=dict(size=4),
        fill='tozeroy',
        fillcolor='rgba(0,255,0,0.1)'
    ))
    fig2.update_layout(
        yaxis=dict(title=dict(text="RUL (hours)")),
        xaxis=dict(title=dict(text="Time")),
        height=400
    )
    st.plotly_chart(fig2, use_container_width=True)

    # Feature importance (embedded in code, no CSV needed)
    st.subheader("Top 10 Most Important Features (Current Values)")
    top_features_list = [
        'bp_1k_5k_mean_ema_10',
        'kurtosis_mean_ema_10',
        'spec_centroid_mean_ema_30',
        'spec_centroid_mean_bearing_range',
        'std_mean_bearing_max',
        'bp_1k_5k_mean_bearing_min',
        'spec_centroid_std_ema_10',
        'peak_to_peak_mean_ema_10',
        'spec_centroid_mean_zscore',
        'peak_to_peak_std_roll_10_std'
    ]

    if len(df_features) > 0:
        # Get current values of top features
        feature_values = df_features[top_features_list].iloc[0]

        fig3 = px.bar(
            x=feature_values.values,
            y=feature_values.index,
            orientation='h',
            labels={'x': 'Feature Value', 'y': 'Feature Name'},
            title=f'Feature Values at Current Time (Bearing {bearing_id}-{axis})'
        )
        fig3.update_traces(marker_color='lightblue')
        st.plotly_chart(fig3, use_container_width=True)

    # Stats table
    st.subheader("Summary Statistics")

    col1, col2 = st.columns(2)

    with col1:
        stats_df1 = pd.DataFrame({
            'Metric': ['Mean RMS', 'Max RMS', 'Min RMS', 'Current RMS'],
            'Value': [
                f"{df['rms_mean'].mean():.4f}",
                f"{df['rms_mean'].max():.4f}",
                f"{df['rms_mean'].min():.4f}",
                f"{latest['rms_mean']:.4f}"
            ]
        })
        st.dataframe(stats_df1, hide_index=True, use_container_width=True)

    with col2:
        stats_df2 = pd.DataFrame({
            'Metric': ['Mean Kurtosis', 'Max Kurtosis', 'Min Kurtosis', 'Current Kurtosis'],
            'Value': [
                f"{df['kurtosis_mean'].mean():.2f}",
                f"{df['kurtosis_mean'].max():.2f}",
                f"{df['kurtosis_mean'].min():.2f}",
                f"{latest['kurtosis_mean']:.2f}"
            ]
        })
        st.dataframe(stats_df2, hide_index=True, use_container_width=True)

    # Data quality info
    st.subheader("Dataset Information")
    info_col1, info_col2, info_col3 = st.columns(3)

    with info_col1:
        st.metric("Total Measurements", f"{len(df):,}")
    with info_col2:
        st.metric("Initial RUL", f"{df['rul_hours'].max():.1f} hours")
    with info_col3:
        st.metric("Time to Failure", f"{df['rul_hours'].max() / 24:.1f} days")

else:
    st.error("❌ No data found for selected bearing")

# Footer
st.markdown("---")
st.markdown("""
**Model Details:**
- **Algorithm:** LightGBM v2 artifact from the earlier tuning regime
- **Validation status:** Prototype only; old row-level metrics are deprecated due to leakage
- **Leakage-safe LOBO MAE:** 226.46 hours
- **Leakage-safe purged time-series MAE:** 122.00 hours
- **Source-of-truth report:** `reports/evaluation/phase1_validation_leakage_safe/validation_report.md`
- **Dataset:** NASA IMS Bearing Dataset
- **Features:** 50 selected from 380 engineered features
- **Author:** Anudeep | Mechanical Engineer → Data Scientist
""")
