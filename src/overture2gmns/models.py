"""Core in-memory network objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Node:
    node_id: int
    x_coord: float
    y_coord: float
    geometry: str
    node_type: str = "intersection"
    activity_type: str = ""
    is_boundary: int | str = ""
    zone_id: int | str = ""
    intersection_id: int | str = ""
    ctrl_type: str = ""
    overture_connector_id: str = ""
    source_key: str = ""


@dataclass(slots=True)
class Link:
    link_id: int
    name: str
    from_node_id: int
    to_node_id: int
    directed: bool
    geometry: str
    dir_flag: int
    length: float
    facility_type: str
    capacity: float
    free_speed: float
    lanes: int
    allowed_uses: str
    overture_class: str
    overture_segment_id: str
    overture_version: int | None
    overture_lr_start: float
    overture_lr_end: float
    overture_heading: str
    speed_source: str
    lanes_source: str
    capacity_source: str
    raw_properties: str = ""


@dataclass
class Network:
    nodes: dict[int, Node] = field(default_factory=dict)
    links: dict[int, Link] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    # One disposition record per candidate interval (source-to-output audit):
    # {overture_segment_id, lr_start, lr_end, disposition}. Lets verification
    # prove every eligible interval is accounted for.
    interval_dispositions: list = field(default_factory=list)

    @property
    def number_of_nodes(self) -> int:
        return len(self.nodes)

    @property
    def number_of_links(self) -> int:
        return len(self.links)
