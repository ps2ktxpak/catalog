"""ps2ktxpak command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common import DIST


def cmd_validate(a) -> int:
    from . import validate
    return validate.run(strict_policy=a.strict_policy)


def cmd_report(a) -> int:
    from . import report
    print(report.REPORTS[a.which]())
    return 0


def cmd_compile(a) -> int:
    from . import compile as c
    text = c.dumps_catalog(c.catalog(a.base_url))
    out = Path(a.out or DIST / "catalog.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text.encode())} bytes)")
    return 0


def cmd_scrape(a) -> int:
    from .scrape import apply, job
    return {"job": job.main, "apply": apply.main}[a.what](a.rest)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ps2ktxpak", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="schemas, cross-references and hosting policy")
    p.add_argument("--strict-policy", action="store_true", help="fail on policy warnings too")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("report", help="read-only views")
    p.add_argument("which", choices=["summary", "paid-hosted", "credits"])
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("compile", help="build the file the app downloads, dist/catalog.json")
    p.add_argument("what", choices=["catalog"])
    p.add_argument("--base-url", default="https://dl.ps2ktxpak.net")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_compile)

    p = sub.add_parser("scrape", help="the Texture Packs Archive scraper: `job` downloads and converts, `apply` writes the results")
    p.add_argument("what", choices=["job", "apply"])
    p.add_argument("rest", nargs=argparse.REMAINDER, help="that command's own options (--help lists them)")
    p.set_defaults(fn=cmd_scrape)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
