#!/usr/bin/env python
"""Build static WV findings card HTML into index.html from findings JSON."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path


def party_margin(value: float) -> str:
    if value > 0:
        return f"D+{abs(value):.2f}"
    if value < 0:
        return f"R+{abs(value):.2f}"
    return "T+0.00"


def ul(items: list[str]) -> str:
    if not items:
        return "<ul style='margin:0;padding-left:18px;'><li>Not available.</li></ul>"
    return "<ul style='margin:0;padding-left:18px;'>" + "".join(items) + "</ul>"


def set_div_content(html_text: str, div_id: str, content: str) -> str:
    pattern = rf"(<div id=\"{re.escape(div_id)}\">)(.*?)(</div>)"
    return re.sub(pattern, rf"\1{content}\3", html_text, flags=re.DOTALL)


def main() -> int:
    findings_path = Path("Data") / "wv_research_findings.json"
    index_path = Path("index.html")
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    index_html = index_path.read_text(encoding="utf-8")

    meta = findings.get("metadata", {})
    detail = findings.get("detailed_description", {})
    years = meta.get("years", [])
    coverage = f"{years[0]}-{years[-1]}" if years else "N/A"
    focus = findings.get("focus_contest", "N/A")
    shift = float(findings.get("focus_statewide_shift_toward_dem_pct", 0))
    first_year = findings.get("focus_earliest_year", "N/A")
    last_year = findings.get("focus_latest_year", "N/A")
    pres = findings.get("latest_presidential_statewide", {})

    summary_html = f"""
<p><strong>Coverage:</strong> {html.escape(coverage)} ({meta.get('counties_count', 'N/A')} counties)</p>
<ul style="margin:0;padding-left:18px;">
  <li><strong>Focus Contest:</strong> {html.escape(str(focus))}</li>
  <li><strong>Statewide Shift:</strong> {shift:.2f} points toward DEM from {first_year} to {last_year}</li>
  <li><strong>Latest Presidential:</strong> {html.escape(str(pres.get('winner', 'N/A')))} {party_margin(float(pres.get('margin_pct', 0)))}</li>
</ul>
""".strip()

    overview = "".join(
        f"<p>{html.escape(p)}</p>" for p in detail.get("overview_paragraphs", [])
    )
    narratives = []
    for n in detail.get("contest_narratives", [])[:10]:
        top = ", ".join(
            f"{html.escape(str(c.get('county', '')))} ({party_margin(float(c.get('margin_pct', 0)))})"
            for c in n.get("strongest_counties_latest", [])[:3]
        )
        narratives.append(
            "<div style='margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #e5e7eb;'>"
            f"<p style='margin:0 0 4px 0;'><strong>{html.escape(str(n.get('contest_type', '')))}</strong></p>"
            f"<p style='margin:0 0 4px 0;'>{html.escape(str(n.get('description', '')))}</p>"
            f"<p style='margin:0;color:#4b5563;'><em>Strongest recent counties:</em> {html.escape(top or 'N/A')}</p>"
            "</div>"
        )
    detail_html = (
        overview
        + "<h6 style='margin:12px 0 6px 0;'>Contest Narratives</h6>"
        + ("".join(narratives) if narratives else "<p>No detailed narratives available.</p>")
    )

    rep_items = [
        f"<li>{html.escape(str(r.get('county', '')))}: {party_margin(float(r.get('earliest_margin_pct', 0)))} -> {party_margin(float(r.get('latest_margin_pct', 0)))} ({float(r.get('shift_toward_dem_pct', 0)):.2f} toward DEM)</li>"
        for r in findings.get("top_shift_toward_republican", [])[:5]
    ]
    dem_items = [
        f"<li>{html.escape(str(r.get('county', '')))}: {party_margin(float(r.get('earliest_margin_pct', 0)))} -> {party_margin(float(r.get('latest_margin_pct', 0)))} ({float(r.get('shift_toward_dem_pct', 0)):.2f} toward DEM)</li>"
        for r in findings.get("top_shift_toward_democratic", [])[:5]
    ]
    year_items = [
        f"<li><strong>{y.get('year', '')}:</strong> {html.escape(str(y.get('summary', '')))}</li>"
        for y in list(detail.get("year_summaries", []))[-8:][::-1]
    ]
    year_html = (
        "<h6 style='margin:0 0 6px 0;'>Largest Shifts Toward Republican</h6>"
        + ul(rep_items)
        + "<h6 style='margin:12px 0 6px 0;'>Largest Shifts Toward Democratic</h6>"
        + ul(dem_items)
        + "<h6 style='margin:12px 0 6px 0;'>Recent Year Summaries</h6>"
        + ul(year_items)
    )

    index_html = set_div_content(index_html, "wv-research-findings-content", summary_html)
    index_html = set_div_content(index_html, "wv-detailed-description-content", detail_html)
    index_html = set_div_content(index_html, "wv-year-highlights-content", year_html)

    index_path.write_text(index_html, encoding="utf-8")
    print("Updated static WV findings cards in index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

