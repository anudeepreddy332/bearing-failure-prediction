# src/models/tune.py
"""
LightGBM Hyperparameter Tuning with Optuna for RUL
Usage:
    python src/models/tune.py --trials 50
"""
import os
import argparse
import logging
from pathlib import Path
import pickle
import numpy as np
import pandas as pd
import optuna
from sqlalchemy import create_engine
import lightgbm as lgb
import warnings

warnings.filterwarnings('ignore')

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://postgres:postgres@localhost:5432/anudeep'
)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('OptunaTuning')


class LGBMTuner:
    def __init__(self, db_url=DATABASE_URL):
        self.engine = create_engine(db_url, echo=False)
        self.X_train, self.X_val, self.y_train, self.y_val = self.load_data()

    def load_data(self):
        features = pd.read_csv('data/processed/selected_features.csv')['feature'].tolist()
        feature_sql = ','.join(features)
        q_train = f"""
        SELECT {feature_sql}, rul_hours FROM features 
        WHERE split='train' AND failed=TRUE AND rul_hours IS NOT NULL
        """
        q_val = f"""
        SELECT {feature_sql}, rul_hours FROM features 
        WHERE split='test' AND failed=TRUE AND rul_hours IS NOT NULL
        """
        train = pd.read_sql(q_train, self.engine)
        val = pd.read_sql(q_val, self.engine)
        X_train = train[features].replace([np.inf, -np.inf], np.nan).fillna(train[features].median())
        y_train = train['rul_hours']
        X_val = val[features].replace([np.inf, -np.inf], np.nan).fillna(train[features].median())
        y_val = val['rul_hours']
        return X_train, X_val, y_train, y_val

    def weighted_mae(self, y_true, y_pred):
        errors = np.abs(y_true - y_pred)
        weights = 1.0 + (1.0 / (y_true + 10))  # More weight as RUL → 0
        return np.mean(errors * weights)

    def optuna_objective(self, trial):
        params = {
            'objective': 'regression',
            'metric': 'mae',
            'boosting_type': 'gbdt',
            'num_leaves': trial.suggest_int('num_leaves', 16, 128),
            'learning_rate': trial.suggest_loguniform('learning_rate', 0.005, 0.3),
            'n_estimators': trial.suggest_int('n_estimators', 80, 500),
            'max_depth': trial.suggest_int('max_depth', 5, 24),
            'min_child_samples': trial.suggest_int('min_child_samples', 10, 100),
            'subsample': trial.suggest_uniform('subsample', 0.6, 1.0),
            'colsample_bytree': trial.suggest_uniform('colsample_bytree', 0.5, 1.0),
            'reg_alpha': trial.suggest_loguniform('reg_alpha', 1e-4, 1),
            'reg_lambda': trial.suggest_loguniform('reg_lambda', 1e-4, 1),
            'random_state': 42,
            'n_jobs': -1,
            'verbose': -1
        }
        model = lgb.LGBMRegressor(**params)
        model.fit(self.X_train, self.y_train)
        preds = model.predict(self.X_val)
        score = self.weighted_mae(self.y_val, preds)  # Use weighted loss for optuna
        return score

    def run_tuning(self, trials=50):
        logger.info("Starting Optuna hyperparameter tuning...")
        study = optuna.create_study(direction="minimize")
        study.optimize(self.optuna_objective, n_trials=trials)
        logger.info(f"Best weighted MAE: {study.best_value:.4f}")
        logger.info(f"Best params: {study.best_trial.params}")

        # Save best model
        best_params = study.best_trial.params.copy()
        best_params.update({
            'objective': 'regression',
            'metric': 'mae',
            'boosting_type': 'gbdt',
            'random_state': 42, 'n_jobs': -1, 'verbose': -1
        })
        final_model = lgb.LGBMRegressor(**best_params)
        final_model.fit(self.X_train, self.y_train)
        model_path = Path('models/lightgbm_v2_tuned.pkl')
        with open(model_path, 'wb') as f:
            pickle.dump(final_model, f)
        logger.info(f"Saved tuned model to {model_path}")


def main():
    parser = argparse.ArgumentParser(description="LightGBM tuning with Optuna")
    parser.add_argument("--trials", type=int, default=50, help="Number of Optuna trials (default: 50)")
    args = parser.parse_args()
    tuner = LGBMTuner()
    tuner.run_tuning(trials=args.trials)


if __name__ == "__main__":
    main()
