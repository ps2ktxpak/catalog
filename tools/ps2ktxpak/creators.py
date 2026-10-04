"""data/creators/*.yaml as one in-memory store: find, create, merge, save.

Importers go through this so that a human-edited field (listed in `locked`, or simply already
filled) is never overwritten by a later import."""
from __future__ import annotations

from pathlib import Path

from .common import CREATORS_DIR, load_yaml, name_key, ordered, slugify, write_yaml

ORDER = ["id", "name", "aliases", "links", "avatar", "identity", "status", "provenance", "locked"]


def _empty(v) -> bool:
    return v in (None, "", [], {})


class Creators:
    def __init__(self, directory: Path = CREATORS_DIR):
        self.dir = directory
        self.recs: dict[str, dict] = {}
        self.dirty: set[str] = set()
        self.conflicts: list[str] = []
        for p in sorted(directory.glob("*.yaml")):
            r = load_yaml(p)
            self.recs[r["id"]] = r
        self.by_key: dict[str, str] = {}
        for cid, r in self.recs.items():
            self._index(cid, r)

    def _index(self, cid: str, r: dict) -> None:
        for n in [r["name"], *r.get("aliases", [])]:
            k = name_key(n)
            if k and self.by_key.setdefault(k, cid) != cid:
                self.conflicts.append(f"name {n!r} of {cid} also matches {self.by_key[k]}")

    def find(self, name: str) -> str | None:
        return self.by_key.get(name_key(name))

    def ensure(self, name: str, source: str, date: str) -> str:
        """The id for `name`, creating the creator if no name or alias matches."""
        name = name.strip()
        cid = self.find(name)
        if cid:
            self.add_alias(cid, name)
            return cid
        base = (slugify(name) or "creator")[:44].strip("-") or "creator"
        cid, n = base, 2
        while cid in self.recs:
            cid, n = f"{base}-{n}", n + 1
        self.recs[cid] = {"id": cid, "name": name, "status": "active",
                          "provenance": {"name": {"source": source, "date": date}}}
        self._index(cid, self.recs[cid])
        self.dirty.add(cid)
        return cid

    def add_alias(self, cid: str, alias: str) -> None:
        r = self.recs[cid]
        alias = alias.strip()
        if not alias or alias == r["name"] or alias in r.get("aliases", []):
            return
        owner = self.by_key.get(name_key(alias))
        if owner and owner != cid:
            self.conflicts.append(f"alias {alias!r} for {cid} already belongs to {owner}")
            return
        r.setdefault("aliases", []).append(alias)
        self.by_key.setdefault(name_key(alias), cid)
        self.dirty.add(cid)

    def set_field(self, cid: str, path: str, value, source: str, date: str, *,
                  confidence: str | None = None, overwrite: bool = False, note: str | None = None) -> bool:
        """Set a dotted path unless it is locked, or already filled and overwrite is False."""
        r = self.recs[cid]
        if path in r.get("locked", []) or _empty(value):
            return False
        node, parts = r, path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        if not _empty(node.get(parts[-1])) and not overwrite:
            return False
        if node.get(parts[-1]) == value:
            return False
        node[parts[-1]] = value
        prov = {"source": source, "date": date}
        if confidence:
            prov["confidence"] = confidence
        if note:
            prov["note"] = note
        r.setdefault("provenance", {})[path] = prov
        self.dirty.add(cid)
        return True

    def lock(self, cid: str, path: str) -> None:
        locked = self.recs[cid].setdefault("locked", [])
        if path not in locked:
            locked.append(path)
            self.dirty.add(cid)

    def save(self) -> int:
        self.dir.mkdir(parents=True, exist_ok=True)
        for cid in sorted(self.dirty):
            write_yaml(self.dir / f"{cid}.yaml", ordered(self.recs[cid], ORDER))
        n = len(self.dirty)
        self.dirty.clear()
        return n
