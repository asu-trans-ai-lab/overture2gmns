"""Generate publication-quality QA/QC figures from qaqc_dataset.json.

Outputs PNGs into figures/ for embedding in the repo README and report.
Clean, consistent styling; osm2gmns = slate reference, overture2gmns = cyan.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager  # noqa: F401

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)
BENCH = HERE.parent.parent / "bench" / "out"
DATA = json.loads((HERE / "qaqc_dataset.json").read_text())

OSM = "#64748b"      # slate — reference
OVR = "#0e7490"      # deep cyan — overture2gmns
PASS = "#15803d"     # green
WARN = "#b45309"     # amber
INK = "#1f2937"
GRID = "#e5e7eb"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": "#cbd5e1", "axes.linewidth": 0.8,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "savefig.dpi": 150, "savefig.bbox": "tight",
})


def _bars_labels(ax, bars, fmt="{:.0f}", dy=0.01, color=INK):
    top = max(b.get_height() for b in bars) or 1
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + top * dy,
                fmt.format(b.get_height()), ha="center", va="bottom",
                fontsize=9, color=color, fontweight="bold")


# ---- Figure 1: behavioral fidelity (VMT/VHT, identical demand) -------------
fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
for ax, metric, title in zip(axes, ("vmt", "vht"), ("VMT (vehicle-miles)", "VHT (vehicle-hours)")):
    regions, osm_v, ovr_v, diffs = [], [], [], []
    for r in ("tempe", "chicago"):
        b = DATA["regions"][r]["behavior"]
        regions.append(r.capitalize())
        osm_v.append(b[f"osm_{metric}"]); ovr_v.append(b[f"ovr_{metric}"])
        diffs.append(b[f"{metric}_diff_pct"])
    x = range(len(regions))
    b1 = ax.bar([i - 0.19 for i in x], osm_v, 0.36, label="osm2gmns", color=OSM)
    b2 = ax.bar([i + 0.19 for i in x], ovr_v, 0.36, label="overture2gmns", color=OVR)
    ax.set_xticks(list(x)); ax.set_xticklabels(regions)
    ax.set_title(title)
    ax.yaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    for i, d in enumerate(diffs):
        ax.text(i, max(osm_v[i], ovr_v[i]) * 1.06, f"{d:+.1f}%",
                ha="center", fontsize=10, color=PASS if abs(d) < 3 else WARN,
                fontweight="bold")
    ax.set_ylim(0, max(max(osm_v), max(ovr_v)) * 1.2)
    ax.ticklabel_format(axis="y", style="plain")
axes[0].legend(loc="upper left", frameon=False, fontsize=10)
fig.suptitle("Behavioral fidelity: identical demand, near-identical assignment",
             fontsize=14, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(FIG / "fig1_behavioral_fidelity.png"); plt.close(fig)

# ---- Figure 2: semantic advantage (tokens) ---------------------------------
tok = DATA["token_semantics_tempe"]
fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), gridspec_kw={"width_ratios": [1.4, 1]})
# junctions + ramps
cats = ["merge\njunctions", "diverge\njunctions", "ramp\nlinks"]
osm_vals = [tok["osm"]["junctions"].get("MERGE", 0),
            tok["osm"]["junctions"].get("DIVERGE", 0), tok["osm"]["ramp_links"]]
ovr_vals = [tok["ovr"]["junctions"].get("MERGE", 0),
            tok["ovr"]["junctions"].get("DIVERGE", 0), tok["ovr"]["ramp_links"]]
x = range(len(cats))
axes[0].bar([i - 0.19 for i in x], osm_vals, 0.36, label="osm2gmns", color=OSM)
axes[0].bar([i + 0.19 for i in x], ovr_vals, 0.36, label="overture2gmns", color=OVR)
axes[0].set_xticks(list(x)); axes[0].set_xticklabels(cats)
axes[0].set_title("Freeway structure recovered (Tempe)")
axes[0].yaxis.grid(True, color=GRID); axes[0].set_axisbelow(True)
axes[0].legend(frameon=False, fontsize=10)
# the punchline: system interchanges
si = [tok["osm"]["system_interchanges"], tok["ovr"]["system_interchanges"]]
bars = axes[1].bar(["osm2gmns", "overture2gmns"], si, color=[OSM, OVR], width=0.55)
axes[1].set_title("System interchanges detected")
axes[1].set_ylim(0, max(si) + 1.2)
axes[1].yaxis.grid(True, color=GRID); axes[1].set_axisbelow(True)
for b, v in zip(bars, si):
    axes[1].text(b.get_x() + b.get_width() / 2, v + 0.08, str(v),
                 ha="center", va="bottom", fontsize=12, fontweight="bold", color=INK)
axes[1].annotate("ramps lost to\nfacility_type collapse", xy=(0, 0.05),
                 xytext=(0, 1.15), ha="center", fontsize=9, color=WARN, style="italic",
                 arrowprops=dict(arrowstyle="->", color=WARN, lw=1))
fig.suptitle("Semantic advantage: Overture preserves ramp topology OSM conversion loses",
             fontsize=13.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(FIG / "fig2_semantic_advantage.png"); plt.close(fig)

# ---- Figure 3: agency model -> Overture match rates (heat-ish grouped) ------
fig, ax = plt.subplots(figsize=(10, 4.4))
models = ["arc_atlanta", "trm_triangle", "nvta"]
labels = {"arc_atlanta": "ARC Atlanta", "trm_triangle": "TRMG2", "nvta": "NVTA"}
overall = [DATA["regions"][m]["mapmatch_model_to_overture"]["overall"] * 100 for m in models]
bars = ax.barh([labels[m] for m in models][::-1], overall[::-1], color=OVR, height=0.5)
for i, v in enumerate(overall[::-1]):
    ax.text(v - 3, i, f"{v:.0f}%", va="center", ha="right", color="white", fontweight="bold")
ax.axvline(100, color=PASS, lw=1.2, ls="--")
ax.set_xlim(0, 108); ax.set_xlabel("agency model links found in the Overture network (%)")
ax.set_title("External validation: agency-coded facilities present in Overture")
ax.xaxis.grid(True, color=GRID); ax.set_axisbelow(True)
ax.text(101, 2.35, "100%", color=PASS, fontsize=9, fontweight="bold")
fig.tight_layout()
fig.savefig(FIG / "fig3_agency_validation.png"); plt.close(fig)

# ---- Figure 4: geometric agreement + connectivity --------------------------
fig, axes = plt.subplots(1, 2, figsize=(10, 4.0))
regions = ["tempe", "chicago"]
corr = [DATA["regions"][r]["structure"]["grid_corr_common"] for r in regions]
cov = [DATA["regions"][r]["structure"]["coverage_jaccard"] for r in regions]
x = range(len(regions))
axes[0].bar([i - 0.19 for i in x], corr, 0.36, color=OVR, label="length correlation")
axes[0].bar([i + 0.19 for i in x], cov, 0.36, color="#38bdf8", label="coverage Jaccard")
axes[0].set_xticks(list(x)); axes[0].set_xticklabels([r.capitalize() for r in regions])
axes[0].set_ylim(0, 1.05); axes[0].axhline(0.9, color=PASS, ls="--", lw=1)
axes[0].set_title("Geometric agreement with osm2gmns")
axes[0].yaxis.grid(True, color=GRID); axes[0].set_axisbelow(True)
axes[0].legend(frameon=False, fontsize=9, loc="lower right")
for i, c in enumerate(corr):
    axes[0].text(i - 0.19, c + 0.02, f"{c:.2f}", ha="center", fontsize=9, fontweight="bold")
# connectivity
osm_c = [DATA["regions"][r]["structure"]["osm_weak_components"] for r in regions]
ovr_c = [DATA["regions"][r]["structure"]["ovr_weak_components"] for r in regions]
axes[1].bar([i - 0.19 for i in x], osm_c, 0.36, color=OSM, label="osm2gmns")
axes[1].bar([i + 0.19 for i in x], ovr_c, 0.36, color=OVR, label="overture2gmns")
axes[1].set_xticks(list(x)); axes[1].set_xticklabels([r.capitalize() for r in regions])
axes[1].set_title("Disconnected components (fewer is better)")
axes[1].yaxis.grid(True, color=GRID); axes[1].set_axisbelow(True)
axes[1].legend(frameon=False, fontsize=9)
for i in x:
    axes[1].text(i - 0.19, osm_c[i] + 1, str(osm_c[i]), ha="center", fontsize=9)
    axes[1].text(i + 0.19, ovr_c[i] + 1, str(ovr_c[i]), ha="center", fontsize=9, fontweight="bold")
fig.suptitle("Geometry and topology: same streets, better connected",
             fontsize=13.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(FIG / "fig4_geometry_topology.png"); plt.close(fig)

# ---- copy the two network maps + token map into figures/ -------------------
for src, dst in ((BENCH / "tempe" / "side_by_side.png", "map_tempe_side_by_side.png"),
                 (BENCH / "chicago" / "side_by_side.png", "map_chicago_side_by_side.png"),
                 (BENCH / "tempe" / "tokens" / "token_map_tempe_overture.png", "map_tempe_tokens.png")):
    if src.exists():
        shutil.copy(src, FIG / dst)

print(f"wrote figures to {FIG}:")
for p in sorted(FIG.glob("*.png")):
    print(f"  {p.name}  ({p.stat().st_size // 1024} KB)")
