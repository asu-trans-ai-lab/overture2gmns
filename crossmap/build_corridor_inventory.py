"""Cross-Map Network QA/QC — corridor inventory spine (Stage 1).

One reference corridor -> matched to many networks -> attributes compared along a shared milepost
ruler s in [0,L] -> reasoned QA/QC issues. Report-only: no source network is modified.

Reuses corridor2gmns (corridor_from_tmc + match_corridor, Engine 2 geometric, per-link milepost).
Emits reports/<CORRIDOR>/: matched_segments.csv, attribute_differences.csv, topology_issues.csv,
review_log.csv  (the dashboard, Stage 2, renders these).

The reference corridor (milepost ruler) is user-supplied — a TMC/LRS/GIS corridor definition; the
example uses I-10 EB. Public-data comparison: OSM (osm2gmns) vs Overture (overture2gmns).
"""
import csv
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# --- configuration (edit here or set env vars) --------------------------------------------------
# corridor2gmns provides the matcher (corridor_from_tmc + match_corridor, Engine 2 geometric).
CORRIDOR2GMNS_DIR = os.environ.get("CORRIDOR2GMNS_DIR", "")
# GMNS link.csv per source: OSM = osm2gmns output (e.g. built from a state .pbf); Overture =
# overture2gmns output. The corridor definition (TMC/LRS/GIS) is yours to provide.
OSM_LINK = os.environ.get("CROSSMAP_OSM_LINK", os.path.join(BASE, "osm_az", "link.csv"))
OVERTURE_LINK = os.environ.get("CROSSMAP_OVERTURE_LINK", os.path.join(BASE, "overture", "link.csv"))
CORRIDOR_TMC = os.environ.get("CROSSMAP_CORRIDOR_TMC", os.path.join(BASE, "corridor", "TMC_Identification.csv"))
# ------------------------------------------------------------------------------------------------

if CORRIDOR2GMNS_DIR:
    sys.path.insert(0, CORRIDOR2GMNS_DIR)
import pandas as pd  # noqa: E402
from corridor2gmns.evidence.corridor_from_tmc import corridor_from_tmc       # noqa: E402
from corridor2gmns.matching.mapmatch_corridor_to_gmns import match_corridor  # noqa: E402

# --- corridor definitions (reference spine = a TMC/LRS/GIS milepost ruler you supply) ---
CORRIDORS = {
    "I10_EB": {"tmc": CORRIDOR_TMC, "road": "I-10", "direction": "EASTBOUND",
               "name": "I-10 Eastbound (Phoenix)"},
}

# --- attribute sources: name -> (link_csv, colmap, gp_types) ---
# colmap keys: lanes, speed(mph), capacity, fclass(raw facility code/tag), name
SENTINEL_CAP = 90000.0
SOURCES = {
    # OSM: osm2gmns GMNS (e.g. built offline from a state .pbf), clipped per corridor.
    # osm2gmns free_speed is km/h -> convert to mph (a documented osm2gmns 1.0.x unit gotcha).
    "OSM": {"link": OSM_LINK, "gp": {"1", "2"}, "clip": True, "speed_kph": True,
            "cols": {"lanes": "lanes", "speed": "free_speed", "capacity": "capacity",
                     "fclass": "facility_type", "name": "name"}},
    # Overture (overture2gmns): vdf_free_speed_mph already in mph; carries provenance
    # (lanes_source/speed_source: surveyed vs inferred_class_default).
    "Overture": {"link": OVERTURE_LINK, "gp": {"motorway", "trunk", "motorway_link"}, "clip": True,
                 "cols": {"lanes": "lanes", "speed": "vdf_free_speed_mph", "capacity": "capacity",
                          "fclass": "facility_type", "name": "name"},
                 "prov": {"lanes": "lanes_source", "speed": "speed_source", "capacity": "capacity_source"}},
}
BIN_MI = 1.0


def _bbox(ev, pad=0.02):
    s = ev.reference_segments
    return (s[["start_longitude", "end_longitude"]].min().min() - pad,
            s[["start_longitude", "end_longitude"]].max().max() + pad,
            s[["start_latitude", "end_latitude"]].min().min() - pad,
            s[["start_latitude", "end_latitude"]].max().max() + pad)


def _load_clipped(link_csv, bbox):
    """Load a large link.csv, keeping only rows whose first geometry vertex is in bbox."""
    minx, maxx, miny, maxy = bbox
    keep = []
    for ch in pd.read_csv(link_csv, low_memory=False, chunksize=200000):
        g = ch["geometry"].astype(str)
        lon = pd.to_numeric(g.str.extract(r"\(+\s*(-?\d+\.\d+)")[0], errors="coerce")
        lat = pd.to_numeric(g.str.extract(r"\(+\s*-?\d+\.\d+\s+(-?\d+\.\d+)")[0], errors="coerce")
        keep.append(ch[(lon >= minx) & (lon <= maxx) & (lat >= miny) & (lat <= maxy)])
    return pd.concat(keep, ignore_index=True)


def _num(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _wkt_coords(wkt, step=1):
    """Parse a LINESTRING WKT -> [[lon,lat],...] (rounded, optionally decimated)."""
    pts = re.findall(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", str(wkt))
    c = [[round(float(x), 5), round(float(y), 5)] for x, y in pts]
    return c[::step] + ([c[-1]] if step > 1 and len(c) > 1 else []) if c else []


def match_source(ev, src, bbox):
    """Match the corridor to one source; return per-link matched segments with attributes + mp."""
    if src.get("clip"):
        base = _load_clipped(src["link"], bbox)
    else:
        base = pd.read_csv(src["link"], low_memory=False)
    if "link_type" not in base.columns and "facility_type" in base.columns:
        base["link_type"] = base["facility_type"].astype(str)
    base["link_type"] = base["link_type"].astype(str)
    sc = match_corridor(ev, base, src["gp"])
    if sc is None or len(sc) == 0:
        return pd.DataFrame()
    c = src["cols"]
    prov = src.get("prov") or {}
    attr = base.set_index("link_id")

    def _inferred(a, col):
        """True if a provenance column marks the value as an inferred / class-default guess."""
        if not col or col not in a.index:
            return False
        v = str(a.get(col)).lower()
        return ("inferred" in v) or ("default" in v)

    rows = []
    for r in sc.itertuples(index=False):
        d = r._asdict()
        lid = d.get("link_id")
        if lid not in attr.index:
            continue
        a = attr.loc[lid]
        a = a.iloc[0] if hasattr(a, "ndim") and getattr(a, "ndim", 1) > 1 else a
        cap = _num(a.get(c["capacity"])) if c["capacity"] else None
        spd = _num(a.get(c["speed"])) if c["speed"] else None
        if spd is not None and src.get("speed_kph"):
            spd = round(spd * 0.621371, 1)      # km/h -> mph
        rows.append({
            "link_id": lid, "mp_begin": _num(d.get("mp_begin")), "mp_end": _num(d.get("mp_end")),
            "lanes": _num(a.get(c["lanes"])) if c["lanes"] else None,
            "speed": spd,
            "capacity": cap, "cap_sentinel": bool(cap is not None and cap >= SENTINEL_CAP),
            "fclass": str(a.get(c["fclass"])) if c["fclass"] else "",
            "name": str(a.get(c["name"])) if c["name"] and c["name"] in a.index else "",
            "lanes_inferred": _inferred(a, prov.get("lanes")),
            "speed_inferred": _inferred(a, prov.get("speed")),
            "match_dist_m": round(_num(d.get("match_dist_m")) or 0, 1),
            "coords": _wkt_coords(a.get("geometry"), step=2),
        })
    df = pd.DataFrame(rows).dropna(subset=["mp_begin"]).sort_values("mp_begin").reset_index(drop=True)
    df["seg_len_mp"] = (df["mp_end"] - df["mp_begin"]).abs().round(3)
    df["confidence"] = (1 - (df["match_dist_m"].clip(0, 300) / 300)).round(3)
    return df


def bin_profile(df, bin_mi=BIN_MI):
    """Per milepost bin: median lanes/speed/capacity, link count, any sentinel, dominant class."""
    if len(df) == 0:
        return {}
    out = {}
    d = df.copy()
    d["mp_bin"] = (d["mp_begin"] / bin_mi).round() * bin_mi
    for mp, g in d.groupby("mp_bin"):
        out[float(mp)] = {
            "lanes": g["lanes"].median(), "speed": g["speed"].median(),
            "capacity": g["capacity"].median(), "n_links": int(len(g)),
            "any_sentinel": bool(g["cap_sentinel"].any()),
            "lanes_inferred": bool(g["lanes_inferred"].mean() >= 0.5) if "lanes_inferred" in g else False,
            "fclass": g["fclass"].mode().iloc[0] if len(g["fclass"].mode()) else "",
        }
    return out


# ---- reasoning: conservative, evidence-based (NetQC taxonomy) ----
def reason_lane(mp, vals, counts, inferred):
    """vals: {src: lanes}; counts: {src: n_links}; inferred: {src: lanes-are-class-default}.
    Return (issue_type, reasoning, conf)."""
    present = {s: v for s, v in vals.items() if v is not None}
    if len(present) < 2:
        return None
    lo_src = min(present, key=present.get)
    hi_src = max(present, key=present.get)
    diff = present[hi_src] - present[lo_src]
    if diff < 1:
        return None
    ev = ", ".join(f"{s}={present[s]:.0f}L" for s in present)
    inf = [s for s in present if inferred.get(s)]
    inf_note = f" [{', '.join(inf)} lanes are inferred class-defaults, not surveyed]" if inf else ""
    # provenance first: if the low outlier is an inferred default, the 'deficit' is a data artifact
    if inferred.get(lo_src):
        others = [s for s in present if s != lo_src]
        return ("LANE_PROVENANCE",
                f"{lo_src} codes {present[lo_src]:.0f} lanes, but that value is an inferred "
                f"class-default (not surveyed); {', '.join(others)} code higher. Treat {lo_src} as "
                f"low-quality evidence here — a provenance artifact, not a true lane deficit. ({ev})", "high")
    # if the low source has many small links here, it may be splitting lanes into parallel links
    if counts.get(lo_src, 1) >= 3 and diff >= 2:
        return ("LANE_SEGMENTATION",
                f"{lo_src} codes {counts[lo_src]} links in this bin — the low lane count may be a "
                f"per-carriageway/auxiliary split rather than a true deficit. Verify segmentation. ({ev}){inf_note}", "medium")
    # two sources agree high, one low -> likely under-coding in the low one
    highs = [s for s in present if present[s] >= present[hi_src] - 0.5]
    if len(highs) >= 2 and lo_src not in highs:
        return ("LANE_UNDERCODE",
                f"{', '.join(highs)} agree at ~{present[hi_src]:.0f} lanes; {lo_src} codes "
                f"{present[lo_src]:.0f}. Likely outdated/under-coded lane inventory in {lo_src}. ({ev}){inf_note}", "high")
    return ("LANE_MISMATCH", f"Lane counts disagree by {diff:.0f} along this bin — review. ({ev}){inf_note}", "medium")


def reason_speed(mp, vals):
    present = {s: v for s, v in vals.items() if v is not None}
    if len(present) < 2:
        return None
    d = max(present.values()) - min(present.values())
    if d <= 15:
        return None
    ev = ", ".join(f"{s}={present[s]:.0f}" for s in present)
    return ("SPEED_MISMATCH",
            f"Free-flow speed differs by {d:.0f} mph — often free-flow vs posted, or a sentinel. "
            f"Informational unless it drives capacity. ({ev})", "low")


def reason_capacity(mp, sentinels):
    hit = [s for s, on in sentinels.items() if on]
    if not hit:
        return None
    return ("CAP_SENTINEL",
            f"Capacity is an uncoded sentinel (>= {SENTINEL_CAP:.0f}) in {', '.join(hit)} — no real "
            f"capacity here; declare the convention at the source before assignment use.", "high")


def build(corridor_id):
    cfg = CORRIDORS[corridor_id]
    outdir = os.path.join(BASE, "reports", corridor_id)
    os.makedirs(outdir, exist_ok=True)
    ev = corridor_from_tmc(cfg["tmc"], road=cfg["road"], direction=cfg["direction"])
    bbox = _bbox(ev)
    print(f"=== {cfg['name']} === reference MP extent from evidence; matching {len(SOURCES)} sources")

    seg_rows, profiles, extents = [], {}, {}
    for name, src in SOURCES.items():
        df = match_source(ev, src, bbox)
        profiles[name] = bin_profile(df)
        if len(df):
            extents[name] = (df["mp_begin"].min(), df["mp_end"].max())
            for r in df.itertuples(index=False):
                seg_rows.append({"source": name, **r._asdict()})
            print(f"  {name:6}: {len(df):4} links, MP {extents[name][0]:.1f}..{extents[name][1]:.1f}, "
                  f"lanes med={df['lanes'].median():.0f}, speed med={df['speed'].median():.0f}"
                  + (f"  [PARTIAL: {src['partial']}]" if src.get("partial") else ""))
        else:
            print(f"  {name:6}: NO MATCH")

    # matched_segments.csv
    seg_cols = ["source", "link_id", "mp_begin", "mp_end", "seg_len_mp", "lanes", "speed",
                "capacity", "cap_sentinel", "fclass", "name", "match_dist_m", "confidence"]
    with open(os.path.join(outdir, "matched_segments.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=seg_cols, extrasaction="ignore"); w.writeheader()
        w.writerows(seg_rows)

    # attribute_differences.csv (per milepost bin) + reasoned issues
    all_bins = sorted({mp for p in profiles.values() for mp in p})
    names = list(SOURCES)
    diff_rows, issues = [], []
    for mp in all_bins:
        lanes = {n: profiles[n].get(mp, {}).get("lanes") for n in names}
        speed = {n: profiles[n].get(mp, {}).get("speed") for n in names}
        counts = {n: profiles[n].get(mp, {}).get("n_links", 0) for n in names}
        sents = {n: profiles[n].get(mp, {}).get("any_sentinel", False) for n in names}
        inferred = {n: profiles[n].get(mp, {}).get("lanes_inferred", False) for n in names}
        row = {"mp_bin": mp}
        for n in names:
            row[f"lanes_{n}"] = round(lanes[n], 1) if lanes[n] is not None else None
            row[f"speed_{n}"] = round(speed[n], 1) if speed[n] is not None else None
            row[f"nlinks_{n}"] = counts[n]
        lp = [v for v in lanes.values() if v is not None]
        row["lane_spread"] = round(max(lp) - min(lp), 1) if len(lp) > 1 else 0
        diff_rows.append(row)
        for res in [reason_lane(mp, lanes, counts, inferred), reason_speed(mp, speed), reason_capacity(mp, sents)]:
            if res:
                issues.append({"mp_bin": mp, "issue_type": res[0], "reasoning": res[1],
                               "confidence": res[2],
                               "evidence": "; ".join(f"{n}:{lanes[n]}" for n in names if lanes[n] is not None)})
    diff_cols = ["mp_bin"] + [f"{a}_{n}" for n in names for a in ("lanes", "speed", "nlinks")] + ["lane_spread"]
    with open(os.path.join(outdir, "attribute_differences.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=diff_cols, extrasaction="ignore"); w.writeheader()
        w.writerows(diff_rows)

    # topology_issues.csv: one-to-many (link-count skew) + coverage gaps
    topo = []
    for mp in all_bins:
        counts = {n: profiles[n].get(mp, {}).get("n_links", 0) for n in names}
        present = {n: c for n, c in counts.items() if c > 0}
        if len(present) >= 2 and max(present.values()) >= 3 * max(1, min(present.values())):
            hi = max(present, key=present.get); lo = min(present, key=present.get)
            topo.append({"mp_bin": mp, "type": "ONE_TO_MANY",
                         "detail": f"{hi} has {present[hi]} links where {lo} has {present[lo]} "
                                   f"(segmentation ratio {present[hi]/max(1,present[lo]):.0f}x)",
                         "counts": " ".join(f"{n}={counts[n]}" for n in names)})
        for n in names:
            if counts[n] == 0 and any(counts[m] > 0 for m in names):
                topo.append({"mp_bin": mp, "type": "COVERAGE_GAP",
                             "detail": f"{n} has no matched link in this bin (others do)",
                             "counts": " ".join(f"{m}={counts[m]}" for m in names)})
    with open(os.path.join(outdir, "topology_issues.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["mp_bin", "type", "detail", "counts"]); w.writeheader()
        w.writerows(topo)

    # review_log.csv (issue lifecycle seed): one row per reasoned issue, status=Detected
    with open(os.path.join(outdir, "review_log.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["issue_id", "mp_bin", "issue_type", "confidence", "status", "verdict",
                    "assigned_to", "resolution", "corrected_value", "reviewer", "review_date", "reasoning"])
        for i, it in enumerate(sorted(issues, key=lambda x: x["mp_bin"]), 1):
            w.writerow([f"{corridor_id}-{i:03d}", it["mp_bin"], it["issue_type"], it["confidence"],
                        "Detected", "", "", "", "", "", "", it["reasoning"]])

    # dashboard_data.json — reference polyline + per-source geometry + issues (Stage 2 renders this)
    refseg = ev.reference_segments.sort_values("mp_begin")
    ref_line = [[round(r.start_longitude, 5), round(r.start_latitude, 5), round(float(r.mp_begin), 3)]
                for r in refseg.itertuples(index=False)]
    last = refseg.iloc[-1]
    ref_line.append([round(last.end_longitude, 5), round(last.end_latitude, 5), round(float(last.mp_end), 3)])
    geom = {n: [] for n in SOURCES}
    for row in seg_rows:
        geom[row["source"]].append({"mp0": round(row["mp_begin"], 2), "mp1": round(row["mp_end"], 2),
                                    "lanes": row["lanes"],
                                    "speed": round(row["speed"], 1) if row["speed"] is not None else None,
                                    "inf": bool(row.get("lanes_inferred")), "c": row["coords"]})
    # offline basemap: nearby major roads from arizona.pbf clip (gray context lines, no tiles)
    context = []
    try:
        ctx = _load_clipped(os.path.join(BASE, "osm_az", "link.csv"), bbox)
        geoms = [_wkt_coords(g, step=3) for g in ctx["geometry"].tolist()]
        geoms = [c for c in geoms if len(c) >= 2]
        if len(geoms) > 3000:                      # cap for a lean, fast SVG
            geoms = geoms[:: max(1, len(geoms) // 3000)]
        context = geoms
    except Exception as e:
        print(f"  (context basemap skipped: {e})")

    dash = {"corridor": cfg["name"], "corridor_id": corridor_id, "context": context,
            "ruler_note": "Milepost ruler = TMC corridor chain (TMC_Identification), cumulative distance "
                          "— not official ADOT LRS (swap in ADOT LRS when available).",
            "sources": list(SOURCES),
            "roles": {"OSM": "osm2gmns · arizona.pbf", "Overture": "overture2gmns"},
            "extents": {n: [round(e[0], 2), round(e[1], 2)] for n, e in extents.items()},
            "partial": {n: SOURCES[n].get("partial") for n in SOURCES if SOURCES[n].get("partial")},
            "reference": ref_line, "geom": geom,
            "issues": [{"mp": it["mp_bin"], "type": it["issue_type"], "conf": it["confidence"],
                        "why": it["reasoning"]} for it in sorted(issues, key=lambda x: x["mp_bin"])],
            "topology": topo, "bin_mi": BIN_MI}
    json.dump(dash, open(os.path.join(outdir, "dashboard_data.json"), "w"), separators=(",", ":"))

    print(f"  issues: {len(issues)} reasoned, {len(topo)} topology  ->  {outdir}")
    it_by = {}
    for it in issues:
        it_by[it["issue_type"]] = it_by.get(it["issue_type"], 0) + 1
    print("  by type:", it_by)
    return outdir


if __name__ == "__main__":
    for cid in (sys.argv[1:] or ["I10_EB"]):
        build(cid)
