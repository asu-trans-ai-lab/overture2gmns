"""Command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from .converter import get_net_from_bbox, get_net_from_file
from .io import output_net_to_csv


def _modes(value: str) -> tuple[str, ...]:
    modes = tuple(item.strip() for item in value.split(",") if item.strip())
    if not modes:
        raise argparse.ArgumentTypeError("At least one mode is required.")
    return modes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overture2gmns")
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert_parser = subparsers.add_parser("convert", help="Convert local Overture GeoJSON or GeoParquet")
    convert_parser.add_argument("--segments", required=True, type=Path)
    convert_parser.add_argument("--connectors", type=Path)
    convert_parser.add_argument("--output", required=True, type=Path)
    convert_parser.add_argument("--modes", type=_modes, default=("auto",))
    convert_parser.add_argument("--link-types", type=_modes, default=(),
                                help="Comma-separated Overture road classes to keep (default: all)")
    convert_parser.add_argument("--retain-raw-properties", action="store_true")

    download_parser = subparsers.add_parser("download", help="Download by bbox and convert")
    download_parser.add_argument("--bbox", required=True, nargs=4, type=float, metavar=("W", "S", "E", "N"))
    download_parser.add_argument("--output", required=True, type=Path)
    download_parser.add_argument("--modes", type=_modes, default=("auto",))
    download_parser.add_argument("--link-types", type=_modes, default=(),
                                 help="Comma-separated Overture road classes to keep (default: all)")
    download_parser.add_argument("--no-connectors", action="store_true")
    download_parser.add_argument("--release", help="Overture release; default is latest")
    download_parser.add_argument("--stac", action="store_true", help="Use the STAC file index")

    verify_parser = subparsers.add_parser(
        "verify", help="Source-to-output conversion verification of a GMNS folder")
    verify_parser.add_argument("gmns_folder", type=Path)
    verify_parser.add_argument("--report", type=Path,
                               help="write the markdown report to this path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "verify":
        from .verification import verify_conversion, verification_report_markdown

        result = verify_conversion(args.gmns_folder)
        report = verification_report_markdown(result)
        if args.report:
            args.report.write_text(report, encoding="utf-8")
        print(report)
        raise SystemExit(0 if result["passed"] else 1)

    if args.command == "convert":
        network = get_net_from_file(
            args.segments,
            args.connectors,
            mode_types=args.modes,
            link_types=args.link_types,
            retain_raw_properties=args.retain_raw_properties,
        )
    else:
        network = get_net_from_bbox(
            args.bbox,
            mode_types=args.modes,
            link_types=args.link_types,
            download_connectors=not args.no_connectors,
            release=args.release,
            stac=args.stac,
        )
    path = output_net_to_csv(network, args.output)
    print(f"Wrote {network.number_of_nodes} nodes and {network.number_of_links} links to {path}")


if __name__ == "__main__":
    main()
