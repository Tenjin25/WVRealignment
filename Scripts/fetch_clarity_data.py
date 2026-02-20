#!/usr/bin/env python
"""Fetch election payloads from a Clarity Elections URL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; WVRealignment/1.0; +https://example.local)"
TIMEOUT = 20

KEYWORDS = (
    "api",
    "json",
    "election",
    "contest",
    "summary",
    "result",
    "county",
    "precinct",
    "jurisdiction",
    "turnout",
    "report",
    "state",
)

KNOWN_ENDPOINTS = (
    "/json/en/electionsettings.json",
    "/json/en/summary.json",
    "/json/en/contests.json",
    "/json/en/results.json",
    "/json/en/status.json",
    "/json/en/electionsettings.js",
    "/json/en/summary.js",
    "/json/en/contests.js",
    "/json/en/results.js",
    "/api/state",
    "/api/summary",
    "/api/results",
    "/api/contests",
    "/api/electionsettings",
)

CORE_FILES = (
    "config.json",
    "colors.json",
    "details.json",
    "status.json",
    "sum.json",
    "vt.json",
    "contestdistrictconfig.json",
    "multicountycontestconfig.json",
    "nav.json",
    "scrollingpagesettings.json",
    "sp.json",
    "summary-details.json",
    "vc.json",
    "vc_status.json",
)

LANG_FILES = (
    "electionsettings.json",
    "summary.json",
)


def fetch_url(url: str) -> tuple[int, bytes, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
            content_type = resp.headers.get("Content-Type", "")
            return status, resp.read(), content_type
    except HTTPError as e:
        return e.code, b"", e.headers.get("Content-Type", "")
    except URLError:
        return 0, b"", ""


def read_json(url: str) -> tuple[int, dict]:
    status, content, _ = fetch_url(url)
    if status != 200 or not content:
        return status, {}
    try:
        return status, json.loads(content.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return status, {}


def normalize_web_base(url: str) -> str:
    p = urlparse(url)
    path = p.path or "/"
    if not path.endswith("/"):
        path = path.rsplit("/", 1)[0] + "/"
    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def election_root(web_base: str) -> str | None:
    p = urlparse(web_base)
    m = re.match(r"^(.*?/[^/]+/?)web\.[^/]+/$", p.path)
    if not m:
        return None
    root_path = m.group(1)
    if not root_path.endswith("/"):
        root_path += "/"
    return urlunparse((p.scheme, p.netloc, root_path, "", "", ""))


def origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/"


def extract_script_urls(index_html: str, web_base: str) -> list[str]:
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', index_html, flags=re.IGNORECASE)
    urls = [urljoin(web_base, s) for s in srcs]
    return sorted(set(urls))


def extract_endpoint_candidates(js_text: str) -> list[str]:
    candidates: set[str] = set(KNOWN_ENDPOINTS)

    quoted_paths = re.findall(r"""['"](/[^'"\\\s]{1,180})['"]""", js_text)
    quoted_rel = re.findall(r"""['"](api/[^'"\\\s]{1,180})['"]""", js_text)

    for item in quoted_paths + ["/" + x for x in quoted_rel]:
        lower = item.lower()
        if not any(k in lower for k in KEYWORDS):
            continue
        if re.search(r"\.(js|css|png|jpg|jpeg|svg|ico|map|woff2?|ttf|html)$", lower):
            continue
        candidates.add(item)

    return sorted(candidates)


def likely_json(content: bytes, content_type: str) -> bool:
    if not content:
        return False
    preview = content[:300].lstrip()
    ctype = content_type.lower()
    if "text/html" in ctype or preview.startswith(b"<!doctype html"):
        return False
    if "json" in ctype:
        return True
    if preview.startswith((b"{", b"[")):
        return True
    if preview.startswith((b"var ", b"let ", b"const ")):
        return True
    return False


def safe_slug(url: str) -> str:
    p = urlparse(url)
    combined = (p.netloc + p.path).strip("/").replace("/", "_")
    combined = re.sub(r"[^A-Za-z0-9._-]+", "_", combined)
    return combined[:120] or "clarity"


def save_payload(out_dir: Path, url: str, payload: bytes, ctype: str, seen_hashes: set[str], index: int) -> dict | None:
    digest = hashlib.sha256(payload).hexdigest()
    if digest in seen_hashes:
        return None
    seen_hashes.add(digest)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", urlparse(url).path.strip("/")) or "root"
    out_file = out_dir / f"{index:04d}_{name}.json"
    out_file.write_bytes(payload)
    return {
        "url": url,
        "status": 200,
        "content_type": ctype,
        "file": str(out_file),
        "sha256": digest,
    }


def build_probe_urls(base_urls: Iterable[str], endpoint_candidates: Iterable[str]) -> list[str]:
    urls: set[str] = set()
    for base in base_urls:
        base = base if base.endswith("/") else base + "/"
        base_origin = origin(base)
        for ep in endpoint_candidates:
            if ep.startswith("http://") or ep.startswith("https://"):
                urls.add(ep)
            elif ep.startswith("/"):
                urls.add(urljoin(base_origin, ep.lstrip("/")))
            else:
                urls.add(urljoin(base, ep))
    return sorted(urls)


def deterministic_download(web_base: str, out_dir: Path, seen_hashes: set[str], start_index: int) -> tuple[int, list[dict], dict]:
    metadata: dict = {"mode": "deterministic_v4", "web_base": web_base}
    downloads: list[dict] = []
    i = start_index

    web_json_url = urljoin(web_base, "web.json")
    status, web_config = read_json(web_json_url)
    metadata["web_json_url"] = web_json_url
    metadata["web_json_status"] = status
    if status != 200 or not web_config:
        return i, downloads, metadata

    state = str(web_config.get("State", "")).strip()
    county = str(web_config.get("County", "")).strip()
    eid = str(web_config.get("EID", "")).strip()
    json_uri = str(web_config.get("jsonUri", "")).strip() or origin(web_base)
    metadata["state"] = state
    metadata["county"] = county
    metadata["eid"] = eid
    metadata["json_uri"] = json_uri
    if not (state and eid):
        return i, downloads, metadata

    county_seg = f"/{county}" if county else ""
    root = f"{json_uri.rstrip('/')}/{state}{county_seg}/{eid}"
    version_url = f"{root}/current_ver.txt"
    s_ver, version_raw, _ = fetch_url(version_url)
    version = version_raw.decode("utf-8", errors="ignore").strip() if s_ver == 200 else ""
    metadata["version_url"] = version_url
    metadata["version_status"] = s_ver
    metadata["version"] = version
    if not version:
        return i, downloads, metadata

    json_root = f"{root}/{version}/json"
    metadata["json_root"] = json_root

    config_url = f"{json_root}/config.json"
    s_cfg, cfg = read_json(config_url)
    lang = str(cfg.get("lang", "")).strip()
    metadata["config_url"] = config_url
    metadata["config_status"] = s_cfg
    metadata["lang"] = lang

    targets: list[str] = [f"{json_root}/{f}" for f in CORE_FILES]
    for fname in LANG_FILES:
        targets.append(f"{json_root}/{fname}")
        if lang:
            targets.append(f"{json_root}/{lang}/{fname}")

    for target in targets:
        s, content, ctype = fetch_url(target)
        if s != 200 or not likely_json(content, ctype):
            continue
        saved = save_payload(out_dir, target, content, ctype, seen_hashes, i)
        if saved:
            downloads.append(saved)
            i += 1

    return i, downloads, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch likely Clarity election payloads.")
    parser.add_argument("url", help="Clarity election URL (page or ngsw.json URL)")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=Path("Data") / "clarity",
        help="Output directory root",
    )
    args = parser.parse_args()

    web_base = normalize_web_base(args.url)
    root = election_root(web_base)
    base_urls = [web_base, origin(web_base)]
    if root:
        base_urls.append(root)

    status, index_bytes, _ = fetch_url(urljoin(web_base, "index.html"))
    if status != 200 or not index_bytes:
        print(f"Could not load index.html from {web_base} (status={status})")
        return 1

    index_text = index_bytes.decode("utf-8", errors="ignore")
    script_urls = extract_script_urls(index_text, web_base)

    endpoint_candidates: set[str] = set(KNOWN_ENDPOINTS)
    discovered_config_values: set[str] = set()

    for script_url in script_urls:
        s, content, _ = fetch_url(script_url)
        if s != 200 or not content:
            continue
        text = content.decode("utf-8", errors="ignore")
        endpoint_candidates.update(extract_endpoint_candidates(text))
        for key in ("apiUri", "jsonUri", "api_uri", "json_uri"):
            for match in re.findall(rf"{key}['\"]?\s*[:=]\s*['\"]([^'\"\\s]+)['\"]", text):
                discovered_config_values.add(match)

    for v in sorted(discovered_config_values):
        if v.startswith("http://") or v.startswith("https://"):
            base_urls.append(v)
        elif v.startswith("/"):
            base_urls.append(urljoin(origin(web_base), v.lstrip("/")))
        else:
            base_urls.append(urljoin(web_base, v))

    slug = safe_slug(web_base)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir / f"{slug}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source_url": args.url,
        "web_base": web_base,
        "downloaded": [],
        "attempted_at_utc": ts,
    }
    seen_hashes: set[str] = set()
    idx = 1

    idx, deterministic_files, deterministic_meta = deterministic_download(web_base, out_dir, seen_hashes, idx)
    manifest["deterministic"] = deterministic_meta
    manifest["downloaded"].extend(deterministic_files)

    probe_urls = build_probe_urls(sorted(set(base_urls)), sorted(endpoint_candidates))
    manifest["probe_count"] = len(probe_urls)

    for url in probe_urls:
        status, content, ctype = fetch_url(url)
        if status != 200 or not likely_json(content, ctype):
            continue
        saved = save_payload(out_dir, url, content, ctype, seen_hashes, idx)
        if saved:
            manifest["downloaded"].append(saved)
            idx += 1

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Deterministic files: {len(deterministic_files)}")
    print(f"Probe URLs: {len(probe_urls)}")
    print(f"Downloaded files: {len(manifest['downloaded'])}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
