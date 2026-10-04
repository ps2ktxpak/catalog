"""Seed each hosted pack's example pictures and YouTube videos from its own announcement thread.

A seed, like import-legacy: a pack that already has `media` (or has it locked) is never touched, so a
person's choice of pictures survives. Only a thread that belongs to exactly one hosted pack is used:
a creator's library thread shows many games and its pictures cannot be told apart.

Only addresses are recorded. The pictures are the creators' own screenshots: the site must show our
resized copies (made later, with a credit), never hotlink the forum."""
from __future__ import annotations

import re
from collections import Counter

from . import resolve
from .common import PACKS_DIR, load_yaml, ordered, write_yaml
from .import_legacy import PACK_ORDER

MAX_IMAGES, MAX_VIDEOS = 8, 3
_FILENAME = re.compile(r"\.(jpe?g|png|gif|webp)$", re.I)


def thread_of(pack: dict) -> str | None:
    for s in pack.get("sources", []):
        if s["kind"] == "forum_thread" and "gbatemp.net/threads/" in s["url"]:
            return s["url"]
    legacy = pack.get("legacy", {}).get("source_url", "")
    return legacy if "gbatemp.net/threads/" in legacy else None


def run(retrieved: str, delay: float = 1.5, limit: int | None = None, refresh: bool = False) -> dict:
    packs = {f.name: load_yaml(f) for f in sorted(PACKS_DIR.glob("*.yaml"))}
    uses = Counter(t for t in (thread_of(p) for p in packs.values()) if t)
    stats = Counter()
    for fn, p in packs.items():
        if p["hosting"]["state"] != "published" or p.get("media") or "media" in p.get("locked", []):
            continue
        url = thread_of(p)
        if not url:
            stats["no_thread"] += 1
            continue
        if uses[url] > 1:
            stats["shared_thread"] += 1
            continue
        if limit is not None and stats["seeded"] + stats["empty"] >= limit:
            break
        _, page = resolve.fetch_page(url, delay, refresh)
        if page is None:
            stats["unreachable"] += 1
            continue
        posts = resolve.parse_posts(page)
        op = posts[0]["author"] if posts else None
        images, videos = [], []
        for post in [x for x in posts[:6] if x["author"] == op][:3]:
            for img in post["images"]:
                if len(images) < MAX_IMAGES and all(i["source_url"] != img["url"] for i in images):
                    entry = {"source_url": img["url"], "thumb_url": img["thumb"]}
                    if img.get("alt") and not _FILENAME.search(img["alt"]):
                        entry["alt"] = img["alt"]
                    images.append(entry)
            for v in post["videos"]:
                if len(videos) < MAX_VIDEOS and all(x["id"] != v["id"] for x in videos):
                    videos.append({"provider": "youtube", "id": v["id"]})
        if not images and not videos:
            stats["empty"] += 1
            continue
        credit = p["credits"][0]["creator"] if p.get("credits") else None
        if credit:
            for i in images:
                i["credit"] = credit
        p["media"] = {k: v for k, v in (("images", images), ("videos", videos)) if v}
        p.setdefault("provenance", {})["media"] = {
            "source": "gbatemp-thread-opening-post", "date": retrieved, "confidence": "medium",
            "note": "the pack's own announcement thread"}
        write_yaml(PACKS_DIR / fn, ordered(p, PACK_ORDER, keep=("credits",)))
        stats["seeded"] += 1
        stats["images"] += len(images)
        stats["videos"] += len(videos)
        print(f"[{stats['seeded']}] {len(images)} pictures, {len(videos)} videos  {p['key']}", flush=True)
    return dict(stats)
