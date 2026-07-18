# crossmap — one-to-many corridor inventory & cross-map QA/QC

Compare road networks **along a shared corridor**, not link-to-link. Map one reference corridor onto
several GMNS networks, project every matched link onto a common milepost ruler `s ∈ [0, L]`, and
compare attributes as **functions of corridor position** — `lanes(s)`, `speed(s)`, `capacity(s)`,
`class(s)`. This dissolves the segmentation mismatch (one link in map A = five links in map B) and
exposes real disagreements, with an evidence-based reasoning layer and a self-contained dashboard.

This build compares two **open** networks:

| source | built by | notes |
|---|---|---|
| **OSM** | `osm2gmns` (e.g. from a state `.pbf`) | offline, repeatable |
| **Overture** | `overture2gmns` | carries attribute **provenance** (`lanes_source`, `speed_source`: surveyed vs `inferred_class_default`) |

## Why it's interesting

Overture's per-segment attributes are often **class-default inferences**, not surveyed values — and
it says so in `*_source`. The comparison feeds that provenance into the reasoning: where Overture's
lanes disagree with OSM *and* Overture marks them inferred, the issue is flagged as a **provenance
artifact** (`LANE_PROVENANCE`), not a true deficit. On the I-10 EB example, Overture codes 2 lanes at
MP 0–2 where OSM's surveyed tags say more — caught automatically.

## Run

```bash
# 1) build each source's GMNS (once):
#    OSM      -> osm2gmns from a .pbf   -> osm_az/link.csv
#    Overture -> overture2gmns          -> overture/link.csv
# 2) provide a corridor definition (TMC / LRS / GIS polyline) with mileposts.
# 3) configure paths (env vars) and run:

export CORRIDOR2GMNS_DIR=/path/to/corridor2gmns          # supplies the geometric matcher
export CROSSMAP_OSM_LINK=osm_az/link.csv
export CROSSMAP_OVERTURE_LINK=overture/link.csv
export CROSSMAP_CORRIDOR_TMC=corridor/TMC_Identification.csv

python build_corridor_inventory.py      # -> reports/<CORRIDOR>/*.csv + dashboard_data.json
python build_dashboard.py               # -> reports/<CORRIDOR>/<CORRIDOR>_dashboard.html
```

The matcher (`corridor_from_tmc` + `match_corridor`, geometric, per-link milepost) comes from
[`corridor2gmns`](https://github.com/asu-trans-ai-lab); the corridor definition is yours to supply
(TMC, an LRS/AllRoads route, or a GIS polyline).

## Outputs — `reports/<CORRIDOR>/`

- `matched_segments.csv` — each source's links with milepost + lanes/speed/capacity/class/name (segmentation preserved)
- `attribute_differences.csv` — per-milepost-bin attributes for every source + spread
- `topology_issues.csv` — one-to-many / many-to-one segmentation, coverage gaps
- `review_log.csv` — issue lifecycle: Detected → Reviewed → Verified → Assigned → Corrected → Revalidated
- `<CORRIDOR>_dashboard.html` — **self-contained, offline** (no tiles, no CDN): an inline-SVG map
  whose basemap is the road network itself, each source as its own offset colored strand (nodes =
  dots), layer toggles, + synchronized linear corridor strips (bar thickness = lanes, hatch =
  inferred) + reasoned issue cards.

A ready-to-open example is in [`example/I10_EB/`](example/I10_EB/) — open the `.html` directly in a
browser (no server, no internet).

## Reasoning categories (conservative, evidence-based)

`LANE_PROVENANCE` (an inferred class-default outlier, not a real deficit) · `LANE_UNDERCODE` ·
`LANE_SEGMENTATION` (per-carriageway/auxiliary split) · `LANE_MISMATCH` · `SPEED_MISMATCH` ·
`CAP_SENTINEL`. Every issue keeps the observed values **and** the likely explanation with evidence
attached — report-only: no source network is modified.

## Notes

- The milepost ruler is only as good as the corridor definition you supply. A TMC chain gives
  cumulative TMC distance; an agency LRS gives official mileposts — swap freely.
- Private agency travel-demand models can be added as extra sources locally (same adapter shape);
  they are intentionally **not** part of this open OSM-vs-Overture build.
