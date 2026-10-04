import pytest

from ps2ktxpak import sheet
from ps2ktxpak.common import (access_from_restriction, classify_link, link_kind, norm_regions, norm_status,
                              norm_type, numbers_in, parse_size_bytes, slugify, source_kind, title_key)
from xlsx_fixture import build

HEADER = ["#", "TITLE", "DOWNLOAD", "REGION", "AUTHOR", "SOCIALS"]


def test_reader_finds_columns_by_header_and_skips_the_banner(tmp_path):
    f = build(tmp_path / "s.xlsx", "PS2", HEADER,
              [["A", "Ape Escape 2", "Link", "NTSC-U", "Someone", None]],
              links={"C3": "https://gbatemp.net/threads/ape.1/", "E3": "https://gbatemp.net/members/someone.9/"})
    headers, rows = sheet.read_tab(f, "PS2")
    assert headers == ["#", "TITLE", "DOWNLOAD", "REGION", "AUTHOR", "SOCIALS"]
    assert len(rows) == 1 and rows[0].n == 3
    r = rows[0]
    assert r.text("TITLE") == "Ape Escape 2"
    assert r.link("DOWNLOAD") == "https://gbatemp.net/threads/ape.1/"
    assert r.link("AUTHOR") == "https://gbatemp.net/members/someone.9/"
    assert r.link("SOCIALS") is None and r.text("SOCIALS") == ""


def test_reader_expands_a_hyperlink_range(tmp_path):
    f = build(tmp_path / "s.xlsx", "PS2", HEADER, [["A", "One", "x", "PAL", "A", None], ["A", "Two", "x", "PAL", "A", None]],
              links={"C3:C4": "https://example.com/shared"})
    _, rows = sheet.read_tab(f, "PS2")
    assert [r.link("DOWNLOAD") for r in rows] == ["https://example.com/shared"] * 2


def test_reader_names_the_tabs_it_has_when_the_tab_is_missing(tmp_path):
    f = build(tmp_path / "s.xlsx", "PS2", HEADER, [])
    with pytest.raises(KeyError, match="PS2"):
        sheet.read_tab(f, "PSP")


@pytest.mark.parametrize("raw,cost,hint", [
    ("Paywall", "paid", None), ("Ads", "free_with_ads", None), ("N/A", "free", None),
    ("Mega", "free", "mega"), ("Telegram", "free", "telegram"), ("", "unknown", None), ("whatever", "unknown", None),
])
def test_restriction_becomes_cost(raw, cost, hint):
    a = access_from_restriction(raw)
    assert a["cost"] == cost and a.get("host_hint") == hint and a["restriction_raw"] == raw


def test_vocabulary_maps():
    assert norm_type("AI Upscale") == "ai_upscale" and norm_type("aI Upscale") == "ai_upscale"
    assert norm_type("nonsense") == "unknown"
    assert norm_status("Completed") == "complete" and norm_status("In-Progress") == "in_progress"
    assert norm_status("TBD") == "unknown" and norm_status("") == "unknown"
    assert norm_regions("NTSC/PAL") == ["NTSC-U", "PAL"] and norm_regions("N/A") == []


def test_sizes_and_titles():
    assert parse_size_bytes("1.5 GB") == int(1.5 * 1024 ** 3) and parse_size_bytes("945 MB") == 945 * 1024 ** 2
    assert parse_size_bytes("1,23gb") == int(1.23 * 1024 ** 3)
    assert parse_size_bytes("Mega") is None
    assert title_key("The Legend of Zelda: Ocarina") == title_key("legend of zelda ocarina")
    assert title_key("Ratchet & Clank") == title_key("Ratchet and Clank")
    assert numbers_in("Final Fantasy XII") != numbers_in("Final Fantasy X-2")  # different games
    assert slugify("Bl4ckH4nd") == "bl4ckh4nd" and slugify("Panda_Venom") == "panda-venom"


def test_link_classification():
    assert link_kind("https://ko-fi.com/x") == "kofi" and link_kind("https://www.youtube.com/@x") == "youtube"
    assert link_kind("https://example.org") == "website"
    assert source_kind("https://gbatemp.net/threads/a.1/") == "forum_thread"
    assert source_kind("https://ko-fi.com/s/abc") == "shop" and source_kind("https://archive.org/details/x") == "mirror"
    assert classify_link("https://mega.nz/file/abc#key") == ("mega", "file")
    assert classify_link("https://mega.nz/folder/abc#key") == ("mega", "folder")
    assert classify_link("https://drive.google.com/drive/folders/1abc") == ("gdrive", "folder")
    assert classify_link("https://drive.google.com/file/d/1abc/view") == ("gdrive", "file")
    assert classify_link("https://ko-fi.com/s/ff85340856") == ("kofi", "shop")
    assert classify_link("https://notahost.example/x")[0] == "other"
