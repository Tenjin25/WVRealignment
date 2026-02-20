#!/usr/bin/env python
"""Flatten Clarity election JSON payloads into CSV outputs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Clarity JSON files to flat CSV."
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        help="Path to a downloaded Clarity folder under Data/clarity",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output CSV path (default depends on level)",
    )
    parser.add_argument(
        "--level",
        choices=["state", "county"],
        default="state",
        help="state=contest/candidate totals, county=contest/county/candidate rows",
    )
    return parser.parse_args()


def find_latest_clarity_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    dirs = [p for p in root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def pick_input_file(folder: Path, name_hint: str) -> Path | None:
    candidates = sorted(folder.glob("*.json"))
    filtered = [
        p
        for p in candidates
        if name_hint in p.name.lower() and "summary-details" not in p.name.lower()
    ]
    return filtered[0] if filtered else None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_contests(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        contests = payload.get("Contests")
        if isinstance(contests, list):
            return [c for c in contests if isinstance(c, dict)]
        return []
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict)]
    return []


def nval(arr: Any, i: int) -> Any:
    if isinstance(arr, list) and i < len(arr):
        return arr[i]
    return None


def build_contest_lookup(contests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for contest in contests:
        key = str(contest.get("K") or "")
        if not key:
            continue
        lookup[key] = contest
    return lookup


def flatten_state_contests(contests: list[dict[str, Any]], source_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for contest in contests:
        names = contest.get("CH", [])
        parties = contest.get("P", [])
        votes = contest.get("V", [])
        pcts = contest.get("PCT", [])
        wins = contest.get("W", [])
        choice_agg = contest.get("CHAggId", [])
        crc = contest.get("CRC", [])
        cro = contest.get("CRO", [])

        max_len = max(
            len(names) if isinstance(names, list) else 0,
            len(parties) if isinstance(parties, list) else 0,
            len(votes) if isinstance(votes, list) else 0,
            len(pcts) if isinstance(pcts, list) else 0,
            len(wins) if isinstance(wins, list) else 0,
            len(choice_agg) if isinstance(choice_agg, list) else 0,
            len(crc) if isinstance(crc, list) else 0,
            len(cro) if isinstance(cro, list) else 0,
            1,
        )

        for i in range(max_len):
            rows.append(
                {
                    "source": source_label,
                    "contest_key": contest.get("K"),
                    "contest_agg_id": contest.get("AggID"),
                    "category_key": contest.get("CATKEY"),
                    "category": contest.get("CAT"),
                    "contest": contest.get("C"),
                    "contest_total_votes": contest.get("T"),
                    "precincts_total": contest.get("TP"),
                    "precincts_reporting": contest.get("PR"),
                    "registered_voters": contest.get("regvoters"),
                    "ballots_cast": contest.get("BC"),
                    "candidate_index": i,
                    "candidate": nval(names, i),
                    "party": nval(parties, i),
                    "votes": nval(votes, i),
                    "pct": nval(pcts, i),
                    "winner_flag": nval(wins, i),
                    "choice_agg_id": nval(choice_agg, i),
                    "crc": nval(crc, i),
                    "cro": nval(cro, i),
                }
            )
    return rows


def flatten_county_contests(
    details_contests: list[dict[str, Any]], contest_lookup: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for contest in details_contests:
        key = str(contest.get("K") or "")
        meta = contest_lookup.get(key, {})

        contest_name = meta.get("C", contest.get("C"))
        category = meta.get("CAT", contest.get("CAT"))
        category_key = meta.get("CATKEY", contest.get("CATKEY"))

        candidate_names = meta.get("CH", [])
        candidate_parties = meta.get("P", []) if meta is not contest else []

        county_names = contest.get("P", [])
        county_votes = contest.get("V", [])
        county_totals = contest.get("T", [])
        county_eids = contest.get("Eid", [])
        county_cids = contest.get("Cid", [])
        county_px = contest.get("PX", [])
        county_py = contest.get("PY", [])

        county_len = len(county_names) if isinstance(county_names, list) else 0
        for county_i in range(county_len):
            county_name = nval(county_names, county_i)
            vote_vector = nval(county_votes, county_i)
            if not isinstance(vote_vector, list):
                vote_vector = []

            county_total = nval(county_totals, county_i)
            max_len = max(
                len(vote_vector),
                len(candidate_names) if isinstance(candidate_names, list) else 0,
                len(candidate_parties) if isinstance(candidate_parties, list) else 0,
                1,
            )

            for cand_i in range(max_len):
                votes = nval(vote_vector, cand_i)
                pct = None
                if isinstance(votes, (int, float)) and isinstance(county_total, (int, float)) and county_total:
                    pct = (votes / county_total) * 100

                rows.append(
                    {
                        "contest_key": key,
                        "contest": contest_name,
                        "category_key": category_key,
                        "category": category,
                        "county": county_name,
                        "county_eid": nval(county_eids, county_i),
                        "county_cid": nval(county_cids, county_i),
                        "county_precincts_total": nval(county_px, county_i),
                        "county_precincts_reporting": nval(county_py, county_i),
                        "county_total_votes": county_total,
                        "candidate_index": cand_i,
                        "candidate": nval(candidate_names, cand_i),
                        "party": nval(candidate_parties, cand_i),
                        "votes": votes,
                        "pct": pct,
                    }
                )

    return rows


def main() -> int:
    args = parse_args()
    clarity_root = Path("Data") / "clarity"
    input_dir = args.input_dir or find_latest_clarity_dir(clarity_root)
    if input_dir is None or not input_dir.exists():
        print("No input directory found. Provide one or download Clarity data first.")
        return 1

    summary_file = pick_input_file(input_dir, "summary")
    sum_file = pick_input_file(input_dir, "_sum")
    if sum_file is None:
        sum_file = pick_input_file(input_dir, "sum")
    details_file = pick_input_file(input_dir, "details")

    if args.level == "state":
        if summary_file is None and sum_file is None:
            print(f"No summary/sum JSON files found in: {input_dir}")
            return 1

        rows: list[dict[str, Any]] = []
        if summary_file is not None:
            rows.extend(flatten_state_contests(get_contests(load_json(summary_file)), "summary"))
        if sum_file is not None:
            rows.extend(flatten_state_contests(get_contests(load_json(sum_file)), "sum"))

        output = args.output or (input_dir / "results_flat.csv")
        fields = [
            "source",
            "contest_key",
            "contest_agg_id",
            "category_key",
            "category",
            "contest",
            "contest_total_votes",
            "precincts_total",
            "precincts_reporting",
            "registered_voters",
            "ballots_cast",
            "candidate_index",
            "candidate",
            "party",
            "votes",
            "pct",
            "winner_flag",
            "choice_agg_id",
            "crc",
            "cro",
        ]
    else:
        if details_file is None:
            print(f"No details JSON file found in: {input_dir}")
            return 1

        contest_lookup: dict[str, dict[str, Any]] = {}
        if summary_file is not None:
            contest_lookup.update(build_contest_lookup(get_contests(load_json(summary_file))))
        if sum_file is not None:
            fallback = build_contest_lookup(get_contests(load_json(sum_file)))
            for k, v in fallback.items():
                contest_lookup.setdefault(k, v)

        rows = flatten_county_contests(get_contests(load_json(details_file)), contest_lookup)
        output = args.output or (input_dir / "results_by_county.csv")
        fields = [
            "contest_key",
            "contest",
            "category_key",
            "category",
            "county",
            "county_eid",
            "county_cid",
            "county_precincts_total",
            "county_precincts_reporting",
            "county_total_votes",
            "candidate_index",
            "candidate",
            "party",
            "votes",
            "pct",
        ]

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Input dir: {input_dir}")
    print(f"Level: {args.level}")
    print(f"Wrote CSV: {output}")
    print(f"Rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
