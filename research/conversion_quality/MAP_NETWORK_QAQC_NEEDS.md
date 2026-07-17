# The Needs for Map-Network QA/QC — a research synthesis

*Why transportation map-network QA/QC is needed, what dimensions it must
cover, and how those needs partition across `overture2gmns` (source-to-output
conversion verification) and `qaqc4gmns` (independent multi-source and
observational evaluation).*

This document motivates the QA/QC design in this repository from the
standards and literature. It is a needs analysis, not a benchmark — the
empirical results live in [CONVERSION_QUALITY_REPORT.md](CONVERSION_QUALITY_REPORT.md).

---

## 1. Why QA/QC is a first-class need, not an afterthought

A routable/model network is a *derived* product: raw map data (OSM, Overture,
agency GIS) is transformed into a node–link graph with directionality,
impedances, and topology. Every transformation stage can silently corrupt the
result, and the downstream cost is high:

- **Model results rest on network data.** The FHWA/TMIP *Travel Model
  Validation and Reasonableness Checking Manual* (2nd ed., 2010) states that
  "the success or failure of the modeling process rests on the input data,"
  and makes highway-network review a formal validation stage
  ([FHWA TMIP, ch. 3](https://www.fhwa.dot.gov/planning/tmip/publications/other_reports/validation_and_reasonableness_2010/ch03.cfm)).
- **Routing fails quietly.** "An unmapped turn restriction, a misplaced
  barrier, or an incorrect one-way attribute can send vehicles along detours
  that make little sense on the ground"
  ([DATAMARK, routable networks](https://datamarkgis.com/insights/what-you-need-to-know-about-routable-networks/)).
  A network can look correct geometrically and still route wrongly.
- **Bad networks manufacture false errors downstream.** A dangling ramp or
  missing movement produces spurious OD-estimation and assignment errors that
  are mis-attributed to demand, not the network. QA/QC before assignment is
  the cheapest place to catch them.

The need is therefore structural: **every map→network pipeline needs an
explicit, auditable QA/QC layer, and that layer has two distinct jobs** —
verifying the *transformation* and evaluating the *network* — which is why
this project splits them across two packages (§6).

## 2. The quality dimensions a map network must be checked on

International and domain standards converge on a small set of dimensions.

### 2.1 ISO 19157 — the geospatial data-quality baseline
ISO 19157:2013 (now ISO 19157-1:2023) defines six data-quality elements for
geographic data: **completeness, logical consistency, positional accuracy,
thematic (attribute) accuracy, temporal quality, and usability**
([ISO 19157](https://www.iso.org/standard/32575.html);
[ICA wiki](https://wiki.icaci.org/index.php?title=ISO_19157:2013_Geographic_information_-_Data_quality)).
These are the top-level axes any map-network QA/QC must address.

### 2.2 Road-network specialization of each dimension
The OSM road-quality literature operationalizes these for road networks:

| ISO dimension | road-network meaning | how it is measured |
|---|---|---|
| **Completeness** | omission (missing roads) + commission (extra roads) | Road Length Difference vs a reference; county-level in the US ([Li 2025, Trans. in GIS](https://onlinelibrary.wiley.com/doi/10.1111/tgis.70077)) |
| **Positional accuracy** | closeness of geometry to true location (absolute + relative) | feature matching with a search distance (~50 m) and change tolerance (~5 m) ([Calgary study](https://ica-abs.copernicus.org/articles/6/124/2023/ica-abs-6-124-2023.pdf)) |
| **Logical consistency** | correct topology: connectivity, valid class transitions, no self-intersections | topological rule checks ([Québec 5-indicator study](https://cdnsciencepub.com/doi/full/10.1139/geomat-2021-0012)) |
| **Thematic accuracy** | correct attributes: class, name, speed, lanes, oneway | attribute agreement vs reference ([SotM 2024, attribute accuracy](https://2024.stateofthemap.org/sessions/R9CVQD/)) |
| **Temporal quality** | currency of the data / release freshness | release metadata, update lineage |
| **Usability** | fit for the intended model/routing purpose | task-based (does it route? does it assign?) |

### 2.3 Routing/topology-specific needs (beyond generic GIS quality)
A *routable* network has needs a static GIS layer does not. Topology quality
frameworks name the concrete defect classes that must be detected and
repaired before routing
([NAPCORE Quality Framework for Road Network Topology](https://napcore.eu/wp-content/uploads/2025/06/NAPCORE-Quality-Framework-for-Topology_v1.1.pdf);
[DATAMARK](https://datamarkgis.com/insights/what-you-need-to-know-about-routable-networks/)):

- **Disconnected components / isolated roads** — unreachable subgraphs.
- **Dangling nodes / topology gaps** — near-miss endpoints that should connect
  but don't (and true dead-ends that legitimately should).
- **Directionality errors** — wrong one-way coding sends traffic the wrong way.
- **Turn-restriction errors** — missing/incorrect prohibited movements.
- **Grade-separation vs intersection** — a geometric crossing that is an
  overpass, not a junction, must not become a routable node.
- **Impedance errors** — missing/unreasonable speed, length, or capacity.

### 2.4 Travel-model-specific needs (beyond routing)
Travel-demand models add requirements that pure routing does not, per
FHWA/TMIP and NCHRP 255/365
([FHWA TMIP ch.3](https://www.fhwa.dot.gov/planning/tmip/publications/other_reports/validation_and_reasonableness_2010/ch03.cfm);
[TMIP validation manual, 2nd ed.](https://rosap.ntl.bts.gov/view/dot/55924)):

- **Facility type** coding (freeway / arterial / collector …) drives capacity
  and VDF selection.
- **Number of through lanes**, **free-flow speed**, and **capacity** per link,
  reviewed for continuity and reasonableness (color-coded network plots).
- **Centroid connectors** — the abstraction that loads zone demand onto the
  network; their number and placement materially affect assignment.
- **One-way verification** — the manual explicitly says all one-way links
  should be visually verified.
- **Distance/path checks** — coded length vs straight-line distance; selected
  paths compared against a web shortest-path service.

## 3. Two fundamentally different QA/QC questions

The needs above answer two questions that must not be conflated:

1. **Did the transformation preserve its source?** (conversion fidelity)
   Given Overture/OSM/agency input, does the produced GMNS network faithfully
   and completely represent *that source* — every eligible segment interval,
   its direction rules, scoped attributes, and access restrictions — with a
   traceable crosswalk and explicit accounting for anything excluded?

2. **Is the network good in the world?** (network quality)
   Independent of any one source, does the network match reality and other
   references — agency models, observed volumes (TMC/INRIX), GPS
   trajectories, posted speeds — and is it internally consistent and
   routable?

Question 1 needs only the converter's own source + output. Question 2 needs
*other* data. They have different inputs, different failure modes, and belong
in different tools.

## 4. The "conflation tax" and why provenance is a need, not a nicety

A recurring, expensive need in map-network work is **conflation** — matching
entities across datasets so attributes and observations can be joined.
Overture's Global Entity Reference System (GERS) exists specifically to
"eliminate the costly *conflation tax* by assigning persistent, unique
identifiers"
([Overture/TomTom GERS case study](https://overturemaps.org/case-study/2024/how-tomtom-enhanced-transportation-networks-with-gers-2/);
[Project Geospatial on GERS](https://projectgeospatial.org/geospatial-frontiers/the-battle-for-the-map-how-overtures-gers-proposal-ignited-a-cultural-war-in-open-source-geospatial-data)).
TomTom's Global Entity Matcher (GEM) is a deep-learning matcher that scores
cross-dataset matches by confidence
([TomTom GEM](https://www.tomtom.com/products/tomtom-gem/)).

The QA/QC implication: **a converter that preserves stable source IDs and a
segment→link crosswalk pays the conflation tax once, at conversion, and makes
all downstream QA/QC (agency comparison, TMC/INRIX association, year-over-year
tracking) cheaper and auditable.** Provenance is therefore a QA/QC need, not a
convenience — it is the precondition for Question 2 to be answerable at scale.

## 5. Normalization is where source fidelity is won or lost

Overture's transportation layer is OSM "normalized and cleared of data
inconsistencies," using GERS + linear referencing to fix "ID stability …
suboptimal sectioning of the road network, and data duplications"
([TomTom engineering: LRS](https://engineering.tomtom.com/overture-transportation-network-linear-referencing/)).
This makes the source cleaner than raw OSM, but shifts the QA/QC burden onto
the *converter*: linear-referenced, scoped attributes (speed/access varying
along a segment) must be split and translated correctly, and the last-matching
rule and directional semantics must be honored. These are exactly the failure
modes a source-to-output verifier must check — and where this project found
and fixed real defects (struct-flattening, null-scoped one-way rules,
capacity-unit convention, and access-excluded interval accounting).

## 6. How the needs partition across this project's packages

The needs analysis maps cleanly onto the two-package architecture:

| need (from §2–§5) | question | package |
|---|---|---|
| Every eligible source interval represented, or explicitly excluded (completeness of *conversion*) | 1 | **overture2gmns** `verify_conversion` — linear-reference conservation + interval disposition |
| Direction/access/scoped-attribute rules faithfully translated | 1 | **overture2gmns** — attribute provenance (observed vs defaulted), rule translation status |
| Source→output crosswalk complete and stable (GERS retained) | 1 | **overture2gmns** — crosswalk completeness check |
| GMNS output integrity (unique IDs, valid FKs, positive length) | 1 | **overture2gmns** — integrity checks |
| Completeness vs an independent reference (omission/commission) | 2 | **qaqc4gmns** — multi-source comparison |
| Positional accuracy vs reference geometry | 2 | **qaqc4gmns** — map-matching / feature matching |
| Topological routability (components, dangling nodes, turn restrictions) | 2 | **qaqc4gmns** — routable-network checks |
| Attribute accuracy vs observations (posted speed, counts) | 2 | **qaqc4gmns** — TMC/INRIX + observational validation |
| Behavioral reasonableness (assignment, path checks) | 2 | **qaqc4gmns** — assignment-based comparison |
| Centroid-connector adequacy, model reasonableness | 2 | **qaqc4gmns** — model-oriented QA (FHWA/TMIP-style) |

The boundary is the answer to "does this need *other* data?" If no →
conversion verification (overture2gmns). If yes → independent evaluation
(qaqc4gmns). This keeps each package's claims precise: overture2gmns can claim
a *verifiable, provenance-preserving transformation*; qaqc4gmns can claim
*independent evidence of network quality*.

## 7. Summary of needs

1. Map→network pipelines need an explicit, auditable QA/QC layer; model and
   routing outcomes depend on it.
2. QA/QC must cover the ISO 19157 dimensions, specialized for roads
   (completeness, positional, logical/topological, thematic, temporal,
   usability), plus routing-specific (connectivity, directionality, turn
   restrictions, grade separation, impedance) and model-specific (facility
   type, lanes, speed, capacity, centroid connectors) needs.
3. Two distinct questions — *did the transformation preserve its source?* and
   *is the network good in the world?* — need separate tooling.
4. Provenance / stable IDs (GERS-style) is a QA/QC need: it pays the
   conflation tax once and makes downstream evaluation auditable.
5. This project answers Question 1 in `overture2gmns` (source-to-output
   verification) and Question 2 in `qaqc4gmns` (independent evaluation).

## Sources

- [FHWA TMIP — Travel Model Validation & Reasonableness Checking Manual, 2nd ed. (2010), ch. 3](https://www.fhwa.dot.gov/planning/tmip/publications/other_reports/validation_and_reasonableness_2010/ch03.cfm) · [full manual](https://rosap.ntl.bts.gov/view/dot/55924)
- [Minimum Travel Demand Model Calibration & Validation Guidelines (2016)](https://tnmug.utk.edu/wp-content/uploads/sites/10/2022/11/Guidelines-Updated-2016.pdf)
- [ISO 19157:2013 Geographic information — Data quality](https://www.iso.org/standard/32575.html) · [ICA wiki summary](https://wiki.icaci.org/index.php?title=ISO_19157:2013_Geographic_information_-_Data_quality) · [ISO 19157-1:2023](https://www.iso.org/standard/78900.html)
- [Li 2025 — OSM road completeness & positional accuracy, US counties (Trans. in GIS)](https://onlinelibrary.wiley.com/doi/10.1111/tgis.70077)
- [Quality Assessment of the OSM Road Network in Calgary (2023)](https://ica-abs.copernicus.org/articles/6/124/2023/ica-abs-6-124-2023.pdf)
- [Five indicators for OSM road-network quality, Québec](https://cdnsciencepub.com/doi/full/10.1139/geomat-2021-0012)
- [Assessing attribute accuracy & logical consistency of OSM road data (SotM 2024)](https://2024.stateofthemap.org/sessions/R9CVQD/)
- [Investigating completeness and omission of OSM roads (arXiv)](https://arxiv.org/pdf/1909.04323)
- [NAPCORE — Quality Framework for Road Network Topology (v1.1, 2025)](https://napcore.eu/wp-content/uploads/2025/06/NAPCORE-Quality-Framework-for-Topology_v1.1.pdf)
- [DATAMARK — What you need to know about routable networks](https://datamarkgis.com/insights/what-you-need-to-know-about-routable-networks/)
- [GMNS specification (Zephyr / FHWA)](https://github.com/zephyr-data-specs/GMNS) · [spec PDF](https://rosap.ntl.bts.gov/view/dot/44136/dot_44136_DS1.pdf)
- [Overture/TomTom — How TomTom enhanced transportation networks with GERS](https://overturemaps.org/case-study/2024/how-tomtom-enhanced-transportation-networks-with-gers-2/)
- [TomTom engineering — Overture transportation network & linear referencing](https://engineering.tomtom.com/overture-transportation-network-linear-referencing/)
- [TomTom Global Entity Matcher (GEM)](https://www.tomtom.com/products/tomtom-gem/)
- [Project Geospatial — GERS and the conflation tax](https://projectgeospatial.org/geospatial-frontiers/the-battle-for-the-map-how-overtures-gers-proposal-ignited-a-cultural-war-in-open-source-geospatial-data)
