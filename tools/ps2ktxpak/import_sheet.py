"""Ingest the Texture Packs Archive spreadsheet (PS2 tab) into data/listings and data/creators.

What is imported: title, author, the row's download page, region, size, restriction, status, type,
and the row's tip and socials links. What is deliberately not: the FREE MIRROR column (the
maintainer's own hosting) and the Blacklist tab (his curation of accusations, not ours to republish).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from . import sheet as xlsx
from .common import (CREATORS_DIR, LISTINGS_FILE, access_from_restriction, https, link_kind, name_key,
                     norm_regions, norm_status, norm_type, parse_size_bytes, sha1_short, title_key,
                     write_jsonl)
from .creators import Creators

SOURCE = "sad-origami-sheet"
_SPLIT = re.compile(r"\s*[|/,&]\s*|\s+and\s+")
_MEMBER = re.compile(r"/members/([^./]+)\.\d+")


def split_authors(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if raw in ("", "N/A"):
        return []
    return [p.strip() for p in _SPLIT.split(raw) if p.strip()]


def run(xlsx_path: Path, retrieved: str, tab: str = "PS2", creators: Creators | None = None) -> dict:
    headers, rows = xlsx.read_tab(xlsx_path, tab)
    missing = {"TITLE", "DOWNLOAD", "AUTHOR"} - set(headers)
    if missing:
        raise SystemExit(f"tab {tab!r} lacks column(s) {sorted(missing)}; its columns are {headers}. "
                         "The sheet's layout changed: update the importer before importing.")
    creators = creators or Creators(CREATORS_DIR)

    # Pass 1: what each author is called and which links the sheet gives them.
    agg: dict[str, dict] = defaultdict(lambda: {"spell": Counter(), "profile": Counter(), "tip": Counter(),
                                                "socials": Counter(), "members": set()})
    entries = []
    for r in rows:
        title = r.text("TITLE")
        if not title:
            continue
        author_raw = r.text("AUTHOR")
        parts = split_authors(author_raw)
        profile, tip, socials = https(r.link("AUTHOR")), https(r.link("DONATE")), https(r.link("SOCIALS"))
        for p in parts:
            a = agg[name_key(p)]
            a["spell"][p] += 1
            if len(parts) == 1:  # a joint row's links cannot be told apart
                for fld, url in (("profile", profile), ("tip", tip), ("socials", socials)):
                    if url:
                        a[fld][url] += 1
                m = _MEMBER.search(profile or "")
                if m:
                    a["members"].add(m.group(1))
        entries.append((r, title, author_raw, parts, profile, tip, socials))

    # Pass 2: creators, in a fixed order so ids come out the same on every run.
    cid_of: dict[str, str] = {}
    for key, a in sorted(agg.items(), key=lambda kv: kv[1]["spell"].most_common(1)[0][0].lower()):
        display = a["spell"].most_common(1)[0][0]
        cid = creators.ensure(display, SOURCE, retrieved)
        cid_of[key] = cid
        for spelling in a["spell"]:
            creators.add_alias(cid, spelling)
        for member in sorted(a["members"]):
            creators.add_alias(cid, member)
        modal = lambda c: c.most_common(1)[0][0] if c else None
        page = modal(a["profile"]) or modal(a["socials"])
        creators.set_field(cid, "links.page", page, SOURCE, retrieved, confidence="high")
        if modal(a["tip"]):
            creators.set_field(cid, "links.tip", [{"kind": link_kind(modal(a["tip"])), "url": modal(a["tip"])}],
                               SOURCE, retrieved, confidence="high")
        if modal(a["socials"]):
            creators.set_field(cid, "links.socials",
                               [{"kind": link_kind(modal(a["socials"])), "url": modal(a["socials"])}],
                               SOURCE, retrieved, confidence="high")

    # Listings.
    records, seen = [], Counter()
    for r, title, author_raw, parts, profile, tip, socials in entries:
        page = https(r.link("DOWNLOAD"))
        base = f"{title_key(title)}|{name_key(author_raw)}|{page or ''}"
        seen[base] += 1
        lid = "l-" + sha1_short(base if seen[base] == 1 else f"{base}|{seen[base]}")
        size_text = r.text("SIZE")
        rec = {
            "id": lid,
            "source": {"name": SOURCE, "tab": tab, "row": r.n, "retrieved": retrieved},
            "title": title,
            "regions": norm_regions(r.text("REGION")),
            "type": norm_type(r.text("TYPE")),
            "completeness": norm_status(r.text("STATUS")),
            "access": access_from_restriction(r.text("RESTRICTION")),
            "creators": [cid_of[name_key(p)] for p in parts],
            "author_raw": author_raw,
            "source_page": page,
            "links": {k: v for k, v in (("profile", profile), ("tip", tip), ("socials", socials)) if v},
            "size": {"text": size_text, "bytes_estimate": parse_size_bytes(size_text)} if size_text else None,
            "raw": {k: v for k, v in (("region", r.text("REGION")), ("status", r.text("STATUS")),
                                      ("type", r.text("TYPE"))) if v},
        }
        # Empty lists stay (an unattributed listing has `creators: []`); empty objects and strings go.
        records.append({k: v for k, v in rec.items() if not (v is None or v == {} or v == "")})
    records.sort(key=lambda x: (x["title"].lower(), x["id"]))
    write_jsonl(LISTINGS_FILE, records)
    creators.save()

    cost = Counter(x["access"]["cost"] for x in records)
    return {"listings": len(records), "creators": len(cid_of), "cost": dict(cost),
            "conflicts": creators.conflicts}
