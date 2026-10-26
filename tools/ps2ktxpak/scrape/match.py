"""Find the pack file a spreadsheet row describes.

A row matches a pack when the pack lists the row's download page among its sources, the pack
credits the row's author, and the game titles agree. A forum library thread lists many games, so
the page alone is not enough. A row that matches nothing is a pack we have no file for yet."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from .sheet import Row


def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(w for w in text.split() if w != "the")


def page_key(url: str | None) -> str | None:
    """One key per page, whatever its spelling: GBAtemp threads by number, others by host and path."""
    if not url:
        return None
    u = urlparse(url.strip())
    host = re.sub(r"^(www\.|m\.)", "", u.netloc.lower())
    if host == "gbatemp.net" and (m := re.search(r"/threads/(?:[^/]*\.)?(\d+)", u.path)):
        return f"gbatemp:{m.group(1)}"
    return f"{host}{u.path.rstrip('/').lower()}"


class Index:
    def __init__(self, packs, creators):
        """`packs` and `creators` are the records, as lists or as the values of any mapping."""
        packs = list(packs.values()) if isinstance(packs, dict) else list(packs)
        creators = list(creators.values()) if isinstance(creators, dict) else list(creators)
        self.packs = {p["key"]: p for p in packs}
        self.by_name = {}
        for c in creators:
            cid = c["id"]
            for n in [cid, c.get("name"), *c.get("aliases", [])]:
                if n:
                    self.by_name.setdefault(norm(n).replace(" ", ""), cid)
        self.by_page = {}
        self.by_creator = {}
        for key, p in self.packs.items():
            for k in {page_key(s.get("url")) for s in p.get("sources", [])} - {None}:
                self.by_page.setdefault(k, []).append(key)
            for c in p.get("credits", []):
                self.by_creator.setdefault(c["creator"], []).append(key)

    def creator_of(self, row: Row) -> str | None:
        return self.by_name.get(norm(row.author).replace(" ", "")) if row.author else None

    def candidates(self, row: Row) -> list[str]:
        """Packs on the row's page, credited to its author, for its game."""
        on_page = self.by_page.get(page_key(row.download), [])
        cid = self.creator_of(row)
        credited = [k for k in on_page
                    if cid and cid in {c["creator"] for c in self.packs[k].get("credits", [])}]
        title = norm(row.title)
        exact = [k for k in credited if _same_game(title, self.packs[k])]
        return exact or [k for k in credited if _same_game(title, self.packs[k], loose=True)]

    def match(self, row: Row) -> str | None:
        found = self.candidates(row)
        if len(found) > 1 and row.region:
            # Two regions of one game by one creator on one page: the region decides.
            region = row.region.upper()
            by_region = [k for k in found if region in self.packs[k].get("game", {}).get("regions", [])]
            if len(by_region) == 1:
                return by_region[0]
        return found[0] if len(found) == 1 else None

    def known(self, row: Row) -> bool:
        """Whether some pack already describes this row: on its page, or by its author for its game."""
        if self.candidates(row):
            return True
        cid, title = self.creator_of(row), norm(row.title)
        serial = (row.serial or "").upper()
        return any(_same_game(title, self.packs[k], loose=True)
                   or serial in self.packs[k].get("game", {}).get("serials", [])
                   for k in self.by_creator.get(cid, []))


def _same_game(title: str, pack: dict, loose: bool = False) -> bool:
    """Same title, ignoring spaces ("Megaman X8" is "Mega Man X8"). Loosely, one title may contain
    the other ("Digital Devil Saga" in "Shin Megami Tensei: Digital Devil Saga"), which is only
    safe once the page and the creator already agree."""
    t = title.replace(" ", "")
    others = [norm(pack.get("game", {}).get("title")).replace(" ", ""), norm(pack.get("name")).replace(" ", "")]
    if loose:
        return any(o and (t in o or o in t) for o in others)
    return t in others
