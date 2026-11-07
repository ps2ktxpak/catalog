"""A page of the raw downloads in the scraper's bucket, with links that expire, for someone who wants the originals.

The bucket stays private. Each link is a signed GET (S3 query-string signing, which R2 accepts) good for at most
seven days; run this again for fresh ones. It needs the bucket's S3 key in RCLONE_CONFIG_<REMOTE>_ACCESS_KEY_ID,
_SECRET_ACCESS_KEY and _ENDPOINT, as the other scrape commands do. The page holds working links, so it is written
under dist/ (not tracked) and must never be committed."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import hmac
import html
import os
import subprocess
import urllib.parse
from pathlib import Path

from .job import url_id

MAX_DAYS = 7
INLINE_FILES = 12  # a download with more files than this lists them under a fold


def _quote(s: str) -> str:
    return urllib.parse.quote(s, safe="-_.~")


def presign(host: str, path: str, key_id: str, secret: str, region: str, when: dt.datetime, expires: int) -> str:
    """The query string that makes a GET of `path` on `host` valid for `expires` seconds from `when` (AWS SigV4)."""
    stamp, day = when.strftime("%Y%m%dT%H%M%SZ"), when.strftime("%Y%m%d")
    scope = f"{day}/{region}/s3/aws4_request"
    query = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": f"{key_id}/{scope}", "X-Amz-Date": stamp,
             "X-Amz-Expires": str(expires), "X-Amz-SignedHeaders": "host"}
    canonical_query = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(query.items()))
    canonical_path = "/".join(_quote(seg) for seg in path.split("/"))
    request = "\n".join(["GET", canonical_path, canonical_query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(request.encode()).hexdigest()])
    k = ("AWS4" + secret).encode()
    for part in (day, region, "s3", "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    return f"{canonical_query}&X-Amz-Signature={hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()}"


def listing(store: str) -> dict[str, list[tuple[str, int]]]:
    """{download id: [(file name, size)]} for everything under sources/, without the job's own source.json."""
    p = subprocess.run(["rclone", "lsf", "-R", "--files-only", "--format", "sp", "--separator", "|", f"{store}/sources"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode:
        raise RuntimeError(f"could not list {store}/sources: {p.stderr.strip()[-300:]}")
    files = collections.defaultdict(list)
    for line in p.stdout.splitlines():
        size, _, path = line.partition("|")
        folder, _, name = path.partition("/")
        if name and name != "source.json":
            files[folder].append((name, int(size)))
    return files


def human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def page(files: dict, packs: dict, creators: dict, link, expires: dt.datetime) -> str:
    """The HTML. `link(download id, file name)` gives each file's address."""
    by_dir = collections.defaultdict(list)
    for key, p in packs.items():
        if url := (p.get("download") or {}).get("url"):
            by_dir[url_id(url)].append(key)

    def creator(c: str) -> str:
        return (creators.get(c) or {}).get("name") or c

    rows = []
    for folder, fs in files.items():
        keys = sorted(by_dir.get(folder, []), key=lambda k: packs[k]["name"].casefold())
        names = [packs[k]["name"] for k in keys] or [f"Download {folder}"]
        who = sorted({creator(c["creator"]) for k in keys for c in packs[k].get("credits", [])})
        serials = sorted({s for k in keys for s in packs[k].get("game", {}).get("serials", [])})
        host = next((packs[k]["download"].get("host") for k in keys if packs[k].get("download", {}).get("host")), "")
        total = sum(s for _, s in fs)
        fs = sorted(fs, key=lambda f: f[0].casefold())
        items = "".join(f'<li><a href="{html.escape(link(folder, n))}" download>{html.escape(n)}</a> '
                        f'<span class="sz">{human(s)}</span></li>' for n, s in fs)
        if len(fs) > INLINE_FILES:
            body = (f'<details><summary>{len(fs)} files, {human(total)}</summary>'
                    f'<p><button type="button" class="copy">Copy all {len(fs)} links</button> '
                    f'<span class="sz">one per line, for <code>wget -i</code> or a download manager</span></p>'
                    f'<ul>{items}</ul></details>')
        else:
            body = f"<ul>{items}</ul>"
        meta = " · ".join(x for x in (", ".join(who), ", ".join(serials), host, human(total)) if x)
        text = " ".join([*names, *who, *serials, *(n for n, _ in fs[:INLINE_FILES])]).lower()
        rows.append((names[0].casefold(),
                     f'<section class="dl" data-q="{html.escape(text)}"><h2>{html.escape(" · ".join(names))}</h2>'
                     f'<p class="meta">{html.escape(meta)}</p>{body}</section>'))
    rows.sort(key=lambda r: r[0])
    count, total = sum(len(f) for f in files.values()), sum(s for f in files.values() for _, s in f)
    return PAGE.format(downloads=len(rows), files=count, size=human(total), expires=expires.strftime("%A %d %B %Y, %H:%M UTC"),
                       sections="\n".join(r for _, r in rows))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raw texture pack downloads</title>
<style>
:root {{ color-scheme: light dark; --line: #8884; --dim: #888; }}
body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 60rem; margin: 0 auto; padding: 1rem 16px 4rem; }}
h1 {{ margin-bottom: .25rem; }}
.top {{ position: sticky; top: 0; background: Canvas; padding: .5rem 0; border-bottom: 1px solid var(--line); }}
input {{ width: 100%; box-sizing: border-box; font: inherit; padding: .5rem; }}
.dl {{ border-bottom: 1px solid var(--line); padding: .5rem 0; }}
.dl h2 {{ font-size: 1.1rem; margin: .25rem 0 0; }}
.meta, .sz {{ color: var(--dim); font-size: .85rem; margin: 0; }}
ul {{ margin: .25rem 0; padding-left: 1.25rem; }}
summary {{ cursor: pointer; }}
[hidden] {{ display: none; }}
</style></head><body>
<h1>Raw texture pack downloads</h1>
<p>{downloads} downloads, {files} files, {size}: the original files exactly as each creator published them,
before any conversion. The links stop working on <strong>{expires}</strong>.</p>
<div class="top"><input id="q" type="search" placeholder="Search by game, creator or serial" autofocus>
<span class="sz"><span id="n">{downloads}</span> shown</span></div>
{sections}
<script>
const rows = [...document.querySelectorAll('.dl')], n = document.getElementById('n');
document.getElementById('q').addEventListener('input', e => {{
  const t = e.target.value.trim().toLowerCase();
  let shown = 0;
  rows.forEach(r => {{ r.hidden = !!t && !r.dataset.q.includes(t); if (!r.hidden) shown++; }});
  n.textContent = shown;
}});
document.addEventListener('click', e => {{
  if (!e.target.classList.contains('copy')) return;
  const text = [...e.target.closest('details').querySelectorAll('a')].map(a => a.href).join('\\n');
  const done = () => {{ e.target.textContent = 'Copied'; }};
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done);
  else {{ const t = document.createElement('textarea'); t.value = text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove(); done(); }}
}});
</script></body></html>
"""


def main(argv=None) -> int:
    from ..validate import load_all

    ap = argparse.ArgumentParser(prog="ps2ktxpak scrape index")
    ap.add_argument("--store", default=os.environ.get("SCRAPE_STORE", "r2:ps2ktxpak-scrape"))
    ap.add_argument("--days", type=float, default=MAX_DAYS, help=f"how long the links last (R2 allows at most {MAX_DAYS})")
    ap.add_argument("--out", type=Path, default=Path("dist/raw-downloads.html"))
    a = ap.parse_args(argv)
    if not 0 < a.days <= MAX_DAYS:
        ap.error(f"--days must be above 0 and at most {MAX_DAYS}")
    remote, _, bucket = a.store.partition(":")
    env = {k: os.environ[f"RCLONE_CONFIG_{remote.upper()}_{k}"] for k in ("ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "ENDPOINT")}
    host = urllib.parse.urlparse(env["ENDPOINT"]).netloc
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    expires = int(a.days * 86400)

    def link(folder: str, name: str) -> str:
        path = f"/{bucket}/sources/{folder}/{name}"
        query = presign(host, path, env["ACCESS_KEY_ID"], env["SECRET_ACCESS_KEY"], "auto", now, expires)
        return f"https://{host}{'/'.join(_quote(s) for s in path.split('/'))}?{query}"

    data = load_all()
    files = listing(a.store)
    out = page(files, data["packs"], data["creators"], link, now + dt.timedelta(seconds=expires))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(out, encoding="utf-8")
    print(f"wrote {a.out} ({len(out.encode())} bytes): {len(files)} downloads, {sum(map(len, files.values()))} files")
    return 0
