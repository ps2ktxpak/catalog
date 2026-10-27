"""The container's job: download each free pack whose files we know the link to, keep the download,
convert it, and record what happened.

Which packs: `listed` packs with a resolved `download` link and no `archive`, that nobody charges
for (the pack's own `access.cost`, and the spreadsheet's Restriction column). Every pack gets a
result in the bucket, so a run that stops resumes where it was, and a pack that failed for a reason
that may pass (quota, network) is tried again on the next run."""
from __future__ import annotations

import datetime as dt
import hashlib
import http.server
import json
import os
import shutil
import signal
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import convert, hosts, match, sheet
from .store import Store

PIPELINE = "ps2ktxpak scrape"
# Final: trying again changes nothing until a person changes the pack's record.
FINAL = {"done", "gone", "unsupported", "empty", "needs_choice", "too_large", "paid"}
MAX_ATTEMPTS = 3
SKIP_HOSTS = {"kofi"}  # a Ko-fi shop item is a checkout, never a download


def today() -> str:
    return dt.date.today().isoformat()


def _mem_kib() -> int | None:
    try:
        return int(Path("/proc/meminfo").read_text().split()[1])
    except (OSError, IndexError, ValueError):
        return None


def is_result(key: str) -> bool:
    """A pack's `results/<key>.json`, not a shard's `results/index-<i>.json` of all of them."""
    name = key.rsplit("/", 1)[-1]
    return name.endswith(".json") and not name.startswith("index-")


def url_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


@dataclass
class Item:
    key: str
    url: str
    title: str
    serials: list
    sheet_size: int | None
    shared_with: list


def plan(packs, creators, rows: list) -> tuple[list[Item], dict]:
    """The packs to fetch, and the ones skipped with the reason (key -> result)."""
    index = match.Index(packs, creators)
    packs = index.packs
    size, paywall = {}, set()
    for r in rows:
        for k in index.candidates(r):
            if r.size_bytes():
                size.setdefault(k, r.size_bytes())
            if r.paid:
                paywall.add(k)
    by_url: dict = {}
    for k, p in packs.items():
        d = p.get("download") or {}
        if d.get("status") == "resolved" and p.get("hosting", {}).get("state") == "listed" and not p.get("archive"):
            by_url.setdefault(d["url"], []).append(k)

    items, skipped = [], {}
    for url, keys in sorted(by_url.items()):
        for k in keys:
            p = packs[k]
            if p.get("access", {}).get("cost") == "paid" or k in paywall:
                skipped[k] = {"status": "paid", "detail": "the creator charges for this pack"}
            elif p["download"].get("host") in SKIP_HOSTS:
                skipped[k] = {"status": "unsupported", "detail": "a shop checkout, not a download"}
            else:
                items.append(Item(k, url, p.get("game", {}).get("title") or p["name"],
                                  p.get("game", {}).get("serials", []), size.get(k),
                                  [o for o in keys if o != k]))
    return items, skipped


class Job:
    def __init__(self, store: Store, work: Path, max_source_bytes: int, shard=(0, 1), only=None):
        self.store, self.work = store, work
        self.max_source_bytes = max_source_bytes
        self.shard, self.only = shard, set(only or [])
        self.status = {"state": "starting", "started": time.time(), "counts": {}, "current": None, "last_error": None,
                       "cpus": os.cpu_count(), "usable_cpus": len(os.sched_getaffinity(0)), "mem_kib": _mem_kib()}
        self._sources: dict = {}  # url -> the files we hold from it, for packs sharing one link
        self._last_source = None

    # -- status, for the Worker ----------------------------------------------------------------
    def serve(self, port: int) -> None:
        job = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(job.status).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def log(self, msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    # -- the loop ------------------------------------------------------------------------------
    def run(self, items: list[Item], skipped: dict) -> dict:
        results = {}
        for key in self.store.list("results"):
            if is_result(key):
                if r := self.store.get_json(key):
                    results[r["key"]] = r
        for k, r in skipped.items():
            if results.get(k, {}).get("status") != r["status"]:
                results[k] = {"key": k, "updated": today(), "attempts": 0, **r}
                self.store.put_json(results[k], f"results/{k}.json")

        mine = [it for it in items if int(url_id(it.url), 16) % self.shard[1] == self.shard[0]
                and (not self.only or it.key in self.only)]
        todo = [it for it in mine if self._again(results.get(it.key, {}))]
        self.status.update(state="running", total=len(mine), todo=len(todo))
        self.log(f"{len(mine)} packs in this shard, {len(todo)} to do")
        for n, it in enumerate(todo, 1):
            self.status.update(current=it.key, position=n)
            prev = results.get(it.key, {})
            r = self.process(it)
            r.update(key=it.key, updated=today(), download_url=it.url,
                     attempts=prev.get("attempts", 0) + (0 if r["status"] in FINAL else 1))
            results[it.key] = r
            self.store.put_json(r, f"results/{it.key}.json")
            self.status["counts"][r["status"]] = self.status["counts"].get(r["status"], 0) + 1
            if r["status"] == "failed":
                self.status["last_error"] = f"{it.key}: {r['detail'][:300]}"
            self.log(f"{n}/{len(todo)} {it.key}: {r['status']} {r.get('detail', '')[:200]}")
            if n % 10 == 0:
                self.store.put_json(results, f"results/index-{self.shard[0]}.json")
        self.store.put_json(results, f"results/index-{self.shard[0]}.json")
        self.status.update(state="finished", current=None, finished=time.time())
        return results

    @staticmethod
    def _again(r: dict) -> bool:
        """Whether a pack still needs doing: never tried, failed fewer than MAX_ATTEMPTS times, or
        converted with other parameters than this image's (its download is reused from the bucket)."""
        if r.get("status") == "done":
            return r["archive"]["converter"]["params"] != convert.PARAMS
        return r.get("status") not in FINAL and r.get("attempts", 0) < MAX_ATTEMPTS

    def process(self, it: Item) -> dict:
        if it.sheet_size and it.sheet_size > self.max_source_bytes:
            return {"status": "too_large", "detail": f"listed at {it.sheet_size} bytes; this run keeps under {self.max_source_bytes}"}
        pack_dir = self.work / it.key
        shutil.rmtree(pack_dir, ignore_errors=True)
        self._last_source = None
        try:
            source = self._last_source = self._download(it, pack_dir / "src")
            files = [pack_dir / "src" / f["name"] for f in source["files"]]
            convert.unpack(files, pack_dir / "x")
            shutil.rmtree(pack_dir / "src", ignore_errors=True)
            layout = self._choose(convert.find_layout(pack_dir / "x"), it)
            dropped = convert.unloadable(layout)
            count = convert.convert(layout, pack_dir / "out")
            shutil.rmtree(pack_dir / "x", ignore_errors=True)
            convert.validate(pack_dir / "out", count)
            facts = convert.pack(pack_dir / "out", pack_dir / "pack.tar.zst", count)
            obj = f"packs/{it.key}.tar.zst"
            self.store.put(pack_dir / "pack.tar.zst", obj)
            main = max(source["files"], key=lambda f: f["size_bytes"])
            return {"status": "done", "serials_found": layout.serials, "source": source,
                    "left_out": {"count": len(dropped), "examples": dropped[:10]},
                    "archive": {"container": "tar+zstd", "object": obj, **facts, "created": today(),
                                "converter": {"tool": "kram", "version": os.environ.get("KRAM_VERSION", ""),
                                              "pipeline": PIPELINE, "params": convert.PARAMS},
                                "source": {"sha256": main["sha256"], "size_bytes": main["size_bytes"],
                                           "url": it.url, "retrieved": source["retrieved"]}}}
        except hosts.Gone as e:
            return {"status": "gone", "detail": str(e)}
        except hosts.Unsupported as e:
            return {"status": "unsupported", "detail": str(e)}
        except hosts.TooLarge as e:
            return {"status": "too_large", "detail": str(e)}
        except convert.NoRoom as e:
            return {"status": "too_large", "detail": str(e), **self._source_of(it)}
        except convert.Empty as e:
            return {"status": "empty", "detail": str(e), **self._source_of(it)}
        except convert.NeedsChoice as e:
            return {"status": "needs_choice", "detail": str(e), **self._source_of(it)}
        except Exception as e:
            self.log(traceback.format_exc())
            return {"status": "failed", "detail": f"{type(e).__name__}: {e}", **self._source_of(it)}
        finally:
            shutil.rmtree(pack_dir, ignore_errors=True)

    def _source_of(self, it: Item) -> dict:
        return {"source": self._last_source} if self._last_source else {}

    def _download(self, it: Item, dest: Path) -> dict:
        """Download what the link holds for this pack, and keep it. A file another pack sharing the
        link already brought in is copied from the bucket instead of from the host."""
        prefix = f"sources/{url_id(it.url)}"
        record = self._sources.get(it.url) or self.store.get_json(f"{prefix}/source.json") \
            or {"url": it.url, "retrieved": today(), "files": []}
        entries = hosts.list_link(it.url, hosts.Want(it.title, it.serials))
        stored = {f["name"]: f for f in record["files"]}
        named = [e for e in entries if e.name]
        whole = len(named) < len(entries)  # a link fetched in one piece (Mega): names unknown until then
        if (whole and record["files"]) or (named and not whole and all(e.name in stored for e in named)):
            mine = record["files"] if whole else [stored[e.name] for e in named]
            dest.mkdir(parents=True, exist_ok=True)
            for f in mine:
                p = self.store._rclone("copyto", self.store._path(f["object"]), str(dest / f["name"]))
                if p.returncode:
                    raise RuntimeError(f"could not fetch our copy {f['object']}: {p.stderr.decode()[-200:]}")
            return {**record, "files": mine}

        known = sum(e.size or 0 for e in entries)
        if known > self.max_source_bytes:
            raise hosts.TooLarge(f"{known} bytes; this run keeps under {self.max_source_bytes}")
        dest.mkdir(parents=True, exist_ok=True)
        for e in entries:
            e.get(dest / e.name if e.name else dest, self.max_source_bytes)
        files = sorted(f for f in dest.rglob("*") if f.is_file())
        total = sum(f.stat().st_size for f in files)
        if not files:
            raise RuntimeError("nothing was downloaded")
        if total > self.max_source_bytes:
            raise hosts.TooLarge(f"the download is {total} bytes; this run keeps under {self.max_source_bytes}")
        mine = []
        for f in files:
            name = str(f.relative_to(dest))
            entry = {"name": name, "object": f"{prefix}/{name}", "size_bytes": f.stat().st_size,
                     "sha256": convert.sha256_file(f)}
            self.store.put(f, entry["object"])
            mine.append(entry)
            stored[name] = entry
        record = {**record, "retrieved": today(), "files": sorted(stored.values(), key=lambda f: f["name"])}
        self.store.put_json(record, f"{prefix}/source.json")
        self._sources[it.url] = record
        return {**record, "files": mine}

    @staticmethod
    def _choose(layout: convert.Layout, it: Item) -> convert.Layout:
        """When one download holds several games, keep the folders of this pack's serials."""
        if len(layout.roots) > 1 and it.serials and len(layout.serials) == len(layout.roots):
            keep = [(r, s) for r, s in zip(layout.roots, layout.serials) if s in it.serials]
            if keep:
                return convert.Layout([r for r, _ in keep], [s for _, s in keep])
            raise convert.NeedsChoice(f"none of the download's serial folders {layout.serials} is this pack's {it.serials}")
        if len(layout.roots) > 1 and it.shared_with:
            raise convert.NeedsChoice(f"one download, shared with {', '.join(it.shared_with)}, holds folders for "
                                      f"{', '.join(layout.serials) or f'{len(layout.roots)} games'}, and this pack names no serial")
        return layout


def main(argv=None) -> int:
    import argparse
    from ..validate import load_all

    ap = argparse.ArgumentParser(prog="ps2ktxpak scrape job")
    ap.add_argument("--store", default=os.environ.get("SCRAPE_STORE", "r2:ps2ktxpak-scrape"))
    ap.add_argument("--work", default=os.environ.get("SCRAPE_WORK", "/work"))
    ap.add_argument("--max-source-gb", type=float, default=float(os.environ.get("SCRAPE_MAX_SOURCE_GB", "6")))
    ap.add_argument("--shard", default=os.environ.get("SCRAPE_SHARD", "0/1"), help="i/n: take every n-th link from i")
    ap.add_argument("--only", nargs="*", help="pack keys")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "0")), help="serve status here")
    ap.add_argument("--sheet", help="a local copy of the spreadsheet, instead of downloading it")
    a = ap.parse_args(argv)

    # In a container this is process 1, which ignores SIGTERM unless it asks for it: without this the
    # Worker's stop() would leave the job running.
    signal.signal(signal.SIGTERM, lambda *_: os._exit(143))
    i, n = (int(x) for x in a.shard.split("/"))
    job = Job(Store(a.store), Path(a.work), int(a.max_source_gb * 1e9), (i, n), a.only)
    if a.port:
        job.serve(a.port)
    rows = sheet.parse(Path(a.sheet).read_bytes() if a.sheet else sheet.fetch())
    data = load_all()
    items, skipped = plan(data["packs"], data["creators"], rows)
    results = job.run(items, skipped)
    counts = {}
    for r in results.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    job.log(f"finished: {counts}")
    if a.port:  # keep answering the Worker until it stops the container
        while True:
            time.sleep(3600)
    return 0
