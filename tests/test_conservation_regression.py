"""Regression fixtures for the 3 Chicago interior-gap segments.

Root cause (2026-07-17): each has an Overture access_restriction denying
motor-vehicle access on a middle linear-reference stretch. The converter
correctly emits no auto link there; the interval is a classified
EXCLUDED_BY_ACCESS_RULE exclusion, NOT a lost interval. These fixtures pin
that behavior so the conservation invariant can never silently regress.
"""

from pathlib import Path

import pytest

import overture2gmns as o2g

FIXTURES = Path(__file__).parent / "fixtures"
CHICAGO = FIXTURES / "chicago_access_denied_segments.geojson"

# (segment id prefix, denied [start,end] on the mainline)
CASES = [
    ("dfc825a8", 0.0754, 0.9375),
    ("242584f1", 0.4330, 0.9481),
    ("5045486b", 0.2570, 0.3479),
]


@pytest.fixture()
def chicago_net(tmp_path):
    net = o2g.get_net_from_file(CHICAGO, mode_types="auto")
    o2g.output_net_to_csv(net, tmp_path)
    return net, tmp_path


def test_access_denied_segments_pass_conservation(chicago_net):
    _, folder = chicago_net
    result = o2g.verify_conversion(folder)
    # No UNACCOUNTED interior holes — the middle stretches are classified.
    assert result["lr_coverage"]["interior_conservation_failures"] == 0
    assert result["passed"] is True


def test_middle_intervals_are_access_excluded(chicago_net):
    _, folder = chicago_net
    result = o2g.verify_conversion(folder)
    counts = result["lr_coverage"]["disposition_counts"]
    # Every one of the 3 denied middle stretches is an explicit exclusion.
    assert counts.get("EXCLUDED_BY_ACCESS_RULE", 0) >= 3
    assert result["lr_coverage"]["access_excluded_informational"] >= 3


@pytest.mark.parametrize("prefix,denied_start,denied_end", CASES)
def test_no_auto_link_spans_denied_stretch(chicago_net, prefix, denied_start, denied_end):
    net, _ = chicago_net
    seg = next(sid for sid in {l.overture_segment_id for l in net.links.values()}
               if sid.startswith(prefix))
    mid = (denied_start + denied_end) / 2.0
    spanning = [l for l in net.links.values()
                if l.overture_segment_id == seg
                and l.overture_lr_start <= mid <= l.overture_lr_end]
    assert spanning == [], f"a link crosses the access-denied stretch of {prefix}"


def test_every_candidate_interval_has_disposition(chicago_net):
    net, folder = chicago_net
    # Reconstructed link count from dispositions must equal actual links.
    result = o2g.verify_conversion(folder)
    assert result["integrity"].get("disposition_link_mismatch", 0) == 0
    # And every interval carries exactly one known disposition.
    known = {"GENERATED_BOTH", "GENERATED_FORWARD", "GENERATED_BACKWARD",
             "EXCLUDED_BY_ACCESS_RULE", "EXCLUDED_ZERO_LENGTH"}
    assert all(d["disposition"] in known for d in net.interval_dispositions)
