"""Follow each listing's source page to the real download.

Layer 1 (this file, no judgement): fetch the GBAtemp thread politely, read the links out of the
opening post and the creator's own follow-ups, and for each embedded YouTube video read the
uploader's description and pinned or own comments with yt-dlp. Record every candidate with a short
context snippet. Decide only the unambiguous cases.

Layer 2 (an agent, see site/src/content/docs/resolving-sources.md): judge what is left (library threads that cover
many games, several candidate links, none) from the evidence this layer wrote.

Rules: public pages only, no login, no downloads, nothing behind a paywall. Pages and video data are
cached under cache/ so a re-run costs no requests."""
from __future__ import annotations

import difflib
import html
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from .common import (CACHE, RESOLUTION_DIR, SCHEMA_DIR, USER_AGENT, classify_link, host_of, https,
                     load_json, numbers_in, sha1_short, title_key, write_json)
from .validate import SHORTENERS, load_all

FILE_HOSTS = {"gdrive", "mega", "mediafire", "terabox", "dropbox", "pixeldrain", "gofile", "archive_org"}
IGNORE_HOSTS = ("facebook.com", "twitter.com", "x.com", "twitch.tv", "bsky.app", "instagram.com", "tiktok.com",
                "imgsli.com", "paypal.com", "paypal.me", "gbatemp.net", "wikipedia.org", "ytimg.com",
                "discord.gg", "discord.com", "imgur.com", "i.imgur.com", "reddit.com", "steamcommunity.com")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
# A file-host link typed as text (often without https://) is not an anchor, so the HTML parser misses it.
TEXT_URL = re.compile(r"(?:https?://)?(?:www\.)?((?:mega\.nz|mega\.co\.nz|drive\.google\.com|mediafire\.com|dropbox\.com|"
                      r"pixeldrain\.com|gofile\.io|archive\.org|1024terabox\.com|terabox\.com|ko-fi\.com|github\.com)/[^\s<>\"')\]]+)", re.I)


def url_hash(url: str) -> str:
    return sha1_short(url, 12)


def resolution_path(url: str) -> Path:
    return RESOLUTION_DIR / f"{url_hash(url)}.json"


# ---- which pages --------------------------------------------------------------------------------

def in_scope() -> dict[str, list[dict]]:
    """{source page: [listing]} for listings we do not host and that are not paid."""
    d = load_all()
    matched = {m["listing"] for m in d["matches"]}
    out: dict[str, list[dict]] = defaultdict(list)
    for l in d["listings"]:
        if l["id"] in matched or l["access"]["cost"] == "paid" or not l.get("source_page"):
            continue
        out[l["source_page"]].append(l)
    return dict(out)


def plan_text() -> str:
    pages = in_scope()
    n = sum(len(v) for v in pages.values())
    hosts = Counter(host_of(u) for u in pages)
    have = [u for u in pages if resolution_path(u).exists()]
    status = Counter()
    for u in have:
        for x in load_json(resolution_path(u)).get("decisions", []):
            status[x["status"]] += 1
    shared = sorted(((len(v), u) for u, v in pages.items() if len(v) > 1), reverse=True)
    lines = [f"{n} listings in scope (not hosted by us, not paid) on {len(pages)} distinct source pages",
             "pages by host: " + ", ".join(f"{h} {c}" for h, c in hosts.most_common(8)),
             f"pages already fetched: {len(have)}; decisions so far: " + (", ".join(f"{k} {v}" for k, v in status.items()) or "none"),
             "pages shared by several listings (libraries): " + "; ".join(f"{c} listings  {u.split('/threads/')[-1][:50]}" for c, u in shared[:6])]
    return "\n".join(lines)


# ---- reading a thread page --------------------------------------------------------------------------

class _Body(HTMLParser):
    """The text and external links of one post body, ignoring quoted posts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.embeds, self.images, self._quote, self._a = [], [], [], [], 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "blockquote":
            self._quote += 1
        if a.get("data-s9e-mediaembed-iframe") and not self._quote:
            # GBAtemp turns a pasted Google Drive link into an embedded player, not a hyperlink.
            try:
                kv = json.loads(a["data-s9e-mediaembed-iframe"])
                src = dict(zip(kv[0::2], kv[1::2])).get("src", "")
            except (ValueError, IndexError):
                src = ""
            m = re.search(r"drive\.google\.com/file/d/([\w-]+)", src)
            if m:
                self.embeds.append({"url": f"https://drive.google.com/file/d/{m.group(1)}/view",
                                    "pos": sum(len(t) for t in self.text)})
        if tag == "a" and a.get("href") and not self._quote:
            self._a = {"href": a["href"], "pos": sum(len(t) for t in self.text), "anchor": []}
            self.links.append(self._a)
        if tag == "img" and "bbImage" in (a.get("class") or "") and not self._quote and (a.get("src") or "").startswith("https://"):
            self.images.append({"thumb": a["src"], "full": (self._a or {}).get("href"), "alt": (a.get("alt") or "").strip()})

    def handle_endtag(self, tag):
        if tag == "blockquote":
            self._quote = max(0, self._quote - 1)
        if tag == "a":
            self._a = None

    def handle_data(self, data):
        if self._quote:
            return
        self.text.append(data)
        if self._a is not None:
            self._a["anchor"].append(data)


def parse_posts(page: str) -> list[dict]:
    """[{author, is_op, text, links[{url, context}], videos[{id, title}]}] for the posts on a thread page."""
    posts = []
    for chunk in re.split(r'(?=<article class="message[^"]*message--post)', page)[1:]:
        head = chunk[:400]
        author = (re.search(r'data-author="([^"]*)"', head) or [None, ""])[1]
        i = chunk.find('class="bbWrapper">')
        if i < 0:
            continue
        end = chunk.find('<div class="js-selectToQuoteEnd">', i)
        body = chunk[i + len('class="bbWrapper">'): end if end > 0 else i + 60000]
        p = _Body()
        p.feed(body)
        text = re.sub(r"\s+", " ", "".join(p.text)).strip()
        pictured = {i["full"] for i in p.images if i["full"]}
        links = []
        for l in p.links:
            url = https(l["href"])
            if not url or l["href"] in pictured:
                continue
            ctx = re.sub(r"\s+", " ", "".join(p.text)[max(0, l["pos"] - 110): l["pos"] + 50]).strip()
            links.append({"url": url, "context": ctx[:160]})
        full = "".join(p.text)
        have = {re.sub(r"^https?://(www\.)?|/+$", "", l["url"]) for l in links}
        extra = [(e["url"], e["pos"]) for e in p.embeds]
        extra += [("https://" + m.group(1).rstrip(".,;:"), m.start()) for m in TEXT_URL.finditer(full)]
        for url, pos in extra:
            if re.sub(r"^https?://(www\.)?|/+$", "", url) in have:
                continue
            have.add(re.sub(r"^https?://(www\.)?|/+$", "", url))
            links.append({"url": url, "context": re.sub(r"\s+", " ", full[max(0, pos - 110): pos + 50]).strip()[:160]})
        # A library thread puts one video per game inside "Spoiler: <game>": keep that title.
        spoilers = [(m.start(), html.unescape(m.group(1)).strip())
                    for m in re.finditer(r'bbCodeSpoiler-button-title">([^<]*)<', body)]
        vids, seen = [], set()
        for m in re.finditer(r"(?:ytimg\.com/vi/|youtube(?:-nocookie)?\.com/embed/|youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})", body):
            if m.group(1) in seen:
                continue
            seen.add(m.group(1))
            title = ""
            for pos, t in spoilers:
                if pos >= m.start():
                    break
                title = t
            vids.append({"id": m.group(1), "title": title})
        pics, seen_pic = [], set()
        for i in p.images:
            url = https(i["full"]) or https(i["thumb"])
            if url and url not in seen_pic:
                seen_pic.add(url)
                pics.append({"url": url, "thumb": i["thumb"], **({"alt": i["alt"][:200]} if i["alt"] else {})})
        posts.append({"author": author, "is_op": "message-threadStarterPost" in head, "text": text,
                      "links": links, "videos": vids, "images": pics})
    return posts


# ---- network ---------------------------------------------------------------------------------------

_last: dict[str, float] = {}


def _polite(host: str, delay: float) -> None:
    wait = _last.get(host, 0) + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()


def fetch_page(url: str, delay: float, refresh: bool) -> tuple[int | None, str | None]:
    cache = CACHE / "gbatemp" / f"{url_hash(url)}.html"
    if cache.exists() and not refresh:
        return 200, cache.read_text(encoding="utf-8", errors="replace")
    _polite(host_of(url), delay)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return None, None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(body, encoding="utf-8")
    return code, body


def fetch_video(vid: str, yt_dlp: str, delay: float, refresh: bool) -> dict | None:
    cache = CACHE / "yt" / f"{vid}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    _polite("youtube.com", max(delay, 2.0))
    try:
        proc = subprocess.run(
            [yt_dlp, "--skip-download", "--no-warnings", "--write-comments", "--extractor-args",
             "youtube:max_comments=8,all,0,0;comment_sort=top", "-J", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    info = json.loads(proc.stdout)
    slim = {"id": vid, "uploader": info.get("uploader"), "uploader_id": info.get("uploader_id"),
            "description": (info.get("description") or "")[:4000],
            "comments": [{"author": c.get("author"), "author_id": c.get("author_id"), "pinned": c.get("is_pinned"),
                          "by_uploader": c.get("author_is_uploader"), "text": (c.get("text") or "")[:1500]}
                         for c in (info.get("comments") or [])[:8]]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    return slim


# ---- evidence ----------------------------------------------------------------------------------------

def _found(url: str, where: str, context: str, by_uploader: bool | None = None) -> dict | None:
    if any(host_of(url) == h or host_of(url).endswith("." + h) for h in IGNORE_HOSTS):
        return None
    host, kind = classify_link(url)
    rec = {"url": url, "host": host, "kind": kind, "where": where, "context": context[:160]}
    if by_uploader is not None:
        rec["by_uploader"] = by_uploader
    return rec


def _video_links(v: dict) -> list[dict]:
    out = []
    for m in URL_RE.finditer(v["description"]):
        u = https(m.group(0).rstrip(".,;"))
        f = u and _found(u, "video_description", v["description"][max(0, m.start() - 100): m.start()].replace("\n", " "), True)
        if f:
            out.append(f)
    for c in v["comments"]:
        where = "video_pinned_comment" if c["pinned"] else "video_comment"
        for m in URL_RE.finditer(c["text"]):
            u = https(m.group(0).rstrip(".,;"))
            f = u and _found(u, where, c["text"][max(0, m.start() - 100): m.start()].replace("\n", " "), bool(c["by_uploader"]))
            if f:
                out.append(f)
    return out


def _dedupe(found: list[dict], cap: int = 40) -> list[dict]:
    seen, out = set(), []
    for f in found:
        if f["url"] not in seen:
            seen.add(f["url"])
            out.append(f)
    return out[:cap]


MAX_PAGES = 8          # thread pages followed for a library thread (a creator's one thread for many games)
MAX_VIDEOS_LIBRARY = 90


def _title_match(a: str, b: str) -> bool:
    """Same game: equal title keys, or near-equal with the same numbers (so XII never meets X-2)."""
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return False
    return ka == kb or (numbers_in(a) == numbers_in(b) and difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.88)


def _uploader_files(video: dict) -> list[dict]:
    """Links the video's own uploader gave that point at a file host (or a Ko-fi shop item)."""
    return [c for c in video.get("links", [])
            if c.get("by_uploader") and c["host"] in FILE_HOSTS | {"kofi"} and (c["host"] != "kofi" or c["kind"] == "shop")]


def _decide(url: str, listings: list[dict], fetched: dict, candidates: list[dict], videos: list[dict], retrieved: str):
    by = {"method": "deterministic", "date": retrieved}
    if fetched["status"] == "http_error" and fetched.get("http") in (404, 410):
        return [{"listing": l["id"], "status": "dead", "base_url": None, "reason": f"the source page returns {fetched['http']}",
                 "confidence": "high", "decided_by": by} for l in listings]
    if len(listings) > 1:
        # A library page: a game is decided only when exactly one video carries its title and that
        # video's uploader gave exactly one file link. Everything else goes to a reader.
        out = []
        for l in listings:
            pool = {c["url"]: c for v in videos if v.get("title") and _title_match(v["title"], l["title"])
                    for c in _uploader_files(v)}
            if len(pool) == 1:
                c = next(iter(pool.values()))
                out.append({"listing": l["id"], "status": "resolved", "base_url": c["url"], "host": c["host"],
                            "kind": c["kind"], "confidence": "medium",
                            "reason": "the only file link from the uploader of the video titled for this game; not yet confirmed to be the pack",
                            "decided_by": by})
        return out
    pool = [c for c in candidates if c["host"] in FILE_HOSTS and c["where"] in ("op",)]
    pool += [c for v in videos for c in _uploader_files(v)
             if c["where"] in ("video_description", "video_pinned_comment", "video_comment")]
    if fetched["status"] == "skipped_unsupported":
        pool = [c for c in candidates if c["host"] in FILE_HOSTS | {"github", "kofi"} and c["where"] == "op"]
    distinct = {c["url"]: c for c in pool}
    if len(distinct) != 1:
        return []
    c = next(iter(distinct.values()))
    return [{"listing": listings[0]["id"], "status": "resolved", "base_url": c["url"], "host": c["host"],
             "kind": c["kind"], "confidence": "medium",
             "reason": f"the only file-host link in {c['where'].replace('_', ' ')}; not yet confirmed to be the pack itself",
             "decided_by": by}]


def _thread_posts(url: str, delay: float, refresh: bool, follow_pages: bool):
    """(http code, page 1 html, posts). With follow_pages, the posts of the following pages too."""
    code, page = fetch_page(url, delay, refresh)
    if page is None:
        return code, None, []
    posts = parse_posts(page)
    if follow_pages:
        path = urlparse(url).path
        last = max([int(n) for n in re.findall(re.escape(path) + r"page-(\d+)", page)] or [1])
        for n in range(2, min(last, MAX_PAGES) + 1):
            _, more = fetch_page(url.rstrip("/") + f"/page-{n}", delay, refresh)
            if more:
                posts += parse_posts(more)
    return code, page, posts


def fetch_all(limit: int | None, only: list[str] | None, retrieved: str, yt_dlp: str, delay: float, refresh: bool) -> int:
    pages = in_scope()
    urls = [u for u in (only or sorted(pages)) if u in pages]
    if only and len(urls) != len(only):
        print("not in scope:", [u for u in only if u not in pages])
    validator = Draft202012Validator(load_json(SCHEMA_DIR / "resolution.schema.json"))
    done = 0
    for url in urls:
        if limit is not None and done >= limit:
            break
        listings = pages[url]
        multi = len(listings) > 1
        out_path = resolution_path(url)
        if out_path.exists() and not refresh:
            old = load_json(out_path)
            if any(d["decided_by"]["method"] != "deterministic" for d in old.get("decisions", [])):
                continue  # a page an agent or a person judged is never refetched over
        fetched: dict = {"at": retrieved, "status": "ok"}
        candidates, videos = [], []
        if "gbatemp.net/threads/" in url:
            code, page, posts = _thread_posts(url, delay, refresh, follow_pages=multi)
            if page is None:
                fetched.update(status="http_error" if code else "unreachable", **({"http": code} if code else {}))
            else:
                title = re.search(r"<title>([^<]*)", page)
                fetched["title"] = re.sub(r"\s*\|\s*GBAtemp.net.*$", "", (title.group(1) if title else "")).strip()[:200]
                op_author = posts[0]["author"] if posts else None
                wanted: list[dict] = []
                for i, p in enumerate(posts[:60 if multi else 15]):
                    where = "op" if i == 0 else "op_followup" if p["author"] == op_author else "reply_by_other"
                    if where == "reply_by_other" and sum(1 for c in candidates if c["where"] == where) >= 6:
                        continue
                    for l in p["links"]:
                        f = _found(l["url"], where, l["context"])
                        if f and f["host"] not in ("youtube",):
                            candidates.append(f)
                    if where in ("op", "op_followup"):
                        for v in p["videos"]:
                            if any(w["id"] == v["id"] for w in wanted):
                                continue
                            if multi:
                                if v["title"] and any(_title_match(v["title"], l["title"]) for l in listings) \
                                        and len(wanted) < MAX_VIDEOS_LIBRARY:
                                    wanted.append(v)
                            elif len(wanted) < 3:
                                wanted.append(v)
                for v in wanted:
                    info = fetch_video(v["id"], yt_dlp, delay, refresh)
                    videos.append({"id": v["id"], **({"title": v["title"][:120]} if v["title"] else {}),
                                   **({"uploader": info["uploader"]} if info and info.get("uploader") else {}),
                                   "links": _dedupe(_video_links(info)) if info else []})
        else:
            fetched.update(status="skipped_unsupported", note="not a GBAtemp thread; the sheet's own link is the candidate")
            f = _found(url, "op", "")
            if f:
                candidates.append(f)
        candidates = _dedupe(candidates, cap=max(40, 3 * len(listings)))
        doc = {"source_url": url, "listings": sorted(l["id"] for l in listings), "fetched": fetched,
               "videos": videos, "candidates": candidates,
               "decisions": _decide(url, listings, fetched, candidates, videos, retrieved)}
        if not doc["videos"]:
            del doc["videos"]
        errs = list(validator.iter_errors(doc))
        if errs:
            print("schema error for", url, errs[0].message[:150])
            continue
        write_json(out_path, doc)
        done += 1
        print(f"[{done}] {fetched['status']:<10} cands={len(candidates):<2} videos={len(videos)} "
              f"decided={len(doc['decisions'])}/{len(listings)}  {url[-70:]}", flush=True)
    return 0


# ---- briefs for agents and applying their decisions ---------------------------------------------------------

def write_brief(name: str, urls: list[str], limit_chars: int) -> int:
    d = load_all()
    creators = {r["id"]: r["name"] for r in d["creators"].values()}
    listing = {l["id"]: l for l in d["listings"]}
    items = []
    for url in urls:
        rp = resolution_path(url)
        if not rp.exists():
            print("no resolution file yet for", url, "- run resolve-fetch --url first")
            return 1
        res = load_json(rp)
        page = CACHE / "gbatemp" / f"{url_hash(url)}.html"
        posts = []
        if page.exists():
            allp = parse_posts(page.read_text(encoding="utf-8", errors="replace"))
            op = allp[0]["author"] if allp else None
            for i, p in enumerate(allp[:8]):
                if i == 0 or p["author"] == op:
                    posts.append({"author": p["author"], "is_op": i == 0, "text": p["text"][:limit_chars]})
        videos = []
        for v in res.get("videos", []):
            yt = CACHE / "yt" / f"{v['id']}.json"
            info = json.loads(yt.read_text(encoding="utf-8")) if yt.exists() else {}
            videos.append({"id": v["id"], "title": v.get("title"), "uploader": info.get("uploader"), "description": (info.get("description") or "")[:1200],
                           "comments": [{"by_uploader": c["by_uploader"], "pinned": c["pinned"], "text": c["text"][:600]}
                                        for c in info.get("comments", [])[:6]]})
        items.append({
            "source_url": url, "thread_title": res["fetched"].get("title"), "fetch_status": res["fetched"]["status"],
            "listings": [{"id": i, "title": listing[i]["title"], "regions": listing[i].get("regions", []),
                          "creators": [creators.get(c, c) for c in listing[i]["creators"]],
                          "size": (listing[i].get("size") or {}).get("text")} for i in res["listings"]],
            "opening_posts_by_the_thread_starter": posts, "candidate_links": res["candidates"], "videos": videos,
            "already_decided": res.get("decisions", []),
        })
    out = CACHE / "briefs" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(items)} source pages)")
    return 0


def apply_decisions(path: Path, model: str, retrieved: str) -> int:
    """Merge [{source_url, listing, status, base_url, host, kind, confidence, reason}] into data/resolution."""
    data = json.loads(path.read_text(encoding="utf-8"))
    decisions = data["decisions"] if isinstance(data, dict) else data
    validator = Draft202012Validator(load_json(SCHEMA_DIR / "resolution.schema.json"))
    # The page is found from the listing id, which is unambiguous, not from the URL the agent typed
    # back (a small model sometimes drops a word from a long thread address).
    page_of = {}
    for f in RESOLUTION_DIR.glob("*.json"):
        doc = load_json(f)
        if not isinstance(doc, dict) or "listings" not in doc:
            continue
        for lid in doc["listings"]:
            page_of[lid] = doc["source_url"]
    by_url = defaultdict(list)
    for x in decisions:
        url = page_of.get(x["listing"])
        if url is None:
            print("listing is on no source page:", x["listing"])
            continue
        if x.get("source_url") != url:
            print(f"note: {x['listing']} came back with a different source_url; using {url[-60:]}")
        by_url[url].append(x)
    applied = skipped = 0
    for url, items in by_url.items():
        rp = resolution_path(url)
        if not rp.exists():
            print("unknown source page:", url)
            skipped += len(items)
            continue
        doc = load_json(rp)
        keep = {x["listing"]: x for x in doc.get("decisions", [])}
        for x in items:
            if x["listing"] not in doc["listings"]:
                print("listing not on that page:", x["listing"])
                skipped += 1
                continue
            if keep.get(x["listing"], {}).get("decided_by", {}).get("method") == "human":
                skipped += 1
                continue
            rec = {k: x[k] for k in ("listing", "status", "base_url", "host", "kind", "confidence", "reason") if x.get(k) is not None}
            for field, allowed in (("confidence", ("high", "medium", "low")),
                                   ("host", ("gdrive", "mega", "mediafire", "terabox", "dropbox", "github", "archive_org",
                                             "pixeldrain", "gofile", "kofi", "patreon", "direct", "other")),
                                   ("kind", ("file", "folder", "shop", "page", "unknown"))):
                if rec.get(field) not in allowed:
                    rec.pop(field, None)  # a stray "N/A" on a decision with no link says nothing; drop it
            if rec["status"] == "resolved" and not rec.get("base_url"):
                print("resolved without a base_url:", x["listing"])
                skipped += 1
                continue
            rec["reason"] = rec.get("reason", "")[:400]
            rec["decided_by"] = {"method": "agent", "model": model, "date": retrieved}
            keep[x["listing"]] = rec
            applied += 1
        doc["decisions"] = sorted(keep.values(), key=lambda r: r["listing"])
        errs = list(validator.iter_errors(doc))
        if errs:
            print("schema error in", url, errs[0].message[:200])
            skipped += len(items)
            continue
        write_json(rp, doc)
    print(f"applied {applied}, skipped {skipped}")
    return 0
