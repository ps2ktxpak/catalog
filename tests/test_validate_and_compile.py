import copy

import pytest

from ps2ktxpak import compile as C
from ps2ktxpak import validate
from ps2ktxpak.common import write_yaml

CREATOR = {"id": "dev1", "name": "Dev One"}
ARCHIVE = {"current": 1, "versions": [{
    "revision": 1, "container": "tar+zstd", "object": "packs/x.tar.zst", "sha256": "a" * 64,
    "size_bytes": 10, "decompressed_size_bytes": 20, "file_count": 3}]}
PACK = {"key": "slus-20000-dev1", "name": "A Pack", "game": {"title": "A Game", "serials": ["SLUS-20000"]},
        "credits": [{"creator": "dev1"}], "access": {"cost": "paid"}, "hosting": {"state": "published"}, "archive": ARCHIVE}
LISTED = {"key": "a-game-dev1", "name": "A Game", "game": {"title": "A Game", "regions": ["PAL"]},
          "credits": [{"creator": "dev1"}], "access": {"cost": "paid"}, "hosting": {"state": "listed"}}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for name, sub in (("CREATORS_DIR", "creators"), ("PACKS_DIR", "packs")):
        monkeypatch.setattr(validate, name, tmp_path / sub)

    class T:
        root = tmp_path

        def write(self, creator=CREATOR, pack=PACK, *more):
            write_yaml(tmp_path / "creators" / f"{creator['id']}.yaml", creator)
            for p in (pack, *more):
                if p:
                    write_yaml(tmp_path / "packs" / f"{p['key']}.yaml", p)
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
    tree.write({"id": "edit", "name": "Edit"}, {**PACK, "credits": [{"creator": "edit"}]})
    assert validate.run() == 1
    assert "reserved for a site page" in capsys.readouterr().out


def test_free_packs_are_fine(tree):
    tree.write(pack={**PACK, "access": {"cost": "free"}})
    assert validate.run(strict_policy=True) == 0


def test_a_pack_that_is_only_listed_is_not_held_to_the_hosting_policy(tree, capsys):
    """Paid, no permission, no serial and no archive: all fine for a pack nobody hosts."""
    tree.write(pack=LISTED)
    assert validate.run(strict_policy=True) == 0
    assert "WARNING" not in capsys.readouterr().out
    assert C.catalog()["entries"] == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda p, c: p["credits"].__setitem__(0, {"creator": "nobody"}), "unknown creator"),
    (lambda p, c: p.update(listed_credits=["nobody"]), "listed_credits names an unknown creator"),
    (lambda p, c: p.update(media={"images": [{"source_url": "https://x.example/a.png", "credit": "nobody"}]}), "unknown creator"),
    (lambda p, c: c.update(links={"page": "http://insecure.example/"}), "links/page"),
    (lambda p, c: p.update(hosting={"state": "sold"}), "hosting/state"),
    (lambda p, c: p["archive"]["versions"][0].update(sha256="short"), "sha256"),
    (lambda p, c: p["archive"].update(current=2), "current revision 2 is not among"),
    (lambda p, c: p["game"].update(serials=[]), "published but has no game serial"),
    (lambda p, c: p.update(permission={"kind": "revoked"}), "published although its creator's permission is revoked"),
    (lambda p, c: p.update(surprise=1), "surprise"),
    (lambda p, c: p.update(download={"status": "found"}), "download/status"),
    (lambda p, c: p["sources"].extend([{"kind": "other", "url": "https://a.example/", "primary": True}] * 2) if "sources" in p else p.update(
        sources=[{"kind": "other", "url": "https://a.example/", "primary": True}] * 2), "more than one primary source"),
])
def test_bad_data_is_an_error(tree, capsys, mutate, expect):
    p, c = copy.deepcopy(PACK), copy.deepcopy(CREATOR)
    mutate(p, c)
    tree.write(creator=c, pack=p)
    assert validate.run() == 1
    assert expect in capsys.readouterr().out


def test_published_pack_without_an_archive_is_awaiting_conversion_and_not_compiled(tree, capsys):
    p = {k: v for k, v in PACK.items() if k != "archive"}
    tree.write(pack=p)
    assert validate.run() == 0
    assert "WARNING awaiting_conversion: 1" in capsys.readouterr().out
    assert validate.run(strict_policy=True) == 1
    assert C.catalog()["entries"] == []


def test_file_name_must_equal_the_key(tree, capsys):
    tree.write()
    (tree.root / "packs" / "slus-20000-dev1.yaml").rename(tree.root / "packs" / "other-name.yaml")
    assert validate.run() == 1
    assert "file name must equal key" in capsys.readouterr().out


def test_two_packs_cannot_share_a_catalog_id(tree, capsys):
    tree.write(CREATOR, {**PACK, "catalog_id": "same-id"}, {**PACK, "key": "slus-20001-dev1", "catalog_id": "same-id"})
    assert validate.run() == 1
    assert "is used by 2 packs" in capsys.readouterr().out


def test_effective_cost_is_the_packs_own_access_or_unknown():
    assert validate.effective_cost({"access": {"cost": "free"}}) == "free"
    assert validate.effective_cost({}) == "unknown"


# ---- the rollup ------------------------------------------------------------------------------------

def test_the_rollup_takes_only_hosted_packs_with_an_archive_and_always_names_an_author(tree):
    p = copy.deepcopy(PACK)
    p.update(credits=[], version="1.2", media={"images": [{"source_url": "https://x.example/a.png"}, {"storage_key": "previews/a.webp"}]})
    tree.write(CREATOR, p, LISTED, {**PACK, "key": "slus-20002-dev1", "hosting": {"state": "withheld"}})
    (e,) = C.catalog()["entries"]
    assert e["id"] == "slus-20000-dev1" and e["authors"] == ["Unknown creator"] and e["credits"] == "Creator not identified."
    assert e["version"] == "1.2"
    assert e["previewUrls"] == ["https://dl.ps2ktxpak.net/previews/a.webp"]
    assert (e["sha256"], e["sizeBytes"], e["fileCount"], e["downloadUrl"]) == ("a" * 64, 10, 3, "https://dl.ps2ktxpak.net/packs/x.tar.zst")


def test_the_rollup_carries_each_credited_creator_with_their_links(tree):
    lead = {"id": "dev2", "name": "Dev Two", "avatar": {"source_url": "https://forum.example/a.jpg"},
            "links": {"page": "https://forum.example/dev2", "distribution": "https://dev2.example/packs",
                      "tip": [{"kind": "kofi", "url": "https://ko-fi.com/dev2"}, {"kind": "patreon", "url": "https://patreon.com/dev2"}],
                      "socials": [{"kind": "youtube", "url": "https://youtube.com/@dev2"}, {"kind": "x", "url": "https://x.com/dev2"}]}}
    write_yaml(tree.root / "creators" / "dev2.yaml", lead)
    p = {**PACK, "credits": [{"creator": "dev2"}, {"creator": "dev1"}], "type": "ai_upscale", "completeness": "in_progress",
         "sources": [{"url": "https://mirror.example/pack", "primary": True}]}
    tree.write(CREATOR, p)
    (e,) = C.catalog()["entries"]
    assert e["authors"] == ["Dev Two", "Dev One"]
    # Lead first; only what the creator has; the first tip and the first socials link.
    assert e["creators"] == [
        {"name": "Dev Two", "page": "https://forum.example/dev2", "avatar": "https://forum.example/a.jpg",
         "tip": "https://ko-fi.com/dev2", "socials": "https://youtube.com/@dev2"},
        {"name": "Dev One"}]
    assert (e["type"], e["completeness"]) == ("ai_upscale", "in_progress")
    # The lead creator's own page wins over the pack's primary source (a mirror, often).
    assert e["sourceUrl"] == "https://dev2.example/packs"


def test_the_source_link_is_the_primary_source_when_the_lead_creator_asked_for_none(tree):
    p = {**PACK, "sources": [{"url": "https://other.example/x"}, {"url": "https://forum.example/t/1", "primary": True}]}
    tree.write(CREATOR, p)
    (e,) = C.catalog()["entries"]
    assert e["sourceUrl"] == "https://forum.example/t/1"


def test_a_creator_with_a_stored_picture_is_shown_by_the_stored_copy(tree):
    tree.write({**CREATOR, "avatar": {"source_url": "https://forum.example/a.jpg", "storage_key": "avatars/dev1.webp"}})
    (e,) = C.catalog()["entries"]
    assert e["creators"] == [{"name": "Dev One", "avatar": "https://dl.ps2ktxpak.net/avatars/dev1.webp"}]


def test_a_pack_with_no_version_gets_one_the_app_accepts(tree):
    tree.write(CREATOR, PACK)
    (e,) = C.catalog()["entries"]
    assert "version" not in PACK and e["version"] == "revision 1"


def test_a_pack_nobody_signed_has_no_creators_and_an_unknown_type_is_left_out(tree):
    tree.write(CREATOR, {**PACK, "credits": [], "type": "unknown", "completeness": "unknown"})
    (e,) = C.catalog()["entries"]
    assert e["creators"] == [] and e["authors"] == ["Unknown creator"]
    assert "type" not in e and "completeness" not in e


# ---- against the real data -------------------------------------------------------------------------

def test_the_compiled_catalog_takes_archive_facts_from_the_packs_and_always_names_an_author():
    d = validate.load_all()
    published = {(p.get("catalog_id") or p["key"]): p for p in d["packs"].values() if p["hosting"]["state"] == "published"}
    doc = C.catalog()
    assert doc["schemaVersion"] == 2 and len(doc["entries"]) == len(published)
    assert len({e["id"] for e in doc["entries"]}) == len(doc["entries"])
    for e in doc["entries"]:
        pack = published[e["id"]]
        a = pack["archive"]
        v = next(x for x in a["versions"] if x["revision"] == a["current"])
        assert (e["sha256"], e["sizeBytes"], e["fileCount"], e["format"], e["archiveRevision"], e["decompressedSizeBytes"]) == (
            v["sha256"], v["size_bytes"], v["file_count"], v["container"], v["revision"], v["decompressed_size_bytes"])
        assert e["downloadUrl"] == f"https://dl.ps2ktxpak.net/{v['object']}"
        assert e["authors"] and all(x.strip() for x in e["authors"])   # older apps drop an entry with none
        assert e["sourceUrl"].startswith("https://")
        assert e["version"] == pack["version"] and e["gameTitle"] == pack["game"]["title"]


def test_the_compiled_catalog_names_every_creator_it_credits():
    d = validate.load_all()
    packs = {(p.get("catalog_id") or p["key"]): p for p in d["packs"].values()}
    for e in C.catalog()["entries"]:
        if e["creators"]:
            assert [c["name"] for c in e["creators"]] == e["authors"]
        else:
            assert e["authors"] == ["Unknown creator"] and not packs[e["id"]].get("credits")
        for c in e["creators"]:
            assert c["name"].strip() and all(v.startswith("https://") for k, v in c.items() if k != "name")
        assert e.get("type", "ai_upscale") in {"ai_upscale", "handcrafted", "mixed", "port", "button_replacement"}
        assert e.get("completeness", "complete") in {"complete", "in_progress", "incomplete", "partial"}


def test_every_pack_is_one_file_and_the_listed_ones_carry_no_hosting_facts():
    d = validate.load_all()
    for fn, p in d["packs"].items():
        assert fn == p["key"] + ".yaml"
        if p["hosting"]["state"] == "listed":  # the only permission one may carry is the creator's no
            assert "archive" not in p and p.get("permission", {"kind": "revoked"})["kind"] == "revoked"
