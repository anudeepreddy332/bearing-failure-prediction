# src/features/compute_stats.py
"""
Compute Feature Statistics for IMS Bearing Data
Generates per-bearing degradation curves and summary statistics

Usage:
    python src/features/compute_stats.py
    python src/features/compute_stats.py --plot-only
"""
import os
import argparse
import logging
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
import matplotlib.pyplot as plt
import seaborn as sns
import warnings

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FeatureStats')

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://postgres:postgres@localhost:5432/anudeep'
)

# Set plot style
sns.set_style('whitegrid')
plt.rcParams['figure.figsize'] = (12, 6)
plt.rcParams['font.size'] = 10


class FeatureStatisticsComputer:
    """Compute and visualize bearing feature statistics"""

    def __init__(self, db_url: str = DATABASE_URL):
        self.engine = create_engine(db_url, echo=False)
        self.output_dir = Path('reports/feature_trends')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_stats_table(self):
        """Create feature_stats table for storing aggregated statistics"""
        logger.info("Creating feature_stats table...")

        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feature_stats (
                    stat_id SERIAL PRIMARY KEY,
                    bearing_id SMALLINT NOT NULL,
                    axis CHAR(1) NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,

                    -- Key features
                    rms_mean REAL,
                    kurtosis_mean REAL,
                    crest_factor_mean REAL,
                    bp_1k_5k_mean REAL,
                    bp_5k_10k_mean REAL,

                    -- Rolling features
                    rms_mean_roll_5_mean REAL,
                    kurtosis_mean_roll_5_mean REAL,

                    -- Slopes (degradation rate)
                    rms_mean_slope_5 REAL,
                    kurtosis_mean_slope_5 REAL,

                    -- Labels
                    rul_hours REAL,
                    failed BOOLEAN,

                    -- Metadata
                    created_at TIMESTAMPTZ DEFAULT NOW(),

                    UNIQUE(bearing_id, axis, timestamp)
                )
            """))

            # Create indexes
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_stats_bearing 
                ON feature_stats(bearing_id, axis, timestamp)
            """))

            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_stats_rul 
                ON feature_stats(rul_hours)
            """))

            logger.info("✓ Table created")

    def compute_statistics(self):
        """Compute and store feature statistics"""
        logger.info("\n" + "=" * 70)
        logger.info("COMPUTING FEATURE STATISTICS")
        logger.info("=" * 70)

        # Load data
        logger.info("Loading features from database...")
        df = pd.read_sql("""
            SELECT 
                bearing_id, axis, timestamp,
                rms_mean, kurtosis_mean, crest_factor_mean,
                bp_1k_5k_mean, bp_5k_10k_mean,
                rms_mean_roll_5_mean, kurtosis_mean_roll_5_mean,
                rms_mean_slope_5, kurtosis_mean_slope_5,
                rul_hours, failed
            FROM features
            ORDER BY bearing_id, axis, timestamp
        """, con=self.engine)

        logger.info(f"✓ Loaded {len(df):,} rows")

        # Insert into stats table
        logger.info("Inserting into feature_stats table...")

        df.to_sql(
            'feature_stats',
            con=self.engine,
            if_exists='replace',  # Replace existing data
            index=False,
            method='multi',
            chunksize=1000
        )

        logger.info(f"✓ Inserted {len(df):,} statistics records")

        # Compute summary statistics per bearing
        self.compute_summary_stats(df)

    def compute_summary_stats(self, df: pd.DataFrame):
        """Compute summary statistics per bearing-axis"""
        logger.info("\n" + "=" * 70)
        logger.info("SUMMARY STATISTICS PER BEARING")
        logger.info("=" * 70)

        summary = []

        for (bearing, axis), group in df.groupby(['bearing_id', 'axis']):
            stats = {
                'bearing_id': bearing,
                'axis': axis,
                'n_samples': len(group),
                'duration_days': (group['timestamp'].max() - group['timestamp'].min()).days,

                # RMS statistics
                'rms_mean_start': group['rms_mean'].iloc[0],
                'rms_mean_end': group['rms_mean'].iloc[-1],
                'rms_mean_change_pct': 100 * (group['rms_mean'].iloc[-1] - group['rms_mean'].iloc[0]) /
                                       group['rms_mean'].iloc[0],
                'rms_mean_max': group['rms_mean'].max(),
                'rms_mean_avg': group['rms_mean'].mean(),

                # Kurtosis statistics
                'kurtosis_mean_start': group['kurtosis_mean'].iloc[0],
                'kurtosis_mean_end': group['kurtosis_mean'].iloc[-1],
                'kurtosis_mean_change_pct': 100 * (group['kurtosis_mean'].iloc[-1] - group['kurtosis_mean'].iloc[0]) / (
                            group['kurtosis_mean'].iloc[0] + 1e-10),
                'kurtosis_mean_max': group['kurtosis_mean'].max(),
                'kurtosis_mean_avg': group['kurtosis_mean'].mean(),

                # RUL
                'failed': group['failed'].iloc[0],
                'rul_min': group['rul_hours'].min() if group['failed'].iloc[0] else None,
                'rul_max': group['rul_hours'].max() if group['failed'].iloc[0] else None,
            }

            summary.append(stats)

        summary_df = pd.DataFrame(summary)

        # Display summary
        logger.info("\n" + "-" * 70)
        logger.info(f"{'Bearing':<10} {'Samples':<8} {'RMS Change':<12} {'Kurt Change':<12} {'Failed':<8}")
        logger.info("-" * 70)

        for _, row in summary_df.iterrows():
            bearing_str = f"{row['bearing_id']}-{row['axis']}"
            logger.info(
                f"{bearing_str:<10} "
                f"{row['n_samples']:<8} "
                f"{row['rms_mean_change_pct']:>10.1f}% "
                f"{row['kurtosis_mean_change_pct']:>10.1f}% "
                f"{'YES' if row['failed'] else 'NO':<8}"
            )

        # Save to CSV
        summary_path = self.output_dir / 'bearing_summary_stats.csv'
        summary_df.to_csv(summary_path, index=False)
        logger.info(f"\n✓ Summary saved to: {summary_path}")

        return summary_df

    def plot_degradation_curves(self):
        """Generate degradation curve plots"""
        logger.info("\n" + "=" * 70)
        logger.info("GENERATING DEGRADATION CURVE PLOTS")
        logger.info("=" * 70)

        # Load data
        df = pd.read_sql("""
            SELECT 
                bearing_id, axis, timestamp,
                rms_mean, kurtosis_mean, 
                rms_mean_roll_5_mean, kurtosis_mean_roll_5_mean,
                rul_hours, failed
            FROM feature_stats
            ORDER BY bearing_id, axis, timestamp
        """, con=self.engine)

        # Plot 1: RMS Trends (All Bearings)
        self.plot_rms_trends(df)

        # Plot 2: Kurtosis Trends (All Bearings)
        self.plot_kurtosis_trends(df)

        # Plot 3: Failed Bearings Comparison
        self.plot_failed_bearings_comparison(df)

        # Plot 4: RUL vs Features
        self.plot_rul_vs_features(df)

        logger.info(f"\n✓ All plots saved to: {self.output_dir}")

    def plot_rms_trends(self, df: pd.DataFrame):
        """Plot RMS trends for all bearings"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('RMS Degradation Trends by Bearing', fontsize=16, fontweight='bold')

        for idx, bearing in enumerate([1, 2, 3, 4]):
            ax = axes[idx // 2, idx % 2]

            bearing_data = df[df['bearing_id'] == bearing]

            for axis in ['x', 'y']:
                data = bearing_data[bearing_data['axis'] == axis]

                # Plot raw RMS
                ax.plot(
                    data['timestamp'],
                    data['rms_mean'],
                    alpha=0.3,
                    linewidth=1,
                    label=f'Axis {axis.upper()} (raw)'
                )

                # Plot smoothed RMS
                ax.plot(
                    data['timestamp'],
                    data['rms_mean_roll_5_mean'],
                    linewidth=2,
                    label=f'Axis {axis.upper()} (smoothed)'
                )

            failed = bearing_data['failed'].iloc[0]
            ax.set_title(f"Bearing {bearing} {'(FAILED)' if failed else '(Censored)'}", fontweight='bold')
            ax.set_xlabel('Time')
            ax.set_ylabel('RMS (Vibration Amplitude)')
            ax.legend(loc='upper left', fontsize=8)
            ax.grid(True, alpha=0.3)

            # Rotate x-axis labels
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

        plt.tight_layout()
        output_path = self.output_dir / 'rms_degradation_trends.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        logger.info(f"✓ Saved: {output_path.name}")

    def plot_kurtosis_trends(self, df: pd.DataFrame):
        """Plot kurtosis trends for all bearings"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('Kurtosis Degradation Trends by Bearing', fontsize=16, fontweight='bold')

        for idx, bearing in enumerate([1, 2, 3, 4]):
            ax = axes[idx // 2, idx % 2]

            bearing_data = df[df['bearing_id'] == bearing]

            for axis in ['x', 'y']:
                data = bearing_data[bearing_data['axis'] == axis]

                # Plot raw kurtosis
                ax.plot(
                    data['timestamp'],
                    data['kurtosis_mean'],
                    alpha=0.3,
                    linewidth=1,
                    label=f'Axis {axis.upper()} (raw)'
                )

                # Plot smoothed kurtosis
                ax.plot(
                    data['timestamp'],
                    data['kurtosis_mean_roll_5_mean'],
                    linewidth=2,
                    label=f'Axis {axis.upper()} (smoothed)'
                )

            failed = bearing_data['failed'].iloc[0]
            ax.set_title(f"Bearing {bearing} {'(FAILED)' if failed else '(Censored)'}", fontweight='bold')
            ax.set_xlabel('Time')
            ax.set_ylabel('Kurtosis (Impulsiveness)')
            ax.legend(loc='upper left', fontsize=8)
            ax.grid(True, alpha=0.3)

            # Rotate x-axis labels
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

        plt.tight_layout()
        output_path = self.output_dir / 'kurtosis_degradation_trends.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        logger.info(f"✓ Saved: {output_path.name}")

    def plot_failed_bearings_comparison(self, df: pd.DataFrame):
        """Compare failed bearings (3 & 4) side by side"""
        failed_df = df[df['failed'] == True]

        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('Failed Bearings Comparison (Bearings 3 & 4)', fontsize=16, fontweight='bold')

        # RMS comparison
        ax = axes[0, 0]
        for bearing in [3, 4]:
            for axis in ['x', 'y']:
                data = failed_df[(failed_df['bearing_id'] == bearing) & (failed_df['axis'] == axis)]
                ax.plot(
                    data['timestamp'],
                    data['rms_mean_roll_5_mean'],
                    linewidth=2,
                    label=f'Bearing {bearing}-{axis.upper()}'
                )
        ax.set_title('RMS Trends', fontweight='bold')
        ax.set_xlabel('Time')
        ax.set_ylabel('RMS (smoothed)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

        # Kurtosis comparison
        ax = axes[0, 1]
        for bearing in [3, 4]:
            for axis in ['x', 'y']:
                data = failed_df[(failed_df['bearing_id'] == bearing) & (failed_df['axis'] == axis)]
                ax.plot(
                    data['timestamp'],
                    data['kurtosis_mean_roll_5_mean'],
                    linewidth=2,
                    label=f'Bearing {bearing}-{axis.upper()}'
                )
        ax.set_title('Kurtosis Trends', fontweight='bold')
        ax.set_xlabel('Time')
        ax.set_ylabel('Kurtosis (smoothed)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

        # RMS vs RUL
        ax = axes[1, 0]
        for bearing in [3, 4]:
            data = failed_df[failed_df['bearing_id'] == bearing]
            ax.scatter(
                data['rul_hours'],
                data['rms_mean'],
                alpha=0.5,
                s=20,
                label=f'Bearing {bearing}'
            )
        ax.set_title('RMS vs Remaining Useful Life', fontweight='bold')
        ax.set_xlabel('RUL (hours)')
        ax.set_ylabel('RMS')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()  # RUL decreases over time

        # Kurtosis vs RUL
        ax = axes[1, 1]
        for bearing in [3, 4]:
            data = failed_df[failed_df['bearing_id'] == bearing]
            ax.scatter(
                data['rul_hours'],
                data['kurtosis_mean'],
                alpha=0.5,
                s=20,
                label=f'Bearing {bearing}'
            )
        ax.set_title('Kurtosis vs Remaining Useful Life', fontweight='bold')
        ax.set_xlabel('RUL (hours)')
        ax.set_ylabel('Kurtosis')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()

        plt.tight_layout()
        output_path = self.output_dir / 'failed_bearings_comparison.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        logger.info(f"✓ Saved: {output_path.name}")

    def plot_rul_vs_features(self, df: pd.DataFrame):
        """Plot RUL vs key features for failed bearings"""
        failed_df = df[df['failed'] == True].copy()

        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('Feature Evolution with Remaining Useful Life (Failed Bearings)', fontsize=16, fontweight='bold')

        # Bin RUL for better visualization
        failed_df['rul_bin'] = pd.cut(failed_df['rul_hours'], bins=20)
        grouped = failed_df.groupby('rul_bin').agg({
            'rms_mean': 'mean',
            'kurtosis_mean': 'mean',
            'rms_mean_roll_5_mean': 'mean',
            'kurtosis_mean_roll_5_mean': 'mean'
        }).reset_index()

        # Extract bin centers
        grouped['rul_center'] = grouped['rul_bin'].apply(lambda x: x.mid)

        # RMS vs RUL
        ax = axes[0, 0]
        ax.plot(grouped['rul_center'], grouped['rms_mean'], 'o-', linewidth=2, markersize=6)
        ax.set_title('RMS vs RUL', fontweight='bold')
        ax.set_xlabel('Remaining Useful Life (hours)')
        ax.set_ylabel('RMS (mean)')
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()

        # Kurtosis vs RUL
        ax = axes[0, 1]
        ax.plot(grouped['rul_center'], grouped['kurtosis_mean'], 'o-', linewidth=2, markersize=6, color='orange')
        ax.set_title('Kurtosis vs RUL', fontweight='bold')
        ax.set_xlabel('Remaining Useful Life (hours)')
        ax.set_ylabel('Kurtosis (mean)')
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()

        # RMS smoothed vs RUL
        ax = axes[1, 0]
        ax.plot(grouped['rul_center'], grouped['rms_mean_roll_5_mean'], 'o-', linewidth=2, markersize=6, color='green')
        ax.set_title('RMS (Smoothed) vs RUL', fontweight='bold')
        ax.set_xlabel('Remaining Useful Life (hours)')
        ax.set_ylabel('RMS (5-file rolling mean)')
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()

        # Kurtosis smoothed vs RUL
        ax = axes[1, 1]
        ax.plot(grouped['rul_center'], grouped['kurtosis_mean_roll_5_mean'], 'o-', linewidth=2, markersize=6,
                color='red')
        ax.set_title('Kurtosis (Smoothed) vs RUL', fontweight='bold')
        ax.set_xlabel('Remaining Useful Life (hours)')
        ax.set_ylabel('Kurtosis (5-file rolling mean)')
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()

        plt.tight_layout()
        output_path = self.output_dir / 'rul_vs_features.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        logger.info(f"✓ Saved: {output_path.name}")

    def run(self, plot_only: bool = False):
        """Run complete feature statistics pipeline"""
        logger.info("=" * 70)
        logger.info("  IMS BEARING FEATURE STATISTICS")
        logger.info("=" * 70)

        if not plot_only:
            # Create table
            self.create_stats_table()

            # Compute statistics
            self.compute_statistics()

        # Generate plots
        self.plot_degradation_curves()

        logger.info("\n" + "=" * 70)
        logger.info("✓✓✓ FEATURE STATISTICS COMPLETE ✓✓✓")
        logger.info("=" * 70)


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Compute Feature Statistics for IMS Bearing Data")

    parser.add_argument(
        '--plot-only',
        action='store_true',
        help='Only generate plots (skip database operations)'
    )

    args = parser.parse_args()

    # Run statistics computation
    computer = FeatureStatisticsComputer()
    computer.run(plot_only=args.plot_only)


if __name__ == "__main__":
    main()
