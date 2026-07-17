# research/conversion_quality

Consolidated QA/QC evidence for overture2gmns conversion **quality** (fidelity,
not runtime). This folder is self-contained and version-controlled.

## Contents

| file | what |
|---|---|
| [CONVERSION_QUALITY_REPORT.md](CONVERSION_QUALITY_REPORT.md) | the report — six quality dimensions, headline verdict, defect changelog |
| `aggregate_qaqc.py` | reproducible aggregator: reads `bench/out/` artifacts → `evidence/` + `qaqc_dataset.json` |
| `qaqc_dataset.json` | one consolidated machine-readable dataset (all regions, all dimensions) |
| `evidence/` | self-contained copies of each source artifact |

## Reproduce

```bash
python research/conversion_quality/aggregate_qaqc.py
```

Requires the bench outputs (`bench/out/`) present locally; they are generated
by `bench/run_all.py <region>` and `bench/step7_mpo_qaqc.py` /
`bench/step8_mapmatch.py`.

## Data policy

NVTA is agency-restricted. No NVTA network files are stored here — only
aggregate statistics (counts, verdicts, match rates) in `evidence/nvta_*.json`
and the report. The aggregator enforces this by copying only summary JSON.

## Summary (as of last aggregation)

- GMNS-valid (0 errors) on all 5 networks
- Geometric agreement with osm2gmns: 0.89 (Tempe) / 0.93 (Chicago) on common cells
- Behavioral agreement: ΔVMT -0.5% (Tempe) / -0.8% (Chicago) under identical demand
- Semantic advantage: 3 system interchanges detected vs 0 from osm2gmns (Tempe)
- Agency validation: ARC & TRM model links 100% present in Overture; NVTA 87%
- 5 conversion-quality defects found and fixed; 16/16 tests guard them
