"""The pack list page is built by TypeScript from the same files this package reads. If the site has been
built, its row counts must equal what the Python side says; otherwise they drifted."""
import re

import pytest

from ps2ktxpak.common import ROOT
from ps2ktxpak.validate import load_all

PAGE = ROOT / "site" / "dist" / "index.html"
built = pytest.mark.skipif(not PAGE.exists(), reason="build the site first: cd site && npm run build")


def _by_state(state):
    return [p for p in load_all()["packs"].values() if p["hosting"]["state"] == state]


@built
def test_packs_page_lists_every_hosted_pack_and_every_listed_one_and_each_has_an_edit_button():
    html = PAGE.read_text(encoding="utf-8")
    assert len(re.findall(r'<tr data-kind="hosted"', html)) == len(_by_state("published"))
    assert len(re.findall(r'<tr data-kind="listed"', html)) == len(_by_state("listed"))
    keys = set(re.findall(r'href="[^"]*/packs/edit/\?key=([^"]+)"', html))
    assert keys == {p["key"] for p in _by_state("published") + _by_state("listed")}


@built
def test_every_credited_creator_has_a_page_and_an_uncredited_pack_says_not_named():
    d = load_all()
    shown = _by_state("published") + _by_state("listed")
    credited = {c["creator"] for p in shown for c in p.get("credits", [])} | {c for p in shown for c in p.get("listed_credits", [])}
    pages = {p.name for p in (ROOT / "site" / "dist" / "creators").iterdir() if p.is_dir()}
    assert credited <= pages, sorted(credited - pages)[:5]
    assert "Not named" in PAGE.read_text(encoding="utf-8")


@built
def test_every_page_links_back_to_the_repository_in_its_header():
    pages = [PAGE, PAGE.parent / "creators" / "index.html", PAGE.parent / "packs" / "edit" / "index.html"]
    for page in pages:
        assert 'href="https://github.com/ps2ktxpak/catalog"' in page.read_text(encoding="utf-8"), page
