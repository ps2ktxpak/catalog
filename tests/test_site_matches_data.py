"""The 'Is your pack here?' page is built by TypeScript from the same files this package reads.
If the site has been built, its row counts must equal what the Python side says; otherwise they drifted."""
import json
import re

import pytest

from ps2ktxpak.common import ROOT, read_jsonl
from ps2ktxpak.validate import load_all

PAGE = ROOT / "site" / "dist" / "index.html"


@pytest.mark.skipif(not PAGE.exists(), reason="build the site first: cd site && npm run build")
def test_packs_page_lists_every_published_pack_and_every_unhosted_listing():
    d = load_all()
    published = [p for p in d["packs"].values() if p["hosting"]["state"] == "published"]
    matched = {m["listing"] for m in d["matches"]}
    unhosted = [l for l in d["listings"] if l["id"] not in matched]
    html = PAGE.read_text(encoding="utf-8")
    assert len(re.findall(r'<tr data-kind="hosted"', html)) == len(published)
    assert len(re.findall(r'<tr data-kind="listed"', html)) == len(unhosted)


@pytest.mark.skipif(not PAGE.exists(), reason="build the site first: cd site && npm run build")
def test_every_credited_creator_has_a_page_and_an_uncredited_pack_says_not_named():
    d = load_all()
    credited = {c["creator"] for p in d["packs"].values() if p["hosting"]["state"] == "published" for c in p.get("credits", [])}
    credited |= {c for l in d["listings"] for c in l["creators"]}
    pages = {p.name for p in (ROOT / "site" / "dist" / "creators").iterdir() if p.is_dir()}
    assert credited <= pages, sorted(credited - pages)[:5]
    assert "Not named" in PAGE.read_text(encoding="utf-8")
