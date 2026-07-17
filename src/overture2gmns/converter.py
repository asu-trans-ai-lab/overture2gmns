"""Overture transportation to GMNS conversion."""

from __future__ import annotations

import hashlib
import json
import warnings
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pyproj import Geod
from shapely.geometry import LineString, Point
from shapely.ops import substring

from .defaults import ROAD_DEFAULTS, SUPPORTED_MODES
from .io import (
    load_overture_records,
    records_from_geodataframe,
)
from .models import Link, Network, Node
from .rules import (
    access_allowed,
    as_rule_list,
    coerce_struct,
    has_conditional_scope,
    speed_limit_mph,
)

GEOD = Geod(ellps="WGS84")
SCOPED_PROPERTIES = (
    "speed_limits",
    "access_restrictions",
    "subclass_rules",
    "road_surface",
    "road_flags",
    "level_rules",
    "width_rules",
)
# Nested Overture fields that GeoJSON round-trips may flatten into strings.
NESTED_PROPERTIES = SCOPED_PROPERTIES + (
    "connectors",
    "names",
    "prohibited_transitions",
    "routes",
    "destinations",
)


def _as_tuple(value: Any) -> tuple:
    """Mirror osm2gmns's string-or-sequence argument handling."""
    if value is None:
        return ()
    return (value,) if isinstance(value, str) else tuple(value)


def _feature_id(record: Mapping[str, Any]) -> str:
    value = record.get("id")
    if value is None:
        raise ValueError("Every segment record must contain an Overture 'id'.")
    return str(value)


def _connector_entries(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    connectors = record.get("connectors") or []
    if hasattr(connectors, "tolist"):
        connectors = connectors.tolist()
    return [dict(item) for item in connectors if isinstance(item, Mapping)]


def _breakpoints(record: Mapping[str, Any], split_at_property_changes: bool) -> list[float]:
    values = {0.0, 1.0}
    for connector in _connector_entries(record):
        if connector.get("at") is not None:
            values.add(float(connector["at"]))
    if split_at_property_changes:
        for property_name in SCOPED_PROPERTIES:
            for rule in as_rule_list(record.get(property_name)):
                between = rule.get("between")
                if isinstance(between, (list, tuple)) and len(between) == 2:
                    values.add(float(between[0]))
                    values.add(float(between[1]))
                if rule.get("at") is not None:
                    values.add(float(rule["at"]))
    return sorted({min(1.0, max(0.0, value)) for value in values})


def _connector_at(record: Mapping[str, Any], lr: float, tolerance: float = 1e-8) -> str | None:
    for connector in _connector_entries(record):
        if connector.get("at") is None:
            continue
        if abs(float(connector["at"]) - lr) <= tolerance:
            connector_id = connector.get("connector_id")
            if connector_id is not None:
                return str(connector_id)
    return None


def _synthetic_node_key(segment_id: str, lr: float) -> str:
    digest = hashlib.sha1(f"{segment_id}@{lr:.12f}".encode("utf-8")).hexdigest()[:16]
    return f"synthetic:{digest}"


def _clean_linestring(line: LineString) -> LineString:
    """Remove consecutive duplicate coordinates introduced by line slicing."""
    coordinates = []
    for coordinate in line.coords:
        if not coordinates or tuple(coordinate) != tuple(coordinates[-1]):
            coordinates.append(coordinate)
    return LineString(coordinates)


def line_length_miles(line: LineString) -> float:
    coordinates = list(line.coords)
    total_meters = 0.0
    for first, second in zip(coordinates, coordinates[1:]):
        _, _, distance = GEOD.inv(first[0], first[1], second[0], second[1])
        total_meters += distance
    return total_meters / 1609.344


def _name(record: Mapping[str, Any]) -> str:
    names = record.get("names")
    if isinstance(names, Mapping):
        primary = names.get("primary")
        if isinstance(primary, str):
            return primary
        if isinstance(primary, Mapping):
            return str(primary.get("value") or primary.get("name") or "")
    return ""


def _subclass(record: Mapping[str, Any], lr: float) -> str:
    result = str(record.get("subclass") or "")
    for rule in as_rule_list(record.get("subclass_rules")):
        between = rule.get("between")
        matches = True
        if isinstance(between, (list, tuple)) and len(between) == 2:
            matches = float(between[0]) <= lr <= float(between[1])
        if matches and rule.get("value") is not None:
            result = str(rule["value"])
    return result


def _facility_type(record: Mapping[str, Any], lr: float) -> str:
    road_class = str(record.get("class") or "unknown")
    subclass = _subclass(record, lr)
    return f"{road_class}_{subclass}" if subclass else road_class


def _raw_json(record: Mapping[str, Any]) -> str:
    retained = {
        key: value
        for key, value in record.items()
        if key not in {"geometry", "bbox", "sources"}
    }
    return json.dumps(retained, default=str, separators=(",", ":"))


def get_net_from_records(
    segment_records: Iterable[Mapping[str, Any]],
    connector_records: Iterable[Mapping[str, Any]] | None = None,
    *,
    mode_types: str | Sequence[str] = "auto",
    network_types: str | Sequence[str] | None = None,
    link_types: str | Sequence[str] = (),
    split_at_property_changes: bool = True,
    road_defaults: Mapping[str, Mapping[str, object]] | None = None,
    retain_raw_properties: bool = False,
) -> Network:
    """Convert in-memory Overture segment/connector records into a GMNS network.

    Parameters
    ----------
    segment_records : iterable of mapping
        Overture ``segment`` records (shapely geometry under ``"geometry"``).
    connector_records : iterable of mapping, optional
        Overture ``connector`` point records. When given, connector geometry is
        authoritative for shared GMNS node coordinates.
    mode_types : str or sequence of str
        Transportation modes to include, mirroring ``osm2gmns.getNetFromFile``.
        Options: 'auto', 'bus', 'truck', 'bike', 'walk'.
    network_types : str or sequence of str, optional
        Backward-compatible alias for ``mode_types`` (osm2gmns 0.x naming).
        Takes precedence when provided.
    link_types : str or sequence of str
        Filter segments to these Overture road classes (e.g. 'motorway',
        'primary'). Empty means all classes.
    split_at_property_changes : bool
        Split segments where scoped properties (speed, access, ...) change so
        each GMNS link has homogeneous attributes.
    road_defaults : mapping, optional
        Per-class overrides for implied speed/lanes/capacity/modes; merged over
        :data:`overture2gmns.defaults.ROAD_DEFAULTS`.
    retain_raw_properties : bool
        Keep the full Overture property payload on each link as JSON.
    """
    modes_input = network_types if network_types is not None else mode_types
    requested_modes = tuple(dict.fromkeys(str(mode).lower() for mode in _as_tuple(modes_input)))
    if not requested_modes:
        raise ValueError("At least one mode type is required.")
    invalid_modes = set(requested_modes) - SUPPORTED_MODES
    if invalid_modes:
        raise ValueError(f"Unsupported mode types: {sorted(invalid_modes)}")

    requested_link_types = {str(item).lower() for item in _as_tuple(link_types)}

    defaults = dict(ROAD_DEFAULTS)
    if road_defaults:
        defaults.update({key: dict(value) for key, value in road_defaults.items()})

    connector_points: dict[str, Point] = {}
    for record in connector_records or []:
        connector_id = record.get("id")
        geometry = record.get("geometry")
        if connector_id is not None and isinstance(geometry, Point):
            connector_points[str(connector_id)] = geometry

    network = Network()
    network.diagnostics = defaultdict(int)
    node_by_key: dict[str, Node] = {}
    next_node_id = 1
    next_link_id = 1

    def ensure_node(key: str, point: Point, connector_id: str | None) -> Node:
        nonlocal next_node_id
        existing = node_by_key.get(key)
        if existing is not None:
            if abs(existing.x_coord - point.x) > 1e-6 or abs(existing.y_coord - point.y) > 1e-6:
                network.diagnostics["connector_coordinate_conflicts"] += 1
            return existing
        node = Node(
            node_id=next_node_id,
            x_coord=float(point.x),
            y_coord=float(point.y),
            geometry=point.wkt,
            node_type="intersection" if connector_id else "attribute_change",
            overture_connector_id=connector_id or "",
            source_key=key,
        )
        network.nodes[node.node_id] = node
        node_by_key[key] = node
        next_node_id += 1
        return node

    for record_input in segment_records:
        record = dict(record_input)
        for key in NESTED_PROPERTIES:
            if isinstance(record.get(key), str):
                parsed = coerce_struct(record[key])
                if isinstance(parsed, str):
                    network.diagnostics[f"unparseable_nested_{key}"] += 1
                record[key] = parsed
        geometry = record.get("geometry")
        if not isinstance(geometry, LineString) or geometry.is_empty:
            network.diagnostics["skipped_invalid_geometry"] += 1
            continue
        if str(record.get("subtype") or "road") != "road":
            network.diagnostics["skipped_non_road"] += 1
            continue

        segment_id = _feature_id(record)
        road_class = str(record.get("class") or "unknown")
        if requested_link_types and road_class.lower() not in requested_link_types:
            network.diagnostics["skipped_filtered_link_type"] += 1
            continue
        class_defaults = defaults.get(road_class, defaults["unknown"])
        implied_modes = set(class_defaults.get("modes", set()))
        breakpoints = _breakpoints(record, split_at_property_changes)

        for start_lr, end_lr in zip(breakpoints, breakpoints[1:]):
            if end_lr - start_lr <= 1e-10:
                continue

            def _record_disposition(status: str) -> None:
                network.interval_dispositions.append({
                    "overture_segment_id": segment_id,
                    "lr_start": float(start_lr), "lr_end": float(end_lr),
                    "disposition": status,
                })

            subline = substring(geometry, start_lr, end_lr, normalized=True)
            if isinstance(subline, LineString):
                subline = _clean_linestring(subline)
            if not isinstance(subline, LineString) or subline.length == 0:
                network.diagnostics["skipped_zero_length_piece"] += 1
                _record_disposition("EXCLUDED_ZERO_LENGTH")
                continue

            start_connector = _connector_at(record, start_lr)
            end_connector = _connector_at(record, end_lr)
            start_point = connector_points.get(start_connector) if start_connector else None
            end_point = connector_points.get(end_connector) if end_connector else None
            if start_point is None:
                start_point = geometry.interpolate(start_lr, normalized=True)
            if end_point is None:
                end_point = geometry.interpolate(end_lr, normalized=True)

            start_key = f"connector:{start_connector}" if start_connector else _synthetic_node_key(segment_id, start_lr)
            end_key = f"connector:{end_connector}" if end_connector else _synthetic_node_key(segment_id, end_lr)
            start_node = ensure_node(start_key, start_point, start_connector)
            end_node = ensure_node(end_key, end_point, end_connector)
            midpoint = (start_lr + end_lr) / 2.0
            made = {"forward": False, "backward": False}

            for heading in ("forward", "backward"):
                allowed = []
                for mode in requested_modes:
                    if access_allowed(
                        record.get("access_restrictions"),
                        lr=midpoint,
                        heading=heading,
                        mode=mode,
                        default_allowed=mode in implied_modes,
                    ):
                        allowed.append(mode)
                if not allowed:
                    continue
                made[heading] = True

                representative_mode = "auto" if "auto" in allowed else allowed[0]
                speed = speed_limit_mph(
                    record.get("speed_limits"),
                    lr=midpoint,
                    heading=heading,
                    mode=representative_mode,
                )
                speed_source = "overture" if speed is not None else "inferred_class_default"
                if speed is None:
                    speed = float(class_defaults["speed_mph"])

                if heading == "forward":
                    from_node, to_node = start_node, end_node
                    directed_geometry = subline
                    dir_flag = 1
                else:
                    from_node, to_node = end_node, start_node
                    directed_geometry = LineString(list(subline.coords)[::-1])
                    dir_flag = -1

                link = Link(
                    link_id=next_link_id,
                    name=_name(record),
                    from_node_id=from_node.node_id,
                    to_node_id=to_node.node_id,
                    directed=True,
                    geometry=directed_geometry.wkt,
                    dir_flag=dir_flag,
                    length=line_length_miles(directed_geometry),
                    facility_type=_facility_type(record, midpoint),
                    # GMNS 'capacity' is TOTAL link capacity (osm2gmns and the
                    # TAPLite kernel convention); class defaults are per-lane.
                    capacity=float(class_defaults["capacity"]) * int(class_defaults["lanes"]),
                    free_speed=float(speed),
                    lanes=int(class_defaults["lanes"]),
                    allowed_uses=",".join(allowed),
                    overture_class=road_class,
                    overture_segment_id=segment_id,
                    overture_version=int(record["version"]) if record.get("version") is not None else None,
                    overture_lr_start=float(start_lr),
                    overture_lr_end=float(end_lr),
                    overture_heading=heading,
                    speed_source=speed_source,
                    lanes_source="inferred_class_default",
                    capacity_source="inferred_class_default",
                    raw_properties=_raw_json(record) if retain_raw_properties else "",
                )
                network.links[link.link_id] = link
                next_link_id += 1

            if made["forward"] and made["backward"]:
                _record_disposition("GENERATED_BOTH")
            elif made["forward"]:
                _record_disposition("GENERATED_FORWARD")
            elif made["backward"]:
                _record_disposition("GENERATED_BACKWARD")
            else:
                # Valid geometry, but no requested mode is permitted in either
                # direction — an explicit source access exclusion, not a loss.
                _record_disposition("EXCLUDED_BY_ACCESS_RULE")

        if record.get("prohibited_transitions"):
            network.diagnostics["segments_with_unexported_turn_restrictions"] += 1
        for restriction in as_rule_list(record.get("access_restrictions")):
            if has_conditional_scope(restriction.get("when")):
                network.diagnostics["conditional_access_rules_not_resolved"] += 1
        for speed_rule in as_rule_list(record.get("speed_limits")):
            if has_conditional_scope(speed_rule.get("when")):
                network.diagnostics["conditional_speed_rules_not_resolved"] += 1

    network.diagnostics = dict(network.diagnostics)
    network.diagnostics.update(
        {
            "node_count": network.number_of_nodes,
            "link_count": network.number_of_links,
            "requested_modes": list(requested_modes),
            "requested_link_types": sorted(requested_link_types),
            "length_unit": "mile",
            "speed_unit": "mph",
        }
    )
    return network


def get_net_from_file(
    segment_file: str | Path,
    connector_file: str | Path | None = None,
    **kwargs: Any,
) -> Network:
    """Parse local Overture files and create a GMNS network.

    Mirrors ``osm2gmns.getNetFromFile``; see :func:`get_net_from_records` for
    the keyword arguments (``mode_types``, ``link_types``, ...).
    """
    segments = load_overture_records(segment_file)
    connectors = load_overture_records(connector_file) if connector_file else None
    return get_net_from_records(segments, connectors, **kwargs)


def get_net_from_bbox(
    bbox: Sequence[float],
    *,
    download_connectors: bool = True,
    release: str | None = None,
    stac: bool = False,
    **kwargs: Any,
) -> Network:
    """Download Overture transportation data for a bbox and convert it."""
    if len(bbox) != 4:
        raise ValueError("bbox must be (west, south, east, north)")
    from .downloader import download_overture_geodataframes

    frames = download_overture_geodataframes(
        bbox,
        feature_types=("segment", "connector") if download_connectors else ("segment",),
        release=release,
        stac=stac,
    )
    connector_gdf = frames.get("connector")
    return get_net_from_records(
        records_from_geodataframe(frames["segment"]),
        records_from_geodataframe(connector_gdf) if connector_gdf is not None else None,
        **kwargs,
    )


# Compatibility aliases patterned after osm2gmns.
getNetFromFile = get_net_from_file
getNetFromBBox = get_net_from_bbox
