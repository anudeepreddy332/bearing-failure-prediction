# src/models/train.py
"""
Baseline Model Training for IMS Bearing RUL Prediction
Trains RandomForest and LightGBM regressors

Usage:
    python src/models/train.py --model rf
    python src/models/train.py --model lgb
    python src/models/train.py --model both
"""
import os
import argparse
import logging
import pickle
import json
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb
import warnings

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ModelTrainer')

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://postgres:postgres@localhost:5432/anudeep'
)


class BearingRULTrainer:
    """Train baseline models for bearing RUL prediction"""

    def __init__(self, db_url: str = DATABASE_URL):
        self.engine = create_engine(db_url, echo=False)
        self.models_dir = Path('models')
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self.selected_features = None
        self.scaler = StandardScaler()

        self.X_train = None
        self.y_train = None
        self.X_test = None
        self.y_test = None

    def load_selected_features(self):
        """Load top 50 selected features"""
        logger.info("Loading selected features...")

        features_path = Path('data/processed/selected_features.csv')
        if not features_path.exists():
            raise FileNotFoundError(
                f"Selected features file not found: {features_path}\n"
                f"Run feature selection first: python src/features/select_features.py"
            )

        features_df = pd.read_csv(features_path)
        self.selected_features = features_df['feature'].tolist()

        logger.info(f"✓ Loaded {len(self.selected_features)} selected features")

        return self.selected_features

    def load_data(self):
        """Load training and test data"""
        logger.info("\n" + "=" * 70)
        logger.info("LOADING DATA")
        logger.info("=" * 70)

        # Load selected features
        features = self.load_selected_features()

        # Build feature list for SQL
        feature_cols_sql = ', '.join(features)

        # Load training data (failed bearings only)
        logger.info("Loading training data...")
        train_query = f"""
        SELECT 
            {feature_cols_sql},
            rul_hours
        FROM features
        WHERE split = 'train' 
          AND failed = TRUE
          AND rul_hours IS NOT NULL
        ORDER BY timestamp
        """

        train_df = pd.read_sql(train_query, con=self.engine)
        logger.info(f"✓ Train: {len(train_df):,} samples")

        # Load test data (failed bearings only)
        logger.info("Loading test data...")
        test_query = f"""
        SELECT 
            {feature_cols_sql},
            rul_hours
        FROM features
        WHERE split = 'test' 
          AND failed = TRUE
          AND rul_hours IS NOT NULL
        ORDER BY timestamp
        """

        test_df = pd.read_sql(test_query, con=self.engine)
        logger.info(f"✓ Test:  {len(test_df):,} samples")

        # Split X and y
        self.X_train = train_df[features]
        self.y_train = train_df['rul_hours']

        self.X_test = test_df[features]
        self.y_test = test_df['rul_hours']

        # Handle any NaNs/Infs
        logger.info("Cleaning data...")
        self.X_train = self.X_train.replace([np.inf, -np.inf], np.nan).fillna(self.X_train.median())
        self.X_test = self.X_test.replace([np.inf, -np.inf], np.nan).fillna(self.X_train.median())

        logger.info(f"✓ Train shape: {self.X_train.shape}")
        logger.info(f"✓ Test shape:  {self.X_test.shape}")
        logger.info(f"✓ Features: {len(features)}")

        # RUL distribution
        logger.info(f"\nRUL distribution:")
        logger.info(
            f"  Train: min={self.y_train.min():.1f}, max={self.y_train.max():.1f}, mean={self.y_train.mean():.1f}")
        logger.info(f"  Test:  min={self.y_test.min():.1f}, max={self.y_test.max():.1f}, mean={self.y_test.mean():.1f}")

    def train_random_forest(self, quick: bool = False):
        """Train RandomForest regressor"""
        logger.info("\n" + "=" * 70)
        logger.info("TRAINING RANDOM FOREST")
        logger.info("=" * 70)

        # Hyperparameters
        if quick:
            params = {
                'n_estimators': 50,
                'max_depth': 10,
                'min_samples_split': 20,
                'min_samples_leaf': 10,
                'random_state': 42,
                'n_jobs': -1,
                'verbose': 0
            }
            logger.info("Using quick mode (50 trees)")
        else:
            params = {
                'n_estimators': 200,
                'max_depth': 20,
                'min_samples_split': 10,
                'min_samples_leaf': 5,
                'max_features': 'sqrt',
                'random_state': 42,
                'n_jobs': -1,
                'verbose': 1
            }
            logger.info("Using full mode (200 trees)")

        logger.info(f"Parameters: {params}")

        # Train model
        logger.info("\nTraining...")
        rf_model = RandomForestRegressor(**params)
        rf_model.fit(self.X_train, self.y_train)

        logger.info("✓ Training complete")

        # Evaluate
        train_metrics = self._evaluate_model(rf_model, self.X_train, self.y_train, "Train")
        test_metrics = self._evaluate_model(rf_model, self.X_test, self.y_test, "Test")

        # Save model
        model_path = self.models_dir / 'random_forest_v1.pkl'
        with open(model_path, 'wb') as f:
            pickle.dump(rf_model, f)
        logger.info(f"\n✓ Model saved: {model_path}")

        # Save metadata
        metadata = {
            'model_type': 'RandomForest',
            'version': 'v1',
            'trained_at': datetime.now().isoformat(),
            'n_features': len(self.selected_features),
            'train_samples': len(self.X_train),
            'test_samples': len(self.X_test),
            'params': params,
            'train_metrics': train_metrics,
            'test_metrics': test_metrics
        }

        metadata_path = self.models_dir / 'random_forest_v1_metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"✓ Metadata saved: {metadata_path}")

        return rf_model, metadata

    def train_lightgbm(self, quick: bool = False):
        """Train LightGBM regressor"""
        logger.info("\n" + "=" * 70)
        logger.info("TRAINING LIGHTGBM")
        logger.info("=" * 70)

        # Hyperparameters
        if quick:
            params = {
                'objective': 'regression',
                'metric': 'mae',
                'boosting_type': 'gbdt',
                'num_leaves': 31,
                'learning_rate': 0.1,
                'n_estimators': 50,
                'random_state': 42,
                'n_jobs': -1,
                'verbose': -1
            }
            logger.info("Using quick mode (50 iterations)")
        else:
            params = {
                'objective': 'regression',
                'metric': 'mae',
                'boosting_type': 'gbdt',
                'num_leaves': 64,
                'learning_rate': 0.05,
                'n_estimators': 200,
                'max_depth': 15,
                'min_child_samples': 20,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'reg_alpha': 0.1,
                'reg_lambda': 0.1,
                'random_state': 42,
                'n_jobs': -1,
                'verbose': -1
            }
            logger.info("Using full mode (200 iterations)")

        logger.info(f"Parameters: {params}")

        # Train model
        logger.info("\nTraining...")
        lgb_model = lgb.LGBMRegressor(**params)
        lgb_model.fit(
            self.X_train, self.y_train,
            eval_set=[(self.X_test, self.y_test)],
            eval_metric='mae',
            callbacks=[lgb.log_evaluation(period=50)]
        )

        logger.info("✓ Training complete")

        # Evaluate
        train_metrics = self._evaluate_model(lgb_model, self.X_train, self.y_train, "Train")
        test_metrics = self._evaluate_model(lgb_model, self.X_test, self.y_test, "Test")

        # Save model
        model_path = self.models_dir / 'lightgbm_v1.pkl'
        with open(model_path, 'wb') as f:
            pickle.dump(lgb_model, f)
        logger.info(f"\n✓ Model saved: {model_path}")

        # Save metadata
        metadata = {
            'model_type': 'LightGBM',
            'version': 'v1',
            'trained_at': datetime.now().isoformat(),
            'n_features': len(self.selected_features),
            'train_samples': len(self.X_train),
            'test_samples': len(self.X_test),
            'params': params,
            'train_metrics': train_metrics,
            'test_metrics': test_metrics
        }

        metadata_path = self.models_dir / 'lightgbm_v1_metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"✓ Metadata saved: {metadata_path}")

        return lgb_model, metadata

    def _evaluate_model(self, model, X, y, dataset_name: str):
        """Evaluate model and return metrics"""
        y_pred = model.predict(X)

        mae = mean_absolute_error(y, y_pred)
        rmse = np.sqrt(mean_squared_error(y, y_pred))
        r2 = r2_score(y, y_pred)

        logger.info(f"\n{dataset_name} Metrics:")
        logger.info(f"  MAE:  {mae:.2f} hours")
        logger.info(f"  RMSE: {rmse:.2f} hours")
        logger.info(f"  R²:   {r2:.4f}")

        return {
            'mae': float(mae),
            'rmse': float(rmse),
            'r2': float(r2)
        }

    def run(self, model_type: str = 'both', quick: bool = False):
        """Run training pipeline"""
        logger.info("=" * 70)
        logger.info("  IMS BEARING RUL PREDICTION - MODEL TRAINING")
        logger.info("=" * 70)

        # Load data
        self.load_data()

        results = {}

        # Train RandomForest
        if model_type in ['rf', 'both']:
            rf_model, rf_metadata = self.train_random_forest(quick=quick)
            results['random_forest'] = rf_metadata

        # Train LightGBM
        if model_type in ['lgb', 'both']:
            lgb_model, lgb_metadata = self.train_lightgbm(quick=quick)
            results['lightgbm'] = lgb_metadata

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("TRAINING SUMMARY")
        logger.info("=" * 70)

        for model_name, metadata in results.items():
            logger.info(f"\n{model_name.upper()}:")
            logger.info(f"  Train MAE:  {metadata['train_metrics']['mae']:.2f} hours")
            logger.info(f"  Test MAE:   {metadata['test_metrics']['mae']:.2f} hours")
            logger.info(f"  Test R²:    {metadata['test_metrics']['r2']:.4f}")

        logger.info("\n" + "=" * 70)
        logger.info("✓✓✓ TRAINING COMPLETE ✓✓✓")
        logger.info("=" * 70)

        return results


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Train baseline models for IMS Bearing RUL Prediction"
    )

    parser.add_argument(
        '--model',
        type=str,
        default='both',
        choices=['rf', 'lgb', 'both'],
        help='Model type to train (rf=RandomForest, lgb=LightGBM, both=both models)'
    )

    parser.add_argument(
        '--quick',
        action='store_true',
        help='Use quick training mode (fewer trees/iterations, faster but less accurate)'
    )

    args = parser.parse_args()

    # Run training
    trainer = BearingRULTrainer()
    results = trainer.run(model_type=args.model, quick=args.quick)


if __name__ == "__main__":
    main()
