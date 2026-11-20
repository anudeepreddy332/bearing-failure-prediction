# src/features/select_features.py
"""
Feature Selection for IMS Bearing Prediction
Ranks features by correlation, mutual information, and redundancy

Usage:
    python src/features/select_features.py --top-n 50
    python src/features/select_features.py --method mi --top-n 30
"""
import os
import argparse
import logging
from pathlib import Path
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sklearn.feature_selection import mutual_info_regression
import warnings

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FeatureSelection')

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://postgres:postgres@localhost:5432/anudeep'
)


class FeatureSelector:
    """Feature selection for bearing failure prediction"""

    def __init__(self, db_url: str = DATABASE_URL):
        self.engine = create_engine(db_url, echo=False)
        self.feature_scores = {}

    def load_training_data(self):
        """Load training data with failed bearings only"""
        logger.info("Loading training data from PostgreSQL...")

        query = """
        SELECT *
        FROM features
        WHERE split = 'train' 
          AND failed = TRUE
          AND rul_hours IS NOT NULL
        ORDER BY timestamp
        """

        df = pd.read_sql(query, con=self.engine)
        logger.info(f"✓ Loaded {len(df):,} training samples")

        return df

    def get_feature_columns(self, df: pd.DataFrame):
        """Get list of feature columns (exclude metadata)"""
        exclude_cols = {
            'feature_id', 'file_name', 'timestamp', 'bearing_id', 'axis',
            'channel', 'n_windows', 'rul_seconds', 'rul_hours',
            'failed', 'censored', 'split'
        }
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        feature_cols = [c for c in numeric_cols if c not in exclude_cols]
        logger.info(f"Found {len(feature_cols)} feature columns")

        return feature_cols

    def correlation_ranking(self, df: pd.DataFrame, feature_cols: list, target: str = 'rul_hours'):
        """Rank features by correlation with target"""
        logger.info("\n" + "=" * 70)
        logger.info("METHOD 1: CORRELATION RANKING")
        logger.info("=" * 70)

        # Compute correlations
        corr_scores = {}

        for col in feature_cols:
            if df[col].notna().sum() < 10:  # Skip if too many nulls
                continue

            try:
                # Pearson correlation
                pearson = df[[col, target]].corr(method='pearson').iloc[0, 1]
                # Spearman correlation (non-linear)
                spearman = df[[col, target]].corr(method='spearman').iloc[0, 1]

                # Use max of absolute values
                corr_scores[col] = max(abs(pearson), abs(spearman))
            except:
                continue

        # Sort by correlation
        sorted_features = sorted(corr_scores.items(), key=lambda x: x[1], reverse=True)

        logger.info(f"\nTop 20 features by correlation:")
        for i, (feat, score) in enumerate(sorted_features[:20], 1):
            logger.info(f"  {i:2}. {feat:50s}: {score:.4f}")

        self.feature_scores['correlation'] = dict(sorted_features)

        return sorted_features

    def mutual_information_ranking(self, df: pd.DataFrame, feature_cols: list, target: str = 'rul_hours'):
        """Rank features by mutual information (non-linear relationships)"""
        logger.info("\n" + "=" * 70)
        logger.info("METHOD 2: MUTUAL INFORMATION RANKING")
        logger.info("=" * 70)

        # Prepare data
        X = df[feature_cols].fillna(df[feature_cols].median())
        y = df[target]

        # Remove infinite values
        X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())

        logger.info(f"Computing MI scores for {X.shape[1]} features...")

        # Compute mutual information
        mi_scores = mutual_info_regression(
            X, y,
            discrete_features=False,
            random_state=42,
            n_neighbors=5
        )

        # Create ranking
        mi_ranking = sorted(
            zip(feature_cols, mi_scores),
            key=lambda x: x[1],
            reverse=True
        )

        logger.info(f"\nTop 20 features by mutual information:")
        for i, (feat, score) in enumerate(mi_ranking[:20], 1):
            logger.info(f"  {i:2}. {feat:50s}: {score:.4f}")

        self.feature_scores['mutual_info'] = dict(mi_ranking)

        return mi_ranking

    def remove_redundant_features(self, df: pd.DataFrame, features: list, threshold: float = 0.95):
        """Remove highly correlated features (redundancy)"""
        logger.info("\n" + "=" * 70)
        logger.info("METHOD 3: REDUNDANCY REMOVAL")
        logger.info("=" * 70)
        logger.info(f"Checking for features with correlation > {threshold}")

        # Compute correlation matrix
        X = df[features].fillna(df[features].median())
        X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())

        corr_matrix = X.corr().abs()

        # Find redundant pairs
        redundant_pairs = []
        to_drop = set()

        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                if corr_matrix.iloc[i, j] > threshold:
                    feat_i = corr_matrix.columns[i]
                    feat_j = corr_matrix.columns[j]
                    redundant_pairs.append((feat_i, feat_j, corr_matrix.iloc[i, j]))

                    # Drop the one with lower correlation to target
                    corr_i = abs(df[[feat_i, 'rul_hours']].corr().iloc[0, 1])
                    corr_j = abs(df[[feat_j, 'rul_hours']].corr().iloc[0, 1])

                    to_drop.add(feat_i if corr_i < corr_j else feat_j)

        logger.info(f"\nFound {len(redundant_pairs)} redundant pairs")
        logger.info(f"Removing {len(to_drop)} redundant features")

        if redundant_pairs[:10]:
            logger.info("\nExample redundant pairs (top 10):")
            for feat_i, feat_j, corr in redundant_pairs[:10]:
                logger.info(f"  {feat_i} <-> {feat_j}: {corr:.3f}")

        # Keep non-redundant features
        final_features = [f for f in features if f not in to_drop]
        logger.info(f"\n✓ Kept {len(final_features)} non-redundant features")

        return final_features, list(to_drop)

    def select_top_features(self, top_n: int = 50, method: str = 'combined'):
        """
        Select top N features

        Args:
            top_n: Number of features to select
            method: 'correlation', 'mutual_info', or 'combined'
        """
        logger.info("\n" + "=" * 70)
        logger.info(f"FINAL SELECTION: TOP {top_n} FEATURES")
        logger.info("=" * 70)

        if method == 'correlation':
            ranked = sorted(
                self.feature_scores['correlation'].items(),
                key=lambda x: x[1],
                reverse=True
            )
        elif method == 'mutual_info':
            ranked = sorted(
                self.feature_scores['mutual_info'].items(),
                key=lambda x: x[1],
                reverse=True
            )
        else:  # combined
            # Average rank from both methods
            all_features = set(self.feature_scores['correlation'].keys()) | \
                           set(self.feature_scores['mutual_info'].keys())

            combined_scores = {}
            for feat in all_features:
                corr_score = self.feature_scores['correlation'].get(feat, 0)
                mi_score = self.feature_scores['mutual_info'].get(feat, 0)

                # Normalize and average
                combined_scores[feat] = (corr_score + mi_score) / 2

            ranked = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)

        # Select top N
        selected_features = [feat for feat, score in ranked[:top_n]]

        logger.info(f"\nSelected {len(selected_features)} features:")
        for i, (feat, score) in enumerate(ranked[:top_n], 1):
            logger.info(f"  {i:2}. {feat:50s}: {score:.4f}")

        return selected_features

    def save_results(self, selected_features: list, redundant_features: list, output_dir: str = "data/processed"):
        """Save feature selection results"""
        logger.info("\n" + "=" * 70)
        logger.info("SAVING RESULTS")
        logger.info("=" * 70)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save selected features
        selected_df = pd.DataFrame({
            'feature': selected_features,
            'rank': range(1, len(selected_features) + 1)
        })
        selected_path = output_path / 'selected_features.csv'
        selected_df.to_csv(selected_path, index=False)
        logger.info(f"✓ Saved selected features: {selected_path}")

        # Save correlation rankings
        corr_df = pd.DataFrame([
            {'feature': feat, 'correlation': score}
            for feat, score in self.feature_scores['correlation'].items()
        ]).sort_values('correlation', ascending=False)
        corr_path = output_path / 'feature_ranking_corr.csv'
        corr_df.to_csv(corr_path, index=False)
        logger.info(f"✓ Saved correlation rankings: {corr_path}")

        # Save MI rankings
        mi_df = pd.DataFrame([
            {'feature': feat, 'mutual_info': score}
            for feat, score in self.feature_scores['mutual_info'].items()
        ]).sort_values('mutual_info', ascending=False)
        mi_path = output_path / 'feature_ranking_mi.csv'
        mi_df.to_csv(mi_path, index=False)
        logger.info(f"✓ Saved MI rankings: {mi_path}")

        # Save redundant features
        redundant_df = pd.DataFrame({'feature': redundant_features})
        redundant_path = output_path / 'redundant_features.csv'
        redundant_df.to_csv(redundant_path, index=False)
        logger.info(f"✓ Saved redundant features: {redundant_path}")

        logger.info("\n✓✓✓ ALL RESULTS SAVED ✓✓✓")

    def run(self, top_n: int = 50, method: str = 'combined'):
        """Run complete feature selection pipeline"""
        logger.info("=" * 70)
        logger.info("  IMS BEARING FEATURE SELECTION")
        logger.info("=" * 70)

        # Load data
        df = self.load_training_data()
        feature_cols = self.get_feature_columns(df)

        # Method 1: Correlation
        corr_ranking = self.correlation_ranking(df, feature_cols)

        # Method 2: Mutual Information
        mi_ranking = self.mutual_information_ranking(df, feature_cols)

        # Select top features
        top_features = self.select_top_features(top_n, method)

        # Remove redundancy
        final_features, redundant = self.remove_redundant_features(
            df, top_features, threshold=0.95
        )

        # If we removed too many, add back next best
        if len(final_features) < top_n:
            logger.info(f"\nAdding {top_n - len(final_features)} features back...")
            all_ranked = sorted(
                self.feature_scores['correlation'].items(),
                key=lambda x: x[1],
                reverse=True
            )
            for feat, score in all_ranked:
                if feat not in final_features and feat not in redundant:
                    final_features.append(feat)
                if len(final_features) >= top_n:
                    break

        logger.info(f"\n✓ Final feature set: {len(final_features)} features")

        # Save results
        self.save_results(final_features, redundant)

        return final_features


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Feature Selection for IMS Bearing Data")

    parser.add_argument(
        '--top-n',
        type=int,
        default=50,
        help='Number of features to select (default: 50)'
    )

    parser.add_argument(
        '--method',
        type=str,
        default='combined',
        choices=['correlation', 'mutual_info', 'combined'],
        help='Selection method (default: combined)'
    )

    args = parser.parse_args()

    # Run feature selection
    selector = FeatureSelector()
    selected_features = selector.run(top_n=args.top_n, method=args.method)

    logger.info("\n✓✓✓ FEATURE SELECTION COMPLETE ✓✓✓")


if __name__ == "__main__":
    main()
