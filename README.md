# overture2gmns

`overture2gmns` is an alpha Python package that converts the Overture Maps transportation theme into a GMNS road network. Its user-facing API intentionally mirrors [`osm2gmns`](https://github.com/jiawlu/OSM2GMNS), while its topology engine is designed around Overture's native `segment` and `connector` model.

```bash
pip install overture2gmns
```

## Conversion quality at a glance

Validated against osm2gmns (reference) and three agency planning models
(ARC Atlanta, TRMG2, NVTA). Full evidence:
[research/conversion_quality/](research/conversion_quality/).

| quality dimension | result | evidence |
|---|---|---|
| **GMNS validity** | 0 errors on all 5 networks | gmns-ready + dtalite_qa |
| **Geometric agreement** | 0.89–0.93 length correlation with osm2gmns | ~500 m grid |
| **Routing consistency** \* | **VMT within 1%** under identical *synthetic* demand | TAPLite assignment |
| **Topology** | *more* connected than osm2gmns (18 vs 22, 74 vs 91 components) | weak components |
| **Semantic fidelity** | **3 system interchanges recovered vs 0** from osm2gmns | freeway tokens |
| **Agency validation** | ARC & TRM model links **100% present**; NVTA 87% | map matching |

\* Relative check only: demand is synthetic (no observed OD) and capacity is an
inferred class default (neither Overture nor OSM provides observed capacity).
It isolates the network as the variable — not a validated volume forecast.
VMT is robust; VHT is more assumption-sensitive.

![Relative routing consistency](research/conversion_quality/figures/fig1_behavioral_fidelity.png)

*Same synthetic demand and same inferred capacity on both networks, so the
converter output is the only variable: VMT stays within 1% in a small city and
a full metro — the network representation does not shift where traffic goes.
This is a controlled relative comparison, not a validated forecast.*

![Semantic advantage](research/conversion_quality/figures/fig2_semantic_advantage.png)

*Where the converters differ: osm2gmns collapses ramp types into `motorway`,
so no freeway system interchange is recoverable — Overture's `subclass=link`
survives, and overture2gmns detects all three Tempe system interchanges.*

## Scope: conversion + verification (not general QA/QC)

`overture2gmns` deliberately stays focused on the pipeline
**Overture data → extraction → GMNS conversion → attribute cleaning →
source-to-output verification**. Its `verify_conversion()` checks that the
transformation faithfully preserves *its own* Overture source (linear-reference
conservation, crosswalk completeness, attribute provenance, GMNS integrity):

```python
import overture2gmns as o2g
result = o2g.verify_conversion("gmns_output")     # or: overture2gmns verify gmns_output
print(o2g.verification_report_markdown(result))
```

Broader evaluation — comparing a network against *other* networks or against
*observations* (agency-model comparison, TMC/INRIX matching, trajectory
validation, assignment-based comparison, dashboards) — lives in the separate
`qaqc4gmns` package, so each package's claims stay precise.

## Why a separate converter is needed

Overture differs materially from raw OSM:

1. **Topology is explicit.** A segment contains connector IDs and normalized linear-reference positions.
2. **Connectors can occur inside a segment.** The converter must split a segment at connector positions before creating GMNS links.
3. **Properties can vary along one segment.** Speed, access, surface, level, and related values can be scoped using `between=[start,end]`; the converter can split at these boundaries.
4. **Rules can be directional and modal.** Overture uses ordered rule lists; the last matching rule determines the value.
5. **Some modeling attributes remain application defaults.** Overture intentionally does not prescribe jurisdiction-specific implied access or implied speed, and the current transportation schema does not directly provide a GMNS-ready lane/capacity model. This package exposes transparent class defaults rather than silently treating them as observed facts.

## Installation

```bash
pip install -e .
```

For direct cloud download through Overture's official Python client:

```bash
pip install -e ".[download]"
```

For local GeoParquet files:

```bash
pip install -e ".[geoparquet]"
```

## Python API (osm2gmns-style)

```python
import overture2gmns as o2g

net = o2g.getNetFromFile(
    "segments.geojson",
    "connectors.geojson",
    mode_types=("auto", "bike", "walk"),   # str or sequence, like osm2gmns
    link_types=("motorway", "primary"),    # optional Overture class filter
)

o2g.fillLinkAttributesWithDefaultValues(
    net,
    default_lanes=True, default_lanes_dict={"motorway": 3},
    default_speed=True,
    default_capacity=True, default_capacity_dict={"primary": 1800},
)
o2g.generateNodeActivityInfo(net)
o2g.consolidateComplexIntersections(net, auto_identify=True, int_buffer=20.0)

o2g.outputNetToCSV(net, "gmns_output")
print(net.number_of_nodes, net.number_of_links)
```

`network_types=` is accepted as a backward-compatible alias for `mode_types=`.

Direct bounding-box access:

```python
net = o2g.getNetFromBBox(
    (-111.95, 33.41, -111.92, 33.44),
    mode_types=("auto",),
    release=None,  # latest release
)
o2g.outputNetToCSV(net, "tempe_gmns")
```

Download-then-convert (the osm2gmns `downloadOSMData` workflow):

```python
files = o2g.downloadOvertureData((-111.95, 33.41, -111.92, 33.44), "raw_overture")
net = o2g.getNetFromFile(files["segment"], files["connector"], mode_types="auto")
```

### API mapping to osm2gmns

| osm2gmns 1.0.x | overture2gmns | Notes |
|---|---|---|
| `getNetFromFile(filepath, mode_types, link_types, ...)` | `getNetFromFile(segment_file, connector_file, mode_types, link_types, ...)` | Overture ships topology in two feature types |
| `downloadOSMData(area_id, path)` | `downloadOvertureData(bbox, folder)` | Overture is queried by bbox, not relation ID |
| `fillLinkAttributesWithDefaultValues(net, ...)` | same name, same signature | dicts keyed by Overture road class; speeds in mph |
| `generateNodeActivityInfo(net, zone_filepath)` | same name, same signature | activity from incident link classes |
| `consolidateComplexIntersections(net, auto_identify, file, int_buffer)` | same name, same signature | Overture has no signal tag; proximity rule only |
| `outputNetToCSV(net, output_folder='')` | same name, same signature | adds `diagnostics.json` |
| `net.number_of_nodes` / `net.number_of_links` | same | |

## Command line

Convert downloaded GeoJSON, GeoJSONSeq, or GeoParquet:

```bash
overture2gmns convert \
  --segments segments.geojson \
  --connectors connectors.geojson \
  --modes auto,bike,walk \
  --output gmns_output
```

Download the latest Overture release for a bounding box and convert it:

```bash
overture2gmns download \
  --bbox -111.95 33.41 -111.92 33.44 \
  --modes auto \
  --output tempe_gmns
```

## Current outputs

- `node.csv`: GMNS nodes, keyed by integer `node_id`, preserving Overture connector IDs, plus `activity_type` / `is_boundary` / `zone_id` / `intersection_id` when generated.
- `link.csv`: directed GMNS links with WKT geometry, length (miles), free speed (mph), inferred lanes/capacity, allowed uses, Overture segment/version IDs, linear-reference ranges, and heading.
- `diagnostics.json`: skipped records, unresolved conditional rules, and turn restrictions not yet exported.

Only `node.csv` and `link.csv` are required for a basic GMNS static network. Extension columns are deliberately retained because GERS/Overture IDs are valuable for conflation and release-to-release tracking.

## Implemented conversion logic

- Reads GeoJSON FeatureCollections, GeoJSONSeq, and optional GeoParquet input.
- Optionally reads authoritative connector point features.
- Splits each road segment at interior connectors.
- Splits at boundaries of geometrically scoped properties.
- Reuses a shared GMNS node whenever segments reference the same connector ID.
- Evaluates forward/backward access independently.
- Applies Overture's "last matching rule" rule-list semantics.
- Converts explicit `km/h` or `mph` speed limits to GMNS mph.
- Falls back to user-replaceable road-class defaults for implied access, speed, lanes, and capacity.
- Emits one directed GMNS link per allowed heading.
- Filters by Overture road class via `link_types`, like osm2gmns's link-type filter.

## Important alpha limitations

1. `prohibited_transitions` are detected but not yet translated to `movement.csv`.
2. Temporal rules (`during`), user-purpose rules (`using`), recognized-status rules, and vehicle-dimension rules require scenario context; they are reported rather than flattened incorrectly.
3. Lane count and capacity are inferred from class defaults and are explicitly marked with source fields.
4. Only `subtype=road` is converted; rail and water are planned extensions.
5. Country/jurisdiction-specific access defaults should replace the generic table for production routing.
6. Very large regional extracts will benefit from a streamed Arrow implementation or a compiled geometry/topology core.

## Testing

```bash
pytest -q
```

The fixtures verify interior-connector splitting, shared-node reuse, directional access, scoped speed limits, mode/class filtering, default filling, node activity generation, intersection consolidation, and GMNS CSV output.

## Licensing and attribution

The package source code is MIT licensed. Overture transportation data is distributed under ODbL and carries upstream attribution requirements. A typical attribution is:

> © OpenStreetMap contributors, Overture Maps Foundation

Users remain responsible for complying with the terms applicable to the specific Overture release and derivative database they distribute.
