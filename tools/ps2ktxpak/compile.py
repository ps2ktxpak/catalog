"""Compile data/ into catalog.json (schemaVersion 2), the one file the app downloads.

In the catalog, names come from the pack's credits, and permission is stated as it is. The source link is
the page its lead creator asked to be linked, else the pack's primary source. Each credited creator comes
with their page, picture, tip and socials links, so an app needs no other file for who made a pack. Archive
facts (hashes, sizes, revision) come from the pack's `archive` block, which only the conversion pipeline
writes. This is the rollup: of all the pack files it takes the hosted ones and puts them in one file. A pack
that is published but has no archive yet is left out: there is nothing for an app to install."""
from __future__ import annotations

import json

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


def _creator(c: dict, base_url: str) -> dict:
    """What an app shows of one creator. A link is left out when the creator has none; the first tip and
    the first socials link are the ones an app has room for."""
    links, avatar = c.get("links", {}), c.get("avatar", {})
    picture = f"{base_url}/{avatar['storage_key']}" if avatar.get("storage_key") else avatar.get("source_url")
    rec = {"name": c["name"]}
    for key, value in (("page", links.get("page")), ("avatar", picture),
                       ("tip", (links.get("tip") or [{}])[0].get("url")),
                       ("socials", (links.get("socials") or [{}])[0].get("url"))):
        if value:
            rec[key] = value
    return rec


def catalog(base_url: str = DEFAULT_BASE) -> dict:
    d = load_all()
    creators = {r["id"]: r for r in d["creators"].values()}
    entries = []
    for pack in sorted((r for r in d["packs"].values() if r["hosting"]["state"] == "published"),
                       key=lambda p: p.get("catalog_id") or p["key"]):
        a = pack.get("archive")
        if a is None:  # published but not converted yet: nothing for an app to install
            continue
        v = next(x for x in a["versions"] if x["revision"] == a["current"])
        names = _creator_names(pack, creators)
        credited = [creators[c["creator"]] for c in pack.get("credits", []) if c["creator"] in creators]
        preferred = credited[0].get("links", {}).get("distribution") if credited else None
        entries.append({
            "id": pack.get("catalog_id") or pack["key"],
            "name": pack["name"],
            "gameTitle": pack["game"]["title"],
            "serials": pack["game"]["serials"],
            "version": pack.get("version") or f"revision {v['revision']}",  # the app drops an entry with none
            "authors": names or [UNKNOWN_CREATOR],
            "credits": "Created by " + ", ".join(names) + "." if names else "Creator not identified.",
            "description": pack.get("description", ""),
            "license": PERMISSION_TEXT[pack.get("permission", {}).get("kind", "unknown")],
            "downloadUrl": f"{base_url}/{v['object']}",
            "format": v["container"],
            "archiveRevision": v["revision"],
            "decompressedSizeBytes": v["decompressed_size_bytes"],
            "sourceUrl": preferred or _primary(pack) or "",
            "sizeBytes": v["size_bytes"],
            "sha256": v["sha256"],
            "fileCount": v["file_count"],
            "previewUrls": [f"{base_url}/{i['storage_key']}" for i in pack.get("media", {}).get("images", []) if i.get("storage_key")],
            # Empty when no one has named the creator; `authors` then holds a placeholder for older apps.
            "creators": [_creator(c, base_url) for c in credited],
            **{k: pack[k] for k in ("type", "completeness") if pack.get(k, "unknown") != "unknown"},
        })
    return {"schemaVersion": 2, "entries": entries}


def dumps_catalog(doc: dict) -> str:
    """Two-space indent, no trailing newline, as textures.json had."""
    return json.dumps(doc, indent=2)
