from pathlib import Path

import overture2gmns as o2g

FIXTURES = Path(__file__).parent / "fixtures"


def _net(tmp_path):
    net = o2g.get_net_from_file(
        FIXTURES / "segments.geojson", FIXTURES / "connectors.geojson",
        mode_types="auto")
    o2g.output_net_to_csv(net, tmp_path)
    return tmp_path


def test_verify_conversion_passes_on_fixture(tmp_path):
    result = o2g.verify_conversion(_net(tmp_path))
    assert result["passed"] is True
    assert result["integrity"]["invalid_node_references"] == 0
    assert result["integrity"]["missing_source_crosswalk"] == 0
    assert result["integrity"]["duplicate_link_ids"] == 0


def test_lr_conservation_tiles_unit_interval(tmp_path):
    result = o2g.verify_conversion(_net(tmp_path))
    lr = result["lr_coverage"]
    # The union of directed pieces of every segment must tile [0,1].
    assert lr["interior_conservation_failures"] == 0
    assert lr["clean_union_tiling"] == lr["segments_checked"]


def test_one_way_segment_still_passes_conservation(tmp_path):
    # Main Street is one-way (backward denied): its backward heading has no
    # links at all, yet the forward pieces tile [0,1], so union conservation
    # holds and verification PASSES. A one-way stretch is never an error.
    result = o2g.verify_conversion(_net(tmp_path))
    assert result["passed"] is True
    assert result["lr_coverage"]["interior_conservation_failures"] == 0


def test_provenance_reports_observed_vs_defaulted(tmp_path):
    result = o2g.verify_conversion(_net(tmp_path))
    # Main Street has Overture speed limits (observed); capacity is always default.
    assert result["attribute_status"]["speed"]["exact_pct"] > 0
    assert result["attribute_status"]["capacity"]["defaulted_pct"] == 100.0


def test_report_markdown_renders(tmp_path):
    result = o2g.verify_conversion(_net(tmp_path))
    md = o2g.verification_report_markdown(result)
    assert "Conversion verification report" in md
    assert "PASS" in md
