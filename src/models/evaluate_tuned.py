# src/models/evaluate_tuned.py
"""
Evaluate tuned LightGBM model with RUL-range breakdown
"""
import os
import pickle
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import matplotlib.pyplot as plt
from pathlib import Path

# Env-first (was hardcoded with no override). Default preserved for local dev.
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/anudeep')


def load_data():
    engine = create_engine(DATABASE_URL, echo=False)
    features = pd.read_csv('data/processed/selected_features.csv')['feature'].tolist()
    feature_sql = ','.join(features)

    q_test = f"""
    SELECT {feature_sql}, rul_hours FROM features 
    WHERE split='test' AND failed=TRUE AND rul_hours IS NOT NULL
    """
    test = pd.read_sql(q_test, engine)

    q_train = f"""
    SELECT {feature_sql}, rul_hours FROM features 
    WHERE split='train' AND failed=TRUE AND rul_hours IS NOT NULL
    """
    train = pd.read_sql(q_train, engine)

    X_test = test[features].replace([np.inf, -np.inf], np.nan).fillna(train[features].median())
    y_test = test['rul_hours'].values

    return X_test, y_test


def evaluate_by_rul_range(y_true, y_pred):
    """Evaluate errors by RUL range"""

    bins = [0, 50, 100, 150, 200, 300, 500, 850]
    labels = ['0-50h', '50-100h', '100-150h', '150-200h', '200-300h', '300-500h', '500+h']

    results = []

    for i, label in enumerate(labels):
        mask = (y_true >= bins[i]) & (y_true < bins[i + 1])
        if mask.sum() == 0:
            continue

        y_true_bin = y_true[mask]
        y_pred_bin = y_pred[mask]

        mae = mean_absolute_error(y_true_bin, y_pred_bin)
        rmse = np.sqrt(mean_squared_error(y_true_bin, y_pred_bin))
        mape = 100 * np.mean(np.abs((y_true_bin - y_pred_bin) / (y_true_bin + 1e-10)))

        results.append({
            'RUL_Range': label,
            'Samples': mask.sum(),
            'MAE': mae,
            'RMSE': rmse,
            'MAPE_%': mape
        })

    return pd.DataFrame(results)


def main():
    print("=" * 70)
    print("  TUNED MODEL EVALUATION")
    print("=" * 70)

    # Load test data
    print("\nLoading test data...")
    X_test, y_test = load_data()
    print(f"✓ Test samples: {len(X_test):,}")

    # Load tuned model
    print("\nLoading tuned model...")
    with open('models/lightgbm_v2_tuned.pkl', 'rb') as f:
        model = pickle.load(f)
    print("✓ Model loaded")

    # Make predictions
    print("\nGenerating predictions...")
    y_pred = model.predict(X_test)

    # Overall metrics
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)

    print("\n" + "=" * 70)
    print("  OVERALL TEST METRICS")
    print("=" * 70)
    print(f"MAE:  {mae:.2f} hours")
    print(f"RMSE: {rmse:.2f} hours")
    print(f"R²:   {r2:.4f}")

    # By RUL range
    print("\n" + "=" * 70)
    print("  ERROR BY RUL RANGE")
    print("=" * 70)

    df_results = evaluate_by_rul_range(y_test, y_pred)
    print("\n" + df_results.to_string(index=False))

    # Critical zone analysis
    critical_mask = y_test < 50
    if critical_mask.sum() > 0:
        critical_mae = mean_absolute_error(y_test[critical_mask], y_pred[critical_mask])
        print(f"\n🎯 CRITICAL ZONE (RUL < 50h):")
        print(f"   Samples: {critical_mask.sum()}")
        print(f"   MAE: {critical_mae:.2f} hours")

        if critical_mae < 10:
            print("   ✅ EXCELLENT - Production ready!")
        elif critical_mae < 15:
            print("   ✅ GOOD - Acceptable for deployment")
        elif critical_mae < 25:
            print("   ⚠️  BORDERLINE - Consider further tuning")
        else:
            print("   ❌ NEEDS IMPROVEMENT")

    # Save results
    output_dir = Path('reports/evaluation')
    output_dir.mkdir(parents=True, exist_ok=True)
    df_results.to_csv(output_dir / 'rul_range_errors_tuned.csv', index=False)
    print(f"\n✓ Results saved to {output_dir / 'rul_range_errors_tuned.csv'}")

    # Plot error distribution
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Scatter plot
    axes[0].scatter(y_test, y_pred, alpha=0.3, s=10)
    axes[0].plot([0, y_test.max()], [0, y_test.max()], 'r--', label='Perfect prediction')
    axes[0].set_xlabel('Actual RUL (hours)')
    axes[0].set_ylabel('Predicted RUL (hours)')
    axes[0].set_title(f'Predictions vs Actuals (MAE={mae:.2f}h)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Residual plot
    residuals = y_pred - y_test
    axes[1].scatter(y_test, residuals, alpha=0.3, s=10)
    axes[1].axhline(0, color='r', linestyle='--')
    axes[1].set_xlabel('Actual RUL (hours)')
    axes[1].set_ylabel('Prediction Error (hours)')
    axes[1].set_title('Residual Plot')
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_dir / 'tuned_model_evaluation.png', dpi=150)
    print(f"✓ Plots saved to {output_dir / 'tuned_model_evaluation.png'}")

    print("\n" + "=" * 70)
    print("✓✓✓ EVALUATION COMPLETE ✓✓✓")
    print("=" * 70)


if __name__ == "__main__":
    main()
