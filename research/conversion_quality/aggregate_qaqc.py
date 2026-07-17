"""Aggregate all QA/QC artifacts into one conversion-quality dataset.

Reads the per-region reports produced by bench/ steps 3-9 and emits:
  - evidence/*.json  : machine-readable copies (self-contained, versioned)
  - qaqc_dataset.json: one consolidated dataset for the narrative report

Restricted-data policy: NVTA network files never leave disk; only aggregate
statistics (counts, match rates, verdicts) are copied here.

Run:  python research/conversion_quality/aggregate_qaqc.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent.parent / "bench" / "out"
EVIDENCE = HERE / "evidence"
EVIDENCE.mkdir(parents=True, exist_ok=True)


def load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def copy_evidence(src: Path, name: str):
    if src.exists():
        shutil.copy(src, EVIDENCE / name)


def gmns_ready_verdict(txt_path: Path) -> dict:
    """Parse the two-line summary out of a gmns_ready_report.txt."""
    if not txt_path.exists():
        return {}
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for tool in ("quick_check", "validate_network"):
        if f"gmns_ready.{tool}" in text:
            seg = text.split(f"gmns_ready.{tool}", 1)[1]
            errors = None
            for line in seg.splitlines():
                s = line.strip()
                if s.startswith("Errors:"):
                    errors = int(s.split(":")[1].strip().split()[0]); break
                if "Errors:" in s and "Warnings" not in s:
                    try: errors = int(s.split("Errors:")[1].split()[0])
                    except Exception: pass
                    break
            out[tool] = {"errors": errors}
    return out


dataset: dict = {"generated_by": "aggregate_qaqc.py", "regions": {}}

# ---- converter-vs-converter regions (Tempe, Chicago) ----------------------
for region in ("tempe", "chicago"):
    comp = load(BENCH / region / "comparison_report.json")
    tap = load(BENCH / region / "taplite_report.json")
    if comp:
        copy_evidence(BENCH / region / "comparison_report.json", f"{region}_comparison.json")
    if tap:
        copy_evidence(BENCH / region / "taplite_report.json", f"{region}_taplite.json")
    gr = gmns_ready_verdict(BENCH / region / "overture2gmns" / "gmns_ready_report.txt")

    entry = {"kind": "converter_vs_converter"}
    if comp:
        osm, ovr, grid = comp["osm2gmns"], comp["overture2gmns"], comp["grid"]
        entry["structure"] = {
            "osm_nodes": osm["nodes"], "ovr_nodes": ovr["nodes"],
            "osm_links": osm["links"], "ovr_links": ovr["links"],
            "osm_length_mi": osm["total_length_mi"], "ovr_length_mi": ovr["total_length_mi"],
            "grid_corr_common": grid.get("correlation_common"),
            "grid_corr_union": grid.get("correlation_union"),
            "coverage_jaccard": grid.get("coverage_jaccard"),
            "osm_weak_components": osm["weak_components"],
            "ovr_weak_components": ovr["weak_components"],
            "length_by_class": {"osm": osm["length_by_class_mi"], "ovr": ovr["length_by_class_mi"]},
            "speed_by_class": {"osm": osm["mean_speed_mph_by_class"],
                               "ovr": ovr["mean_speed_mph_by_class"]},
        }
    if tap:
        o, v = tap.get("osm2gmns", {}), tap.get("overture2gmns", {})
        if o.get("vmt") and v.get("vmt"):
            entry["behavior"] = {
                "osm_vmt": o["vmt"], "ovr_vmt": v["vmt"],
                "osm_vht": o["vht"], "ovr_vht": v["vht"],
                "vmt_diff_pct": round(100 * (v["vmt"] - o["vmt"]) / o["vmt"], 1),
                "vht_diff_pct": round(100 * (v["vht"] - o["vht"]) / o["vht"], 1),
                "osm_qa_ok": o.get("qa_ok"), "ovr_qa_ok": v.get("qa_ok"),
            }
    entry["gmns_ready"] = gr
    for direction in ("ovr_to_osm", "osm_to_ovr"):
        mm = load(BENCH / region / f"mapmatch_{direction}" / "mapmatch_report.json")
        if mm:
            entry.setdefault("mapmatch", {})[direction] = {
                "trace_match_rate": mm["trace_match_rate"], "traces": mm["traces"]}
    dataset["regions"][region] = entry

# ---- token semantics (Tempe) ----------------------------------------------
tok_ovr = load(BENCH / "tempe" / "tokens" / "tokens_tempe_overture.json")
tok_osm = load(BENCH / "tempe" / "tokens" / "tokens_tempe_osm.json")
if tok_ovr and tok_osm:
    for src, name in ((BENCH / "tempe" / "tokens" / "tokens_tempe_overture.json", "tempe_tokens_overture.json"),
                      (BENCH / "tempe" / "tokens" / "tokens_tempe_osm.json", "tempe_tokens_osm.json")):
        copy_evidence(src, name)
    def systems(payload):
        return sum(c for k, c in payload["histogram"]["interchanges"].items()
                   if k.startswith("SYSTEM"))
    dataset["token_semantics_tempe"] = {
        "osm": {"junctions": tok_osm["histogram"]["junctions"],
                "system_interchanges": systems(tok_osm),
                "ramp_links": tok_osm["ramp_links"], "osm_ramp_heuristic": tok_osm["osm_ramp_heuristic"]},
        "ovr": {"junctions": tok_ovr["histogram"]["junctions"],
                "system_interchanges": systems(tok_ovr),
                "ramp_links": tok_ovr["ramp_links"]},
    }

# ---- MPO validation (ARC, TRM, NVTA) --------------------------------------
for mpo in ("arc_atlanta", "trm_triangle", "nvta"):
    struct = load(BENCH / "mpo" / mpo / "structure_summary.json")
    qa = load(BENCH / "mpo" / mpo / "dtalite_qa.json")
    if struct:
        copy_evidence(BENCH / "mpo" / mpo / "structure_summary.json", f"{mpo}_structure.json")
    if qa:
        copy_evidence(BENCH / "mpo" / mpo / "dtalite_qa.json", f"{mpo}_dtalite_qa.json")
    fwd = load(BENCH / "mpo" / mpo / "mapmatch_mpo_to_ovr" / "mapmatch_report.json")
    rev = load(BENCH / "mpo" / mpo / "mapmatch_ovr_to_mpo" / "mapmatch_report.json")
    entry = {"kind": "mpo_validation"}
    if struct:
        entry["structure"] = {k: struct[k] for k in (
            "label", "nodes", "links", "zones", "centroid_connectors",
            "connector_share_of_links", "total_length_mi", "units") if k in struct}
    if qa:
        entry["dtalite_qa_ok"] = qa.get("ok")
    entry["gmns_ready"] = gmns_ready_verdict(BENCH / "mpo" / mpo / "gmns_ready_report.txt")
    if fwd:
        entry["mapmatch_model_to_overture"] = {
            "overall": fwd["trace_match_rate"],
            "per_class": {k: v["trace_match_rate"] for k, v in fwd["per_class"].items()}}
    if rev:
        entry["mapmatch_overture_to_model"] = {"overall": rev["trace_match_rate"]}
    dataset["regions"][mpo] = entry

(HERE / "qaqc_dataset.json").write_text(json.dumps(dataset, indent=2))
n_ev = len(list(EVIDENCE.glob("*.json")))
print(f"aggregated {len(dataset['regions'])} regions; {n_ev} evidence files -> {EVIDENCE}")
for region, e in dataset["regions"].items():
    tag = e["kind"]
    if "behavior" in e:
        print(f"  {region}: {tag}, VMT {e['behavior']['vmt_diff_pct']:+}% "
              f"corr {e['structure']['grid_corr_common']}")
    elif tag == "mpo_validation":
        f = e.get("mapmatch_model_to_overture", {}).get("overall", "-")
        print(f"  {region}: {tag}, model->ovr {f}, qa_ok {e.get('dtalite_qa_ok')}")
