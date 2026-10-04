"""ps2ktxpak command line."""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

from .common import CACHE, DIST, USER_AGENT, today

SHEET_ID = "1sif8FeRGJRbytK8wFRXgF6Hke9V6GUFs"  # Sad Origami's Texture Packs Archive
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"


def _fetch_sheet(retrieved: str) -> Path:
    dest = CACHE / f"sheet-{retrieved}.xlsx"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(SHEET_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    return dest


def cmd_import_sheet(a) -> int:
    from . import import_sheet
    retrieved = a.retrieved or today()
    path = Path(a.xlsx) if a.xlsx else _fetch_sheet(retrieved)
    s = import_sheet.run(path, retrieved, a.tab)
    print(f"listings {s['listings']}, creators {s['creators']}, cost {s['cost']}")
    for c in s["conflicts"]:
        print("conflict:", c)
    return 0


def cmd_import_legacy(a) -> int:
    from . import import_legacy
    s = import_legacy.run(a.base_url, a.retrieved or today(), a.offline)
    print({k: v for k, v in s.items() if k != "conflicts"})
    for c in s["conflicts"]:
        print("conflict:", c)
    return 0


def cmd_link_listings(a) -> int:
    from . import link_listings
    s = link_listings.run()
    print(f"matched {s['matched']} packs ({s['lines']} lines); unmatched {len(s['unmatched'])}; ambiguous {len(s['ambiguous'])}")
    return 0


def cmd_validate(a) -> int:
    from . import validate
    return validate.run(strict_policy=a.strict_policy)


def cmd_report(a) -> int:
    from . import report
    print(report.REPORTS[a.which]())
    return 0


def cmd_compile(a) -> int:
    from . import compile as c
    import json
    if a.what == "catalog":
        text = c.dumps_catalog(c.catalog(a.mode, a.base_url))
        out = Path(a.out or DIST / "textures.json")
    else:
        text = json.dumps(c.links_v1(), indent=1, ensure_ascii=False) + "\n"
        out = Path(a.out or DIST / "texture-pack-links.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text.encode())} bytes)")
    return 0


def cmd_seed(a) -> int:
    for fn, ns in ((cmd_import_sheet, argparse.Namespace(xlsx=a.xlsx, retrieved=a.retrieved, tab="PS2")),
                   (cmd_import_legacy, argparse.Namespace(base_url=a.base_url, retrieved=a.retrieved, offline=a.offline)),
                   (cmd_link_listings, argparse.Namespace()),
                   (cmd_validate, argparse.Namespace(strict_policy=False))):
        rc = fn(ns)
        if rc:
            return rc
    return 0


def cmd_resolve_plan(a) -> int:
    from . import resolve
    print(resolve.plan_text())
    return 0


def cmd_resolve_fetch(a) -> int:
    from . import resolve
    return resolve.fetch_all(limit=a.limit, only=a.url, retrieved=a.retrieved or today(),
                             yt_dlp=a.yt_dlp, delay=a.delay, refresh=a.refresh)


def cmd_resolve_brief(a) -> int:
    from . import resolve
    return resolve.write_brief(a.name, a.url, a.limit_chars)


def cmd_resolve_apply(a) -> int:
    from . import resolve
    return resolve.apply_decisions(Path(a.file), model=a.model, retrieved=a.retrieved or today())


def cmd_media_fetch(a) -> int:
    from . import media
    print(media.run(a.retrieved or today(), delay=a.delay, limit=a.limit, refresh=a.refresh))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ps2ktxpak", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import-sheet", help="ingest the spreadsheet's PS2 tab into data/listings and data/creators")
    p.add_argument("--xlsx", help="a downloaded workbook; default: download the live sheet")
    p.add_argument("--retrieved", help="date to record (YYYY-MM-DD); default today")
    p.add_argument("--tab", default="PS2")
    p.set_defaults(fn=cmd_import_sheet)

    p = sub.add_parser("import-legacy", help="one-time seed of packs and archives from the live catalog")
    p.add_argument("--base-url", default="https://dl.ps2ktxpak.net")
    p.add_argument("--offline", action="store_true", help="use cache/live only")
    p.add_argument("--retrieved")
    p.set_defaults(fn=cmd_import_legacy)

    sub.add_parser("link-listings", help="match sheet listings to hosted packs").set_defaults(fn=cmd_link_listings)

    p = sub.add_parser("validate", help="schemas, cross-references and hosting policy")
    p.add_argument("--strict-policy", action="store_true", help="fail on policy warnings too")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("report", help="read-only views")
    p.add_argument("which", choices=["summary", "paid-hosted", "unmatched", "credits"])
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("compile", help="build the files the app downloads into dist/")
    p.add_argument("what", choices=["catalog", "links"])
    p.add_argument("--mode", choices=["cleaned", "faithful"], default="cleaned")
    p.add_argument("--base-url", default="https://dl.ps2ktxpak.net")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_compile)

    p = sub.add_parser("seed", help="import-sheet, import-legacy, link-listings, validate")
    p.add_argument("--xlsx")
    p.add_argument("--base-url", default="https://dl.ps2ktxpak.net")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--retrieved")
    p.set_defaults(fn=cmd_seed)

    sub.add_parser("resolve-plan", help="which source pages need following").set_defaults(fn=cmd_resolve_plan)

    p = sub.add_parser("resolve-fetch", help="deterministic pass: fetch pages, extract links, record candidates")
    p.add_argument("--limit", type=int, help="stop after this many pages")
    p.add_argument("--url", action="append", help="only this source page (repeatable)")
    p.add_argument("--yt-dlp", default="yt-dlp", help="path to yt-dlp")
    p.add_argument("--delay", type=float, default=1.5, help="seconds between requests to one site")
    p.add_argument("--refresh", action="store_true", help="ignore cached pages")
    p.add_argument("--retrieved")
    p.set_defaults(fn=cmd_resolve_fetch)

    p = sub.add_parser("resolve-brief", help="write an evidence file for an agent to judge")
    p.add_argument("name")
    p.add_argument("--url", action="append", required=True)
    p.add_argument("--limit-chars", type=int, default=3500)
    p.set_defaults(fn=cmd_resolve_brief)

    p = sub.add_parser("resolve-apply", help="merge an agent's or a person's decisions into data/resolution")
    p.add_argument("file")
    p.add_argument("--model", default="unspecified")
    p.add_argument("--retrieved")
    p.set_defaults(fn=cmd_resolve_apply)

    p = sub.add_parser("media-fetch", help="seed example pictures and YouTube ids onto hosted packs from their threads")
    p.add_argument("--limit", type=int)
    p.add_argument("--delay", type=float, default=1.5)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--retrieved")
    p.set_defaults(fn=cmd_media_fetch)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
