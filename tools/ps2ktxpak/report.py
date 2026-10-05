"""Read-only views over the data, for the people deciding things."""
from __future__ import annotations

from collections import Counter, defaultdict

from .validate import effective_cost, load_all


def _context():
    d = load_all()
    creators = {r["id"]: r for r in d["creators"].values()}
    packs = {r["key"]: r for r in d["packs"].values()}
    return creators, packs


def _names(pack, creators):
    return ", ".join(creators[c["creator"]]["name"] for c in pack.get("credits", []) if c["creator"] in creators) or "(unknown)"


def _by_state(packs):
    return {state: [p for p in packs.values() if p["hosting"]["state"] == state] for state in {p["hosting"]["state"] for p in packs.values()}}


def summary() -> str:
    creators, packs = _context()
    by_state = _by_state(packs)
    hosted, listed = by_state.get("published", []), by_state.get("listed", [])
    eff = Counter(effective_cost(p) for p in hosted)
    flags = Counter(f for p in packs.values() for f in p.get("needs_review", []))
    downloads = Counter(p["download"]["status"] for p in listed if "download" in p)
    lines = [
        f"creators            {len(creators)}",
        f"hosted packs        {len(hosted)}   (effective cost: " + ", ".join(f"{k} {v}" for k, v in sorted(eff.items())) + ")",
        f"  awaiting conversion    {sum(1 for p in hosted if 'archive' not in p)}",
        f"  needs credit review    " + ", ".join(f"{k} {v}" for k, v in sorted(flags.items())),
        f"listed packs        {len(listed)}   (not hosted; by cost: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(effective_cost(p) for p in listed).items())) + ")",
        f"  download search        {sum(downloads.values())} decisions " + (", ".join(f"{k} {v}" for k, v in sorted(downloads.items())) or "(none yet)"),
        "other states        " + (", ".join(f"{k} {len(v)}" for k, v in sorted(by_state.items()) if k not in ("published", "listed")) or "(none)"),
    ]
    return "\n".join(lines)


def paid_hosted() -> str:
    creators, packs = _context()
    rows = defaultdict(list)
    for p in packs.values():
        if p["hosting"]["state"] == "published" and effective_cost(p) == "paid" \
                and p.get("permission", {}).get("kind") not in ("creator_uploaded", "creator_approved"):
            rows[_names(p, creators)].append(p["game"]["title"])
    out = [f"{sum(len(v) for v in rows.values())} hosted packs are listed as paid and have no recorded permission:"]
    for who, games in sorted(rows.items(), key=lambda kv: -len(kv[1])):
        out.append(f"  {who}: {len(games)}  (" + "; ".join(sorted(games)[:4]) + ("; ..." if len(games) > 4 else "") + ")")
    return "\n".join(out)


def credits() -> str:
    """The packs whose credit nobody has checked yet: the list for Sad Origami's reviewers."""
    creators, packs = _context()
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


REPORTS = {"summary": summary, "paid-hosted": paid_hosted, "credits": credits}
