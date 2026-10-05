"""The pack form's logic (site/src/lib/pack-form.mjs) run in Node against the real data and checked with the
Python side: what it writes must load, validate and pass the validator here, and an untouched pack must come
back byte for byte. A new pack starts hosted, which for a pack nothing has converted yet means published and
awaiting conversion."""
import copy
import json
import shutil
import subprocess

import jsonschema
import pytest
from test_validate_and_compile import ARCHIVE, CREATOR, LISTING, MATCH, PACK, tree  # noqa: F401  (the fixture)

from ps2ktxpak import validate
from ps2ktxpak.common import PACKS_DIR, ROOT, SCHEMA_DIR, load_yaml, write_yaml

RUNNER = ROOT / "tests" / "creator_form_runner.mjs"
pytestmark = pytest.mark.skipif(
    not shutil.which("node") or not (ROOT / "site" / "node_modules" / "ajv").exists(),
    reason="needs node and `npm install` in site/")

SCHEMA = json.loads((SCHEMA_DIR / "pack.schema.json").read_text(encoding="utf-8"))
SCHEMA_CHECK = jsonschema.Draft202012Validator(SCHEMA)
DATE = "2099-01-01"


def run(op, **kw):
    r = subprocess.run(["node", str(RUNNER)], input=json.dumps({"op": op, "date": DATE, **kw}),
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def load(text, tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text(text, encoding="utf-8")
    return load_yaml(p)


def draft(**kw):
    return {"key": "", "name": "A Pack", "title": "A Game", "serials": "SLUS-20964", "type": "unknown",
            "completeness": "unknown", "description": "", "cost": "free", "hosting": "hosted",
            "credits": [{"who": "Pankeko", "id": "", "role": "author", "note": ""}],
            "sources": [{"kind": "mirror", "url": "https://mega.nz/folder/abc", "primary": True, "note": ""}],
            "images": [], "videos": [], **kw}


def build(d, base=None, creators=None):
    case = {"draft": d, "base": base}
    if creators is not None:
        case["creators"] = creators
    return run("packBuild", cases=[case])[0]


def with_key(d):
    d = copy.deepcopy(d)
    d["key"] = run("newKey", cases=[{"serials": [d["serials"]], "lead": "pankeko", "existing": []}])[0]
    return d


def test_an_untouched_pack_comes_back_byte_for_byte():
    files = sorted(PACKS_DIR.glob("*.yaml"))
    texts = [f.read_text(encoding="utf-8") for f in files]
    out = run("packRoundtrip", texts=texts)
    assert [f.name for f, a, b in zip(files, texts, out) if a != b] == []


def test_a_new_pack_starts_hosted_with_the_creators_approval(tmp_path):
    d = with_key(draft(description="  Everything.  ", type="ai_upscale", completeness="complete",
                       images=[{"url": "imgur.com/a.png", "alt": "A", "caption": "", "who": "pankeko", "id": ""}],
                       videos=[{"url": "https://youtu.be/dQw4w9WgXcQ", "title": ""}]))
    r = build(d)
    assert r["problems"] == []
    rec = load(r["yaml"], tmp_path)
    assert not list(SCHEMA_CHECK.iter_errors(rec))
    assert rec["key"] == "slus-20964-pankeko" and "catalog_id" not in rec
    assert rec["hosting"] == {"state": "published", "since": DATE}
    assert rec["permission"]["kind"] == "creator_approved" and rec["permission"]["date"] == DATE
    assert rec["access"] == {"cost": "free"}
    assert rec["game"] == {"title": "A Game", "serials": ["SLUS-20964"]}
    assert rec["credits"] == [{"creator": "pankeko"}]
    assert rec["description"] == "Everything."
    assert rec["media"] == {"images": [{"source_url": "https://imgur.com/a.png", "alt": "A", "credit": "pankeko"}],
                            "videos": [{"provider": "youtube", "id": "dQw4w9WgXcQ"}]}
    assert list(rec) == ["key", "name", "game", "credits", "type", "completeness", "description", "sources", "media",
                         "access", "permission", "hosting"]


def test_listed_only_is_withheld_and_grants_nothing(tmp_path):
    rec = load(build(with_key(draft(hosting="listed", sources=[])))["yaml"], tmp_path)
    assert rec["hosting"]["state"] == "withheld" and rec["permission"] == {"kind": "unknown"}
    assert "sources" not in rec
    assert build(with_key(draft(hosting="listed", sources=[])))["problems"] == []


def test_a_new_pack_passes_the_validator_as_awaiting_conversion_even_when_paid(tree, tmp_path, capsys):  # noqa: F811
    r = build(with_key(draft(cost="paid")))
    assert r["problems"] == []
    pack = load(r["yaml"], tmp_path)
    tree.write(creator={"id": "pankeko", "name": "Pankeko"}, pack=pack, archive=None, listing=None, match=None)
    assert validate.run() == 0
    out = capsys.readouterr().out
    assert "WARNING awaiting_conversion: 1" in out
    assert "paid_but_hosted: 0" in out or "paid_but_hosted" not in out


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(name=" "), "A name is needed"),
    (lambda d: d.update(title=""), "A game title is needed"),
    (lambda d: d.update(serials=""), "At least one game serial"),
    (lambda d: d.update(serials="SLUS-20964, hello"), "“hello” is not a game serial"),
    (lambda d: d.update(description="x" * 2001), "limited to 2000"),
    (lambda d: d.update(credits=[]), "At least one creator"),
    (lambda d: d.update(credits=[{"who": "Nobody At All", "id": "", "role": "author", "note": ""}]), "No creator named “Nobody At All”"),
    (lambda d: d["credits"].append({"who": "PANKEKO", "id": "", "role": "author", "note": ""}), "credited twice"),
    (lambda d: d.update(sources=[]), "Hosting needs a link"),
    (lambda d: d.update(sources=[{"kind": "mirror", "url": "http://x.example/a", "primary": False, "note": ""}]), "https://"),
    (lambda d: d["sources"].append({"kind": "forum_thread", "url": "gbatemp.net/threads/x.1/", "primary": True, "note": ""}), "Only one source"),
    (lambda d: d.update(videos=[{"url": "https://vimeo.com/1", "title": ""}]), "not a YouTube link"),
    (lambda d: d.update(images=[{"url": "ftp://x.example/a.png", "alt": "", "caption": "", "who": "", "id": ""}]), "https://"),
    (lambda d: d.update(images=[{"url": "https://x.example/a.png", "alt": "", "caption": "", "who": "Nobody At All", "id": ""}]), "No creator named"),
])
def test_what_cannot_be_stored_is_refused(mutate, message):
    d = with_key(draft())
    mutate(d)
    messages = [p["message"] for p in build(d)["problems"]]
    assert any(message in m for m in messages), messages


def test_a_creator_is_found_by_name_alias_or_case_and_a_stored_id_is_kept(tmp_path):
    creators = [{"id": "ab", "name": "A.B.", "aliases": ["Alpha Beta"]}, {"id": "ab2", "name": "A B", "aliases": []}]
    d = with_key(draft(credits=[{"who": "alpha beta", "id": "", "role": "converter", "note": "textures only"}]))
    rec = load(build(d, creators=creators)["yaml"], tmp_path)
    assert rec["credits"] == [{"creator": "ab", "role": "converter", "note": "textures only"}]
    # "A B" and "A.B." read as the same name; a stored credit keeps the creator it already has.
    d = with_key(draft(credits=[{"who": "A B", "id": "ab2", "role": "author", "note": ""}]))
    assert load(build(d, creators=creators)["yaml"], tmp_path)["credits"] == [{"creator": "ab2"}]


def test_editing_keeps_what_the_form_does_not_show(tmp_path):
    text = (PACKS_DIR / "sces-50885-quicksliver1.yaml").read_text(encoding="utf-8")
    base = load_yaml(PACKS_DIR / "sces-50885-quicksliver1.yaml")
    d = run("packDraft", text=text)
    d["description"] = "A new description."
    d["videos"][0]["title"] = "Trailer"
    r = build(d, base=base)
    assert r["problems"] == []
    rec = load(r["yaml"], tmp_path)
    assert not list(SCHEMA_CHECK.iter_errors(rec))
    assert rec["description"] == "A new description."
    assert rec["media"]["videos"] == [{"provider": "youtube", "id": "1GXan3ZnYwg", "title": "Trailer"}]
    for untouched in ("catalog_id", "legacy", "hosting", "permission", "credits", "sources", "game", "name"):
        assert rec[untouched] == base[untouched], untouched
    assert "access" not in rec  # cost, permission and hosting are for a new pack only


def test_an_edit_keeps_a_pictures_thumbnail_and_review_flags(tmp_path):
    name = next(f.name for f in sorted(PACKS_DIR.glob("*.yaml")) if "needs_review" in f.read_text(encoding="utf-8") and "images:" in f.read_text(encoding="utf-8"))
    base = load_yaml(PACKS_DIR / name)
    d = run("packDraft", text=(PACKS_DIR / name).read_text(encoding="utf-8"))
    d["images"][0]["alt"] = "Changed"
    rec = load(build(d, base=base)["yaml"], tmp_path)
    assert rec["media"]["images"][0]["thumb_url"] == base["media"]["images"][0]["thumb_url"]
    assert rec["media"]["images"][0]["alt"] == "Changed"
    assert rec["needs_review"] == base["needs_review"]


def test_clearing_a_list_removes_it(tmp_path):
    base = load_yaml(PACKS_DIR / "sces-50885-quicksliver1.yaml")
    d = run("packDraft", text=(PACKS_DIR / "sces-50885-quicksliver1.yaml").read_text(encoding="utf-8"))
    d["videos"] = []
    rec = load(build(d, base=base)["yaml"], tmp_path)
    assert "media" not in rec


def test_an_edit_of_a_pack_without_credits_is_not_blocked():
    name = next(f.name for f in sorted(PACKS_DIR.glob("*.yaml")) if "credits: []" in f.read_text(encoding="utf-8"))
    base = load_yaml(PACKS_DIR / name)
    d = run("packDraft", text=(PACKS_DIR / name).read_text(encoding="utf-8"))
    d["description"] = "Edited."
    assert build(d, base=base)["problems"] == []


def test_file_names_are_derived_the_way_the_importer_derives_them():
    packs = [(f.stem, load_yaml(f)) for f in sorted(PACKS_DIR.glob("*.yaml"))]
    cases = [{"serials": p["game"]["serials"], "lead": (p["credits"][0]["creator"] if p["credits"] else "unknown"), "existing": []} for _, p in packs]
    got = run("newKey", cases=cases)
    off = [(k, g) for (k, _), g in zip(packs, got) if not (k == g or k.startswith(g + "-"))]
    assert off == []
    assert run("newKey", cases=[{"serials": ["SLUS-20964", "SCES-50001"], "lead": "pankeko", "existing": ["sces-50001-pankeko", "sces-50001-pankeko-2"]},
                                {"serials": ["SLUS-20964"], "lead": "x" * 70, "existing": []}]) == [
        "sces-50001-pankeko-3", ("slus-20964-" + "x" * 70)[:76]]


def test_packs_that_share_a_serial_are_pointed_out():
    packs = [{"key": "a", "name": "A", "serials": ["SLUS-1"]}, {"key": "b", "name": "B", "serials": ["SLES-2", "SLUS-1"]}, {"key": "c", "name": "C", "serials": ["SCUS-3"]}]
    assert run("similar", serials=["SLUS-1"], packs=packs) == [{"key": "a", "name": "A"}, {"key": "b", "name": "B"}]
    assert run("similar", serials=["SLUS-1"], packs=packs, exceptKey="a") == [{"key": "b", "name": "B"}]


def test_serials_are_read_in_the_forms_people_write_them():
    got = run("serials", texts=["SLUS-20964", "slus_209.64", "SLUS 20964, sces-50885;SLPM66000", "SLUS-20964 SLUS-20964", "", "hello SLUS-20964 world"])
    assert [g["serials"] for g in got] == [["SLUS-20964"], ["SLUS-20964"], ["SLUS-20964", "SCES-50885", "SLPM-66000"], ["SLUS-20964"], [], ["SLUS-20964"]]
    assert [g["bad"] for g in got] == [[], [], [], [], [], ["hello", "world"]]


def test_youtube_links_are_reduced_to_the_video_id():
    ok = ["dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ?t=5", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=x",
          "youtube.com/embed/dQw4w9WgXcQ", "https://m.youtube.com/shorts/dQw4w9WgXcQ", "https://youtube.com/live/dQw4w9WgXcQ"]
    assert run("youtube", inputs=ok) == ["dQw4w9WgXcQ"] * len(ok)
    assert run("youtube", inputs=["https://vimeo.com/dQw4w9WgXcQ", "https://www.youtube.com/@channel", "short", "", "https://youtu.be/"]) == [None] * 5


def test_source_kinds_are_guessed_from_the_address():
    urls = ["https://gbatemp.net/threads/x.1/", "https://gbatemp.net/members/x.1/", "https://www.youtube.com/watch?v=x", "https://github.com/a/b",
            "https://drive.google.com/drive/folders/x", "https://mega.nz/folder/x", "https://www.patreon.com/x", "https://example.org/"]
    assert run("sourceKind", urls=urls) == ["forum_thread", "creator_page", "video", "repository", "mirror", "mirror", "creator_page", "other"]


def test_the_vocabularies_are_the_schemas():
    labels = run("vocabularies")
    assert set(labels["type"]) == set(SCHEMA["properties"]["type"]["enum"])
    assert set(labels["completeness"]) == set(SCHEMA["properties"]["completeness"]["enum"])
    assert set(labels["cost"]) == set(SCHEMA["properties"]["access"]["properties"]["cost"]["enum"])
    assert set(labels["role"]) == set(SCHEMA["properties"]["credits"]["items"]["properties"]["role"]["enum"])
    assert set(labels["source"]) == set(SCHEMA["properties"]["sources"]["items"]["properties"]["kind"]["enum"])


def test_the_new_file_link_carries_the_path_and_the_text_intact():
    from urllib.parse import parse_qs, urlparse
    text = "key: x\nname: 'Spyro: A Hero''s Tail & co 100% #1'\n"
    u = urlparse(run("packFileUrl", key="slus-20964-pankeko", text=text))
    q = parse_qs(u.query, keep_blank_values=True)
    assert u.path == "/ps2ktxpak/catalog/new/main" and q["filename"] == ["data/packs/slus-20964-pankeko.yaml"] and q["value"] == [text]
