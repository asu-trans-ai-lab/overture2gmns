"""overture2gmns public API.

Converts Overture Maps transportation data to GMNS networks with a
user-facing API patterned after osm2gmns.
"""

from .converter import (
    get_net_from_bbox,
    get_net_from_file,
    get_net_from_records,
    getNetFromBBox,
    getNetFromFile,
)
from .downloader import download_overture_data, downloadOvertureData
from .io import output_net_to_csv, outputNetToCSV
from .models import Link, Network, Node
from .postprocess import (
    consolidate_complex_intersections,
    consolidateComplexIntersections,
    fill_link_attributes_with_default_values,
    fillLinkAttributesWithDefaultValues,
    generate_node_activity_info,
    generateNodeActivityInfo,
)
from .verification import verify_conversion, verification_report_markdown

__all__ = [
    "Link",
    "Network",
    "Node",
    # snake_case API
    "get_net_from_bbox",
    "get_net_from_file",
    "get_net_from_records",
    "output_net_to_csv",
    "download_overture_data",
    "fill_link_attributes_with_default_values",
    "generate_node_activity_info",
    "consolidate_complex_intersections",
    # osm2gmns-style aliases
    "getNetFromBBox",
    "getNetFromFile",
    "outputNetToCSV",
    "downloadOvertureData",
    "fillLinkAttributesWithDefaultValues",
    "generateNodeActivityInfo",
    "consolidateComplexIntersections",
    # source-to-output conversion verification (in-scope QA)
    "verify_conversion",
    "verification_report_markdown",
]

__version__ = "0.2.0"
