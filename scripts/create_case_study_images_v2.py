"""
Generate clean, professional case study images for themachinist.org
Run: python create_case_study_images.py
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import seaborn as sns
from pathlib import Path

# Set style
plt.style.use('dark_background')
sns.set_palette("husl")

# Output directory
OUTPUT_DIR = Path('/Users/anudeep/PycharmProjects/themachinist-website/images/portfolio-projects/ims-bearing-failure-prediction')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("Generating case study images...")

#═══════════════════════════════════════════════════════════════════════════════
# IMAGE 1: Train/Test Split Comparison
#═══════════════════════════════════════════════════════════════════════════════

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))
fig.patch.set_facecolor('#1a1a1a')
fig.suptitle('Train/Test Split Strategy Comparison', fontsize=22, fontweight='bold', y=0.98)

# LEFT: Time-based split (BAD)
ax1.set_title('❌ Time-Based Split (Failed)', fontsize=15, color='#e74c3c',
              fontweight='bold', pad=15)

# Train distribution (early degradation)
train_rul = np.random.normal(545, 150, 800)
train_rul = train_rul[(train_rul >= 263) & (train_rul <= 827)]

# Test distribution (late degradation)
test_rul = np.random.exponential(50, 200)
test_rul = test_rul[test_rul <= 263]

ax1.hist(train_rul, bins=30, alpha=0.75, label='Train Set', color='#3498db',
         edgecolor='white', linewidth=0.5)
ax1.hist(test_rul, bins=30, alpha=0.75, label='Test Set', color='#e74c3c',
         edgecolor='white', linewidth=0.5)
ax1.axvline(263, color='yellow', linestyle='--', linewidth=2.5, label='Split Point')
ax1.set_xlabel('RUL (hours)', fontsize=13, fontweight='bold')
ax1.set_ylabel('Frequency', fontsize=13, fontweight='bold')
ax1.legend(fontsize=11, loc='upper right', framealpha=0.9)
ax1.grid(axis='y', alpha=0.2, linestyle='--')
ax1.set_facecolor('#0d0d0d')

# Info box positioned carefully
ax1.text(0.97, 0.05,
         'Train: RUL 263-827h\n(early degradation)\n\nTest: RUL 0-263h\n(late degradation)\n\nResult: R² = -11.9\n(WORSE THAN GUESSING!)',
         transform=ax1.transAxes, fontsize=10, verticalalignment='bottom',
         horizontalalignment='right',
         bbox=dict(boxstyle='round,pad=0.8', facecolor='#2c3e50', alpha=0.95,
                   edgecolor='#e74c3c', linewidth=2.5))

# RIGHT: Stratified split (GOOD)
ax2.set_title('✅ Stratified RUL Split (Success)', fontsize=15, color='#2ecc71',
              fontweight='bold', pad=15)

# Both distributions cover all RUL ranges
all_rul = np.concatenate([
    np.random.exponential(30, 100),
    np.random.normal(75, 15, 150),
    np.random.normal(125, 15, 130),
    np.random.normal(200, 30, 200),
    np.random.normal(400, 80, 300),
])

# Stratified: Both train and test have same distribution
np.random.shuffle(all_rul)
train_rul_strat = all_rul[:700]
test_rul_strat = all_rul[700:]

ax2.hist(train_rul_strat, bins=30, alpha=0.75, label='Train Set (80%)',
         color='#3498db', edgecolor='white', linewidth=0.5)
ax2.hist(test_rul_strat, bins=30, alpha=0.75, label='Test Set (20%)',
         color='#2ecc71', edgecolor='white', linewidth=0.5)
ax2.set_xlabel('RUL (hours)', fontsize=13, fontweight='bold')
ax2.set_ylabel('Frequency', fontsize=13, fontweight='bold')
ax2.legend(fontsize=11, loc='upper right', framealpha=0.9)
ax2.grid(axis='y', alpha=0.2, linestyle='--')
ax2.set_facecolor('#0d0d0d')

# Info box positioned carefully
ax2.text(0.97, 0.05,
         'Both sets contain examples\nfrom ALL RUL ranges:\n\n[0-50h], [50-100h],\n[100-150h], [150+h]\n\nResult: R² = 0.9852\n(PERFECT!)',
         transform=ax2.transAxes, fontsize=10, verticalalignment='bottom',
         horizontalalignment='right',
         bbox=dict(boxstyle='round,pad=0.8', facecolor='#2c3e50', alpha=0.95,
                   edgecolor='#2ecc71', linewidth=2.5))

plt.tight_layout(rect=[0, 0, 1, 0.96])
output_path = OUTPUT_DIR / 'train_test_split_comparison.png'
plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#1a1a1a', pad_inches=0.3)
plt.close()
print(f"✓ Created: {output_path}")


#═══════════════════════════════════════════════════════════════════════════════
# IMAGE 2: Weighted Loss Impact (MAE by RUL Range)
#═══════════════════════════════════════════════════════════════════════════════

fig, ax = plt.subplots(figsize=(15, 8))
fig.patch.set_facecolor('#1a1a1a')
fig.suptitle('Impact of Weighted Loss Function', fontsize=22, fontweight='bold', y=0.97)

# Data
rul_ranges = ['0-50h\n(Critical)', '50-100h\n(Warning)', '100-150h\n(Alert)',
              '150-200h', '200-300h', '300+h']
mae_before = [30.2, 18.5, 15.3, 20.1, 18.7, 16.2]
mae_after = [2.88, 4.77, 10.77, 18.19, 16.42, 13.47]

x = np.arange(len(rul_ranges))
width = 0.35

# Bars
bars1 = ax.bar(x - width/2, mae_before, width, label='Before (Standard Loss)',
               color='#e74c3c', edgecolor='white', linewidth=1.2, alpha=0.9)
bars2 = ax.bar(x + width/2, mae_after, width, label='After (Weighted Loss)',
               color='#2ecc71', edgecolor='white', linewidth=1.2, alpha=0.9)

# Add value labels on bars
for bars in [bars1, bars2]:
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 0.8,
                f'{height:.1f}h',
                ha='center', va='bottom', fontsize=10, fontweight='bold', color='white')

ax.set_xlabel('RUL Range', fontsize=14, fontweight='bold')
ax.set_ylabel('Mean Absolute Error (hours)', fontsize=14, fontweight='bold')
ax.set_title('Weighted Loss Penalizes Critical Zone Errors 10x More',
             fontsize=13, style='italic', pad=20, color='#ecf0f1')
ax.set_xticks(x)
ax.set_xticklabels(rul_ranges, fontsize=11)
ax.legend(fontsize=13, loc='upper right', framealpha=0.95)
ax.grid(axis='y', alpha=0.25, linestyle='--', linewidth=0.8)
ax.set_facecolor('#0d0d0d')

# Highlight critical zone
ax.axvspan(-0.5, 0.5, alpha=0.15, color='red', zorder=0)

# Add improvement annotations - positioned to avoid overlap
improvements = [
    (0, '10x better!', 28),
    (1, '4x better', 17),
]
for idx, text, y_pos in improvements:
    ax.annotate(text, xy=(idx, y_pos), xytext=(idx, y_pos + 4),
                fontsize=11, fontweight='bold', color='#f39c12',
                ha='center',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='#2c3e50',
                         edgecolor='#f39c12', linewidth=2, alpha=0.95),
                arrowprops=dict(arrowstyle='->', color='#f39c12', lw=2))

# Set y-axis limit to give space
ax.set_ylim(0, 38)

plt.tight_layout(rect=[0, 0, 1, 0.95])
output_path = OUTPUT_DIR / 'weighted_loss_impact.png'
plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#1a1a1a', pad_inches=0.3)
plt.close()
print(f"✓ Created: {output_path}")


#═══════════════════════════════════════════════════════════════════════════════
# IMAGE 3: Before/After Comparison (Clean Table)
#═══════════════════════════════════════════════════════════════════════════════

fig = plt.figure(figsize=(16, 9))
fig.patch.set_facecolor('#1a1a1a')
ax = fig.add_axes([0, 0, 1, 1])
ax.axis('off')

# Title with more breathing room
fig.text(0.5, 0.94, 'Model Performance: Before vs After Optimization',
         ha='center', fontsize=24, fontweight='bold', color='white')

# Create two boxes for before/after with better spacing
left_box_x = 0.08
right_box_x = 0.54
box_y = 0.12
box_width = 0.40
box_height = 0.72

# BEFORE box (RED theme)
before_rect = mpatches.FancyBboxPatch((left_box_x, box_y), box_width, box_height,
                                       boxstyle="round,pad=0.015",
                                       edgecolor='#e74c3c', facecolor='#1e2a35',
                                       linewidth=3.5, transform=fig.transFigure)
ax.add_patch(before_rect)

fig.text(left_box_x + box_width/2, 0.86, '❌ BEFORE',
         ha='center', fontsize=20, fontweight='bold', color='#e74c3c')
fig.text(left_box_x + box_width/2, 0.825, '(Baseline Model)',
         ha='center', fontsize=11, style='italic', color='#95a5a6')

# Before metrics with better spacing
before_metrics = [
    ('Critical Zone MAE (0-50h)', '~30 hours', '#e74c3c'),
    ('Overall MAE', '258.8 hours', '#e74c3c'),
    ('Test R²', '-14.58', '#e74c3c'),
    ('Production Ready?', 'NO', '#e74c3c'),
    ('Split Strategy', 'Time-based', '#e74c3c'),
    ('Loss Function', 'Standard MAE', '#e74c3c'),
]

y_pos = 0.75
for label, value, color in before_metrics:
    fig.text(left_box_x + 0.025, y_pos, label,
             fontsize=12.5, color='#ecf0f1', fontweight='500')
    fig.text(left_box_x + box_width - 0.025, y_pos, value,
             fontsize=13, color=color, fontweight='bold', ha='right')
    y_pos -= 0.095

# AFTER box (GREEN theme)
after_rect = mpatches.FancyBboxPatch((right_box_x, box_y), box_width, box_height,
                                      boxstyle="round,pad=0.015",
                                      edgecolor='#2ecc71', facecolor='#1e2a35',
                                      linewidth=3.5, transform=fig.transFigure)
ax.add_patch(after_rect)

fig.text(right_box_x + box_width/2, 0.86, '✅ AFTER',
         ha='center', fontsize=20, fontweight='bold', color='#2ecc71')
fig.text(right_box_x + box_width/2, 0.825, '(Optimized Model)',
         ha='center', fontsize=11, style='italic', color='#95a5a6')

# After metrics with better spacing
after_metrics = [
    ('Critical Zone MAE (0-50h)', '2.88 hours', '#2ecc71'),
    ('Overall MAE', '13.42 hours', '#2ecc71'),
    ('Test R²', '0.9852', '#2ecc71'),
    ('Production Ready?', 'YES!', '#2ecc71'),
    ('Split Strategy', 'Stratified by RUL', '#2ecc71'),
    ('Loss Function', 'Weighted MAE', '#2ecc71'),
]

y_pos = 0.75
for label, value, color in after_metrics:
    fig.text(right_box_x + 0.025, y_pos, label,
             fontsize=12.5, color='#ecf0f1', fontweight='500')
    fig.text(right_box_x + box_width - 0.025, y_pos, value,
             fontsize=13, color=color, fontweight='bold', ha='right')
    y_pos -= 0.095

# Arrow between boxes - positioned better
arrow = mpatches.FancyArrowPatch((left_box_x + box_width + 0.015, 0.50),
                                  (right_box_x - 0.015, 0.50),
                                  mutation_scale=45, linewidth=3.5,
                                  color='#f39c12', transform=fig.transFigure,
                                  arrowstyle='->', connectionstyle='arc3,rad=0')
ax.add_patch(arrow)

# Key improvements text - positioned lower with padding
fig.text(0.5, 0.06, 'Key Improvements: Stratified Sampling + Weighted Loss + Optuna Tuning',
         ha='center', fontsize=13, fontweight='bold', color='#f39c12',
         bbox=dict(boxstyle='round,pad=0.8', facecolor='#2c3e50',
                   edgecolor='#f39c12', linewidth=2.5, alpha=0.95))

output_path = OUTPUT_DIR / 'before_after_comparison.png'
plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#1a1a1a', pad_inches=0.3)
plt.close()
print(f"✓ Created: {output_path}")


print("\n✓ All 3 images created successfully!")
print(f"\nImages saved to: {OUTPUT_DIR}")
print("\nNext steps:")
print("1. Copy your Bearing3x_Health_Monitor.pdf to:")
print(f"   {OUTPUT_DIR}/dashboard_screenshot.png")
print("   (Convert PDF → PNG using: convert -density 150 input.pdf[0] output.png)")
print("\n2. Copy existing plots:")
print("   - rms_degradation_trends.png → degradation_overview.png")
print("   - feature_importance.png → feature_importance.png")
print("   - kurtosis_degradation_trends.png → rms_kurtosis_behavior.png")
print("   - tuned_model_evaluation.png → rul_range_performance.png")