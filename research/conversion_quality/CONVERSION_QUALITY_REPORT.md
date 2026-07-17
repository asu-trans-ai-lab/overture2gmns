# Conversion Quality QA/QC Report — overture2gmns

**Scope:** fidelity of the overture2gmns conversion, independent of runtime.
All numbers are aggregated by `aggregate_qaqc.py` from the bench artifacts in
`evidence/` and regenerate with one command. Reproduce:

```bash
python research/conversion_quality/aggregate_qaqc.py   # rebuilds evidence/ + qaqc_dataset.json
```

**Test set:** two converter-vs-converter regions (Tempe AZ, Chicago metro,
osm2gmns as reference) and three agency planning models used as external
ground truth (ARC Atlanta, TRMG2 North Carolina, NVTA Northern Virginia —
NVTA network data is agency-restricted; only aggregate statistics appear here).

**Restricted-data policy:** no NVTA network files are copied into this folder;
`evidence/nvta_*.json` contain counts, verdicts, and match rates only.

---

## 1. Quality dimensions

Conversion quality is assessed on six independent axes, each with its own
evidence. A converter can pass one and fail another (e.g., perfect geometry
with broken directionality), so all six are reported separately.

| # | dimension | question | primary evidence |
|---|---|---|---|
| 1 | GMNS validity | is the output a well-formed GMNS network? | gmns-ready, dtalite_qa |
| 2 | Geometric coverage | are the same streets present, in the same place? | grid length correlation, map-match |
| 3 | Attribute fidelity | are speed/lanes/capacity/class right? | length-by-class, speed-by-class, capacity semantics |
| 4 | Topological integrity | is connectivity and directionality correct? | weak components, one-way audit |
| 5 | Semantic fidelity | are interchanges/ramps/managed lanes preserved? | interchange & ML tokens |
| 6 | Behavioral fidelity | does it route the same under identical demand? | TAPLite VMT/VHT diff |

---

## 2. Headline verdict

overture2gmns output is **GMNS-valid, geometrically faithful, and
behaviorally interchangeable with osm2gmns** at the assignment level, and it
**preserves semantic freeway structure that osm2gmns loses**. The one class
of defects found during development were all in the *pipeline* (format
round-trips, rule-scope handling, capacity units), not the source data, and
all are fixed and regression-tested.

| region | GMNS valid | geom corr (common cells) | VMT diff vs osm | verdict |
|---|---|---:|---:|---|
| Tempe | 0 errors | 0.89 | **-0.5%** | interchangeable |
| Chicago metro | 0 errors | 0.93 | **-0.8%** | interchangeable |

---

## 3. Dimension 1 — GMNS validity

Every converted network passes both gmns-ready checks (quick_check,
validate_network) with **0 errors**, and the dtalite_qa (taplite4mpo) gate
returns ok. This holds for the converter output (Tempe, Chicago) and for all
three agency networks run through the same validators.

| network | gmns-ready quick_check | validate_network | dtalite_qa |
|---|---|---|---|
| Tempe overture2gmns | 0 errors | 0 errors | — |
| Chicago overture2gmns | 0 errors | 0 errors | — |
| ARC Atlanta | 0 errors | 0 errors | ok |
| TRMG2 | 0 errors | 0 errors | ok |
| NVTA | 0 errors | 0 errors | ok |

Warnings remain (centroid grouping, dual-unit hints) but no errors. Bug #4
(unsorted link.csv failing the Level-3 dual-unit check) was fixed by
emitting forward-star-sorted links plus `vdf_length_mi`/`vdf_free_speed_mph`.

## 4. Dimension 2 — geometric coverage

Directed link length aggregated on a ~500 m grid, then correlated between the
osm2gmns and overture2gmns networks:

| region | correlation (common cells) | correlation (union) | coverage Jaccard |
|---|---:|---:|---:|
| Tempe | **0.89** | 0.80 | 0.94 |
| Chicago | **0.93** | 0.80 | 0.86 |

The common-cell correlation isolates conversion agreement; the union
correlation is lower only because the OSM extracts are polygon-clipped while
the Overture pull is a bounding rectangle (extra Overture coverage at bbox
corners). Map-matching confirms directionally: **osm2gmns links match onto
the overture2gmns network at 99.3%** (Tempe) — everything OSM has, Overture
has and places within tolerance.

## 5. Dimension 3 — attribute fidelity

**Speed:** length-weighted mean free speed agrees closely by class; Overture
carries observed (TomTom-normalized) limits where present, marked
`speed_source=overture`, vs class defaults elsewhere.

**Capacity (fixed during this study):** the GMNS `capacity` column is TOTAL
link capacity (osm2gmns and TAPLite kernel convention). overture2gmns
initially wrote per-lane values (bug #3); after the fix, motorway reads
2,200 pc/h/ln × lanes, consistent with osm2gmns (2,300) and the HCM base
value. **Agency caution:** MWCOG/NVTA freeway capacities are ~950 vph/ln
(period/service capacity) — a different quantity from HCM, never compared raw.

**Class:** Overture promotes some OSM secondary mileage to primary
(offsetting +/- shifts), harmless for assignment but relevant if capacity
defaults key off functional class.

## 6. Dimension 4 — topological integrity

**Connectivity:** the overture2gmns network is *more* connected than the
osm2gmns reference in both regions — fewer disconnected components and a
larger routable share.

| region | osm weak components | ovr weak components |
|---|---:|---:|
| Tempe | 22 | **18** |
| Chicago | 91 | **74** |

**Directionality (bug #2, fixed):** Overture materializes rule `when` scopes
with explicit nulls; the initial converter treated every rule as conditional
and dropped one-way restrictions, making **all 806 Tempe motorway pieces
bidirectional**. Fixed via a non-null scope test and regression-tested; the
directionality is now correct and is a structural check in the bench.

## 7. Dimension 5 — semantic fidelity (the differentiator)

Geometry matching cannot distinguish a diamond from a diverging-diamond, or
detect that a converter collapsed freeway-to-freeway ramps. The token layer
(bench/step9) measures this directly on Tempe freeways:

| token metric | osm2gmns | overture2gmns |
|---|---:|---:|
| junction tokens (merge / diverge) | 35 / 35 | 80 / 79 |
| ramp links | 188 (heuristic) | 507 |
| **system interchanges detected** | **0** | **3** |

osm2gmns collapses `motorway_link` into `motorway` (its known facility_type
limitation), so freeway-to-freeway ramps are unrecoverable and **no system
interchange is detectable** — despite the two networks agreeing geometrically
at 87-99%. Overture's explicit `subclass=link` survives conversion.
Managed-lane tokens extend this: Overture's named express-lane facilities
(I-66/495/95 Express) reconcile with NVTA's PMLIMIT-restricted coding to
within ~9% on I-66 — comparable only at the token layer.

**Conclusion:** for interchange, ramp, and managed-lane analysis,
overture2gmns is materially higher-fidelity than an OSM-derived conversion.

## 8. Dimension 6 — behavioral fidelity

Identical synthetic demand (all-pairs among grid-sampled zone centroids at
the same physical locations in both networks) assigned by TAPLite:

| region | osm VMT | ovr VMT | ΔVMT | osm VHT | ovr VHT | ΔVHT |
|---|---:|---:|---:|---:|---:|---:|
| Tempe | 194,211 | 193,279 | **-0.5%** | 6,227 | 6,199 | -0.4% |
| Chicago | 561,481 | 557,219 | **-0.8%** | 18,770 | 19,230 | +2.5% |

At the level MPOs care about — where traffic goes and how long it takes — the
Overture-derived network reproduces the OSM-derived network within ~1% VMT in
both a small city and a full metro. Chicago's +2.5% VHT is consistent with
Overture's denser connector-level segmentation on arterials, not with missing
or mis-coded facilities.

## 9. Agency-model validation (external ground truth)

The converter's realism is cross-checked against three real planning models
via map matching. Agency model links matching **onto** the Overture network
test whether Overture contains the agency's coded facilities:

| model | model → Overture (overall) | freeway/arterial classes | local/collector classes | dtalite_qa |
|---|---:|---|---|---|
| ARC Atlanta | 100% | 100% (all 11 classes) | 100% | ok |
| TRMG2 | 100% | 100% (all 9 classes) | 100% | ok |
| NVTA | 87% | FTYPE 1-3: 97-100% | FTYPE 4-6: 73-77% | ok |

Every facility the ARC and TRM models code — including managed lanes and
ramps — exists in the Overture conversion. NVTA's lower rate is a
coding-convention effect (median-centerline geometry; the reverse-direction
residential residual is the local streets a model abstracts into centroid
connectors, which is expected, not a conversion defect).

## 10. Defects found and fixed (conversion-quality changelog)

| # | defect | quality dimension | status |
|---|---|---|---|
| 1 | GeoJSON round-trip flattened Overture struct columns to strings | topology (2) / semantics (5) | fixed: coerce_struct + GeoParquet default |
| 2 | null rule-scopes treated as conditional → all freeways bidirectional | directionality (4) | fixed + regression test |
| 3 | capacity written per-lane vs GMNS total convention | attributes (3) | fixed: converter + fill scale by lanes |
| 4 | unsorted link.csv, no dual-unit columns | GMNS validity (1) | fixed: forward-star sort + vdf_* columns |
| 5 | breakpoint clamp could duplicate values | geometry (2) | fixed: set-dedup |

All five surfaced *because* the QA/QC harness compared against an independent
reference. A converter tested only against itself would have shipped every
one of them. 16/16 unit tests now guard the fixes.

## 11. Files in this report

- `CONVERSION_QUALITY_REPORT.md` — this document
- `aggregate_qaqc.py` — reproducible aggregator (reads bench outputs)
- `qaqc_dataset.json` — consolidated machine-readable dataset
- `evidence/` — self-contained copies of every source artifact
  (comparison, taplite, tokens, structure summaries, dtalite_qa verdicts)
