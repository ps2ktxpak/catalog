"""Match spreadsheet listings to the packs we host: writes data/links/listing-pack.jsonl.

Order of evidence: the GBAtemp thread both point at, then the game title (with the hand-checked
spelling aliases, then a close-title fallback that insists on the same numbers), narrowed by creator,
region and exact link. A match a human wrote (method: manual) is kept and wins."""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from urllib.parse import urlparse

from .common import (LISTINGS_FILE, MATCHES_FILE, PACKS_DIR, TITLE_ALIASES_FILE, load_yaml, numbers_in,
                     read_jsonl, region_of_serial, title_key, write_jsonl)


def thread_id(url: str | None) -> str | None:
    p = urlparse(url or "")
    if "gbatemp.net" not in p.netloc:
        return None
    m = re.search(r"/threads/(?:[^/]*\.)?(\d+)", p.path)
    return m.group(1) if m else None


def load_packs() -> dict[str, dict]:
    return {rec["key"]: rec for rec in (load_yaml(f) for f in sorted(PACKS_DIR.glob("*.yaml")))}


def run() -> dict:
    listings = read_jsonl(LISTINGS_FILE)
    packs = load_packs()
    aliases = {a["pack"]: a["listing"] for a in (load_yaml(TITLE_ALIASES_FILE) or [])}
    manual = [m for m in read_jsonl(MATCHES_FILE) if m["method"] == "manual"]
    manual_packs = {m["pack"] for m in manual}

    by_thread, by_title = defaultdict(list), defaultdict(list)
    for l in listings:
        t = thread_id(l.get("source_page"))
        if t:
            by_thread[t].append(l)
        by_title[title_key(l["title"])].append(l)

    out, stats = list(manual), {"matched": 0, "unmatched": [], "ambiguous": []}
    for key, p in sorted(packs.items()):
        if key in manual_packs:
            stats["matched"] += 1
            continue
        tk = title_key(p["game"]["title"])
        credit_ids = {c["creator"] for c in p.get("credits", [])}
        pack_urls = [s["url"] for s in p.get("sources", [])] + [p.get("legacy", {}).get("source_url", "")]
        threads = {t for t in (thread_id(u) for u in pack_urls) if t}

        pool, method = [], None
        for t in sorted(threads):
            pool += by_thread.get(t, [])
        if pool:
            method = "thread"
            same = [l for l in pool if title_key(l["title"]) in (tk, aliases.get(tk))]
            pool = same or pool  # a creator's library thread carries many games: narrow to this one
        else:
            if tk in by_title:
                pool, method = by_title[tk], "title"
            elif aliases.get(tk) in by_title:
                pool, method = by_title[aliases[tk]], "alias"
            else:
                want = numbers_in(p["game"]["title"])
                for close in difflib.get_close_matches(tk, list(by_title), n=5, cutoff=0.86):
                    cand = [l for l in by_title[close] if numbers_in(l["title"]) == want]
                    if cand:
                        pool, method = cand, "close_title"
                        break
        if not pool:
            stats["unmatched"].append(key)
            continue

        if credit_ids:
            mine = [l for l in pool if credit_ids & set(l["creators"])]
            if not mine:
                stats["unmatched"].append(key)  # the sheet lists this game, but under someone else
                continue
            pool = mine
        regions = {region_of_serial(s) for s in p["game"]["serials"]} - {None}
        fit = [l for l in pool if not l.get("regions") or "multi" in l["regions"] or regions & set(l["regions"])]
        pool = fit or pool
        exact = [l for l in pool if l.get("source_page") in pack_urls]
        pool = exact or pool
        if len(pool) > 1:
            same_work = len({(l.get("source_page"), tuple(l["creators"])) for l in pool}) == 1
            if not same_work:
                stats["ambiguous"].append(key)
                continue  # several different listings fit; a human decides
        confidence = ("high" if (method in ("thread", "alias") or credit_ids) and method != "close_title"
                      else "medium" if method == "close_title" else "low")
        for l in pool:
            out.append({"listing": l["id"], "pack": key, "method": method, "confidence": confidence})
        stats["matched"] += 1

    out.sort(key=lambda m: (m["pack"], m["listing"]))
    write_jsonl(MATCHES_FILE, out)
    stats["lines"] = len(out)
    return stats
