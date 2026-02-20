#!/usr/bin/env python
"""Convert Clarity county-level CSV into OpenElections county format."""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


OFFICE_MAP = {
    "U.S. PRESIDENT": "President",
    "U.S. SENATOR": "U.S. Senate",
    "U.S. HOUSE OF REPRESENTATIVES": "U.S. House",
    "STATE SENATOR": "State Senate",
    "HOUSE OF DELEGATES": "House of Delegates",
    "GOVERNOR": "Governor",
    "SECRETARY OF STATE": "Secretary of State",
    "AUDITOR": "Auditor",
    "TREASURER": "Treasurer",
    "COMMISSIONER OF AGRICULTURE": "Commissioner of Agriculture",
    "ATTORNEY GENERAL": "Attorney General",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert results_by_county.csv to OpenElections county CSV"
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        type=Path,
        help="Path to results_by_county.csv (defaults to latest clarity folder)",
    )
    parser.add_argument("--date", default="20241105", help="Election date as YYYYMMDD")
    parser.add_argument("--state", default="wv", help="State postal abbreviation")
    parser.add_argument("--election", default="general", help="Election type")
    parser.add_argument(
        "--out",
        type=Path,
        help="Output path (default: Data/openelections-data-wv/<year>/<file>.csv)",
    )
    parser.add_argument(
        "--include-statewide",
        action="store_true",
        help="Include blank-county statewide aggregate rows",
    )
    return parser.parse_args()


def find_latest_results_by_county() -> Path | None:
    root = Path("Data") / "clarity"
    if not root.exists():
        return None
    dirs = [p for p in root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    latest = max(dirs, key=lambda p: p.stat().st_mtime)
    p = latest / "results_by_county.csv"
    return p if p.exists() else None


def normalize_office_and_district(contest: str) -> tuple[str, str]:
    contest = (contest or "").strip()
    if not contest:
        return "", ""

    if contest.startswith("Amendment"):
        return contest, ""

    head = contest
    tail = ""
    if "," in contest:
        head, tail = [x.strip() for x in contest.split(",", 1)]

    office = OFFICE_MAP.get(head, head.title() if head.isupper() else head)
    district = ""

    if tail:
        m = re.search(r"(\d+)(?:st|nd|rd|th)\s+Congressional District", tail, flags=re.I)
        if m:
            district = m.group(1)
        else:
            m = re.search(r"(\d+)(?:st|nd|rd|th)\s+Senatorial District", tail, flags=re.I)
            if m:
                district = m.group(1)
            else:
                m = re.search(r"(\d+)(?:st|nd|rd|th)\s+District", tail, flags=re.I)
                if m:
                    district = m.group(1)
                else:
                    district = tail

    return office, district


def to_int(v: str) -> int:
    return int(round(float(v)))


def main() -> int:
    args = parse_args()

    input_csv = args.input_csv or find_latest_results_by_county()
    if input_csv is None or not input_csv.exists():
        print("Could not find results_by_county.csv. Pass input path explicitly.")
        return 1

    year = args.date[:4]
    default_name = f"{args.date}__{args.state.lower()}__{args.election.lower()}__county.csv"
    output = args.out or (Path("Data") / "openelections-data-wv" / year / default_name)
    output.parent.mkdir(parents=True, exist_ok=True)

    rows_out: list[dict[str, str | int]] = []
    aggregates: dict[tuple[str, str, str, str], int] = defaultdict(int)

    with input_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            office, district = normalize_office_and_district(row.get("contest", ""))
            county = (row.get("county") or "").strip()
            party = (row.get("party") or "").strip()
            candidate = (row.get("candidate") or "").strip()
            votes = to_int(row.get("votes", "0"))

            if not office or not candidate:
                continue

            rows_out.append(
                {
                    "county": county,
                    "office": office,
                    "district": district,
                    "party": party,
                    "candidate": candidate,
                    "votes": votes,
                }
            )
            aggregates[(office, district, party, candidate)] += votes

    if args.include_statewide:
        for (office, district, party, candidate), votes in aggregates.items():
            rows_out.append(
                {
                    "county": "",
                    "office": office,
                    "district": district,
                    "party": party,
                    "candidate": candidate,
                    "votes": votes,
                }
            )

    rows_out.sort(key=lambda r: (str(r["office"]), str(r["district"]), str(r["candidate"]), str(r["county"])))

    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["county", "office", "district", "party", "candidate", "votes"]
        )
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Input: {input_csv}")
    print(f"Output: {output}")
    print(f"Rows: {len(rows_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
