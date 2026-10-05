"""Read-only views over the data, for the people deciding things."""
from __future__ import annotations

from collections import Counter, defaultdict

from .validate import effective_cost, load_all


def _context():
    d = load_all()
    creators = {r["id"]: r for r in d["creators"].values()}
    packs = {r["key"]: r for r in d["packs"].values()}
    listing = {l["id"]: l for l in d["listings"]}
    matched = defaultdict(list)
    for m in d["matches"]:
        matched[m["pack"]].append(m["listing"])
    costs = {k: [listing[i]["access"]["cost"] for i in ids if i in listing] for k, ids in matched.items()}
    return d, creators, packs, listing, matched, costs


def _names(pack, creators):
    return ", ".join(creators[c["creator"]]["name"] for c in pack.get("credits", []) if c["creator"] in creators) or "(unknown)"


def summary() -> str:
    d, creators, packs, listing, matched, costs = _context()
    hosted = [p for p in packs.values() if p["hosting"]["state"] == "published"]
    eff = Counter(effective_cost(p, costs.get(p["key"], [])) for p in hosted)
    matched_listings = {i for ids in matched.values() for i in ids}
    unhosted = [l for l in listing.values() if l["id"] not in matched_listings]
    res = Counter(x["status"] for r in d["resolution"].values() for x in r.get("decisions", []))
    flags = Counter(f for p in packs.values() for f in p.get("needs_review", []))
    lines = [
        f"creators            {len(creators)}",
        f"hosted packs        {len(hosted)}   (effective cost: " + ", ".join(f"{k} {v}" for k, v in sorted(eff.items())) + ")",
        f"  matched to a listing   {sum(1 for p in hosted if p['key'] in matched)}",
        f"  needs credit review    " + ", ".join(f"{k} {v}" for k, v in sorted(flags.items())),
        f"sheet listings      {len(listing)}   ({len(matched_listings)} are packs we host; {len(unhosted)} are not)",
        "  not hosted, by cost  " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(l['access']['cost'] for l in unhosted).items())),
        f"link resolution     {sum(res.values())} decisions " + (", ".join(f"{k} {v}" for k, v in sorted(res.items())) or "(none yet)"),
    ]
    return "\n".join(lines)


def paid_hosted() -> str:
    d, creators, packs, listing, matched, costs = _context()
    rows = defaultdict(list)
    for p in packs.values():
        if p["hosting"]["state"] == "published" and effective_cost(p, costs.get(p["key"], [])) == "paid" \
                and p.get("permission", {}).get("kind") not in ("creator_uploaded", "creator_approved"):
            rows[_names(p, creators)].append(p["game"]["title"])
    out = [f"{sum(len(v) for v in rows.values())} hosted packs are listed as paid and have no recorded permission:"]
    for who, games in sorted(rows.items(), key=lambda kv: -len(kv[1])):
        out.append(f"  {who}: {len(games)}  (" + "; ".join(sorted(games)[:4]) + ("; ..." if len(games) > 4 else "") + ")")
    return "\n".join(out)


def unmatched() -> str:
    d, creators, packs, listing, matched, costs = _context()
    out = [f"{sum(1 for k in packs if k not in matched)} hosted packs have no matching sheet listing:"]
    for k, p in sorted(packs.items()):
        if k not in matched:
            out.append(f"  {k}  [{_names(p, creators)}]  {p['game']['title']}")
    return "\n".join(out)


def credits() -> str:
    """The packs whose credit nobody has checked yet: the list for Sad Origami's reviewers."""
    d, creators, packs, listing, matched, costs = _context()
    by = defaultdict(list)
    for k, p in sorted(packs.items()):
        for f in p.get("needs_review", []):
            by[f].append(k)
    out = []
    for f, keys in by.items():
        out.append(f"\n## {f}  ({len(keys)})")
        for k in keys:
            p = packs[k]
            out.append(f"  {k}: {p['game']['title']} -> {_names(p, creators)}")
    return "\n".join(out).lstrip("\n")


REPORTS = {"summary": summary, "paid-hosted": paid_hosted, "unmatched": unmatched, "credits": credits}
