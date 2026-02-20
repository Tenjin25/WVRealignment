#!/usr/bin/env python
"""Convert an ESRI Shapefile (.shp) to GeoJSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    import shapefile
except ModuleNotFoundError:
    print(
        "Missing dependency: pyshp. Install with: .\\.venv\\Scripts\\python -m pip install pyshp",
        file=sys.stderr,
    )
    raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a .shp file to GeoJSON.")
    parser.add_argument("input_shp", type=Path, help="Path to input .shp file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .geojson path (defaults next to input file)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_shp = args.input_shp

    if not input_shp.exists():
        print(f"Input file not found: {input_shp}", file=sys.stderr)
        return 1
    if input_shp.suffix.lower() != ".shp":
        print(f"Input must be a .shp file: {input_shp}", file=sys.stderr)
        return 1

    output = args.output or input_shp.with_suffix(".geojson")
    output.parent.mkdir(parents=True, exist_ok=True)

    reader = shapefile.Reader(str(input_shp))
    feature_collection = reader.__geo_interface__

    with output.open("w", encoding="utf-8") as f:
        json.dump(feature_collection, f)

    print(f"Wrote GeoJSON: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
