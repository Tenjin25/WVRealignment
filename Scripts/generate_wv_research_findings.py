#!/usr/bin/env python
"""Generate West Virginia-focused research findings from aggregated election JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import pstdev


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate WV research findings from aggregated election JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("Data") / "wv_election_results_aggregated.json",
        help="Aggregated input JSON file.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("Data") / "wv_research_findings.md",
        help="Output Markdown findings file.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("Data") / "wv_research_findings.json",
        help="Output structured findings JSON file.",
    )
    parser.add_argument(
        "--focus-contest",
        default="president",
        help="Contest key to use for county realignment findings.",
    )
    parser.add_argument(
        "--recent-year",
        type=int,
        default=None,
        help="Optional explicit year for latest snapshot; defaults to max year in data.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_county_results_for_contest(
    data: dict, year: int, contest_type: str
) -> dict[str, dict]:
    year_key = str(year)
    year_block = data.get("results_by_year", {}).get(year_key, {})
    contest_block = year_block.get(contest_type, {})
    if not contest_block:
        return {}
    first_key = next(iter(contest_block.keys()))
    return contest_block[first_key].get("results", {})


def statewide_from_counties(counties: dict[str, dict]) -> dict[str, float]:
    dem = sum(int(v.get("dem_votes", 0)) for v in counties.values())
    rep = sum(int(v.get("rep_votes", 0)) for v in counties.values())
    other = sum(int(v.get("other_votes", 0)) for v in counties.values())
    total = sum(int(v.get("total_votes", 0)) for v in counties.values())
    two_party = dem + rep
    margin = dem - rep
    margin_pct = round((margin / two_party * 100.0), 2) if two_party else 0.0
    winner = "DEM" if margin > 0 else "REP" if margin < 0 else "TIE"
    return {
        "dem_votes": dem,
        "rep_votes": rep,
        "other_votes": other,
        "total_votes": total,
        "two_party_total": two_party,
        "margin": margin,
        "margin_pct": margin_pct,
        "winner": winner,
    }


def sort_presidential_shifts(
    earliest: dict[str, dict], latest: dict[str, dict]
) -> tuple[list[dict], list[dict]]:
    shared = sorted(set(earliest.keys()) & set(latest.keys()))
    shifts: list[dict] = []
    for county in shared:
        e_margin = float(earliest[county].get("margin_pct", 0.0))
        l_margin = float(latest[county].get("margin_pct", 0.0))
        shifts.append(
            {
                "county": county,
                "earliest_margin_pct": round(e_margin, 2),
                "latest_margin_pct": round(l_margin, 2),
                "shift_toward_dem_pct": round(l_margin - e_margin, 2),
            }
        )
    shifts_dem = sorted(shifts, key=lambda x: x["shift_toward_dem_pct"], reverse=True)
    shifts_rep = sorted(shifts, key=lambda x: x["shift_toward_dem_pct"])
    return shifts_rep, shifts_dem


def county_volatility_by_presidential_year(
    data: dict, presidential_years: list[int]
) -> list[dict]:
    county_series: dict[str, list[float]] = {}
    for year in presidential_years:
        counties = get_county_results_for_contest(data, year, "president")
        for county, rec in counties.items():
            county_series.setdefault(county, []).append(float(rec.get("margin_pct", 0.0)))

    out = []
    for county, margins in county_series.items():
        if len(margins) < 2:
            continue
        out.append(
            {
                "county": county,
                "n_elections": len(margins),
                "margin_stddev": round(pstdev(margins), 2),
                "avg_margin_pct": round(sum(margins) / len(margins), 2),
            }
        )
    return sorted(out, key=lambda x: x["margin_stddev"], reverse=True)


def build_contest_narratives(data: dict, years: list[int], contests: list[str]) -> list[dict]:
    out: list[dict] = []
    for contest in contests:
        contest_years = [y for y in years if get_county_results_for_contest(data, y, contest)]
        if not contest_years:
            continue

        first_year = contest_years[0]
        last_year = contest_years[-1]
        first_state = statewide_from_counties(
            get_county_results_for_contest(data, first_year, contest)
        )
        last_counties = get_county_results_for_contest(data, last_year, contest)
        last_state = statewide_from_counties(last_counties)
        shift = round(last_state["margin_pct"] - first_state["margin_pct"], 2)

        strongest_latest = sorted(
            [
                {
                    "county": county,
                    "winner": rec.get("winner", "TIE"),
                    "margin_pct": float(rec.get("margin_pct", 0.0)),
                }
                for county, rec in last_counties.items()
            ],
            key=lambda x: abs(x["margin_pct"]),
            reverse=True,
        )[:5]

        trend_word = "toward Democrats" if shift > 0 else "toward Republicans" if shift < 0 else "flat"
        description = (
            f"In {contest}, statewide two-party margin moved from {fmt_margin(first_state['margin_pct'])} "
            f"in {first_year} to {fmt_margin(last_state['margin_pct'])} in {last_year}, "
            f"a {abs(shift):.2f}-point shift {trend_word}."
        )

        out.append(
            {
                "contest_type": contest,
                "years_covered": contest_years,
                "first_year": first_year,
                "last_year": last_year,
                "first_statewide": first_state,
                "last_statewide": last_state,
                "shift_toward_dem_pct": shift,
                "strongest_counties_latest": strongest_latest,
                "description": description,
            }
        )
    return out


def build_year_summaries(data: dict, years: list[int]) -> list[dict]:
    out: list[dict] = []
    for year in years:
        contests = sorted(data.get("results_by_year", {}).get(str(year), {}).keys())
        if not contests:
            continue
        snapshots = []
        for contest in contests:
            state = statewide_from_counties(get_county_results_for_contest(data, year, contest))
            snapshots.append(
                {
                    "contest_type": contest,
                    "winner": state["winner"],
                    "margin_pct": state["margin_pct"],
                }
            )
        snapshots_sorted = sorted(snapshots, key=lambda x: abs(x["margin_pct"]), reverse=True)
        overview = "; ".join(
            [f"{s['contest_type']} {s['winner']} {fmt_margin(s['margin_pct'])}" for s in snapshots_sorted[:4]]
        )
        out.append({"year": year, "contest_results": snapshots, "summary": overview})
    return out


def fmt_margin(value: float) -> str:
    party = "D" if value > 0 else "R" if value < 0 else "T"
    return f"{party}{abs(value):.2f}"


def build_markdown(findings: dict) -> str:
    lines: list[str] = []
    lines.append("# West Virginia Election Research Findings")
    lines.append("")
    lines.append(
        f"- Coverage years: {findings['metadata']['years'][0]} to {findings['metadata']['years'][-1]}"
    )
    lines.append(f"- Counties in dataset: {findings['metadata']['counties_count']}")
    lines.append(f"- Contests: {', '.join(findings['metadata']['contests'])}")
    lines.append("")

    lines.append("## Key Findings")
    lines.append(
        f"- Focus contest `{findings['focus_contest']}` shifted from "
        f"{fmt_margin(findings['focus_earliest_statewide']['margin_pct'])} in {findings['focus_earliest_year']} "
        f"to {fmt_margin(findings['focus_latest_statewide']['margin_pct'])} in {findings['focus_latest_year']}."
    )
    lines.append(
        f"- Net statewide movement toward Democrats across focus years: "
        f"{findings['focus_statewide_shift_toward_dem_pct']:+.2f} points."
    )
    lines.append(
        f"- Latest presidential winner: {findings['latest_presidential_statewide']['winner']} "
        f"({fmt_margin(findings['latest_presidential_statewide']['margin_pct'])})."
    )
    lines.append("")

    lines.append("## Presidential Statewide Trend")
    lines.append("")
    lines.append("| Year | Winner | Margin | DEM Votes | REP Votes |")
    lines.append("|---|---|---:|---:|---:|")
    for row in findings["presidential_statewide_by_year"]:
        lines.append(
            f"| {row['year']} | {row['winner']} | {fmt_margin(row['margin_pct'])} | "
            f"{row['dem_votes']:,} | {row['rep_votes']:,} |"
        )
    lines.append("")

    lines.append("## Biggest County Shifts (Focus Contest)")
    lines.append("")
    lines.append("### Toward Republican")
    for row in findings["top_shift_toward_republican"][:10]:
        lines.append(
            f"- {row['county']}: {fmt_margin(row['earliest_margin_pct'])} -> "
            f"{fmt_margin(row['latest_margin_pct'])} "
            f"({row['shift_toward_dem_pct']:+.2f} toward DEM)"
        )
    lines.append("")
    lines.append("### Toward Democratic")
    for row in findings["top_shift_toward_democratic"][:10]:
        lines.append(
            f"- {row['county']}: {fmt_margin(row['earliest_margin_pct'])} -> "
            f"{fmt_margin(row['latest_margin_pct'])} "
            f"({row['shift_toward_dem_pct']:+.2f} toward DEM)"
        )
    lines.append("")

    lines.append(f"## {findings['recent_year']} Snapshot By Contest")
    for row in findings["recent_year_contest_snapshot"]:
        lines.append(
            f"- {row['contest_type']}: {row['winner']} {fmt_margin(row['margin_pct'])} "
            f"(DEM {row['dem_votes']:,}, REP {row['rep_votes']:,})"
        )
    lines.append("")

    lines.append("## Most Volatile Counties (Presidential)")
    for row in findings["most_volatile_counties"][:10]:
        lines.append(
            f"- {row['county']}: stdev {row['margin_stddev']:.2f}, "
            f"average margin {fmt_margin(row['avg_margin_pct'])} "
            f"across {row['n_elections']} elections"
        )
    lines.append("")

    lines.append("## Detailed Description")
    for paragraph in findings["detailed_description"]["overview_paragraphs"]:
        lines.append(paragraph)
        lines.append("")

    lines.append("### Contest Narratives")
    for item in findings["detailed_description"]["contest_narratives"]:
        lines.append(
            f"- {item['contest_type']}: {item['description']}"
        )
        top = ", ".join(
            [f"{c['county']} ({fmt_margin(c['margin_pct'])})" for c in item["strongest_counties_latest"][:3]]
        )
        if top:
            lines.append(f"  Latest strongest counties: {top}.")
    lines.append("")

    lines.append("### Year-by-Year Highlights")
    for row in findings["detailed_description"]["year_summaries"]:
        lines.append(f"- {row['year']}: {row['summary']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    data = load_json(args.input)
    metadata = data.get("metadata", {})
    years = sorted(int(y) for y in metadata.get("years", []))
    if not years:
        raise ValueError("No years found in metadata.")

    focus_contest = args.focus_contest
    focus_years = [y for y in years if get_county_results_for_contest(data, y, focus_contest)]
    if len(focus_years) < 2:
        raise ValueError(
            f"Need at least two years for contest '{focus_contest}'. Found: {focus_years}"
        )

    focus_earliest_year = focus_years[0]
    focus_latest_year = focus_years[-1]
    focus_earliest = get_county_results_for_contest(data, focus_earliest_year, focus_contest)
    focus_latest = get_county_results_for_contest(data, focus_latest_year, focus_contest)
    focus_earliest_statewide = statewide_from_counties(focus_earliest)
    focus_latest_statewide = statewide_from_counties(focus_latest)
    focus_shift = round(
        focus_latest_statewide["margin_pct"] - focus_earliest_statewide["margin_pct"], 2
    )
    top_rep_shift, top_dem_shift = sort_presidential_shifts(focus_earliest, focus_latest)

    presidential_years = [y for y in years if get_county_results_for_contest(data, y, "president")]
    presidential_statewide = []
    for y in presidential_years:
        state = statewide_from_counties(get_county_results_for_contest(data, y, "president"))
        presidential_statewide.append({"year": y, **state})

    recent_year = args.recent_year if args.recent_year else years[-1]
    recent_contests = sorted(data.get("results_by_year", {}).get(str(recent_year), {}).keys())
    recent_snapshot = []
    for contest in recent_contests:
        state = statewide_from_counties(get_county_results_for_contest(data, recent_year, contest))
        recent_snapshot.append({"contest_type": contest, **state})

    latest_pres_state = {}
    if presidential_years:
        latest_pres_state = statewide_from_counties(
            get_county_results_for_contest(data, presidential_years[-1], "president")
        )

    contest_narratives = build_contest_narratives(data, years, metadata.get("contests", []))
    year_summaries = build_year_summaries(data, years)
    overview_paragraphs = [
        (
            f"This WV-focused dataset covers {years[0]} through {years[-1]} with county-level "
            f"returns harmonized across multiple historical source formats."
        ),
        (
            "Margins are calculated as Democratic minus Republican two-party margin percentage; "
            "positive values indicate a Democratic edge and negative values indicate a Republican edge."
        ),
        (
            "Contest narratives below describe first-to-latest statewide movement and identify the "
            "counties with the largest absolute margins in the most recent available year."
        ),
    ]

    findings = {
        "metadata": {
            "years": years,
            "counties_count": metadata.get("counties_count"),
            "contests": metadata.get("contests", []),
            "source_file": str(args.input),
        },
        "focus_contest": focus_contest,
        "focus_earliest_year": focus_earliest_year,
        "focus_latest_year": focus_latest_year,
        "focus_earliest_statewide": focus_earliest_statewide,
        "focus_latest_statewide": focus_latest_statewide,
        "focus_statewide_shift_toward_dem_pct": focus_shift,
        "presidential_statewide_by_year": presidential_statewide,
        "latest_presidential_statewide": latest_pres_state,
        "top_shift_toward_republican": top_rep_shift,
        "top_shift_toward_democratic": top_dem_shift,
        "recent_year": recent_year,
        "recent_year_contest_snapshot": recent_snapshot,
        "most_volatile_counties": county_volatility_by_presidential_year(data, presidential_years),
        "detailed_description": {
            "overview_paragraphs": overview_paragraphs,
            "contest_narratives": contest_narratives,
            "year_summaries": year_summaries,
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    md = build_markdown(findings)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md, encoding="utf-8")

    print(f"Input: {args.input}")
    print(f"Output JSON: {args.output_json}")
    print(f"Output Markdown: {args.output_md}")
    print(f"Focus contest: {focus_contest}")
    print(f"Years analyzed: {years[0]}-{years[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
