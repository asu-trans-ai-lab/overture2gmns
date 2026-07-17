"""Behavioral (VMT/VHT) comparison of two GMNS networks over one region.

Generalizes step5's identical-demand TAPLite comparison to any two GMNS
folders — used here to add an agency-model MPO check: the overture2gmns
Triangle network vs the agency TRMG2 network, under byte-identical synthetic
demand between physically identical zone centroids.

This is a RELATIVE routing-consistency check, not a validated forecast:
demand is synthetic (no observed OD). For an agency-vs-Overture pair the two
networks additionally differ in coded speed / capacity / facility type (not
just topology), so VMT (path-length driven) is the interpretable signal and
VHT is only indicative. See CONVERSION_QUALITY_REPORT.md methodology.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from step5_taplite import (
    _read_csv, build_scenario, run_kernel, summarize_assignment,
    snap_centers, zone_centers,
)


def run(label_a: str, folder_a: Path, tool_a: str,
        label_b: str, folder_b: Path, tool_b: str,
        out: Path, extent_from: str = "b") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    folders = {label_a: (Path(folder_a), tool_a), label_b: (Path(folder_b), tool_b)}

    # Shared zone centers over the SMALLER extent (default: network B, the
    # Overture subarea) so both networks contain every zone.
    extent_label = label_b if extent_from == "b" else label_a
    centers = zone_centers(_read_csv(folders[extent_label][0] / "node.csv"))
    snapped = {lab: snap_centers(centers, f) for lab, (f, _) in folders.items()}
    common = sorted(set.intersection(*(set(m) for m in snapped.values())))
    zone_maps = {lab: {snapped[lab][idx]: rank + 1 for rank, idx in enumerate(common)}
                 for lab in folders}
    print(f"[step10] shared zones: {len(common)} of {len(centers)} grid centers")

    results = {}
    for lab, (folder, tool) in folders.items():
        scenario = out / f"tap_{lab}"
        info = build_scenario(folder, scenario, tool, zone_maps[lab])
        run_dir = scenario / "normalized" if (scenario / "normalized").exists() else scenario
        run_kernel(scenario, timeout=1800)
        summary = summarize_assignment(scenario)
        results[lab] = {**info, **summary}
        print(f"[step10] {lab}: links={info['links']} vmt={summary.get('vmt')} "
              f"vht={summary.get('vht')}")

    a, b = results[label_a], results[label_b]
    if a.get("vmt") and b.get("vmt"):
        results["_diff"] = {
            "vmt_diff_pct": round(100 * (b["vmt"] - a["vmt"]) / a["vmt"], 1),
            "vht_diff_pct": round(100 * (b["vht"] - a["vht"]) / a["vht"], 1)
            if a.get("vht") else None,
            "reference": label_a, "candidate": label_b, "zones": len(common),
        }
    (out / "behavioral_pair_report.json").write_text(json.dumps(results, indent=2))
    print(f"[step10] wrote {out / 'behavioral_pair_report.json'}")
    if "_diff" in results:
        print(f"  ΔVMT {results['_diff']['vmt_diff_pct']:+}%  "
              f"ΔVHT {results['_diff']['vht_diff_pct']:+}%")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--a-label", required=True)
    parser.add_argument("--a-folder", required=True, type=Path)
    parser.add_argument("--a-tool", default="agency")
    parser.add_argument("--b-label", required=True)
    parser.add_argument("--b-folder", required=True, type=Path)
    parser.add_argument("--b-tool", default="overture2gmns")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    run(args.a_label, args.a_folder, args.a_tool,
        args.b_label, args.b_folder, args.b_tool, args.out)
