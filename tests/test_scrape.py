"""The scraper's decisions that need no network: reading the sheet, matching rows to packs, picking a
game's file out of a library folder, laying out a download, and writing results into pack files."""
import io
import json
import struct

import pytest

from ps2ktxpak import validate
from ps2ktxpak.common import load_yaml, write_yaml
from ps2ktxpak.scrape import apply as A
from ps2ktxpak.scrape import convert, hosts, job, match, sheet

openpyxl = pytest.importorskip("openpyxl")

CREATOR = {"id": "dev1", "name": "Dev One", "aliases": ["dev_one"]}
THREAD = "https://gbatemp.net/threads/a-library.123/"


def pack(key, title, **kw):
    p = {"key": key, "name": title, "game": {"title": title}, "credits": [{"creator": "dev1"}],
         "sources": [{"kind": "forum_thread", "url": THREAD, "primary": True}],
         "access": {"cost": "free"}, "hosting": {"state": "listed"},
         "download": {"status": "resolved", "url": "https://mega.nz/file/abc#def", "host": "mega", "kind": "file"}}
    p.update(kw)
    return p


def workbook(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PS2"
    ws.append(["#", "Game Title", "Mirror Download", "Download", "Region", "Size", "Restriction", "Pack Author"])
    for r in rows:
        ws.append(r)
    for n in range(2, ws.max_row + 1):
        ws.cell(n, 4).hyperlink = THREAD
        ws.cell(n, 3).hyperlink = "https://mirror.example/should-never-be-read"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_columns_are_found_by_header_and_the_mirror_column_is_never_read():
    rows = sheet.parse(workbook([["A", "A Game", "Link", "Link", "PAL", "5,03 GB", "Paywall", "Dev_One"]]))
    (r,) = rows
    assert (r.title, r.download, r.region, r.author) == ("A Game", THREAD, "PAL", "Dev_One")
    assert r.paid and r.size_bytes() == 5_030_000_000
    assert "mirror" not in json.dumps(vars(r))


def test_a_sheet_without_a_needed_column_is_refused():
    wb = openpyxl.Workbook()
    wb.active.title = "PS2"
    wb.active.append(["Game Title", "Download"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="author"):
        sheet.parse(buf.getvalue())


def test_a_library_thread_row_matches_its_own_game_only():
    ix = match.Index([pack("game-a-dev1", "Game A"), pack("game-b-dev1", "Game B")], [CREATOR])
    row = sheet.Row(row=2, title="Game B", download="https://gbatemp.net/threads/whatever.123", author="dev_one")
    assert ix.match(row) == "game-b-dev1"
    assert ix.known(sheet.Row(row=3, title="Game C", download=THREAD, author="Dev One")) is False


def test_a_title_spelled_another_way_still_matches_on_its_own_page():
    ix = match.Index([pack("smt-dev1", "Shin Megami Tensei: Digital Devil Saga")], [CREATOR])
    assert ix.match(sheet.Row(row=2, title="Digital Devil Saga", download=THREAD, author="Dev One")) == "smt-dev1"


def entries(*names):
    return [hosts.Entry(n, 1, lambda d, l: d) for n in names]


def test_a_library_folder_gives_the_file_named_for_the_game():
    folder = entries("Ratatouille PCSX2 HD Pack.7z", "Ratchet & Clank PCSX2 HD Pack.rar", "Burnout PS2.rar", "Other.7z")
    assert [e.name for e in hosts.pick(folder, hosts.Want("Ratchet & Clank"))] == ["Ratchet & Clank PCSX2 HD Pack.rar"]


def test_a_differently_spelled_file_is_taken_only_when_it_clearly_wins():
    folder = entries("Chou Aniki - Seinaru Protein Densetsu (Japan) PCSX2 HD Pack.7z", "Spongebob Atlantis.rar",
                     "SpongeBob SquarePants Battle For Bikini Bottom.7z", "Burnout PS2.rar")
    assert hosts.pick(folder, hosts.Want("Cho Aniki: Seinaru Protein Densetsu"))[0].name.startswith("Chou Aniki")
    with pytest.raises(hosts.Unsupported):
        hosts.pick(folder, hosts.Want("Kingdom Hearts"))


def test_a_folder_holding_one_pack_in_parts_is_taken_whole():
    folder = entries("pack.part1.rar", "pack.part2.rar", "readme.txt")
    assert len(hosts.pick(folder, hosts.Want("Some Game"))) == 3


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def test_several_regions_in_serial_folders_are_one_pack(tmp_path):
    touch(tmp_path / "SLUS-21349" / "replacements" / "a.dds")
    touch(tmp_path / "SLES_533.93" / "replacements" / "b.png")
    layout = convert.find_layout(tmp_path)
    assert sorted(layout.serials) == ["SLES-53393", "SLUS-21349"]


def test_two_replacements_folders_without_serials_are_a_choice(tmp_path):
    touch(tmp_path / "2K" / "replacements" / "a.dds")
    touch(tmp_path / "4K" / "replacements" / "a.dds")
    with pytest.raises(convert.NeedsChoice, match="2K"):
        convert.find_layout(tmp_path)


def test_a_mac_resource_fork_folder_and_a_nested_replacements_folder_are_no_choice(tmp_path):
    touch(tmp_path / "SLUS-20616" / "replacements" / "a.dds")
    touch(tmp_path / "__MACOSX" / "SLUS-20616" / "replacements" / "._a.dds")
    touch(tmp_path / "SLUS-20616" / "replacements" / "replacements" / "b.dds")
    assert convert.find_layout(tmp_path).roots == [tmp_path / "SLUS-20616" / "replacements"]


def test_only_files_the_emulator_loads_are_converted(tmp_path):
    keep = ["21e0f980f6dbe2f-60984954bd47201a-00005993.png", "b327f87ac0294386-00002a80.dds",
            "3d95916159fb6dec-5d46340bd88b677e-r25x17-00001e13.png", "91452daee38b05b4-r124010c01780000-00006a53.png"]
    drop = ["hud-arrow-right-01.png", "31fd400e1949dfa3-27d8587c61eaa0d8-r0x384-00002654 - Copy.png", "preview.png"]
    for name in keep + drop + ["b327f87ac0294386-00002a80-mip1.dds", "readme.txt"]:
        touch(tmp_path / "replacements" / name)
    layout = convert.find_layout(tmp_path)
    assert sorted(b.name for b, _ in convert._families(layout.roots[0])) == sorted(keep)
    assert convert.unloadable(layout) == sorted(drop)


def png(path, w, h):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big"))


def test_pruning_a_converted_pack_takes_out_what_conversion_now_leaves_out(tmp_path):
    keep = tmp_path / "replacements" / "b327f87ac0294386-00002a80.ktx"
    for p in [keep, tmp_path / "replacements" / "hud" / "hud-arrow-right-01.ktx",
              tmp_path / "replacements" / "b327f87ac0294386-00002a80 - Copy.ktx"]:
        touch(p)
    assert convert.prune(tmp_path) == ["replacements/b327f87ac0294386-00002a80 - Copy.ktx",
                                       "replacements/hud/hud-arrow-right-01.ktx"]
    assert [p for p in tmp_path.rglob("*")] == [tmp_path / "replacements", keep]


def test_a_few_unreadable_textures_are_left_out_but_many_fail_the_pack(tmp_path, monkeypatch):
    kram = tmp_path / "kram"  # stands in for kram: refuses files whose name holds "bad"
    kram.write_text('#!/bin/sh\ncase "$3" in *bad*) exit 1;; esac\nfor a; do o="$a"; done\n: > "$o"\n')
    kram.chmod(0o755)
    monkeypatch.setattr(convert, "KRAM", str(kram))
    names = [f"{i:x}-00001993" for i in range(20)] + ["bad1-00001993", "bad2-00001993"]
    for n in names:
        png(tmp_path / "in" / "replacements" / f"{n}.png", 64, 64)
    layout = convert.find_layout(tmp_path / "in")
    count, unreadable = convert.convert(layout, tmp_path / "out")
    assert count == 20 and [u.split()[0] for u in unreadable] == ["bad1-00001993.png", "bad2-00001993.png"]
    assert not (tmp_path / "out" / "replacements" / "bad1-00001993.ktx").exists()
    for n in ["bad3-00001993", "bad4-00001993"]:
        png(tmp_path / "in" / "replacements" / f"{n}.png", 64, 64)
    with pytest.raises(RuntimeError, match="4 of 24"):
        convert.convert(layout, tmp_path / "out2")


def test_files_broken_in_the_download_are_left_out_without_failing_the_pack(tmp_path, monkeypatch):
    kram = tmp_path / "kram"  # stands in for kram: refuses empty files and short DDS files
    kram.write_text('#!/bin/sh\n[ -s "$3" ] && [ "${3##*.}" = png ] || exit 1\n'
                    'for a; do o="$a"; done\n: > "$o"\n')
    kram.chmod(0o755)
    monkeypatch.setattr(convert, "KRAM", str(kram))
    root = tmp_path / "in" / "replacements"
    for i in range(10):
        png(root / f"{i:x}-00001993.png", 64, 64)
        (root / f"e{i:x}-00001993.png").write_bytes(b"")  # empty, as Rule of Rose ships 259 of its textures
    short = root / "f0-00001993.dds"  # 64x64 DXT5 needs 128 + 16 * 16 bytes
    short.write_bytes(b"DDS " + struct.pack("<7I", 124, 0, 64, 64, 0, 0, 1) + bytes(52) + b"DXT5"
                      + bytes(40))
    layout = convert.find_layout(tmp_path / "in")
    count, unreadable = convert.convert(layout, tmp_path / "out")
    assert count == 10 and len(unreadable) == 11
    assert all(u.endswith("broken in the download") for u in unreadable)


def test_mip_files_of_the_wrong_size_are_replaced_by_generated_mips(tmp_path):
    base = tmp_path / "a-00001993.png"
    png(base, 512, 256)
    good = {1: tmp_path / "a-00001993-mip1.png", 2: tmp_path / "a-00001993-mip2.png"}
    png(good[1], 256, 128)
    png(good[2], 128, 64)
    assert "-mip" in convert._encode_argv(base, good, tmp_path / "a.ktx")
    png(good[2], 512, 256)  # a full-size copy, as one pack ships
    assert "-mip" not in convert._encode_argv(base, good, tmp_path / "a.ktx")


def test_a_1x1_texture_gets_one_level(tmp_path):
    base = tmp_path / "a-00001993.png"
    png(base, 1, 1)
    mip = tmp_path / "a-00001993-mip1.png"
    png(mip, 1, 1)
    argv = convert._encode_argv(base, {1: mip}, tmp_path / "a.ktx")
    assert argv[argv.index("-mipcount") + 1] == "1" and "-mip" not in argv


def test_a_pack_that_failed_too_often_is_retried_only_when_named():
    r = {"status": "failed", "attempts": job.MAX_ATTEMPTS}
    assert not job.Job._again(r) and job.Job._again(r, retry=True)
    assert not job.Job._again({"status": "gone"}, retry=True)


def test_a_resumed_job_reads_pack_results_but_not_the_shard_indexes():
    assert job.is_result("results/jak-2-renegade-marcelus.json")
    assert not job.is_result("results/index-0.json")


def test_only_the_first_volume_of_a_split_archive_is_opened():
    assert convert.is_archive(convert.Path("p.part1.rar")) and not convert.is_archive(convert.Path("p.part2.rar"))
    assert convert.is_archive(convert.Path("p.7z.001")) and not convert.is_archive(convert.Path("p.7z.002"))


def test_paid_packs_and_shop_links_are_never_fetched():
    packs = [pack("free-dev1", "Free"), pack("paid-dev1", "Paid", access={"cost": "paid"}),
             pack("shop-dev1", "Shop", download={"status": "resolved", "url": "https://ko-fi.com/s/x", "host": "kofi"}),
             pack("row-paid-dev1", "Row Paid"), pack("revoked-dev1", "Revoked", permission={"kind": "revoked"})]
    rows = [sheet.Row(row=2, title="Row Paid", download=THREAD, author="Dev One", restriction="Paywall")]
    items, skipped = job.plan(packs, [CREATOR], rows)
    assert [i.key for i in items] == ["free-dev1"]
    assert {k: r["status"] for k, r in skipped.items()} == {"paid-dev1": "paid", "row-paid-dev1": "paid", "shop-dev1": "unsupported",
                                                          "revoked-dev1": "revoked"}


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PACKS_DIR", tmp_path)
    return tmp_path


DONE = {"status": "done", "updated": "2026-10-25", "serials_found": ["SLUS-21349"],
        "archive": {"container": "tar+zstd", "object": "packs/game-a-dev1.tar.zst", "sha256": "b" * 64,
                    "size_bytes": 10, "decompressed_size_bytes": 20, "file_count": 8, "created": "2026-10-25",
                    "converter": {"tool": "kram", "version": "97c56df", "pipeline": "ps2ktxpak scrape", "params": "p"},
                    "source": {"sha256": "c" * 64, "size_bytes": 30, "url": "https://mega.nz/file/abc#def", "retrieved": "2026-10-25"}}}


def test_a_converted_pack_becomes_withheld_with_its_archive(packs_dir):
    write_yaml(packs_dir / "game-a-dev1.yaml", pack("game-a-dev1", "Game A"))
    A.apply({"game-a-dev1": DONE})
    p = load_yaml(packs_dir / "game-a-dev1.yaml")
    assert p["hosting"]["state"] == "withheld"
    assert p["archive"]["versions"][0]["object"] == "packs/game-a-dev1.tar.zst"
    assert p["game"]["serials"] == ["SLUS-21349"]
    assert list(p)[-1] == "archive"


def test_a_pack_someone_changed_is_left_alone(packs_dir):
    write_yaml(packs_dir / "game-a-dev1.yaml", pack("game-a-dev1", "Game A", hosting={"state": "published"}))
    before = (packs_dir / "game-a-dev1.yaml").read_text()
    report = A.apply({"game-a-dev1": DONE})
    assert (packs_dir / "game-a-dev1.yaml").read_text() == before
    assert "game-a-dev1" in next(iter(report.values()))


def test_a_pack_whose_creator_revoked_permission_is_never_withheld(packs_dir):
    write_yaml(packs_dir / "game-a-dev1.yaml", pack("game-a-dev1", "Game A", permission={"kind": "revoked"}))
    report = A.apply({"game-a-dev1": DONE})
    assert "archive" not in load_yaml(packs_dir / "game-a-dev1.yaml") and "game-a-dev1" in str(report)


def test_a_gone_link_is_marked_dead(packs_dir):
    write_yaml(packs_dir / "game-a-dev1.yaml", pack("game-a-dev1", "Game A"))
    A.apply({"game-a-dev1": {"status": "gone", "updated": "2026-10-25", "download_url": "https://mega.nz/file/abc#def"}})
    assert load_yaml(packs_dir / "game-a-dev1.yaml")["download"]["status"] == "dead"


def test_the_applied_pack_passes_the_schema(packs_dir, monkeypatch):
    monkeypatch.setattr(validate, "PACKS_DIR", packs_dir)
    monkeypatch.setattr(validate, "CREATORS_DIR", packs_dir / "creators")
    write_yaml(packs_dir / "creators" / "dev1.yaml", CREATOR)
    write_yaml(packs_dir / "game-a-dev1.yaml", pack("game-a-dev1", "Game A"))
    A.apply({"game-a-dev1": DONE})
    assert validate.run(quiet=True) == 0


def test_mediafire_signed_in_takes_the_direct_link_and_a_removed_file_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(hosts, "MEDIAFIRE_EMAIL", "a@b")
    monkeypatch.setattr(hosts, "MEDIAFIRE_PASSWORD", "pw")
    calls = []

    def api(call, **params):
        calls.append((call, params.get("quick_key")))
        if call.startswith("user/"):
            return {"result": "Success", "session_token": "t"}
        if params["quick_key"] == "gone0":
            return {"result": "Success", "links": [{"quickkey": "gone0", "error": "Invalid QuickKey"}]}
        return {"result": "Success", "links": [{"direct_download": "https://download1.mediafire.com/x/f.7z"}]}
    monkeypatch.setattr(hosts, "_mediafire_api", api)
    monkeypatch.setattr(hosts, "curl", lambda url, dest, limit: (url, dest))
    [e] = hosts.mediafire("https://www.mediafire.com/file_premium/abc123/Pack.7z/file")
    assert e.get(tmp_path / "f", None) == ("https://download1.mediafire.com/x/f.7z", tmp_path / "f")
    assert calls[-1] == ("file/get_links.php", "abc123")
    with pytest.raises(hosts.Gone):
        hosts._mediafire_file("https://www.mediafire.com/file/gone0/x.rar/file", tmp_path / "g", None)


def test_an_empty_mega_folder_is_gone(tmp_path, monkeypatch):
    tool = tmp_path / "megatools"  # stands in for megatools: succeeds and downloads nothing
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    monkeypatch.setattr(hosts, "MEGATOOLS", str(tool))
    [e] = hosts.mega("https://mega.nz/folder/KLJy1Zia#DPIlpfIxvfItptcamfKr6Q")
    with pytest.raises(hosts.Gone):
        e.get(tmp_path / "dl", None)


def test_an_encrypted_archive_is_extracted_with_the_pack_password_and_named_without_it(tmp_path, monkeypatch):
    seven = tmp_path / "7zz"  # stands in for 7-Zip: the archive's password is "pw"
    seven.write_text('#!/bin/sh\nfor a; do case "$a" in -ppw) exit 0;; -p*) '
                     'echo "ERROR: Wrong password : x.png" >&2; exit 2;; esac; done\nexit 2\n')
    seven.chmod(0o755)
    monkeypatch.setattr(convert, "SEVEN_ZIP", str(seven))
    archive = tmp_path / "pack.rar"
    archive.write_bytes(b"Rar!")
    convert.extract(archive, tmp_path / "a", "pw")
    with pytest.raises(RuntimeError, match="gives no password"):
        convert.extract(archive, tmp_path / "b")


def test_a_download_without_an_extension_is_known_by_its_first_bytes(tmp_path):
    rar, png_file = tmp_path / "vvmyv7pg3cc8aqj", tmp_path / "readme"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00")
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert convert.is_archive(rar) and not convert.is_archive(png_file)
