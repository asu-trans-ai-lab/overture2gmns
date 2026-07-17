"""Input and GMNS output helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from shapely.geometry import shape

from .models import Network


def load_geojson_features(path: str | Path) -> list[dict[str, Any]]:
    """Load a GeoJSON FeatureCollection or newline-delimited GeoJSON features."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] == "{":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
            return list(payload.get("features") or [])
        if isinstance(payload, dict) and payload.get("type") == "Feature":
            return [payload]
    features: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            features.append(json.loads(line))
    return features


def normalized_feature(feature: dict[str, Any]) -> dict[str, Any]:
    """Flatten a GeoJSON feature into an Overture-like record."""
    properties = dict(feature.get("properties") or {})
    feature_id = feature.get("id") or properties.get("id")
    if feature_id is not None:
        properties["id"] = str(feature_id)
    geometry_value = feature.get("geometry")
    properties["geometry"] = shape(geometry_value) if geometry_value else None
    return properties


def records_from_geodataframe(gdf: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for _, row in gdf.iterrows():
        record = row.to_dict()
        records.append(record)
    return records


def _records_from_parquet(file_path: Path, batch_size: int = 8192):
    """Stream records from (Geo)Parquet without materializing the file.

    Works on both geopandas-written GeoParquet and raw Arrow parquet from
    Overture's record_batch_reader (geometry arrives as WKB either way).
    """
    try:
        import pyarrow.parquet as pq
        from shapely import from_wkb
    except ImportError as exc:
        raise ImportError(
            "GeoParquet input requires 'pip install overture2gmns[geoparquet]'."
        ) from exc

    parquet_file = pq.ParquetFile(file_path)
    for batch in parquet_file.iter_batches(batch_size=batch_size):
        for row in batch.to_pylist():
            geometry = row.get("geometry")
            if isinstance(geometry, (bytes, bytearray)):
                row["geometry"] = from_wkb(bytes(geometry))
            yield row


def load_overture_records(path: str | Path):
    """Read local Overture GeoJSON/GeoJSONSeq or GeoParquet records.

    GeoParquet is streamed lazily (safe for metro-scale extracts); GeoJSON is
    materialized in memory.
    """
    file_path = Path(path)
    if file_path.suffix.lower() in {".parquet", ".geoparquet"}:
        return _records_from_parquet(file_path)
    return [normalized_feature(feature) for feature in load_geojson_features(file_path)]


NODE_FIELDS = [
    "node_id", "x_coord", "y_coord", "geometry", "node_type", "ctrl_type",
    "activity_type", "is_boundary", "zone_id", "intersection_id",
    "overture_connector_id", "source_key",
]

LINK_FIELDS = [
    "link_id", "name", "from_node_id", "to_node_id", "directed", "geometry",
    "dir_flag", "length", "facility_type", "capacity", "free_speed", "lanes",
    "allowed_uses", "vdf_length_mi", "vdf_free_speed_mph",
    "overture_class", "overture_segment_id", "overture_version",
    "overture_lr_start", "overture_lr_end", "overture_heading", "speed_source",
    "lanes_source", "capacity_source", "raw_properties",
]


def output_net_to_csv(network: Network, output_folder: str | Path = "") -> Path:
    """Write ``node.csv``, ``link.csv``, and ``diagnostics.json`` in GMNS format.

    Mirrors ``osm2gmns.outputNetToCSV``: an empty ``output_folder`` writes to
    the current working directory.
    """
    output_path = Path(output_folder) if str(output_folder) else Path.cwd()
    output_path.mkdir(parents=True, exist_ok=True)

    with (output_path / "node.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=NODE_FIELDS)
        writer.writeheader()
        for node in network.nodes.values():
            writer.writerow({field: getattr(node, field) for field in NODE_FIELDS})

    with (output_path / "link.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LINK_FIELDS)
        writer.writeheader()
        # Sorted by from_node_id: GMNS validators and the TAPLite kernel
        # expect forward-star ordering.
        for link in sorted(
            network.links.values(), key=lambda item: (item.from_node_id, item.to_node_id)
        ):
            row = {field: getattr(link, field, "") for field in LINK_FIELDS}
            # Explicit dual-unit columns (MAG/ASU GMNS convention). Package
            # units are already miles/mph, so these mirror length/free_speed.
            row["vdf_length_mi"] = link.length
            row["vdf_free_speed_mph"] = link.free_speed
            writer.writerow(row)

    # Interval-disposition audit: one row per candidate interval, so
    # verification can prove every eligible interval is accounted for.
    dispositions = getattr(network, "interval_dispositions", [])
    if dispositions:
        with (output_path / "interval_disposition.csv").open(
                "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=["overture_segment_id", "lr_start", "lr_end", "disposition"])
            writer.writeheader()
            writer.writerows(dispositions)

    (output_path / "diagnostics.json").write_text(
        json.dumps(network.diagnostics, indent=2, sort_keys=True), encoding="utf-8"
    )
    return output_path


# Compatibility alias patterned after osm2gmns.
outputNetToCSV = output_net_to_csv
