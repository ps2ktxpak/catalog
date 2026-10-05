"""Check every file in data/ against its schema, then check the files against each other.

Errors fail the run. Warnings are policy findings that need a decision, not a typo fix: they are
printed with counts and only fail under --strict-policy."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

from .common import CREATORS_DIR, PACKS_DIR, SCHEMA_DIR, host_of, load_json, load_yaml

# Shorteners hide where a link goes; the ad-gating ones (ouo.io and kin) also put an advert in front of it.
SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rb.gy", "shorturl.at",
              "ouo.io", "ouo.press", "adf.ly", "linkvertise.com", "link-hub.net", "exe.io", "shrinkme.io", "shorte.st",
              "fc.lc", "clk.sh", "bc.vc", "sub2unlock.com", "work.ink", "lootlinks.com", "loot-link.com")
PERMITTING = ("creator_uploaded", "creator_approved")
# Routes under /creators/ on the site: a creator with one of these ids would shadow a page.
RESERVED_CREATOR_IDS = ("edit",)


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_json(SCHEMA_DIR / f"{name}.schema.json"))


def _urls(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _urls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _urls(v)
    elif isinstance(obj, str) and obj.startswith("https://"):
        yield obj


def effective_cost(pack: dict) -> str:
    """What the public pays for this pack where its creator distributes it."""
    return pack.get("access", {}).get("cost", "unknown")


def load_all() -> dict:
    def many(directory, loader):
        return {p.name: loader(p) for p in sorted(directory.glob("*.yaml"))} if directory.exists() else {}
    return {"creators": many(CREATORS_DIR, load_yaml), "packs": many(PACKS_DIR, load_yaml)}


def run(strict_policy: bool = False, quiet: bool = False) -> int:
    d = load_all()
    errors: list[str] = []
    warnings: dict[str, list[str]] = defaultdict(list)

    def check(schema: str, rec, where: str):
        for e in sorted(_validator(schema).iter_errors(rec), key=lambda e: list(e.path)):
            path = "/".join(str(p) for p in e.path) or "(top)"
            errors.append(f"{where}: {path}: {e.message[:200]}")

    # Each file against its schema, and its name against its id.
    for fn, r in d["creators"].items():
        check("creator", r, f"creators/{fn}")
        if fn != f"{r.get('id')}.yaml":
            errors.append(f"creators/{fn}: file name must equal id {r.get('id')!r}")
    for fn, r in d["packs"].items():
        check("pack", r, f"packs/{fn}")
        if fn != f"{r.get('key')}.yaml":
            errors.append(f"packs/{fn}: file name must equal key {r.get('key')!r}")

    creators, packs = d["creators"], {r["key"]: r for r in d["packs"].values() if "key" in r}
    creator_ids = {r["id"] for r in creators.values() if "id" in r}
    for cid in sorted(creator_ids.intersection(RESERVED_CREATOR_IDS)):
        errors.append(f"creators/{cid}.yaml: {cid!r} is reserved for a site page")
    wire = Counter(p.get("catalog_id") or p["key"] for p in packs.values())
    for w, n in wire.items():
        if n > 1:
            errors.append(f"catalog id {w[:60]} is used by {n} packs")

    # Cross-references and the rules a schema cannot say.
    for key, p in packs.items():
        for field in ("credits", "listed_credits"):
            for c in p.get(field, []):
                cid = c["creator"] if isinstance(c, dict) else c
                if cid not in creator_ids:
                    errors.append(f"packs/{key}: {field} names an unknown creator {cid!r}")
        for i in p.get("media", {}).get("images", []):
            if i.get("credit") and i["credit"] not in creator_ids:
                errors.append(f"packs/{key}: a picture is credited to an unknown creator {i['credit']!r}")
        if sum(1 for s in p.get("sources", []) if s.get("primary")) > 1:
            errors.append(f"packs/{key}: more than one primary source")
        if p.get("hosting", {}).get("state") == "published":
            if p.get("permission", {}).get("kind") == "revoked":
                errors.append(f"packs/{key}: published although its creator's permission is revoked")
            if not p.get("game", {}).get("serials"):
                errors.append(f"packs/{key}: published but has no game serial, so no game can be matched to it")
            a = p.get("archive")
            if not a:
                # Accepted for hosting, but the conversion pipeline has not made a copy yet.
                warnings["awaiting_conversion"].append(key)
            elif a["current"] not in {v["revision"] for v in a["versions"]}:
                errors.append(f"packs/{key}: archive current revision {a['current']} is not among its versions")

    # Links: https is in the schema; shorteners hide where a link goes.
    for label, recs in (("creator", creators.values()), ("pack", packs.values())):
        for r in recs:
            for u in _urls(r):
                if host_of(u) in SHORTENERS:
                    warnings["url_shortener"].append(f"{label} {r.get('id') or r.get('key')}: {u}")

    # Policy: what we host must be free to the public, or the creator must have said yes.
    for key, p in packs.items():
        if p.get("hosting", {}).get("state") != "published":
            continue
        if effective_cost(p) == "paid" and p.get("permission", {}).get("kind") not in PERMITTING:
            warnings["paid_but_hosted"].append(key)

    if not quiet:
        states = Counter(p.get("hosting", {}).get("state") for p in packs.values())
        print(f"checked: {len(creators)} creators, {len(packs)} packs (" + ", ".join(f"{n} {s}" for s, n in sorted(states.items())) + ")")
        for e in errors[:40]:
            print("ERROR  ", e)
        if len(errors) > 40:
            print(f"... and {len(errors) - 40} more errors")
        for kind, items in warnings.items():
            print(f"WARNING {kind}: {len(items)}" + (f" (e.g. {', '.join(items[:3])})" if items else ""))
        print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors or (strict_policy and warnings) else 0
