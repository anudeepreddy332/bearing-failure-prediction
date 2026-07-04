import numpy as np
import pandas as pd
from typing import List
import warnings
warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

def add_rolling_features(df: pd.DataFrame, feature_cols: List[str], 
                        windows: List[int] = [3, 5, 10]) -> pd.DataFrame:
    """
    Add rolling mean and std features per bearing-axis.
    Captures short-term trends and smooths noise.
    """

    for col in feature_cols:
        for w in windows:
            # Rolling mean
            df[f'{col}_roll_{w}_mean'] = df.groupby(['bearing', 'axis'])[col].transform(
                lambda x: x.rolling(window=w, min_periods=1).mean()
            )
            # Rolling std
            df[f'{col}_roll_{w}_std'] = df.groupby(['bearing', 'axis'])[col].transform(
                lambda x: x.rolling(window=w, min_periods=1).std()
            )
    
    return df

def add_delta_features(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """
    Add delta features (diff and pct_change) to capture rate of change.
    Rising RMS/vibration is important for failure prediction.
    """
    
    for col in feature_cols:
        # Absolute difference
        df[f'{col}_diff_1'] = df.groupby(['bearing', 'axis'])[col].transform(
            lambda x: x.diff().fillna(0)
        )
        # Percentage change
        df[f'{col}_pct_change_1'] = df.groupby(['bearing', 'axis'])[col].transform(
            lambda x: x.pct_change().fillna(0)
        )
    
    return df

def add_ema_features(df: pd.DataFrame, feature_cols: List[str], 
                    alphas: List[float] = [0.1, 0.3, 0.5]) -> pd.DataFrame:
    """
    Add exponential moving average features.
    """

    for col in feature_cols:
        for alpha in alphas:
            df[f'{col}_ema_{int(alpha*100)}'] = df.groupby(['bearing', 'axis'])[col].transform(
                lambda x: x.ewm(alpha=alpha, adjust=False).mean()
            )
    
    return df

def add_rolling_slope_features(df: pd.DataFrame, feature_cols: List[str], 
                              windows: List[int] = [5, 10]) -> pd.DataFrame:
    """
    Add rolling slope features to capture trend direction.
    Positive slope indicates worsening condition.
    """
    for col in feature_cols:
        for w in windows:
            def slope_func(x):
                if len(x) < 2: return 0.0
                x_idx = np.arange(len(x))
                return np.polyfit(x_idx, x.values, 1)[0]
            df[f'{col}_slope_{w}'] = df.groupby(['bearing', 'axis'])[col].transform(
                lambda x: x.rolling(window=w, min_periods=2).apply(slope_func, raw=False)
            )
    
    return df

def add_zscore_features(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """
    Add z-score normalization per bearing/axis.
    Removes scale differences between machines.
    """

    for col in feature_cols:
        # Z-score normalization per bearing-axis combination
        df[f'{col}_zscore'] = df.groupby(['bearing', 'axis'])[col].transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-8)
        )
    
    return df

def add_bearing_aggregates(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """
    Add per-bearing aggregates combining X/Y channels.
    Creates bearing-level features from individual axis measurements.
    """
    # Group by bearing and timestamp to get both axes at same time
    for col in feature_cols:
        grouped = df.groupby(['bearing', 'timestamp'])[col]

        # Max across axes
        df[f'{col}_bearing_max'] = grouped.transform('max')
        
        # Min across axes
        df[f'{col}_bearing_min'] = grouped.transform('min')
        
        # Mean across axes
        df[f'{col}_bearing_mean'] = grouped.transform('mean')
        
        # Range (max - min)
        df[f'{col}_bearing_range'] = grouped.transform(lambda x: x.max() - x.min())
    
    return df

def create_temporal_features(df: pd.DataFrame, 
                           base_features: List[str] = None) -> pd.DataFrame:
    """
    Main function to create all temporal features.
    Args:
        df: Input dataframe with base features
    Returns:
        DataFrame with additional temporal features
    """
    if base_features is None:
        # Default to key vibration features
        base_features = ['rms_mean', 'std_mean', 'kurtosis_mean', 'crest_factor_mean', 
                        'spec_centroid_mean', 'bp_0_1k_mean', 'bp_1k_5k_mean', 'bp_5k_10k_mean']
    
    df = df.sort_values(['bearing', 'axis', 'timestamp']).reset_index(drop=True)

    df = add_rolling_features(df, base_features)
    df = add_delta_features(df, base_features)
    df = add_ema_features(df, base_features)
    df = add_rolling_slope_features(df, base_features)
    df = add_zscore_features(df, base_features)
    df = add_bearing_aggregates(df, base_features)
    
    print(f"Added {len(df.columns) - len(base_features) - 5} new features") #minus meta cols
    return df
