# overture2gmns roadmap

Scope discipline: overture2gmns stays focused on **conversion + attribute
cleaning + source-to-output verification**. Independent evaluation
(multi-source comparison, map matching, observational validation) lives in
the separate `qaqc4gmns` package. Every item below deepens the core claim —
*a reproducible, provenance-preserving, verifiable transformation of Overture
transportation features into modeling-ready GMNS* — rather than broadening
scope.

Priorities are grounded in what the QA/QC benchmark actually surfaced (see
`research/conversion_quality/`). Tier order = impact on the core claim.

## Shipped (v0.2.0)

- osm2gmns-compatible API; Overture-native topology (connector + scoped-rule
  splits, last-matching-rule, directional/modal access, GERS IDs retained).
- Streamed Arrow→parquet download; GeoJSON struct-string recovery.
- **Source-to-output verification** (`verify_conversion`, `overture2gmns verify`):
  linear-reference conservation, attribute provenance (observed vs defaulted),
  GMNS integrity.
- **Interval-disposition accounting**: every candidate interval gets one
  disposition (`GENERATED_BOTH/FORWARD/BACKWARD`, `EXCLUDED_BY_ACCESS_RULE`,
  `EXCLUDED_ZERO_LENGTH`) written to `interval_disposition.csv`; verification
  distinguishes truly-unaccounted holes (ERROR) from classified exclusions,
  and reconciles reconstructed vs actual link count. Closed the 3 Chicago
  "interior gap" findings (all were legitimate access exclusions).

## Tier 1 — airtight conservation (target v0.2.x)

Small, high-confidence work that makes the conservation claim complete.

- [ ] **Enforce the invariant in the converter**, not only in the verifier:
      `N_candidate = N_generated + N_excluded + N_merged`, emitting
      `ERROR_UNACCOUNTED` at conversion time so a lost interval can never reach
      output silently.
- [ ] **Explicit `EXCLUDED_OUTSIDE_CLIP` disposition** recorded by the
      converter (test whether a connector `at` maps outside the retained
      geometry), instead of the verify-time prefix/suffix heuristic — which a
      multipart clipped geometry could defeat.
- [ ] **Error on LR overlaps**, not just gaps (spec wants gap = overlap = 0).
- [ ] **Geometric length-conservation check** `|L_source − ΣL_pieces| ≤ ε`,
      catching geometry↔linear-reference mismatches the interval check can't.
- [ ] **Reproducibility manifest** (`reproducibility_manifest.json`): Overture
      release, package version, git commit, config hash, source-file hashes,
      dependency + Python versions.
- [ ] **Verification report bundle** (`verification/` folder: summary
      JSON/CSV, `segment_conservation.csv`, `interval_disposition.csv`,
      `attribute_provenance.csv`, `gmns_integrity.csv`, HTML report) — a direct
      paper artifact.
- [ ] `overture2gmns inspect-segment` debug command: reconstruct
      source geometry → breakpoints → candidate intervals → links →
      dispositions for one segment.

## Tier 2 — attribute cleaning depth (target v0.3.0)

The spec's strongest intended component; currently the thinnest.

- [ ] **Dual retention** — keep source *and* cleaned value per attribute
      (`source_*_value`, `*_source`, `*_cleaning_rule`, `*_confidence`).
- [ ] **Use Overture lane data when present** instead of always defaulting
      (don't imply defaults are observed).
- [ ] **Explicit road-class crosswalk table**
      (`overture_class → gmns_facility_type → assignment_type →
      default_parameter_group`).
- [ ] **Name / route normalization** (route_id, route_number,
      Interstate/US/State designations, directional suffixes) — needed for
      corridor-continuity QA.
- [ ] Speed cleaning hierarchy with confidence (explicit → directional →
      class default → missing-with-warning).

## Tier 3 — feature completeness

- [ ] **`movement.csv` from `prohibited_transitions`** (+ movement crosswalk,
      + `path_restriction.csv` for complex multi-link restrictions). Currently
      detected (362 in Tempe) but written to diagnostics only.
- [ ] **Optional degree-2 simplification** — conservation-preserving merge of
      links with identical attributes at non-critical degree-2 nodes; merged
      crosswalk preserves all contributing segments.
- [ ] **Rail / water subtypes** (currently road-only).
- [ ] Resolve conditional rules (`during`/`using`/`recognized`/`vehicle`) into
      GMNS TOD/scenario records instead of reporting-only.

## Tier 4 — performance (only after Tiers 1–3; profile before rewrite)

Measured: ~3,200 links/s (Python) vs ~40,600 (osm2gmns C++), convert-only.

- [ ] **Profile** the convert path (expect ≥70% in the geodesic-length loop +
      `shapely.substring`).
- [ ] **Vectorize** — batch `pyproj.Geod.line_length`, shapely 2.x vectorized
      ops, drop per-link object churn (likely 3–5× with no compiled code).
- [ ] Reserve an **Arrow-native Rust core** (`arrow-rs`/`polars` + `pyo3`) for
      statewide/national scale only — reads columnar memory directly, skipping
      Python object materialization.

## Cross-cutting

- [ ] Multipart / self-looping / clipped-geometry regression fixtures.
- [ ] Streamed output for statewide extracts (converter currently materializes
      all links in memory).
