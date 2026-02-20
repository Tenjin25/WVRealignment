#!/usr/bin/env python
"""Build WV aggregation JSON in a rich schema compatible with index.html."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

OFFICE_MAP = {
    "PRESIDENT": ("president", "President of the United States"),
    "U.S. PRESIDENT": ("president", "President of the United States"),
    "US PRESIDENT": ("president", "President of the United States"),
    "PRESIDENT OF THE UNITED STATES": ("president", "President of the United States"),
    "U.S. SENATE": ("us_senate", "United States Senator"),
    "US SENATE": ("us_senate", "United States Senator"),
    "SENATE": ("us_senate", "United States Senator"),
    "GOVERNOR": ("governor", "Governor"),
    "SECRETARY OF STATE": ("secretary_of_state", "Secretary of State"),
    "ATTORNEY GENERAL": ("attorney_general", "Attorney General"),
    "AUDITOR": ("auditor", "Auditor"),
    "STATE AUDITOR": ("auditor", "Auditor"),
    "AUDITOR OF STATE": ("auditor", "Auditor"),
    "TREASURER": ("state_treasurer", "State Treasurer"),
    "STATE TREASURER": ("state_treasurer", "State Treasurer"),
    "COMMISSIONER OF AGRICULTURE": (
        "commissioner_of_agriculture",
        "Commissioner of Agriculture",
    ),
    # Historical typo in some files
    "COMMISIONER OF AGRICULTURE": (
        "commissioner_of_agriculture",
        "Commissioner of Agriculture",
    ),
}

PARTY_MAP = {
    "D": "DEM",
    "DEM": "DEM",
    "DEMOCRAT": "DEM",
    "DEMOCRATIC": "DEM",
    "R": "REP",
    "REP": "REP",
    "REPUBLICAN": "REP",
    "LBN": "LIB",
    "LIB": "LIB",
    "LIBERTARIAN": "LIB",
    "MTN": "MTN",
    "MOUNTAIN": "MTN",
    "CST": "CST",
    "CONSTITUTION": "CST",
    "IND": "IND",
    "INDEPENDENT": "IND",
    "NON": "NPA",
    "NPA": "NPA",
    "NO AFFILIATION": "NPA",
}

COUNTY_ALIASES = {
    "glimer": "gilmer",
    "pocohontas": "pocahontas",
    "pocohantas": "pocahontas",
}


def county_norm_token(v: str) -> str:
    return re.sub(r"[^a-z]", "", (v or "").strip().lower())


def normalize_text(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip()).upper()


def normalize_office(v: str) -> str:
    return normalize_text(v).replace("  ", " ")


def normalize_party(v: str) -> str:
    p = normalize_text(v)
    if not p:
        return ""
    return PARTY_MAP.get(p, p)


def normalize_county_name(v: str) -> str:
    c = re.sub(r"\s+", " ", (v or "").strip())
    c = re.sub(r"\s+COUNTY$", "", c, flags=re.IGNORECASE)
    return c


def display_county_name(v: str) -> str:
    c = normalize_county_name(v)
    if not c:
        return c
    if c.isupper():
        t = c.title()
        # Preserve Mc* capitalization in title-cased uppercase inputs.
        t = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), t)
        return t
    return c


def county_key(v: str) -> str:
    return normalize_text(normalize_county_name(v))


def infer_county_from_filename(path: Path) -> str:
    # e.g. 20221108__wv__general__barbour__precinct.csv
    m = re.search(r"__([a-z]+(?:_[a-z]+)*)__precinct(?:\.+csv)?$", path.name.lower())
    if not m:
        return ""
    return display_county_name(m.group(1).replace("_", " "))


def extract_votes(row: dict[str, str]) -> int:
    lowered = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
    for key in ("votes", "total votes", "total_votes"):
        if key in lowered:
            return to_int(str(lowered[key]))
    return 0


def load_county_lookup(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    lookup: dict[str, str] = {}
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name = (
            props.get("NAME20")
            or props.get("COUNTYNAME")
            or props.get("NAME")
            or props.get("County")
            or ""
        )
        name = display_county_name(name)
        if not name:
            continue
        lookup[county_norm_token(name)] = name
    return lookup


def canonicalize_county_name(raw: str, county_lookup: dict[str, str]) -> str:
    c = normalize_county_name(raw)
    if not c:
        return ""
    if not county_lookup:
        return display_county_name(c)
    token = county_norm_token(c)
    token = COUNTY_ALIASES.get(token, token)
    return county_lookup.get(token, "")


def normalize_candidate_name(raw: str) -> str:
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s:
        return ""
    t = s.lower().title()
    # Preserve common name patterns.
    t = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), t)
    t = re.sub(r"\b(O')([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    # Roman numerals and suffixes.
    t = re.sub(r"\b(Ii|Iii|Iv|V|Vi|Vii|Viii|Ix|X)\b", lambda m: m.group(0).upper(), t)
    t = re.sub(r"\bJr\.?\b", "Jr.", t, flags=re.IGNORECASE)
    t = re.sub(r"\bSr\.?\b", "Sr.", t, flags=re.IGNORECASE)
    return t


def infer_year_from_filename(path: Path) -> str:
    m = re.match(r"^(\d{4})", path.name)
    if m:
        return m.group(1)
    parent_year = path.parent.name
    if re.match(r"^\d{4}$", parent_year):
        return parent_year
    raise ValueError(f"Cannot infer year from filename: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WV aggregated election JSON for map app")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional single input OpenElections county CSV",
    )
    parser.add_argument(
        "--input-glob",
        default=str(Path("Data") / "openelections-data-wv" / "*" / "*__wv__general__*.csv"),
        help="Glob for multi-year general CSV inputs",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=1950,
        help="Minimum year (inclusive) to include when using --input-glob",
    )
    parser.add_argument(
        "--min-counties-per-contest",
        type=int,
        default=20,
        help="Minimum number of counties required to keep a contest in a given year",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("Data") / "wv_election_results_aggregated.json",
        help="Output aggregation JSON path",
    )
    parser.add_argument(
        "--counties-geojson",
        type=Path,
        default=Path("Data") / "tl_2020_54_county20" / "tl_2020_54_county20.geojson",
        help="Optional county boundary GeoJSON used to validate canonical county names",
    )
    return parser.parse_args()


def to_int(v: str) -> int:
    v = (v or "").strip()
    if not v:
        return 0
    v = v.replace(",", "")
    if v in {"-", "--"}:
        return 0
    return int(round(float(v)))


def pick_top_candidate(entries: list[tuple[str, int]]) -> str:
    if not entries:
        return ""
    return max(entries, key=lambda x: x[1])[0]


def compute_competitiveness(margin_pct: float) -> dict[str, str]:
    abs_margin = abs(margin_pct)
    winner_party = "Democratic" if margin_pct > 0 else "Republican" if margin_pct < 0 else "Tie"
    code_prefix = "D" if margin_pct > 0 else "R" if margin_pct < 0 else "T"

    if abs_margin >= 40:
        category = f"Annihilation {winner_party}" if winner_party != "Tie" else "Tossup"
        code = f"{code_prefix}_ANNIHILATION" if code_prefix != "T" else "T_TOSSUP"
        color = "#08306b" if margin_pct > 0 else "#67000d" if margin_pct < 0 else "#f7f7f7"
    elif abs_margin >= 30:
        category = f"Dominant {winner_party}" if winner_party != "Tie" else "Tossup"
        code = f"{code_prefix}_DOMINANT" if code_prefix != "T" else "T_TOSSUP"
        color = "#08519c" if margin_pct > 0 else "#a50f15" if margin_pct < 0 else "#f7f7f7"
    elif abs_margin >= 20:
        category = f"Stronghold {winner_party}" if winner_party != "Tie" else "Tossup"
        code = f"{code_prefix}_STRONGHOLD" if code_prefix != "T" else "T_TOSSUP"
        color = "#3182bd" if margin_pct > 0 else "#cb181d" if margin_pct < 0 else "#f7f7f7"
    elif abs_margin >= 10:
        category = f"Safe {winner_party}" if winner_party != "Tie" else "Tossup"
        code = f"{code_prefix}_SAFE" if code_prefix != "T" else "T_TOSSUP"
        color = "#6baed6" if margin_pct > 0 else "#ef3b2c" if margin_pct < 0 else "#f7f7f7"
    elif abs_margin > 5.5:
        category = f"Likely {winner_party}" if winner_party != "Tie" else "Tossup"
        code = f"{code_prefix}_LIKELY" if code_prefix != "T" else "T_TOSSUP"
        color = "#9ecae1" if margin_pct > 0 else "#fb6a4a" if margin_pct < 0 else "#f7f7f7"
    elif abs_margin > 0.99:
        category = f"Lean {winner_party}" if winner_party != "Tie" else "Tossup"
        code = f"{code_prefix}_LEAN" if code_prefix != "T" else "T_TOSSUP"
        color = "#c6dbef" if margin_pct > 0 else "#fcae91" if margin_pct < 0 else "#f7f7f7"
    elif abs_margin >= 0.5:
        category = f"Tilt {winner_party}" if winner_party != "Tie" else "Tossup"
        code = f"{code_prefix}_TILT" if code_prefix != "T" else "T_TOSSUP"
        color = "#e1f5fe" if margin_pct > 0 else "#fee8c8" if margin_pct < 0 else "#f7f7f7"
    else:
        category = "Tossup"
        code = "T_TOSSUP"
        color = "#f7f7f7"

    return {
        "category": category,
        "party": winner_party if winner_party != "Tie" else "Tossup",
        "code": code,
        "color": color,
    }


def main() -> int:
    args = parse_args()
    county_lookup = load_county_lookup(args.counties_geojson)
    if args.input is not None:
        input_paths = [args.input]
    else:
        discovered = sorted(Path().glob(args.input_glob))
        by_year: dict[int, list[Path]] = defaultdict(list)
        for p in discovered:
            year = int(infer_year_from_filename(p))
            if year < args.min_year:
                continue
            by_year[year].append(p)

        input_paths = []
        for year in sorted(by_year.keys()):
            year_paths = by_year[year]
            has_county_file = any(p.name.lower().endswith("__county.csv") for p in year_paths)
            for p in year_paths:
                name = p.name.lower()
                if has_county_file and "precinct" in name:
                    continue
                input_paths.append(p)

    if not input_paths:
        raise FileNotFoundError(
            f"No input files found. --input={args.input} --input-glob={args.input_glob}"
        )

    # year -> contest_type -> county -> list[(party, candidate, votes)]
    grouped_by_year: dict[str, dict[str, dict[str, list[tuple[str, str, int]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # year -> contest_type -> contest display label
    contest_labels_by_year: dict[str, dict[str, str]] = defaultdict(dict)
    county_name_by_key: dict[str, str] = {}
    seen_entries: set[tuple[str, str, str, str, str, int]] = set()

    for input_path in input_paths:
        if not input_path.exists():
            raise FileNotFoundError(f"Input not found: {input_path}")
        year = infer_year_from_filename(input_path)
        with input_path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                county = (row.get("county") or "").strip()
                if not county:
                    county = infer_county_from_filename(input_path)
                county = canonicalize_county_name(county, county_lookup)
                office = normalize_office(row.get("office") or "")
                party = normalize_party(row.get("party") or "")
                candidate = normalize_candidate_name(row.get("candidate") or "")
                votes = extract_votes(row)

                if not county:
                    # Skip rows where county cannot be inferred.
                    continue
                if office not in OFFICE_MAP:
                    continue
                if not candidate:
                    continue

                ckey = county_key(county)
                if not ckey:
                    continue
                county_name_by_key.setdefault(ckey, display_county_name(county))

                contest_type, contest_name = OFFICE_MAP[office]
                dedupe_key = (year, contest_type, ckey, party, candidate, votes)
                if dedupe_key in seen_entries:
                    continue
                seen_entries.add(dedupe_key)
                contest_labels_by_year[year][contest_type] = contest_name
                grouped_by_year[year][contest_type][ckey].append((party, candidate, votes))

    results_by_year: dict[str, dict[str, dict[str, object]]] = {}
    all_contests: set[str] = set()
    years_with_data: list[int] = []
    counties_seen: set[str] = set()

    for year in sorted(grouped_by_year.keys()):
        year_grouped = grouped_by_year[year]
        if not year_grouped:
            continue
        results_for_year: dict[str, dict[str, object]] = {}

        for contest_type, county_rows in sorted(year_grouped.items()):
            if len(county_rows) < args.min_counties_per_contest:
                continue
            contest_name = contest_labels_by_year[year][contest_type]
            contest_key = f"{contest_type}_{year}"
            county_results: dict[str, dict[str, object]] = {}

            for ckey in sorted(county_rows.keys(), key=lambda x: county_name_by_key.get(x, x)):
                entries = county_rows[ckey]
                county = county_name_by_key.get(ckey, ckey.title())
                counties_seen.add(ckey)
                party_totals: dict[str, int] = defaultdict(int)
                for party, _candidate, votes in entries:
                    party_totals[party if party else "NONPARTISAN"] += votes

                dem_entries = [(cand, v) for party, cand, v in entries if party == "DEM"]
                rep_entries = [(cand, v) for party, cand, v in entries if party == "REP"]

                dem_votes = sum(v for _, v in dem_entries)
                rep_votes = sum(v for _, v in rep_entries)
                total_votes = sum(v for _p, _c, v in entries)
                two_party_total = dem_votes + rep_votes
                other_votes = max(0, total_votes - two_party_total)

                dem_candidate = pick_top_candidate(dem_entries)
                rep_candidate = pick_top_candidate(rep_entries)

                margin = dem_votes - rep_votes
                margin_pct = round((margin / two_party_total * 100.0), 2) if two_party_total else 0.0

                if dem_votes > rep_votes:
                    winner = "DEM"
                elif rep_votes > dem_votes:
                    winner = "REP"
                else:
                    winner = "TIE"

                county_results[county] = {
                    "county": county,
                    "contest": contest_name,
                    "year": year,
                    "dem_candidate": dem_candidate,
                    "rep_candidate": rep_candidate,
                    "dem_votes": dem_votes,
                    "rep_votes": rep_votes,
                    "other_votes": other_votes,
                    "total_votes": total_votes,
                    "two_party_total": two_party_total,
                    "margin": margin,
                    "margin_pct": margin_pct,
                    "winner": winner,
                    "competitiveness": compute_competitiveness(margin_pct),
                    "all_parties": dict(sorted(party_totals.items())),
                }

            results_for_year[contest_type] = {
                contest_key: {
                    "contest_name": contest_name,
                    "results": county_results,
                }
            }
            all_contests.add(contest_type)

        if results_for_year:
            years_with_data.append(int(year))
            results_by_year[year] = results_for_year

    output_obj = {
        "metadata": {
            "title": "West Virginia Election Results",
            "years": sorted(years_with_data),
            "contests": sorted(all_contests),
            "counties_count": len(counties_seen),
        },
        "results_by_year": results_by_year,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output_obj, f, indent=2)

    print("Inputs:")
    for p in input_paths:
        print(f"  - {p}")
    print(f"Output: {args.output}")
    print(f"Years: {sorted(years_with_data)}")
    print(f"Contests: {sorted(all_contests)}")
    print(f"Counties: {len(counties_seen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
