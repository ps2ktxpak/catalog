import copy

import pytest

from ps2ktxpak import media, resolve, validate
from ps2ktxpak.common import load_yaml, write_yaml

THREAD = "https://gbatemp.net/threads/some-pack.100/"
PAGE = '''
<article class="message    message-threadStarterPost message--post   js-post   " data-author="maker">
<div class="bbWrapper">My pack.<br />
<a href="https://gbatemp.net/attachments/shot1-png.1/"><img src="https://gbatemp.net/data/attachments/0/1-aa.jpg?hash=x" class="bbImage " alt="shot1.png" width="267" height="150" /></a>
<a href="https://gbatemp.net/attachments/shot2-png.2/"><img src="https://gbatemp.net/data/attachments/0/2-bb.jpg?hash=y" class="bbImage " alt="Battle HUD" width="267" height="150" /></a>
<span data-s9e-mediaembed="youtube"><span><span style="background:url(https://i.ytimg.com/vi/aPoUWnktTc4/hqdefault.jpg)"></span></span></span>
</div><div class="js-selectToQuoteEnd">&nbsp;</div></article>
<article class="message   message--post   js-post   " data-author="stranger">
<div class="bbWrapper"><img src="https://gbatemp.net/data/attachments/0/9-zz.jpg" class="bbImage " alt="not the maker's" /></div><div class="js-selectToQuoteEnd">&nbsp;</div></article>
'''


def pack(key, thread=THREAD, **extra):
    p = {"key": key, "name": "P", "game": {"title": "G", "serials": ["SLUS-20000"]}, "credits": [{"creator": "maker"}],
         "sources": [{"kind": "forum_thread", "url": thread, "primary": True}], "hosting": {"state": "published"}}
    p.update(extra)
    return p


@pytest.fixture
def packs(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "PACKS_DIR", tmp_path)
    monkeypatch.setattr(resolve, "fetch_page", lambda url, delay, refresh: (200, PAGE))
    return tmp_path


def test_a_single_pack_thread_seeds_credited_pictures_and_a_video(packs):
    write_yaml(packs / "slus-20000-maker.yaml", pack("slus-20000-maker"))
    stats = media.run("2026-10-03")
    m = load_yaml(packs / "slus-20000-maker.yaml")["media"]
    assert stats["seeded"] == 1 and stats["images"] == 2 and stats["videos"] == 1
    assert [i["source_url"] for i in m["images"]] == ["https://gbatemp.net/attachments/shot1-png.1/",
                                                      "https://gbatemp.net/attachments/shot2-png.2/"]
    assert all(i["credit"] == "maker" for i in m["images"])           # credited to the lead creator
    assert "alt" not in m["images"][0] and m["images"][1]["alt"] == "Battle HUD"   # a file name is not alt text
    assert m["videos"] == [{"provider": "youtube", "id": "aPoUWnktTc4"}]
    assert "not the maker's" not in str(m)                              # a stranger's reply is not the creator's picture


def test_a_library_thread_shared_by_several_packs_is_skipped(packs):
    write_yaml(packs / "a.yaml", pack("slus-20000-maker"))
    write_yaml(packs / "b.yaml", pack("slus-20001-maker"))
    assert media.run("2026-10-03") == {"shared_thread": 2}


def test_existing_or_locked_media_is_never_touched(packs):
    write_yaml(packs / "slus-20000-maker.yaml", pack("slus-20000-maker", media={"videos": [{"provider": "youtube", "id": "AAAAAAAAAAA"}]}))
    write_yaml(packs / "slus-20001-maker.yaml", pack("slus-20001-maker", thread="https://gbatemp.net/threads/other.5/", locked=["media"]))
    assert media.run("2026-10-03") == {}
    assert load_yaml(packs / "slus-20000-maker.yaml")["media"]["videos"][0]["id"] == "AAAAAAAAAAA"


PACK_OK = {"key": "slus-20000-maker", "name": "P", "game": {"title": "G", "serials": ["SLUS-20000"]},
           "credits": [{"creator": "maker"}], "hosting": {"state": "draft"}}


def _errors(media_block):
    p = copy.deepcopy(PACK_OK)
    p["media"] = media_block
    return list(validate._validator("pack").iter_errors(p))


def test_media_schema_accepts_good_and_rejects_bad_entries():
    assert not _errors({"images": [{"source_url": "https://gbatemp.net/attachments/a-png.1/", "credit": "maker"}],
                        "videos": [{"provider": "youtube", "id": "aPoUWnktTc4"}]})
    assert not _errors({"images": [{"storage_key": "media/slus-20000-maker/1.webp", "caption": "HUD"}]})
    assert _errors({"images": [{"alt": "no address at all"}]})                              # needs source_url or storage_key
    assert _errors({"images": [{"source_url": "http://insecure.example/a.png"}]})            # https only
    assert _errors({"videos": [{"provider": "youtube", "id": "short"}]})                      # a real 11-character id
    assert _errors({"videos": [{"provider": "vimeo", "id": "aPoUWnktTc4"}]})


def test_a_mirrored_picture_reaches_the_catalogs_preview_urls_but_not_the_faithful_rebuild(monkeypatch):
    from ps2ktxpak import compile as C
    p = pack("slus-20000-maker", catalog_id="legacy-id", legacy={"authors": ["x"], "preview_urls": ["https://old.example/p.png"]},
             media={"images": [{"source_url": "https://gbatemp.net/attachments/a-png.1/", "storage_key": "media/a/1.webp"},
                               {"source_url": "https://gbatemp.net/attachments/b-png.2/"}]})
    arch = {"key": "slus-20000-maker", "current": 1, "versions": [{
        "revision": 1, "container": "tar+zstd", "object": "packs/legacy-id.tar.zst", "sha256": "a" * 64,
        "size_bytes": 1, "decompressed_size_bytes": 2, "file_count": 3}]}
    data = {"packs": {"p.yaml": p}, "archives": {"a.json": arch}, "creators": {"m.yaml": {"id": "maker", "name": "Maker"}}}
    monkeypatch.setattr(C, "load_all", lambda: data)
    [cleaned] = C.catalog("cleaned", "https://dl.example")["entries"]
    [faithful] = C.catalog("faithful", "https://dl.example")["entries"]
    assert cleaned["previewUrls"] == ["https://old.example/p.png", "https://dl.example/media/a/1.webp"]   # only the picture we host
    assert faithful["previewUrls"] == ["https://old.example/p.png"]
