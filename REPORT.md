# overture2gmns vs osm2gmns vs planning models — full QA/QC report

Date: 2026-07-17. All results reproducible from `bench/` (steps 1–9) and
`../gmns_eco_system/` demos. Companion artifact (MPO brief):
https://claude.ai/code/artifact/b9e343f4-9857-4e56-9447-211aac0736a0

## 1. Requirements and scope

- Mirror the osm2gmns 1.0.1 user-facing API on Overture Maps data
  (`getNetFromFile(mode_types, link_types, ...)`, `fillLinkAttributesWithDefaultValues`,
  `generateNodeActivityInfo`, `consolidateComplexIntersections`, `outputNetToCSV`,
  `downloadOvertureData`; `network_types` kept as alias).
- Prove interchangeability at three levels: structure (geometry/attributes),
  behavior (identical-demand TAPLite assignment), semantics (tokens).
- Validate against real planning models (ARC Atlanta, TRMG2, NVTA) with
  gmns-ready + taplite4mpo (dtalite_qa) + map-matching + capacity checks.

## 2. overture2gmns: bugs found and fixed during the benchmark

| # | defect | symptom | fix |
|---|---|---|---|
| 1 | GeoJSON round-trips flatten Overture struct columns to numpy-repr strings | connector topology silently lost (nodes == links) | `rules.coerce_struct` recovery; GeoParquet default; streamed Arrow download |
| 2 | `when` scopes materialized with explicit nulls treated as conditional | one-way rules ignored → **all freeways bidirectional** (806/806 in Tempe) | `has_conditional_scope` (non-None test); regression test |
| 3 | capacity written per-lane where GMNS/kernel expect total | motorway cap/lane read 1,100 vs osm2gmns 2,300 | converter+fill multiply by lanes; bench step5 no longer double-counts |
| 4 | link.csv unsorted; no dual-unit columns | gmns-ready Level-3 FAIL | forward-star sort; `vdf_length_mi`/`vdf_free_speed_mph` emitted |
| 5 | breakpoint clamp could duplicate values | spurious zero-length pieces | set-dedup |

Current state: 16/16 tests, wheel builds, clean-venv install verified,
gmns-ready validate_network passes (0 errors).

## 3. osm2gmns: issues to report upstream (jiawlu/OSM2GMNS)

1. **facility_type collapses `motorway_link` into `motorway`** (link road
   types generally). Consequence measured by the token layer: freeway-to-
   freeway ramps become unrecoverable — the Tempe OSM network yields **zero
   detectable system interchanges** vs 3 in the Overture network, despite
   87–99% geometric agreement. Request: preserve the OSM highway value in an
   output column (e.g., `osm_highway`).
2. **link.csv is not sorted by from_node_id** — trips gmns-ready's
   forward-star check and requires re-sorting before CSR-based kernels.
3. **No dual-unit columns** (`vdf_length_mi`, `vdf_free_speed_mph`) —
   gmns-ready Level-3 dual-unit check fails on raw osm2gmns output.
4. `downloadOSMData` accepts only relation `area_id`, not bbox (usability;
   Overpass workaround required).
5. `Network` object exposes only counts — no Python-side link/node access.

None of these block use; #1 matters most for interchange/managed-lane work.

## 4. Converter-vs-converter results (identical area and modes)

| metric | Tempe | Chicago metro |
|---|---:|---:|
| grid length correlation (common ~500 m cells) | 0.89 | 0.93 |
| drivable length diff (ovr vs osm) | +9.0% | +12.6% (bbox fringe) |
| TAPLite ΔVMT, *synthetic* demand | **−0.5%** | **−0.8%** |
| TAPLite ΔVHT, *synthetic* demand | −0.4% | +2.5% |
| weak components (fewer better) | 18 vs 22 | 74 vs 91 |
| map-match ovr→osm / osm→ovr | 87.8% / **99.3%** | — |

The assignment rows are a **relative** check, not a forecast: demand is
synthetic (no observed OD) and capacity is an inferred class default (neither
Overture nor OSM provides capacity), held identical on both networks so the
converter output is the only variable. ΔVMT (robust, path-length driven)
shows routing does not diverge; ΔVHT is assumption-sensitive and not a
validated delay difference.

Conclusion: **routes consistently under matched assumptions** at the
assignment level; Overture ⊃ OSM in coverage; semantic ramp information
survives only in Overture. A true behavioral validation (observed OD +
capacity) is future work.

## 5. Planning-model QA (ARC, TRMG2, NVTA)

| network | format QA | model→Overture | Overture→model | connectors | capacity semantics |
|---|---|---|---|---|---|
| ARC Atlanta (EPSG:2240 ft, m/kmh) | pass | **100%** all 11 classes | 72.6% (residential 10%) | 27,066 = 19% of links | per-link, HCM-like |
| TRMG2 (lonlat, mi/kmh) | pass | **100%** all 9 classes | 69.4% (residential 13%) | 12,366 = 16% | per-link |
| NVTA (EPSG:2248 ft; restricted) | pass, 0 errors | 97–100% FTYPE 1–3; **73–77% FTYPE 4–6** | 44% @25 m → 87–90% arterial+ @40 m | 15,986 = 32% | **PM-period ~950 vph/ln** ≠ HCM |

Method findings:
- **Bidirectional match + radius sweep = coding-convention fingerprint**:
  true-shape networks (ARC/TRM) match at 25 m; centerline-coded networks
  (NVTA/MWCOG) need 40 m+. Forward-direction failures (NVTA FTYPE 4–6)
  are the actionable geometry QA punch-list.
- **Centroid connectors abstract exactly the local streets Overture keeps**
  (reverse-match residential 10–13%); connector share 16–32% of links.
- **Never compare agency `capacity` to HCM/converter values raw** — MWCOG
  period/service capacities run ~2.4× lower than HCM.
- **Managed lanes**: NVTA codes them as PMLIMIT-restricted links (FTYPE 6 is
  ramps); Overture as named facilities. On I-66: 37.8 restricted mi vs 41.5
  ML mi — **consistent within ~9%**, comparable only at the token layer.

## 6. Ecosystem packages and token2net QA/QC functions

Prototypes at `../gmns_eco_system/` (all demos green):
`gmns2gmns` (unit-aware summary/diff — caught bug #3), `lrs2gmns`
(bidirectional event projection; 1.1 m snaps; route milepost tables),
`signal4gmns` (phasing motifs, geometry–phasing contradiction QA, motif
transfer), `freeval4gmns` (HCM segmentation + token capacities).
Composition demo: I-66 = 43 links → 15 gore junctions → **23 HCM segments
(7 merge/6 diverge/1 weave/9 basic)** FREEVAL-style, fully automated.

**token2net reading-direction QA/QC catalog** (prototype:
`bench/step9_tokenize.py` + `../gmns_eco_system/express_lane_tokens.py`):

| QA/QC function | token level | catches |
|---|---|---|
| semantic network diff (token histograms) | L0–L2 | ramp-class loss, missing system interchanges (invisible to geometry QA) |
| interchange motif inventory & map | L2 | miscoded interchange types; validated vs aerials (Tempe diamonds/system junctions correct) |
| merge/diverge/weave sequencing | L0 | HCM facility segmentation, weave detection, influence areas |
| token-conditioned capacity priors | L0–L2 | class-default capacity errors; base for INRIX posteriors |
| ML_FACILITY / ML_ACCESS tokens | ML | managed-lane extent + access spacing (median 0.44–0.68 mi NoVA); cross-representation equivalence (named facility ↔ PMLIMIT) |
| geometry–phasing contradiction (signal4gmns) | signal | 8-phase timing at 3-leg nodes; UTDF join errors |
| known misclassification (v1) | L2 | collector-distributor roads break FF-gore detection (I-10/US-60 → "PARCLO") — fix queued |

## 7. Map-matching: contribution to MapMatching4GMNS / mapmatcher4gmns

Recommendation: **yes, contribute — to both, differently.**
- **mapmatcher4gmns (PyPI, Python HMM)** — where our code runs today; PR:
  (a) bug fix: `pd.to_datetime(..., infer_datetime_format=)` crashes on
  pandas ≥2 (`matcher/mapmatch.py:2046`); (b) bug fix: `LoadNetFromCSV(folder=...)`
  fails to resolve files (explicit node_file/link_file required); (c) new
  module `crossnet` — synthetic probe generation from link geometry
  (50 m spacing + headings, class-stratified, bbox/connector filters) +
  bidirectional match-rate evaluation. Bundle prepared at
  `../gmns_eco_system/mapmatching_contrib/`.
- **MapMatching4GMNS (asu-trans-ai-lab, C++ engine)** — add the same probe
  generator + workflow as a documented example ("network cross-validation
  mode"); the C++ engine then serves as a second independent matcher — a
  true two-engine verification (mirroring the access4gmns multi-engine
  pattern: same probes, two engines, agreement = algorithm check).
- After merge: bump PyPI (`mapmatcher4gmns` 0.1.10) — release notes drafted
  in the bundle.

## 8. Release plan

1. `overture2gmns` 0.1.0 → PyPI (wheel ready; add sdist + GitHub repo + CI).
2. `access4gmns` 0.1.0 → PyPI (tests green; niche documented).
3. mapmatcher4gmns PR + 0.1.10 (above).
4. Promote `gmns2gmns` → dev/git_release split once step 3/7/8 refactor
   lands; `lrs2gmns`/`signal4gmns`/`freeval4gmns` follow as they harden.
5. token2net: fold step9 tokenizer + ML tokens in as the reading direction.
