"""Source-to-output conversion verification (in scope for overture2gmns).

This module verifies that the Overture-to-GMNS transformation is internally
consistent and complete *with respect to its own source segments and the
crosswalk it emitted*. It does NOT compare against other networks, TMC data,
trajectories, or agency models — that is qaqc4gmns's responsibility.

Runs on a written GMNS folder (node.csv + link.csv) using the provenance
columns overture2gmns emits: overture_segment_id, overture_lr_start/end,
overture_heading, speed_source, lanes_source, capacity_source.

Verification statuses (per the conversion spec):
  EXACT                  value taken directly from Overture
  TRANSFORMED_EQUIVALENT translated/normalized, meaning preserved
  DEFAULTED              filled from a class default (not observed)
  PARTIALLY_SUPPORTED    represented with known loss
  UNSUPPORTED            present in source, not representable
  EXCLUDED               intentionally dropped
  ERROR                  integrity violation
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

csv.field_size_limit(10_000_000)

LR_TOLERANCE = 1e-6


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _lr_coverage(intervals: list[tuple[float, float]]) -> dict[str, Any]:
    """Coverage of [start,end] pieces against the unit interval [0,1].

    Classifies any shortfall as `interior` (a hole with coverage on both
    sides — a real conservation failure) vs `edge` (a missing prefix/suffix,
    consistent with study-area boundary clipping — expected, not an error).
    """
    ordered = sorted((min(a, b), max(a, b)) for a, b in intervals)
    merged: list[list[float]] = []
    overlap = 0.0
    for start, end in ordered:
        if merged and start <= merged[-1][1] + LR_TOLERANCE:
            overlap += max(0.0, merged[-1][1] - start)
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    covered = sum(b - a for a, b in merged)
    gap = max(0.0, 1.0 - covered)
    # interior gap = coverage does not reach from 0 to 1 as a single run
    interior_gap = 0.0
    if merged:
        prefix = merged[0][0]                      # missing [0, first_start]
        suffix = 1.0 - merged[-1][1]               # missing [last_end, 1]
        interior_gap = max(0.0, gap - max(0.0, prefix) - max(0.0, suffix))
    return {"covered": round(covered, 6), "gap": round(gap, 6),
            "interior_gap": round(interior_gap, 6), "overlap": round(overlap, 6)}


def verify_conversion(gmns_folder: str | Path) -> dict[str, Any]:
    """Verify a written GMNS network against its own Overture provenance.

    Returns a structured result with integrity issues, linear-reference
    coverage, and attribute-provenance distributions.
    """
    folder = Path(gmns_folder)
    nodes = _read_csv(folder / "node.csv")
    links = _read_csv(folder / "link.csv")
    node_ids = {str(n["node_id"]) for n in nodes}

    result: dict[str, Any] = {"folder": str(folder), "links": len(links),
                              "nodes": len(nodes)}
    issues: list[dict] = []

    # ---- Report E: GMNS output integrity ---------------------------------
    seen_link_ids: set[str] = set()
    dup_links = 0
    bad_node_ref = 0
    nonpositive_len = 0
    missing_crosswalk = 0
    bad_heading = 0
    seen_directed: set[tuple[str, str, str, str]] = set()
    dup_directed = 0

    for link in links:
        lid = str(link.get("link_id"))
        if lid in seen_link_ids:
            dup_links += 1
        seen_link_ids.add(lid)
        if str(link.get("from_node_id")) not in node_ids or str(link.get("to_node_id")) not in node_ids:
            bad_node_ref += 1
        if _f(link.get("vdf_length_mi")) <= 0 and _f(link.get("length")) <= 0:
            nonpositive_len += 1
        if not str(link.get("overture_segment_id") or "").strip():
            missing_crosswalk += 1
        if str(link.get("overture_heading") or "") not in ("forward", "backward", ""):
            bad_heading += 1
        # unintended duplicate directed link (same seg/heading/lr already seen)
        key = (str(link.get("overture_segment_id")), str(link.get("overture_heading")),
               str(link.get("overture_lr_start")), str(link.get("overture_lr_end")))
        if key in seen_directed and key[0]:
            dup_directed += 1
        seen_directed.add(key)

    integrity = {
        "duplicate_link_ids": dup_links,
        "invalid_node_references": bad_node_ref,
        "nonpositive_length": nonpositive_len,
        "missing_source_crosswalk": missing_crosswalk,
        "invalid_heading": bad_heading,
        "duplicate_directed_pieces": dup_directed,
    }
    for name, count in integrity.items():
        if count:
            issues.append({"status": "ERROR", "check": name, "count": count})
    result["integrity"] = integrity

    # ---- Report D: linear-reference conservation --------------------------
    # Conservation invariant: the UNION of all directed pieces of a segment
    # must tile [0,1] (every part of the source produced at least one link).
    # A gap in a single heading is NOT an error — it is a one-way stretch
    # (that direction legitimately has no link there); it is reported as
    # directionality, informationally.
    by_seg: dict[str, list[tuple[float, float]]] = defaultdict(list)
    by_seg_heading: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for link in links:
        seg = str(link.get("overture_segment_id") or "")
        if not seg:
            continue
        heading = str(link.get("overture_heading") or "forward")
        piece = (_f(link.get("overture_lr_start")), _f(link.get("overture_lr_end")))
        by_seg[seg].append(piece)
        by_seg_heading[(seg, heading)].append(piece)

    interior_failures = edge_clipped = clean = 0
    worst = []
    for seg, intervals in by_seg.items():
        cov = _lr_coverage(intervals)
        if cov["interior_gap"] > 1e-4:       # real conservation failure (a hole)
            interior_failures += 1
            worst.append({"segment": seg, **cov})
        elif cov["gap"] > 1e-4:              # prefix/suffix missing = boundary clip
            edge_clipped += 1
        else:
            clean += 1

    one_way_stretches = sum(
        1 for intervals in by_seg_heading.values()
        if _lr_coverage(intervals)["gap"] > 1e-4)

    result["lr_coverage"] = {
        "segments_checked": len(by_seg),
        "clean_union_tiling": clean,
        "interior_conservation_failures": interior_failures,
        "edge_clipped_informational": edge_clipped,
        "one_way_stretches_informational": one_way_stretches,
        "worst_interior": sorted(worst, key=lambda w: -w["interior_gap"])[:10],
    }
    if interior_failures:
        issues.append({"status": "ERROR", "check": "lr_interior_conservation_gap",
                       "count": interior_failures})

    # ---- Report C: attribute provenance distribution ----------------------
    provenance: dict[str, Counter] = {}
    for field in ("speed_source", "lanes_source", "capacity_source"):
        provenance[field] = Counter(str(l.get(field) or "unknown") for l in links)
    result["attribute_provenance"] = {k: dict(v) for k, v in provenance.items()}

    # attribute status roll-up (EXACT vs DEFAULTED share)
    def status_share(counter: Counter) -> dict:
        total = sum(counter.values()) or 1
        exact = counter.get("overture", 0)
        return {"exact_pct": round(100 * exact / total, 1),
                "defaulted_pct": round(100 * (total - exact) / total, 1)}
    result["attribute_status"] = {
        "speed": status_share(provenance["speed_source"]),
        "lanes": status_share(provenance["lanes_source"]),
        "capacity": status_share(provenance["capacity_source"]),
    }

    result["issues"] = issues
    result["passed"] = not any(i["status"] == "ERROR" for i in issues)
    return result


def verification_report_markdown(result: dict[str, Any]) -> str:
    """Human-readable conversion-verification report (Report D/E/C)."""
    lr = result["lr_coverage"]
    lines = [
        "# Conversion verification report",
        f"Source: `{result['folder']}` — {result['links']} links, {result['nodes']} nodes",
        f"\n**Verdict: {'PASS' if result['passed'] else 'FAIL'}** "
        f"({len([i for i in result['issues'] if i['status'] == 'ERROR'])} errors)",
        "\n## Output integrity (Report E)",
        "| check | violations |", "|---|---:|",
    ]
    for name, count in result["integrity"].items():
        lines.append(f"| {name} | {count} |")
    lines += [
        "\n## Linear-reference conservation (Report D)",
        f"- segments checked: {lr['segments_checked']}",
        f"- clean union [0,1] tiling: {lr['clean_union_tiling']}",
        f"- **interior conservation failures (holes): {lr['interior_conservation_failures']}**",
        f"- edge-clipped at boundary (expected): {lr['edge_clipped_informational']}",
        f"- one-way stretches (informational): {lr['one_way_stretches_informational']}",
        "\n## Attribute provenance (Report C)",
        "| attribute | from Overture | defaulted |", "|---|---:|---:|",
    ]
    for attr, s in result["attribute_status"].items():
        lines.append(f"| {attr} | {s['exact_pct']}% | {s['defaulted_pct']}% |")
    return "\n".join(lines)
