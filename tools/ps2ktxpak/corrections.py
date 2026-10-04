"""Apply data/overrides/hand-corrections.yaml: set the listed fields, record why, lock them."""
from __future__ import annotations

from .common import CORRECTIONS_FILE, PACKS_DIR, load_yaml, write_yaml
from .creators import Creators

SOURCE = "hand-correction"


def _set_path(rec: dict, path: str, value) -> bool:
    node, parts = rec, path.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    old = node.get(parts[-1])
    if isinstance(old, list) and isinstance(value, list) and path == "aliases":
        value = old + [v for v in value if v not in old]
    if old == value:
        return False
    node[parts[-1]] = value
    return True


def apply(creators: Creators, packs_order: list[str] | None = None) -> int:
    """Returns the number of fields changed. Creator targets go through the creator store; pack
    targets are edited in place in data/packs."""
    if not CORRECTIONS_FILE.exists():
        return 0
    changed = 0
    for item in load_yaml(CORRECTIONS_FILE) or []:
        kind, ident = item["target"].split(":", 1)
        for path, value in item["set"].items():
            if kind == "creator":
                if ident not in creators.recs:
                    raise SystemExit(f"hand-corrections: no creator {ident!r}")
                if path == "aliases":
                    for a in value:
                        creators.add_alias(ident, a)
                    changed += 1
                    continue
                if creators.set_field(ident, path, value, SOURCE, item["date"], confidence="high",
                                      overwrite=True, note=item["reason"]):
                    changed += 1
                creators.lock(ident, path)
            else:
                f = PACKS_DIR / f"{ident}.yaml"
                if not f.exists():
                    raise SystemExit(f"hand-corrections: no pack {ident!r}")
                rec = load_yaml(f)
                if _set_path(rec, path, value):
                    rec.setdefault("provenance", {})[path] = {"source": SOURCE, "date": item["date"],
                                                              "confidence": "high", "note": item["reason"]}
                    changed += 1
                locked = rec.setdefault("locked", [])
                if path not in locked:
                    locked.append(path)
                write_yaml(f, rec)
    creators.save()
    return changed
