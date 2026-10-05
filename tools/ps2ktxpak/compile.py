"""Compile data/ into the files the app downloads.

  catalog  -> textures.json (schemaVersion 2), what every installed build reads
  links    -> texture-pack-links.json (schemaVersion 1), a compatibility projection for the builds
              that read jpolo1224's overlay

In the catalog, names come from the pack's credits, the source link from its primary source, and
permission is stated as it is. Archive facts (hashes, sizes, revision) come from data/archives,
never from a pack file. A pack that is published but has no archive record yet is left out: there
is nothing for an app to install."""
from __future__ import annotations

import json

from .common import STATUS_LABEL, TYPE_LABEL
from .validate import load_all

DEFAULT_BASE = "https://dl.ps2ktxpak.net"
UNKNOWN_CREATOR = "Unknown creator"  # older apps drop a pack whose authors list is empty
PERMISSION_TEXT = {
    "creator_uploaded": "Uploaded by its creator",
    "creator_approved": "Hosted with its creator's approval",
    "community_mirror": "Community mirror; the creator has not been asked",
    "unknown": "Redistribution permission not recorded",
    "revoked": "Permission withdrawn",
}


def _creator_names(pack: dict, creators: dict[str, dict]) -> list[str]:
    return [creators[c["creator"]]["name"] for c in pack.get("credits", []) if c["creator"] in creators]


def _primary(pack: dict) -> str | None:
    for s in pack.get("sources", []):
        if s.get("primary"):
            return s["url"]
    return pack["sources"][0]["url"] if pack.get("sources") else None


def catalog(base_url: str = DEFAULT_BASE) -> dict:
    d = load_all()
    creators = {r["id"]: r for r in d["creators"].values()}
    archives = {r["key"]: r for r in d["archives"].values()}
    entries = []
    for pack in sorted((r for r in d["packs"].values() if r["hosting"]["state"] == "published"),
                       key=lambda p: p.get("catalog_id") or p["key"]):
        a = archives.get(pack["key"])
        if a is None:  # published but not converted yet: nothing for an app to install
            continue
        v = next(x for x in a["versions"] if x["revision"] == a["current"])
        names = _creator_names(pack, creators)
        entries.append({
            "id": pack.get("catalog_id") or pack["key"],
            "name": pack["name"],
            "gameTitle": pack["game"]["title"],
            "serials": pack["game"]["serials"],
            "version": pack.get("version", ""),
            "authors": names or [UNKNOWN_CREATOR],
            "credits": "Created by " + ", ".join(names) + "." if names else "Creator not identified.",
            "description": pack.get("description", ""),
            "license": PERMISSION_TEXT[pack.get("permission", {}).get("kind", "unknown")],
            "downloadUrl": f"{base_url}/{v['object']}",
            "format": v["container"],
            "archiveRevision": v["revision"],
            "decompressedSizeBytes": v["decompressed_size_bytes"],
            "sourceUrl": _primary(pack) or "",
            "sizeBytes": v["size_bytes"],
            "sha256": v["sha256"],
            "fileCount": v["file_count"],
            "previewUrls": [f"{base_url}/{i['storage_key']}" for i in pack.get("media", {}).get("images", []) if i.get("storage_key")],
        })
    return {"schemaVersion": 2, "entries": entries}


def links_v1() -> dict:
    """The overlay file older builds of the namco branch read. Tip and socials are per creator in
    our data, so a pack gets its lead creator's; the original file carried a few per-pack ones."""
    d = load_all()
    creators = {r["id"]: r for r in d["creators"].values()}
    packs, people = {}, {}
    converted = {r["key"] for r in d["archives"].values()}
    for pack in sorted((r for r in d["packs"].values() if r["hosting"]["state"] == "published" and r["key"] in converted),
                       key=lambda p: p.get("catalog_id") or p["key"]):
        wire = pack.get("catalog_id") or pack["key"]
        cs = [creators[c["creator"]] for c in pack.get("credits", []) if c["creator"] in creators]
        rec: dict = {}
        if cs:
            rec["creator"] = ", ".join(c["name"] for c in cs)
            lead = cs[0]
            tip, soc = (lead.get("links", {}).get("tip") or [None])[0], (lead.get("links", {}).get("socials") or [None])[0]
            if tip:
                rec["tip"] = tip["url"]
            if soc:
                rec["socials"] = soc["url"]
            page = lead.get("links", {}).get("page")
            rec_person = {k: v for k, v in (("page", page), ("avatar", lead.get("avatar", {}).get("source_url"))) if v}
            if rec_person:
                people[lead["name"]] = rec_person
        else:
            rec["unknown"] = True
        src = _primary(pack)
        if src:
            lead_pref = cs[0].get("links", {}).get("distribution") if cs else None
            rec["source"] = lead_pref or src
        if pack.get("type", "unknown") != "unknown":
            rec["type"] = TYPE_LABEL[pack["type"]]
        if pack.get("completeness", "unknown") != "unknown":
            rec["status"] = STATUS_LABEL[pack["completeness"]]
        packs[wire] = rec
    return {"schemaVersion": 1, "creators": dict(sorted(people.items())), "packs": packs}


def dumps_catalog(doc: dict) -> str:
    """The format of the live file: two-space indent, no trailing newline."""
    return json.dumps(doc, indent=2)
