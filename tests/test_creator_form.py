"""The creator form's logic (site/src/lib/creator-form.mjs) run in Node against the real data and checked
with the Python side: what it writes must load and validate here, and an untouched record must come back
byte for byte, or a pull request from the form would carry noise."""
import json
import shutil
import subprocess
from urllib.parse import parse_qs, urlparse

import jsonschema
import pytest

from ps2ktxpak.common import CREATORS_DIR, ROOT, SCHEMA_DIR, load_yaml

RUNNER = ROOT / "tests" / "creator_form_runner.mjs"
pytestmark = pytest.mark.skipif(
    not shutil.which("node") or not (ROOT / "site" / "node_modules" / "ajv").exists(),
    reason="needs node and `npm install` in site/")

SCHEMA = json.loads((SCHEMA_DIR / "creator.schema.json").read_text(encoding="utf-8"))
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
    return {"id": "", "name": "", "aliases": [], "page": "", "distribution": "", "tip": [], "socials": [], **kw}


def build(d, base=None, creators=()):
    return run("build", cases=[{"draft": d, "base": base, "creators": list(creators)}])[0]


def test_an_untouched_creator_comes_back_byte_for_byte():
    files = sorted(CREATORS_DIR.glob("*.yaml"))
    texts = [f.read_text(encoding="utf-8") for f in files]
    out = run("roundtrip", texts=texts)
    assert [f.name for f, a, b in zip(files, texts, out) if a != b] == []


def test_a_new_creator_loads_and_validates_here(tmp_path):
    d = draft(id="zoe-under-pixel", name="Zoë Ünder_Pixel", aliases=["ZUP", " ZUP ", "Zoe"],
              page="gbatemp.net/members/zoe.1/", tip=[{"kind": "kofi", "url": "https://ko-fi.com/zoe"}],
              socials=[{"kind": "youtube", "url": "https://www.youtube.com/@zoe"}, {"kind": "website", "url": ""}])
    r = build(d)
    assert r["problems"] == []
    rec = load(r["yaml"], tmp_path)
    assert not list(SCHEMA_CHECK.iter_errors(rec))
    assert rec["id"] == "zoe-under-pixel" and rec["status"] == "active"
    assert rec["aliases"] == ["ZUP", "Zoe"]
    assert rec["links"] == {"page": "https://gbatemp.net/members/zoe.1/",
                            "tip": [{"kind": "kofi", "url": "https://ko-fi.com/zoe"}],
                            "socials": [{"kind": "youtube", "url": "https://www.youtube.com/@zoe"}]}
    assert list(rec) == ["id", "name", "aliases", "links", "status"]


@pytest.mark.parametrize("name", ["Yes", "no", "On", "off", "null", "~", "1:30", "0x1F", "1e3", "2026-10-03", "y", "123",
                                  "a: b", "- x", "# hi", "it's", 'say "hi"', "trailing:", "日本語"])
def test_names_a_yaml_1_1_reader_would_misread_come_back_as_the_same_text(name, tmp_path):
    r = build(draft(id="x1", name=name, aliases=[name + " II"]))
    rec = load(r["yaml"], tmp_path)
    assert rec["name"] == name and rec["aliases"] == [name + " II"]


def test_editing_changes_only_what_was_touched(tmp_path):
    base = load_yaml(CREATORS_DIR / "ewgeha.yaml")
    d = draft(id="ewgeha", name="Ewgeha", page=base["links"]["page"], socials=base["links"]["socials"],
              tip=[{"kind": "kofi", "url": "ko-fi.com/ewgeha"}])
    r = build(d, base=base)
    assert r["problems"] == []
    rec = load(r["yaml"], tmp_path)
    assert not list(SCHEMA_CHECK.iter_errors(rec))
    assert rec["name"] == "Ewgeha" and rec["links"]["tip"] == [{"kind": "kofi", "url": "https://ko-fi.com/ewgeha"}]
    assert rec["links"]["page"] == base["links"]["page"] and rec["links"]["socials"] == base["links"]["socials"]
    assert rec["avatar"] == base["avatar"]
    assert set(rec) == set(base)  # nothing is added: no bookkeeping about who changed what


def test_clearing_a_field_removes_it(tmp_path):
    base = load_yaml(CREATORS_DIR / "ewgeha.yaml")
    r = build(draft(id="ewgeha", name=base["name"], page=base["links"]["page"], socials=[]), base=base)
    rec = load(r["yaml"], tmp_path)
    assert "socials" not in rec["links"]


def test_no_change_is_no_change():
    base = load_yaml(CREATORS_DIR / "ewgeha.yaml")
    text = (CREATORS_DIR / "ewgeha.yaml").read_text(encoding="utf-8")
    d = draft(id="ewgeha", name=base["name"], page=base["links"]["page"], socials=base["links"]["socials"])
    assert build(d, base=base)["yaml"] == text


@pytest.mark.parametrize("field, value, message", [
    ("page", "http://gbatemp.net/members/x.1/", "https://"),
    ("page", "https://user:pw@gbatemp.net/", "username"),
    ("page", "someone@example.com", "email"),
    ("page", "ftp://example.com/x", "https://"),
    ("page", "javascript:alert(1)", "https://"),
    ("page", "not a url", "spaces"),
    ("page", "localhost", "valid"),
    ("distribution", "https://" + "a" * 2050 + ".com", "long"),
])
def test_addresses_that_cannot_be_stored_are_refused(field, value, message):
    r = build(draft(id="x1", name="X One", **{field: value}))
    assert any(message in p["message"] and p["field"] == field for p in r["problems"]), r["problems"]


def test_a_bare_host_gets_https_and_a_typed_address_is_kept_as_typed():
    got = run("normalize", inputs=["  gbatemp.net/members/x.1/ ", "https://Example.com/A?b=1#c", ""])
    assert [g["url"] for g in got] == ["https://gbatemp.net/members/x.1/", "https://Example.com/A?b=1#c", ""]
    assert not any("error" in g for g in got)


def test_handles_names_and_aliases_are_checked_against_the_stored_creators():
    others = [{"id": "pankeko", "name": "Pankeko", "aliases": ["pan keko"]}, {"id": "edit-me", "name": "Edit Me", "aliases": []}]
    taken = build(draft(id="pankeko", name="Someone"), creators=others)["problems"]
    assert [p["message"] for p in taken] == ["That handle is taken"]
    assert any("reserved" in p["message"] for p in build(draft(id="edit", name="Edit"), creators=others)["problems"])
    assert any("pattern" in p["message"] or "Lower-case" in p["message"] for p in build(draft(id="Bad Id", name="B"), creators=others)["problems"])
    clash = build(draft(id="new-one", name="PAN-KEKO"), creators=others)["problems"]
    assert clash and clash[0]["creator"] == "pankeko"
    alias = build(draft(id="new-one", name="New One", aliases=["Pan Keko"]), creators=others)["problems"]
    assert alias and alias[0]["creator"] == "pankeko"
    assert [p["field"] for p in build(draft(id="new-one", name="  "), creators=others)["problems"]] == ["name"]


def test_an_edit_is_not_blocked_by_a_name_clash_that_is_already_in_the_data():
    a = {"id": "a", "name": "Alpha", "aliases": ["Beta"]}
    b = {"id": "b", "name": "Beta", "aliases": []}
    r = build(draft(id="a", name="Alpha", aliases=["Beta"], page="https://gbatemp.net/members/a.1/"), base=a, creators=[a, b])
    assert r["problems"] == []
    r = build(draft(id="a", name="Alpha", aliases=["Beta", "Gamma", "BETA2"]), base=a, creators=[a, b, {"id": "c", "name": "Gamma", "aliases": []}])
    assert [p["message"] for p in r["problems"]] == ["“Gamma” already belongs to Gamma"]


NAMES = ["Pankeko", "Zoë Ünder_Pixel", "Ünïcödé", "  spaced   out  ", "AI-Upscale!!", "日本語", "Crème Brûlée", "ǆungla", "ßeta", "O'Brien",
         "x" * 80, "---", "!!!", "A--B", "Ｆｕｌｌｗｉｄｔｈ"]
SLUGS = ["pankeko", "zoe-under-pixel", "unicode", "spaced-out", "ai-upscale", "", "creme-brulee", "dzungla", "eta", "o-brien",
         "x" * 80, "", "", "a-b", "fullwidth"]
KEYS = ["pankeko", "zonderpixel", "ncd", "spacedout", "aiupscale", "", "crmebrle", "ungla", "eta", "obrien",
        "x" * 80, "", "", "ab", ""]


def test_handles_come_from_the_name_by_fixed_rules():
    """The rules (ASCII fold, lower-case, runs of anything else to one dash) are written down here because
    every existing handle and every name match in the data was made with them."""
    assert run("slug", names=NAMES) == SLUGS
    assert run("nameKey", names=NAMES) == KEYS
    existing = ["pankeko", "pankeko-2", "creator", "ewgeha"]
    cases = [{"name": n, "existing": existing} for n in ["Pankeko", "---", "Ewgeha", "New Person", "y" * 70]]
    assert run("newId", cases=cases) == ["pankeko-3", "creator-2", "ewgeha-2", "new-person", "y" * 44]


def test_the_stored_handles_follow_the_rules():
    """A creator's handle is its name's slug, with a number when two names make the same one."""
    creators = [load_yaml(f) for f in sorted(CREATORS_DIR.glob("*.yaml"))]
    slugs = run("slug", names=[c["name"] for c in creators])
    base = [s[:44].strip("-") or "creator" for s in slugs]
    odd = [(c["id"], b) for c, b in zip(creators, base) if not (c["id"] == b or c["id"].startswith(b + "-"))]
    assert odd == []


def test_every_kind_offered_is_in_the_schema_and_labelled():
    enum = SCHEMA["$defs"]["kindUrl"]["properties"]["kind"]["enum"]
    k = run("kinds")
    assert set(k["tip"]) <= set(enum) and set(k["social"]) <= set(enum)
    assert set(k["labels"]) == set(enum)


def test_link_kinds_are_guessed_from_the_host():
    urls = ["https://www.youtube.com/@x", "https://youtu.be/abc", "https://ko-fi.com/x", "https://www.patreon.com/x", "https://x.com/y",
            "https://bsky.app/profile/y", "https://gbatemp.net/members/x.1/", "https://someone.github.io/", "https://example.org/", "https://notyoutube.com/"]
    assert run("detect", urls=urls) == ["youtube", "youtube", "kofi", "patreon", "x", "bluesky", "gbatemp", "github", "website", "website"]


def test_the_new_file_link_carries_the_path_and_the_text_intact():
    text = "id: zoe\nname: 'Zoë & co: 100% #1'\nstatus: active\n"
    url = run("newFileUrl", id="zoe", text=text)
    u = urlparse(url)
    q = parse_qs(u.query, keep_blank_values=True)
    assert (u.scheme, u.netloc, u.path) == ("https", "github.com", "/ps2ktxpak/catalog/new/main")
    assert q["filename"] == ["data/creators/zoe.yaml"] and q["value"] == [text]
