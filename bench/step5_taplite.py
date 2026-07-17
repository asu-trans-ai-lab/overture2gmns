"""Step 5: TAPLite/dtalite_qa smoke test on both networks.

Builds a runnable TAP scenario from each GMNS output:
  - normalizes link.csv units to miles/mph (TAPLite kernel conventions),
  - picks K grid-sampled zone centroids inside the largest strongly connected
    component so every OD pair is routable,
  - synthesizes an all-pairs demand table,
  - runs dtalite_qa (taplite4mpo) validate/prepare as the QA gate,
  - runs the TAPLite kernel (taplite.dll) on the prepared scenario,
  - summarizes assignment results (VMT/VHT/max v/c) for cross-network diffing.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import osm_dir, overture_dir, region_dir, REGIONS

KMH_TO_MPH = 0.621371192237334
METERS_PER_MILE = 1609.344
NUM_ZONES_TARGET = 25
DEMAND_PER_PAIR = 50.0


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _largest_scc(links: list[dict]) -> set[str]:
    """Kosaraju over the directed link graph."""
    forward: dict[str, list[str]] = defaultdict(list)
    backward: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()
    for row in links:
        a, b = str(row["from_node_id"]), str(row["to_node_id"])
        forward[a].append(b)
        backward[b].append(a)
        nodes.update((a, b))

    order: list[str] = []
    seen: set[str] = set()
    for start in nodes:
        if start in seen:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        seen.add(start)
        while stack:
            node, idx = stack[-1]
            neighbors = forward.get(node, [])
            if idx < len(neighbors):
                stack[-1] = (node, idx + 1)
                nxt = neighbors[idx]
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append((nxt, 0))
            else:
                order.append(node)
                stack.pop()

    best: set[str] = set()
    assigned: set[str] = set()
    for start in reversed(order):
        if start in assigned:
            continue
        component = {start}
        assigned.add(start)
        stack2 = [start]
        while stack2:
            node = stack2.pop()
            for nxt in backward.get(node, []):
                if nxt not in assigned:
                    assigned.add(nxt)
                    component.add(nxt)
                    stack2.append(nxt)
        if len(component) > len(best):
            best = component
    return best


def zone_centers(nodes: list[dict]) -> list[tuple[float, float]]:
    """Grid of target zone-centroid coordinates over a node extent."""
    xs = [_f(row["x_coord"]) for row in nodes]
    ys = [_f(row["y_coord"]) for row in nodes]
    grid_n = max(2, int(NUM_ZONES_TARGET ** 0.5))
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    step_x = (max_x - min_x) / grid_n or 1e-9
    step_y = (max_y - min_y) / grid_n or 1e-9
    return [
        (min_x + (gx + 0.5) * step_x, min_y + (gy + 0.5) * step_y)
        for gx in range(grid_n)
        for gy in range(grid_n)
    ]


def snap_centers(centers: list[tuple[float, float]], network_folder: Path) -> dict[int, str]:
    """Snap each shared center to the nearest node in the network's largest
    SCC. Returns {center_index: node_id}; a node claimed by an earlier center
    is not reused."""
    nodes = _read_csv(network_folder / "node.csv")
    links = _read_csv(network_folder / "link.csv")
    scc = _largest_scc(links)
    candidates = [row for row in nodes if str(row["node_id"]) in scc]
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for index, (cx, cy) in enumerate(centers):
        best = min(
            candidates,
            key=lambda row: (_f(row["x_coord"]) - cx) ** 2 + (_f(row["y_coord"]) - cy) ** 2,
        )
        node_id = str(best["node_id"])
        if node_id not in used:
            used.add(node_id)
            mapping[index] = node_id
    return mapping


def build_scenario(
    network_folder: Path,
    scenario_folder: Path,
    tool: str,
    zone_nodes: dict[str, int],
) -> dict:
    """Write a TAPLite scenario using a pre-agreed zone set.

    ``zone_nodes`` maps this network's node_id -> shared zone_id so both
    networks receive byte-identical demand between physically identical
    zone locations.
    """
    scenario_folder.mkdir(parents=True, exist_ok=True)
    nodes = _read_csv(network_folder / "node.csv")
    links = _read_csv(network_folder / "link.csv")
    # TAPLite kernel conventions: length in METERS, free_speed in mph.
    # osm2gmns emits meters & km/h; overture2gmns emits miles & mph.
    length_scale = 1.0 if tool == "osm2gmns" else METERS_PER_MILE
    speed_scale = KMH_TO_MPH if tool == "osm2gmns" else 1.0
    scc = _largest_scc(links)

    # TAPLite centroid convention: zone nodes come first (node_id == zone_id
    # == 1..Z) and everything else starts at first_through_node_id = Z + 1.
    renumber: dict[str, int] = {}
    for old_id, zone_id in sorted(zone_nodes.items(), key=lambda item: item[1]):
        renumber[old_id] = zone_id
    next_id = len(zone_nodes) + 1
    for row in nodes:
        old_id = str(row["node_id"])
        if old_id not in renumber:
            renumber[old_id] = next_id
            next_id += 1

    with (scenario_folder / "node.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["node_id", "zone_id", "x_coord", "y_coord"])
        for row in sorted(nodes, key=lambda item: renumber[str(item["node_id"])]):
            new_id = renumber[str(row["node_id"])]
            zone_id = new_id if new_id <= len(zone_nodes) else 0
            writer.writerow([new_id, zone_id, row["x_coord"], row["y_coord"]])

    with (scenario_folder / "link.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["link_id", "from_node_id", "to_node_id", "length",
                         "lanes", "capacity", "free_speed", "link_type"])
        renumbered = sorted(
            links,
            key=lambda row: (renumber[str(row["from_node_id"])], renumber[str(row["to_node_id"])]),
        )
        for index, row in enumerate(renumbered, start=1):
            lanes = max(1, int(_f(row.get("lanes"), 1)))
            # GMNS capacity is already TOTAL in both converters (overture2gmns
            # fixed 2026-07-17 — it previously wrote per-lane, and this step
            # multiplied by lanes, double-counting the osm side).
            capacity = _f(row.get("capacity"), 1000.0 * lanes) or 1000.0 * lanes
            # Prefer the explicit dual-unit columns when present (agency
            # networks and overture2gmns both emit them); this is unit-safe
            # regardless of the raw length/free_speed units. Fall back to the
            # tool-scaled raw columns (osm2gmns: meters + km/h).
            miles = _f(row.get("vdf_length_mi")) or _f(row.get("length")) * length_scale / METERS_PER_MILE
            mph = _f(row.get("vdf_free_speed_mph")) or _f(row.get("free_speed"), 25.0) * speed_scale
            writer.writerow([
                index,
                renumber[str(row["from_node_id"])],
                renumber[str(row["to_node_id"])],
                round(miles * METERS_PER_MILE, 6),   # kernel wants meters
                lanes,
                round(capacity, 1),
                round(mph or 25.0, 1),
                1,
            ])

    zone_ids = sorted(zone_nodes.values())
    with (scenario_folder / "demand.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["o_zone_id", "d_zone_id", "volume"])
        for origin in zone_ids:
            for destination in zone_ids:
                if origin != destination:
                    writer.writerow([origin, destination, DEMAND_PER_PAIR])

    with (scenario_folder / "settings.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["number_of_iterations", "number_of_processors",
                         "route_output", "first_through_node_id"])
        writer.writerow([20, 4, 1, len(zone_nodes) + 1])

    return {"zones": len(zone_ids), "scc_nodes": len(scc), "links": len(links)}


def run_kernel(scenario_folder: Path, timeout: int = 900) -> dict:
    code = "from taplite import taplite as t; t._lib.DTA_AssignmentAPI()"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=scenario_folder, capture_output=True, text=True, timeout=timeout,
    )
    (scenario_folder / "kernel_log.txt").write_text(
        proc.stdout + "\n" + proc.stderr, encoding="utf-8", errors="replace"
    )
    return {"returncode": proc.returncode}


def summarize_assignment(scenario_folder: Path) -> dict:
    performance = scenario_folder / "link_performance.csv"
    if not performance.exists():
        return {"assignment_output": False}
    vmt = vht = volume_total = 0.0
    max_doc = 0.0
    rows = _read_csv(performance)
    for row in rows:
        vmt += _f(row.get("VMT"))
        vht += _f(row.get("VHT"))
        volume_total += _f(row.get("vehicle_volume"))
        max_doc = max(max_doc, _f(row.get("doc")))
    return {"assignment_output": len(rows) > 0, "vmt": round(vmt, 0),
            "vht": round(vht, 0), "total_link_volume": round(volume_total, 0),
            "max_doc": round(max_doc, 3)}


def run(region: str, skip_kernel: bool = False) -> None:
    results = {}
    folders = {
        tool: folder
        for tool, folder in (("osm2gmns", osm_dir(region)), ("overture2gmns", overture_dir(region)))
        if (folder / "link.csv").exists()
    }
    if not folders:
        print(f"[step5:{region}] no networks found")
        return

    # One shared zone-center set (gridded over the reference network extent),
    # snapped into each network's SCC; only mutually valid zones survive, so
    # every network is assigned byte-identical demand.
    reference = folders.get("osm2gmns") or next(iter(folders.values()))
    centers = zone_centers(_read_csv(reference / "node.csv"))
    snapped = {tool: snap_centers(centers, folder) for tool, folder in folders.items()}
    common_centers = sorted(set.intersection(*(set(m) for m in snapped.values())))
    zone_maps = {
        tool: {snapped[tool][idx]: rank + 1 for rank, idx in enumerate(common_centers)}
        for tool in folders
    }
    print(f"[step5:{region}] shared zones: {len(common_centers)} of {len(centers)} grid centers")

    for tool, folder in folders.items():
        scenario = region_dir(region) / f"tap_{tool}"
        info = build_scenario(folder, scenario, tool, zone_maps[tool])
        print(f"[step5:{region}] {tool}: scenario with {info['zones']} zones, "
              f"{info['links']} links (SCC {info['scc_nodes']} nodes)")

        entry = {"scenario": str(scenario), **info}
        try:
            from dtalite_qa import control
            prep = control.prepare(str(scenario), out_dir=str(scenario / "normalized"))
            entry["qa_ok"] = prep["ok"]
            entry["qa_access_problems"] = prep.get("access_problems")
            validation = prep.get("validate")
            entry["qa_errors"] = [str(m) for m in getattr(validation, "errors", [])][:20]
            entry["qa_warnings"] = [str(m) for m in getattr(validation, "warnings", [])][:10]
        except Exception as exc:  # QA layer failure is itself a finding
            entry["qa_ok"] = False
            entry["qa_error"] = repr(exc)

        if not skip_kernel:
            run_dir = scenario / "normalized" if (scenario / "normalized" / "link.csv").exists() else scenario
            try:
                entry.update(run_kernel(run_dir))
                entry.update(summarize_assignment(run_dir))
            except Exception as exc:
                entry["kernel_error"] = repr(exc)
        results[tool] = entry

    report = region_dir(region) / "taplite_report.json"
    report.write_text(json.dumps(results, indent=2))
    print(f"[step5:{region}] wrote {report}")
    for tool, entry in results.items():
        print(f"  {tool}: qa_ok={entry.get('qa_ok')} "
              f"assignment={entry.get('assignment_output')} vmt={entry.get('vmt')} vht={entry.get('vht')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("region", choices=sorted(REGIONS))
    parser.add_argument("--skip-kernel", action="store_true")
    args = parser.parse_args()
    run(args.region, skip_kernel=args.skip_kernel)
