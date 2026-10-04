"""Seed data/packs and data/archives from what is live today.

Inputs, all public: the catalog (textures.json), the creator links file jpolo1224 built from the
spreadsheet (texture-pack-links.json) and each pack's conversion record (packs/<id>.json). This is a
one-time seed: a pack that already has a file is left exactly as a human may have edited it.
"""
from __future__ import annotations

import concurrent.futures
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import corrections
from .common import (ARCHIVES_DIR, CACHE, PACKS_DIR, USER_AGENT, https, load_json, load_yaml, name_key,
                     norm_status, norm_type, ordered, source_kind, write_json, write_yaml)
from .creators import Creators

BASE_URL = "https://dl.ps2ktxpak.net"
SRC_CATALOG = "emucorex-textures-catalog"
SRC_LINKS = "texture-pack-links (jpolo1224, from sad-origami-sheet)"
PACK_ORDER = ["key", "catalog_id", "name", "game", "credits", "type", "completeness", "description", "sources", "media",
              "access", "permission", "hosting", "needs_review", "legacy", "provenance", "locked"]


# ---- fetching ------------------------------------------------------------------------------------

def _get(url: str, dest: Path, offline: bool) -> bytes | None:
    if dest.exists():
        return dest.read_bytes()
    if offline:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
    except (urllib.error.URLError, TimeoutError):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return body


def fetch_live(base_url: str, offline: bool) -> tuple[dict, dict, dict[str, dict]]:
    """(catalog, links file, {pack id: conversion record}). Cached under cache/live/."""
    import json
    live = CACHE / "live"
    cat = _get(f"{base_url}/textures.json", live / "textures.json", offline)
    links = _get(f"{base_url}/texture-pack-links.json", live / "texture-pack-links.json", offline)
    if cat is None:
        raise SystemExit(f"cannot read {base_url}/textures.json (offline, or the host is unreachable)")
    catalog = json.loads(cat)
    links_doc = json.loads(links) if links else {"packs": {}, "creators": {}}
    ids = [e["id"] for e in catalog["entries"]]

    def side(pid):
        body = _get(f"{base_url}/packs/{pid}.json", live / "packs" / f"{pid}.json", offline)
        return pid, (json.loads(body) if body else None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        sidecars = {pid: s for pid, s in pool.map(side, ids) if s}
    return catalog, links_doc, sidecars


# ---- reading the catalog's creator text ------------------------------------------------------------

def catalog_names(entry: dict) -> list[str]:
    """Creator names inside a catalog entry's `authors`. The field is often a sentence cut at 'and'
    ("HD texture pack created" / "maintained by X."), a credit line, or an admission of not knowing."""
    text = " and ".join(a.strip() for a in entry.get("authors", []) if a.strip())
    if re.search(r"not identified|Community Archive$|community mirror$", text, re.I):
        return []
    m = re.search(r"credited to (.+?) by the curated", text)
    if m:
        return [a.strip() for a in m.group(1).split("|") if a.strip()]
    m = re.search(r"(?:created|maintained) by (.+?)(?: \(| for |\.?$)", text)
    if m:
        return [m.group(1).strip()]
    if re.search(r"texture|pack\b|created|maintained", text, re.I):
        return []
    m = re.match(r"(\S+) \(repository mirror by", text)
    if m:
        return [m.group(1)]
    return [p.strip() for a in entry.get("authors", []) for p in re.split(r"[:|]", a) if p.strip()]


# ---- the seed ------------------------------------------------------------------------------------

def run(base_url: str, retrieved: str, offline: bool = False) -> dict:
    catalog, links_doc, sidecars = fetch_live(base_url, offline)
    links = links_doc.get("packs", {})
    creators = Creators()
    corrections.apply(creators)  # aliases first, so a catalog name like "IceBullet" finds its creator

    existing = {}
    for f in PACKS_DIR.glob("*.yaml"):
        rec = load_yaml(f)
        existing[rec.get("catalog_id") or rec["key"]] = rec["key"]
    taken = set(existing.values())

    stats = {"packs": 0, "kept_existing": 0, "no_sidecar": 0, "sha_mismatch": 0,
             "flags": {"credit_assigned_from_listing": 0, "co_credit_unconfirmed": 0, "credit_unknown": 0}}
    for e in sorted(catalog["entries"], key=lambda x: x["id"]):
        pid = e["id"]
        L = links.get(pid) or {}

        # Credits: the links file's creator names first, then any catalog-credited creator the
        # sheet did not confirm (losing a credit is the failure to avoid; a human decides).
        cat = catalog_names(e)
        if L.get("creator"):
            names, basis = [n.strip() for n in L["creator"].split(", ") if n.strip()], "links"
        elif L.get("unknown"):
            names, basis = [], "unknown"
        else:
            names, basis = list(cat), "catalog"
        cids: list[str] = []
        for n in names:
            cid = creators.ensure(n, SRC_LINKS if basis == "links" else SRC_CATALOG, retrieved)
            if cid not in cids:
                cids.append(cid)
        flags = []
        if basis == "links" and not cat:
            flags.append("credit_assigned_from_listing")
        extra = []
        for n in cat:
            cid = creators.ensure(n, SRC_CATALOG, retrieved)
            if cid not in cids and cid not in extra:
                extra.append(cid)
        if extra and basis != "unknown":
            cids += extra
            flags.append("co_credit_unconfirmed")
        if not cids:
            flags.append("credit_unknown")
        for f in flags:
            stats["flags"][f] += 1

        if pid in existing:
            key = existing[pid]
        else:
            lead = cids[0] if cids else "unknown"
            base = f"{min(e['serials']).lower()}-{lead}"[:76].rstrip("-")
            key, n = base, 2
            while key in taken:
                key, n = f"{base}-{n}", n + 1
            taken.add(key)

        # Archive record: the pipeline's facts for this pack.
        side = sidecars.get(pid)
        archive = {
            "revision": e["archiveRevision"], "container": e["format"],
            "object": urlparse(e["downloadUrl"]).path.lstrip("/"),
            "sha256": e["sha256"], "size_bytes": e["sizeBytes"],
            "decompressed_size_bytes": e["decompressedSizeBytes"], "file_count": e["fileCount"],
            "created": None,
            "converter": {"tool": "kram", "pipeline": "migrate.py (2026-09)",
                          "params": "astc6x6 quality 98, up to 7 mip levels; tar --format=gnu | zstd -19 --long=27"},
        }
        if side:
            archive["source"] = {"sha256": side["source"]["sha256"], "size_bytes": side["source"]["sizeBytes"]}
            if side["archive"]["sha256"].lower() != e["sha256"].lower():
                stats["sha_mismatch"] += 1
        else:
            stats["no_sidecar"] += 1
        write_json(ARCHIVES_DIR / f"{key}.json", {
            "key": key, "current": e["archiveRevision"],
            "versions": [{k: v for k, v in archive.items() if v is not None}]})

        if pid in existing:
            stats["kept_existing"] += 1
            continue

        primary = https(L.get("source")) or e["sourceUrl"]
        sources = [{"kind": source_kind(primary), "url": primary, "primary": True}]
        if e["sourceUrl"] != primary:
            sources.append({"kind": source_kind(e["sourceUrl"]), "url": e["sourceUrl"], "primary": False,
                            "note": "the catalog's original link"})
        conf = ("low" if "credit_assigned_from_listing" in flags
                else "medium" if "co_credit_unconfirmed" in flags or basis != "links" else "high")
        src = {"source": SRC_CATALOG, "date": retrieved}
        pack = {
            "key": key, "catalog_id": pid, "name": e["name"],
            "game": {"title": e.get("gameTitle") or e["name"], "serials": list(e["serials"])},
            "credits": [{"creator": c} for c in cids],
            "type": norm_type(L.get("type", "")), "completeness": norm_status(L.get("status", "")),
            "description": e.get("description", ""),
            "sources": sources,
            "permission": {"kind": "unknown",
                           "note": "Inherited from the EmuCoreX-Textures catalog; no permission was recorded."},
            "hosting": {"state": "published"},
            "needs_review": flags,
            "legacy": {"authors": e["authors"], "credits": e.get("credits", ""), "license": e.get("license", ""),
                       "source_url": e["sourceUrl"], "version": e.get("version", ""),
                       "preview_urls": e.get("previewUrls", [])},
            "provenance": {
                "name": src, "game": src, "description": src, "sources": src,
                "credits": {"source": SRC_LINKS if basis == "links" else SRC_CATALOG, "date": retrieved,
                            "confidence": conf},
                "permission": {"source": "importer", "date": retrieved,
                               "note": "the catalog this pack came from records none"},
            },
        }
        write_yaml(PACKS_DIR / f"{key}.yaml", ordered(pack, PACK_ORDER, keep=("credits",)))
        stats["packs"] += 1

    # Creators the links file knows: their page and picture.
    for name, rec in (links_doc.get("creators") or {}).items():
        cid = creators.ensure(name, SRC_LINKS, retrieved)
        creators.set_field(cid, "links.page", https(rec.get("page")), SRC_LINKS, retrieved, confidence="medium")
        creators.set_field(cid, "avatar.source_url", https(rec.get("avatar")), SRC_LINKS, retrieved,
                           confidence="medium")
    corrections.apply(creators)
    creators.save()
    stats["creators_total"] = len(creators.recs)
    stats["conflicts"] = creators.conflicts
    return stats
