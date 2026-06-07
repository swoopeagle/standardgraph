"""Crosswalk mapping confidence analysis and visualizations."""
import sqlite3
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "common_core.db"
OUT = Path(__file__).parent.parent / "docs" / "crosswalk_analysis.png"

conn = sqlite3.connect(DB)

# ── 1. Raw confidence distribution ───────────────────────────────────────────
scores = [r[0] for r in conn.execute("SELECT confidence_score FROM crosswalk_mappings").fetchall()]
scores = np.array(scores)

# ── 2. Cumulative count at each threshold ─────────────────────────────────────
thresholds = np.arange(0.70, 1.001, 0.01)
cumulative = [np.sum(scores >= t) for t in thresholds]
pct_retained = [100 * c / len(scores) for c in cumulative]

# ── 3. Per-system breakdown ────────────────────────────────────────────────────
INTL = ['dodea','aero','sg-moe','jp-mext','nz-moe','au-acara','au-vic',
        'cambridge','ib-myp','ib-dp','uk-nc','uk-aqa','gb-sco','ie-ncca',
        'hk-edb','gh-nacca','za-caps']

sys_data = conn.execute("""
    SELECT source_system,
           COUNT(*) as total,
           AVG(confidence_score) as avg_conf,
           SUM(CASE WHEN confidence_score >= 0.9 THEN 1 ELSE 0 END) as high,
           SUM(CASE WHEN confidence_score >= 0.8 AND confidence_score < 0.9 THEN 1 ELSE 0 END) as med,
           SUM(CASE WHEN confidence_score < 0.8 THEN 1 ELSE 0 END) as low
    FROM crosswalk_mappings
    WHERE source_system IN ({})
    GROUP BY source_system
    ORDER BY avg_conf DESC
""".format(','.join('?' * len(INTL))), INTL).fetchall()

conn.close()

# ── Layout ─────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(18, 13), facecolor='#0f1117')
gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.42, wspace=0.35,
                       left=0.07, right=0.97, top=0.92, bottom=0.08)

DARK   = '#0f1117'
PANEL  = '#1a1d27'
GRID   = '#2a2d3a'
TEXT   = '#e8eaf0'
MUTED  = '#8890a8'
BLUE   = '#4f8ef7'
GREEN  = '#3ecf8e'
AMBER  = '#f59e0b'
RED    = '#ef4444'
PURPLE = '#a78bfa'

def styled_ax(ax, title):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.title.set_color(TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID)
    ax.grid(color=GRID, linewidth=0.5, linestyle='--', alpha=0.7)
    ax.set_title(title, fontsize=11, fontweight='bold', pad=10)

# ── Panel 1: Confidence histogram ─────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
styled_ax(ax1, 'Confidence Score Distribution')
n, bins, patches = ax1.hist(scores, bins=60, color=BLUE, edgecolor=DARK, linewidth=0.3, alpha=0.9)
# Colour-code by threshold zones
for patch, left in zip(patches, bins[:-1]):
    if left >= 0.9:
        patch.set_facecolor(GREEN)
    elif left >= 0.8:
        patch.set_facecolor(BLUE)
    elif left >= 0.7:
        patch.set_facecolor(AMBER)
ax1.axvline(0.70, color=AMBER,  linewidth=1.5, linestyle='--', label='0.70 (default)')
ax1.axvline(0.80, color=BLUE,   linewidth=1.5, linestyle='--', label='0.80 (strong)')
ax1.axvline(0.90, color=GREEN,  linewidth=1.5, linestyle='--', label='0.90 (high)')
ax1.set_xlabel('Confidence Score')
ax1.set_ylabel('# Mappings')
ax1.legend(fontsize=8, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)

# Annotations
total = len(scores)
for thresh, color, label, ypos in [
    (0.70, AMBER,  f"{np.sum(scores>=0.70):,} total", 0.92),
    (0.80, BLUE,   f"{np.sum(scores>=0.80):,} ≥0.80",  0.82),
    (0.90, GREEN,  f"{np.sum(scores>=0.90):,} ≥0.90",  0.72),
]:
    ax1.text(0.97, ypos, label, transform=ax1.transAxes,
             ha='right', color=color, fontsize=8.5, fontweight='bold')

# ── Panel 2: Mappings retained vs threshold ───────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
styled_ax(ax2, 'Mappings Retained at Each Threshold')
ax2.plot(thresholds, cumulative, color=BLUE, linewidth=2.5)
ax2.fill_between(thresholds, cumulative, alpha=0.15, color=BLUE)

for t, color, lbl in [(0.70, AMBER, '0.70'), (0.80, BLUE, '0.80'), (0.85, PURPLE, '0.85'), (0.90, GREEN, '0.90')]:
    c = int(np.sum(scores >= t))
    ax2.axvline(t, color=color, linewidth=1.2, linestyle=':', alpha=0.8)
    ax2.scatter([t], [c], color=color, s=60, zorder=5)
    ax2.text(t + 0.003, c + 120, f'{c:,}', color=color, fontsize=8, fontweight='bold')

ax2.set_xlabel('Confidence Threshold')
ax2.set_ylabel('# Mappings Retained')
ax2.set_xlim(0.695, 1.005)

# ── Panel 3: % retained curve ─────────────────────────────────────────────────
ax3 = fig.add_subplot(gs[0, 2])
styled_ax(ax3, '% of Mappings Retained')
ax3.plot(thresholds, pct_retained, color=PURPLE, linewidth=2.5)
ax3.fill_between(thresholds, pct_retained, alpha=0.15, color=PURPLE)
ax3.set_xlabel('Confidence Threshold')
ax3.set_ylabel('% Retained')
ax3.set_xlim(0.695, 1.005)
ax3.set_ylim(0, 105)
for t, color in [(0.70, AMBER), (0.80, BLUE), (0.85, PURPLE), (0.90, GREEN)]:
    pct = 100 * np.sum(scores >= t) / total
    ax3.axvline(t, color=color, linewidth=1.2, linestyle=':', alpha=0.8)
    ax3.text(t + 0.003, pct + 2, f'{pct:.0f}%', color=color, fontsize=8, fontweight='bold')

# ── Panel 4: International systems stacked bar ────────────────────────────────
ax4 = fig.add_subplot(gs[1, :2])
styled_ax(ax4, 'International Systems — Mapping Confidence Breakdown')

labels = [r[0] for r in sys_data]
highs  = [r[3] for r in sys_data]
meds   = [r[4] for r in sys_data]
lows   = [r[5] for r in sys_data]
avgs   = [r[2] for r in sys_data]

x = np.arange(len(labels))
w = 0.6
b1 = ax4.bar(x, lows,  w, label='0.70–0.79',  color=AMBER,  alpha=0.85)
b2 = ax4.bar(x, meds,  w, bottom=lows,         label='0.80–0.89', color=BLUE,  alpha=0.85)
b3 = ax4.bar(x, highs, w, bottom=[l+m for l,m in zip(lows,meds)], label='≥0.90', color=GREEN, alpha=0.85)

ax4.set_xticks(x)
ax4.set_xticklabels(labels, rotation=35, ha='right', fontsize=9)
ax4.set_ylabel('# Mappings')
ax4.legend(fontsize=8.5, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, loc='upper right')

# Avg confidence line on secondary axis
ax4b = ax4.twinx()
ax4b.set_facecolor(PANEL)
ax4b.plot(x, avgs, color=RED, linewidth=1.8, marker='o', markersize=5, label='Avg confidence', zorder=5)
ax4b.set_ylabel('Avg Confidence', color=RED, fontsize=9)
ax4b.tick_params(axis='y', colors=RED, labelsize=8)
ax4b.set_ylim(0.70, 1.05)
ax4b.spines['right'].set_edgecolor(RED)

# ── Panel 5: Threshold impact table ───────────────────────────────────────────
ax5 = fig.add_subplot(gs[1, 2])
ax5.set_facecolor(PANEL)
ax5.axis('off')
ax5.set_title('Threshold Impact Summary', fontsize=11, fontweight='bold',
              color=TEXT, pad=10)

rows = []
for t in [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]:
    c = int(np.sum(scores >= t))
    p = 100 * c / total
    rows.append([f'{t:.2f}', f'{c:,}', f'{p:.1f}%'])

col_labels = ['Threshold', 'Mappings', '% Kept']
table = ax5.table(
    cellText=rows,
    colLabels=col_labels,
    cellLoc='center',
    loc='center',
    bbox=[0.05, 0.1, 0.9, 0.8],
)
table.auto_set_font_size(False)
table.set_fontsize(10)
for (row, col), cell in table.get_celld().items():
    cell.set_facecolor(PANEL if row > 0 else GRID)
    cell.set_edgecolor(GRID)
    cell.set_text_props(color=TEXT if row > 0 else TEXT, fontweight='bold' if row == 0 else 'normal')
    if row > 0:
        t_val = float(rows[row-1][0])
        if t_val >= 0.90:
            cell.set_facecolor('#1a2f1a')
        elif t_val >= 0.80:
            cell.set_facecolor('#1a1f2f')
        elif t_val >= 0.70:
            cell.set_facecolor('#2f2a1a')

# ── Title ──────────────────────────────────────────────────────────────────────
fig.suptitle(
    f'StandardGraph Crosswalk Analysis  ·  {total:,} total mappings across {len(set(r[0] for r in sys_data))} intl systems',
    fontsize=14, fontweight='bold', color=TEXT, y=0.97
)

OUT.parent.mkdir(exist_ok=True)
plt.savefig(OUT, dpi=150, bbox_inches='tight', facecolor=DARK)
print(f"Saved: {OUT}")
plt.show()
