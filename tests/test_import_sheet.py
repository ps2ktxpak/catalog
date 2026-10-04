import json

from ps2ktxpak import import_sheet
from ps2ktxpak.creators import Creators
from xlsx_fixture import build

HEADER = ["#", "TITLE", "DOWNLOAD", "FREE MIRROR", "REGION", "SIZE", "RESTRICTION", "STATUS", "TYPE", "AUTHOR", "DONATE", "SOCIALS"]


def make(tmp_path, monkeypatch):
    rows = [
        ["A", "Ape Escape 2", "Link", "Need Mega Account", "NTSC-U", "1.5 GB", "Paywall", "Completed", "AI Upscale", "Bl4ckH4nd", "Link", "N/A"],
        ["A", "Ape Escape 3", "Link", "x", "PAL", "800 MB", "Mega", "In-Progress", "Handcrafted", "Bl4ckH4nd", "Link", "N/A"],
        ["B", "Burnout 3", "Link", "x", "NTSC/PAL", "Mega", "N/A", "Complete", "Mixed", "Dev1 | Dev2", "N/A", "N/A"],
        ["C", "Crash", "Link", "x", "N/A", "", "", "TBD", "Unknown", "N/A", "N/A", "N/A"],
    ]
    links = {"C3": "https://gbatemp.net/threads/ape-2.100/", "C4": "https://gbatemp.net/threads/ape-3.101/",
             "C5": "https://gbatemp.net/threads/burnout.102/", "C6": "https://gbatemp.net/threads/crash.103/",
             "J3": "https://gbatemp.net/members/bl4ckh4nd.609354/", "J4": "https://gbatemp.net/members/bl4ckh4nd.609354/",
             "K3": "https://ko-fi.com/bl4ckh4nd", "K4": "https://ko-fi.com/bl4ckh4nd",
             "J5": "https://gbatemp.net/members/dev1.1/"}
    xlsx = build(tmp_path / "s.xlsx", "PS2", HEADER, rows, links)
    monkeypatch.setattr(import_sheet, "LISTINGS_FILE", tmp_path / "listings.jsonl")
    creators = Creators(tmp_path / "creators")
    summary = import_sheet.run(xlsx, "2026-10-03", creators=creators)
    recs = [json.loads(l) for l in (tmp_path / "listings.jsonl").read_text().splitlines()]
    return summary, recs, creators


def test_listings_carry_normalised_fields(tmp_path, monkeypatch):
    summary, recs, creators = make(tmp_path, monkeypatch)
    assert summary["listings"] == 4 and summary["cost"] == {"paid": 1, "free": 2, "unknown": 1}
    by = {r["title"]: r for r in recs}
    ape2 = by["Ape Escape 2"]
    assert ape2["access"] == {"cost": "paid", "restriction_raw": "Paywall"}
    assert ape2["type"] == "ai_upscale" and ape2["completeness"] == "complete" and ape2["regions"] == ["NTSC-U"]
    assert ape2["source_page"] == "https://gbatemp.net/threads/ape-2.100/"
    assert ape2["size"]["bytes_estimate"] == int(1.5 * 1024 ** 3)
    assert by["Ape Escape 3"]["access"]["host_hint"] == "mega"
    assert by["Burnout 3"]["regions"] == ["NTSC-U", "PAL"]
    assert by["Crash"]["creators"] == [] and by["Crash"]["completeness"] == "unknown"


def test_the_free_mirror_column_is_never_imported(tmp_path, monkeypatch):
    _, recs, _ = make(tmp_path, monkeypatch)
    assert "Need Mega Account" not in json.dumps(recs)


def test_joint_authors_become_two_creators_without_guessing_their_links(tmp_path, monkeypatch):
    _, recs, creators = make(tmp_path, monkeypatch)
    burnout = next(r for r in recs if r["title"] == "Burnout 3")
    assert burnout["creators"] == ["dev1", "dev2"]
    assert "links" not in creators.recs["dev1"] or "page" not in creators.recs["dev1"].get("links", {})  # joint row: no attribution of links


def test_creator_gets_the_modal_links_with_provenance(tmp_path, monkeypatch):
    _, _, creators = make(tmp_path, monkeypatch)
    c = creators.recs["bl4ckh4nd"]
    assert c["links"]["page"] == "https://gbatemp.net/members/bl4ckh4nd.609354/"
    assert c["links"]["tip"] == [{"kind": "kofi", "url": "https://ko-fi.com/bl4ckh4nd"}]
    assert c["provenance"]["links.page"]["source"] == "sad-origami-sheet"


def test_reimport_is_stable_and_keeps_a_locked_field(tmp_path, monkeypatch):
    _, first, creators = make(tmp_path, monkeypatch)
    creators.set_field("bl4ckh4nd", "links.page", "https://example.com/mine", "hand", "2026-10-04", overwrite=True)
    creators.lock("bl4ckh4nd", "links.page")
    creators.save()
    ids_before = [r["id"] for r in first]
    summary = import_sheet.run(tmp_path / "s.xlsx", "2026-10-05", creators=Creators(tmp_path / "creators"))
    again = [json.loads(l) for l in (tmp_path / "listings.jsonl").read_text().splitlines()]
    assert [r["id"] for r in again] == ids_before                       # listing ids do not move
    assert Creators(tmp_path / "creators").recs["bl4ckh4nd"]["links"]["page"] == "https://example.com/mine"  # lock held


def test_a_changed_layout_is_refused_loudly(tmp_path, monkeypatch):
    import pytest
    xlsx = build(tmp_path / "bad.xlsx", "PS2", ["#", "TITLE", "LINK", "WRITER"], [["A", "x", "y", "z"]])
    monkeypatch.setattr(import_sheet, "LISTINGS_FILE", tmp_path / "l.jsonl")
    with pytest.raises(SystemExit, match="layout changed"):
        import_sheet.run(xlsx, "2026-10-03", creators=Creators(tmp_path / "c"))
