"""Write what a scrape found into the pack files, on a maintainer's machine.

It changes only what the scrape is the authority on:
  - a converted pack: `hosting` becomes `withheld` (we have it and do not serve it yet), the
    `archive` block is added, and the serial folders found in the download fill `game.serials`
    when the pack names none;
  - a link the host says is gone: `download.status` becomes `dead`.
Everything else is reported, never written: a pack someone has already changed (no longer
`listed`, or already has an archive) is left alone. Spreadsheet rows that match no pack are
listed for a person to look at."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..common import PACKS_DIR, load_yaml, write_yaml
from . import match, sheet

WITHHELD_REASON = "Downloaded and converted; not served until someone decides to host it."


def fetch_results(bucket: str, shards: int, out: Path) -> list[Path]:
    """Copy each shard's results/index-<i>.json out of R2 with wrangler (its own login, no keys here)."""
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(shards):
        dest = out / f"index-{i}.json"
        p = subprocess.run(["npx", "--yes", "wrangler@4.42.0", "r2", "object", "get",
                            f"{bucket}/results/index-{i}.json", "--remote", "--file", str(dest)],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if p.returncode:
            raise RuntimeError(f"could not fetch results/index-{i}.json: {p.stderr.strip()[-300:]}")
        paths.append(dest)
    return paths


def load_results(paths: list[Path]) -> dict:
    results = {}
    for p in paths:
        for key, r in json.loads(p.read_text()).items():
            if key not in results or r.get("updated", "") >= results[key].get("updated", ""):
                results[key] = r
    return results


def apply(results: dict) -> dict:
    """Edit the pack files. Returns {what happened: [keys]}."""
    report: dict = {}
    for key, r in sorted(results.items()):
        path = PACKS_DIR / f"{key}.yaml"
        if not path.exists():
            report.setdefault("no such pack", []).append(key)
            continue
        pack = load_yaml(path)
        status = r["status"]
        if status == "done":
            if pack.get("permission", {}).get("kind") == "revoked":
                report.setdefault("converted, but the creator does not want it hosted; left alone", []).append(key)
                continue
            if pack.get("archive") or pack.get("hosting", {}).get("state") != "listed":
                report.setdefault("converted, but the pack changed since; left alone", []).append(key)
                continue
            a = r["archive"]
            version = {"revision": 1, "container": a["container"], "object": a["object"], "sha256": a["sha256"],
                       "size_bytes": a["size_bytes"], "decompressed_size_bytes": a["decompressed_size_bytes"],
                       "file_count": a["file_count"], "created": a["created"],
                       "source": {k: a["source"][k] for k in ("sha256", "size_bytes", "url", "retrieved") if k in a["source"]},
                       "converter": {k: a["converter"][k] for k in ("tool", "version", "pipeline", "params") if a["converter"].get(k)}}
            pack["hosting"] = {"state": "withheld", "reason": WITHHELD_REASON, "since": a["created"]}
            if r.get("serials_found") and not pack.get("game", {}).get("serials"):
                pack["game"]["serials"] = r["serials_found"]
            pack["archive"] = {"current": 1, "versions": [version]}
            write_yaml(path, pack)
            report.setdefault("converted and stored (now withheld)", []).append(key)
        elif status == "gone":
            d = pack.get("download") or {}
            if d.get("status") == "resolved" and d.get("url") == r.get("download_url"):
                d["status"] = "dead"
                d["note"] = f"The host says this file is no longer there (checked {r['updated']})."
                write_yaml(path, pack)
                report.setdefault("link gone (download marked dead)", []).append(key)
        else:
            report.setdefault(status, []).append(f"{key}: {r.get('detail', '')}")
    return report


def unmatched_rows(rows: list, packs, creators) -> list:
    index = match.Index(packs, creators)
    return [r for r in rows if not index.known(r)]


def main(argv=None) -> int:
    import argparse
    from ..validate import load_all

    ap = argparse.ArgumentParser(prog="ps2ktxpak scrape apply")
    ap.add_argument("index", nargs="*", type=Path, help="results/index-<i>.json files already fetched")
    ap.add_argument("--bucket", default="ps2ktxpak-scrape")
    ap.add_argument("--shards", type=int, default=1, help="how many shards the run had")
    ap.add_argument("--cache", type=Path, default=Path("cache/scrape"))
    ap.add_argument("--sheet", help="a local copy of the spreadsheet, instead of downloading it")
    a = ap.parse_args(argv)

    paths = a.index or fetch_results(a.bucket, a.shards, a.cache)
    report = apply(load_results(paths))
    for what, keys in report.items():
        print(f"\n{what}: {len(keys)}")
        for k in keys:
            print(f"  {k}")
    d = load_all()
    rows = sheet.parse(Path(a.sheet).read_bytes() if a.sheet else sheet.fetch())
    loose = unmatched_rows(rows, d["packs"], d["creators"])
    print(f"\nspreadsheet rows no pack describes: {len(loose)}")
    for r in loose:
        print(f"  row {r.row}: {r.title} ({r.author}; {r.region or 'no region'}; {r.restriction or 'no restriction'})")
    return 0
