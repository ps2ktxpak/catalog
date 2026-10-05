import copy
import json

import pytest

from ps2ktxpak import compile as C
from ps2ktxpak import validate
from ps2ktxpak.common import load_yaml, write_json, write_jsonl, write_yaml

CREATOR = {"id": "dev1", "name": "Dev One"}
PACK = {"key": "slus-20000-dev1", "name": "A Pack", "game": {"title": "A Game", "serials": ["SLUS-20000"]},
        "credits": [{"creator": "dev1"}], "hosting": {"state": "published"}}
ARCHIVE = {"key": "slus-20000-dev1", "current": 1, "versions": [{
    "revision": 1, "container": "tar+zstd", "object": "packs/x.tar.zst", "sha256": "a" * 64,
    "size_bytes": 10, "decompressed_size_bytes": 20, "file_count": 3}]}
LISTING = {"id": "l-aaaaaaaaaa", "source": {"name": "sad-origami-sheet", "tab": "PS2", "row": 3, "retrieved": "2026-10-03"},
           "title": "A Game", "access": {"cost": "paid", "restriction_raw": "Paywall"}, "creators": ["dev1"]}
MATCH = {"listing": "l-aaaaaaaaaa", "pack": "slus-20000-dev1", "method": "title", "confidence": "high"}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for name, sub in (("CREATORS_DIR", "creators"), ("PACKS_DIR", "packs"), ("ARCHIVES_DIR", "archives"),
                      ("RESOLUTION_DIR", "resolution")):
        monkeypatch.setattr(validate, name, tmp_path / sub)
    monkeypatch.setattr(validate, "LISTINGS_FILE", tmp_path / "listings.jsonl")
    monkeypatch.setattr(validate, "MATCHES_FILE", tmp_path / "matches.jsonl")

    class T:
        root = tmp_path

        def write(self, creator=CREATOR, pack=PACK, archive=ARCHIVE, listing=LISTING, match=MATCH):
            write_yaml(tmp_path / "creators" / f"{creator['id']}.yaml", creator)
            write_yaml(tmp_path / "packs" / f"{pack['key']}.yaml", pack)
            if archive:
                write_json(tmp_path / "archives" / f"{archive['key']}.json", archive)
            write_jsonl(tmp_path / "listings.jsonl", [listing] if listing else [])
            write_jsonl(tmp_path / "matches.jsonl", [match] if match else [])
            return self
    return T()


def test_a_consistent_tree_passes_and_a_paid_hosted_pack_is_a_warning(tree, capsys):
    tree.write()
    assert validate.run() == 0
    assert "WARNING paid_but_hosted: 1" in capsys.readouterr().out
    assert validate.run(strict_policy=True) == 1


def test_creator_permission_clears_the_policy_warning(tree, capsys):
    p = copy.deepcopy(PACK)
    p["permission"] = {"kind": "creator_approved"}
    tree.write(pack=p)
    assert validate.run(strict_policy=True) == 0


def test_a_creator_cannot_take_an_id_the_site_uses_for_a_page(tree, capsys):
    tree.write(creator={"id": "edit", "name": "Edit"}, pack={**PACK, "credits": [{"creator": "edit"}]}, listing={**LISTING, "creators": ["edit"]})
    assert validate.run() == 1
    assert "reserved for a site page" in capsys.readouterr().out


def test_free_packs_are_fine(tree):
    l = copy.deepcopy(LISTING)
    l["access"] = {"cost": "free", "restriction_raw": "N/A"}
    tree.write(listing=l)
    assert validate.run(strict_policy=True) == 0


@pytest.mark.parametrize("mutate,expect", [
    (lambda p, a, c: p["credits"].__setitem__(0, {"creator": "nobody"}), "unknown creator"),
    (lambda p, a, c: c["links"].update({"page": "http://insecure.example/"}) if "links" in c else c.update(links={"page": "http://insecure.example/"}), "links/page"),
    (lambda p, a, c: p.update(hosting={"state": "sold"}), "hosting/state"),
    (lambda p, a, c: a["versions"][0].update(sha256="short"), "sha256"),
    (lambda p, a, c: p.update(surprise=1), "surprise"),
])
def test_bad_data_is_an_error(tree, capsys, mutate, expect):
    p, a, c = copy.deepcopy(PACK), copy.deepcopy(ARCHIVE), copy.deepcopy(CREATOR)
    mutate(p, a, c)
    tree.write(creator=c, pack=p, archive=a)
    assert validate.run() == 1
    assert expect in capsys.readouterr().out


def test_published_pack_without_an_archive_is_awaiting_conversion_and_not_compiled(tree, capsys):
    tree.write(archive=None)
    assert validate.run() == 0
    assert "WARNING awaiting_conversion: 1" in capsys.readouterr().out
    assert validate.run(strict_policy=True) == 1
    assert C.catalog("cleaned")["entries"] == []
    assert C.links_v1()["packs"] == {}


def test_file_name_must_equal_the_key(tree, capsys):
    tree.write()
    (tree.root / "packs" / "slus-20000-dev1.yaml").rename(tree.root / "packs" / "other-name.yaml")
    assert validate.run() == 1
    assert "file name must equal key" in capsys.readouterr().out


def test_effective_cost_prefers_the_packs_own_override():
    assert validate.effective_cost({}, ["free", "paid"]) == "paid"
    assert validate.effective_cost({}, ["free"]) == "free" and validate.effective_cost({}, []) == "unknown"
    assert validate.effective_cost({"access": {"cost": "free"}}, ["paid"]) == "free"


# ---- against the real data -----------------------------------------------------------------------

def test_the_compiled_catalog_takes_archive_facts_from_the_archives_and_always_names_an_author():
    d = validate.load_all()
    archives = {a["key"]: a for a in d["archives"].values()}
    published = {(p.get("catalog_id") or p["key"]): p for p in d["packs"].values() if p["hosting"]["state"] == "published"}
    doc = C.catalog()
    assert doc["schemaVersion"] == 2 and len(doc["entries"]) == len(published)
    assert len({e["id"] for e in doc["entries"]}) == len(doc["entries"])
    for e in doc["entries"]:
        pack = published[e["id"]]
        a = archives[pack["key"]]
        v = next(x for x in a["versions"] if x["revision"] == a["current"])
        assert (e["sha256"], e["sizeBytes"], e["fileCount"], e["format"], e["archiveRevision"], e["decompressedSizeBytes"]) == (
            v["sha256"], v["size_bytes"], v["file_count"], v["container"], v["revision"], v["decompressed_size_bytes"])
        assert e["downloadUrl"] == f"https://dl.ps2ktxpak.net/{v['object']}"
        assert e["authors"] and all(x.strip() for x in e["authors"])   # older apps drop an entry with none
        assert e["sourceUrl"].startswith("https://")
        assert e["version"] == pack.get("version", "") and e["gameTitle"] == pack["game"]["title"]


def test_a_pack_with_no_credits_is_compiled_as_an_unknown_creator_and_previews_come_from_stored_copies(tree):
    p = copy.deepcopy(PACK)
    p.update(credits=[], version="1.2", media={"images": [{"source_url": "https://x.example/a.png"}, {"storage_key": "previews/a.webp"}]})
    tree.write(pack=p)
    (e,) = C.catalog()["entries"]
    assert e["authors"] == ["Unknown creator"] and e["credits"] == "Creator not identified."
    assert e["version"] == "1.2"
    assert e["previewUrls"] == ["https://dl.ps2ktxpak.net/previews/a.webp"]
