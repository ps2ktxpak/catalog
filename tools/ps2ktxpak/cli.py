"""ps2ktxpak command line."""
from __future__ import annotations

import argparse
import json
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
    if a.what == "catalog":
        text = c.dumps_catalog(c.catalog(a.base_url))
        out = Path(a.out or DIST / "textures.json")
    else:
        text = json.dumps(c.links_v1(), indent=1, ensure_ascii=False) + "\n"
        out = Path(a.out or DIST / "texture-pack-links.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text.encode())} bytes)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ps2ktxpak", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="schemas, cross-references and hosting policy")
    p.add_argument("--strict-policy", action="store_true", help="fail on policy warnings too")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("report", help="read-only views")
    p.add_argument("which", choices=["summary", "paid-hosted", "credits"])
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("compile", help="build the files the app downloads into dist/")
    p.add_argument("what", choices=["catalog", "links"])
    p.add_argument("--base-url", default="https://dl.ps2ktxpak.net")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_compile)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
