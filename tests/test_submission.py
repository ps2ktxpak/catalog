"""A submission is what the forms file as a GitHub issue and .github/workflows/submission.yml applies. These tests
run the real command (tools/node/apply-submission.mjs) on a copy of the data: what it writes must equal what the
page previews, and anything outside the allowlist must be refused without touching a file."""
import json
import re
import shutil
import subprocess
from urllib.parse import parse_qs, urlparse

import jsonschema
import pytest
import yaml

from ps2ktxpak.common import ROOT, load_yaml

RUNNER = ROOT / "tests" / "creator_form_runner.mjs"
CLI = ROOT / "tools" / "node" / "apply-submission.mjs"
pytestmark = pytest.mark.skipif(
    not shutil.which("node") or not (ROOT / "site" / "node_modules" / "ajv").exists(),
    reason="needs node and `npm install` in site/")
DATE = "2099-01-01"


def run(op, **kw):
    r = subprocess.run(["node", str(RUNNER)], input=json.dumps({"op": op, "date": DATE, **kw}), capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / "schema", tmp_path / "schema")
    shutil.copytree(ROOT / "data" / "creators", tmp_path / "data" / "creators")
    shutil.copytree(ROOT / "data" / "packs", tmp_path / "data" / "packs")
    return tmp_path


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*.yaml"))}


def apply(root, body):
    (root / "body.md").write_text(body, encoding="utf-8")
    r = subprocess.run(["node", str(CLI), "--root", str(root), "--body-file", str(root / "body.md"),
                        "--result-file", str(root / "result.json"), "--date", DATE], capture_output=True, text=True)
    return r.returncode, json.loads((root / "result.json").read_text())


def body(sub, who="Someone"):
    return f"### Submission\n\n```json\n{json.dumps(sub)}\n```\n\n### Who is submitting\n\n{who}\n"


def creator_draft(**kw):
    return {"id": "", "name": "", "aliases": [], "page": "", "distribution": "", "tip": [], "socials": [], **kw}


def pack_draft(**kw):
    key = run("newKey", cases=[{"serials": ["SLUS-20964"], "lead": "pankeko", "existing": []}])[0]
    return {"key": key, "name": "A Pack", "title": "A Game", "serials": "SLUS-20964", "type": "ai_upscale", "completeness": "complete",
            "description": "", "cost": "free", "hosting": "hosted",
            "credits": [{"who": "Pankeko", "id": "", "role": "author", "note": ""}],
            "sources": [{"kind": "mirror", "url": "https://mega.nz/folder/abc", "primary": True, "note": ""}],
            "images": [], "videos": [], **kw}


def filed(kind, draft, base=None):
    return run("submit", kind=kind, draft=draft, base=base)


def check_matches_preview(root, kind, draft, base_path=None):
    base = load_yaml(root / base_path) if base_path else None
    f = filed(kind, draft, base)
    code, result = apply(root, f["body"])
    assert code == 0 and result["ok"], result
    assert (root / result["path"]).read_text(encoding="utf-8") == f["preview"]
    schema = json.loads((ROOT / "schema" / f"{kind}.schema.json").read_text())
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(load_yaml(root / result["path"])))
    return f, result


def test_a_new_creator_is_filed_and_written_as_previewed(root):
    d = creator_draft(id="zoe-test", name="Zoë Test", aliases=["ZT"], page="gbatemp.net/members/zoe.1/",
                      socials=[{"kind": "youtube", "url": "youtube.com/@zoe"}])
    f, result = check_matches_preview(root, "creator", d)
    assert result == {"ok": True, "kind": "creator", "op": "create", "id": "zoe-test", "path": "data/creators/zoe-test.yaml"}
    assert f["title"] == "Add creator zoe-test"
    rec = load_yaml(root / result["path"])
    assert list(rec) == ["id", "name", "aliases", "links", "status"]


def test_a_creator_edit_files_only_what_changed_and_leaves_the_rest(root):
    base = load_yaml(root / "data/creators/ewgeha.yaml")
    d = creator_draft(id="ewgeha", name="Ewgeha", page=base["links"]["page"], socials=[], tip=[{"kind": "kofi", "url": "ko-fi.com/ewgeha"}])
    f, result = check_matches_preview(root, "creator", d, "data/creators/ewgeha.yaml")
    assert sorted(f["sub"]["set"]) == ["links.socials", "links.tip", "name"]
    rec = load_yaml(root / result["path"])
    assert rec["avatar"] == base["avatar"] and rec["links"]["page"] == base["links"]["page"] and "socials" not in rec["links"]


def test_a_new_hosted_pack_and_a_listed_only_pack(root):
    f, result = check_matches_preview(root, "pack", pack_draft(videos=[{"url": "youtu.be/dQw4w9WgXcQ", "title": ""}]))
    rec = load_yaml(root / result["path"])
    assert rec["hosting"]["state"] == "published" and rec["permission"]["kind"] == "creator_approved" and rec["access"] == {"cost": "free"}
    assert f["sub"]["new"] == {"cost": "free", "hosting": "hosted"}
    d = pack_draft(hosting="listed", cost="paid", sources=[])
    d["key"] += "-2"
    _, result = check_matches_preview(root, "pack", d)
    rec = load_yaml(root / result["path"])
    assert rec["hosting"]["state"] == "withheld" and rec["permission"] == {"kind": "unknown"} and rec["access"] == {"cost": "paid"}


def test_a_pack_edit_keeps_what_the_form_does_not_show(root):
    path = "data/packs/sces-50885-quicksliver1.yaml"
    base = load_yaml(root / path)
    d = run("packDraft", text=(root / path).read_text(encoding="utf-8"))
    d["description"] = "A new description."
    d["videos"][0]["title"] = "Trailer"
    f, result = check_matches_preview(root, "pack", d, path)
    assert sorted(f["sub"]["set"]) == ["description", "media"] and "new" not in f["sub"]
    rec = load_yaml(root / result["path"])
    for untouched in ("catalog_id", "legacy", "hosting", "permission", "credits", "sources", "game"):
        assert rec[untouched] == base[untouched]
    d["videos"] = []
    check_matches_preview(root, "pack", d, path)  # clearing a list is a change too


def test_what_is_filed_fits_in_an_issue_address_for_the_ordinary_case():
    f = filed("pack", pack_draft(description="x" * 400))
    q = parse_qs(urlparse(f["url"]).query)
    assert len(f["url"]) < 7500 and q["template"] == ["submission.yml"] and json.loads(q["payload"][0]) == f["sub"]
    assert q["title"] == ["Add pack " + f["sub"]["id"]]


GOOD = {"v": 1, "kind": "creator", "op": "update", "id": "ewgeha", "set": {"name": "Ewgeha"}}


def refused(root, text, expect):
    before = tree(root)
    code, result = apply(root, text)
    assert code == 1 and result["ok"] is False
    assert any(expect in e for e in result["errors"]), result["errors"]
    assert tree(root) == before, "a refused submission must not change any file"


@pytest.mark.parametrize("change, expect", [
    (lambda s: s["set"].update(permission={"kind": "creator_approved"}), "cannot be changed"),
    (lambda s: s["set"].update(locked=[]), "cannot be changed"),
    (lambda s: s["set"].update(provenance={}), "cannot be changed"),
    (lambda s: s["set"].update(**{"links.page": "http://example.com/x"}), "https://"),
    (lambda s: s["set"].update(**{"links.page": "https://user:pw@example.com/x"}), "username"),
    (lambda s: s["set"].update(name="two\nlines"), "control characters"),
    (lambda s: s["set"].update(name=["not", "a", "string"]), "string"),
    (lambda s: s.update(set={}), "nothing to change"),
    (lambda s: s.pop("set"), "changes are missing"),
    (lambda s: s.update(v=2), "version"),
    (lambda s: s.update(kind="avatar"), "kind"),
    (lambda s: s.update(op="delete"), "operation"),
    (lambda s: s.update(id="../../etc/passwd"), "identifier"),
    (lambda s: s.update(id="Ewgeha"), "identifier"),
    (lambda s: s.update(id="nobody-here"), "no creator"),
    (lambda s: s.update(op="create"), "already exists"),
    (lambda s: s.update(**{"new": {"cost": "free", "hosting": "hosted"}}), "applies only to a new pack"),
    (lambda s: s.update(extra=1), "Unknown field"),
    (lambda s: s["set"].update(aliases=["Pankeko"]), "already belongs to"),
    (lambda s: s["set"].update(**{"links.tip": [{"kind": "kofi", "url": "https://ko-fi.com/x", "extra": 1}]}), "additional properties"),
])
def test_a_submission_outside_the_allowlist_is_refused_and_changes_nothing(root, change, expect):
    sub = json.loads(json.dumps(GOOD))
    change(sub)
    refused(root, body(sub), expect)


def test_handles_the_site_uses_for_pages_are_reserved(root):
    refused(root, body({"v": 1, "kind": "creator", "op": "create", "id": "edit", "set": {"name": "Edit"}}), "reserved")


def test_pack_submissions_cannot_grant_hosting_or_name_stored_copies(root):
    path = "data/packs/sces-50885-quicksliver1.yaml"
    pid = "sces-50885-quicksliver1"
    for field in ("hosting", "permission", "access", "legacy", "needs_review", "key", "catalog_id"):
        refused(root, body({"v": 1, "kind": "pack", "op": "update", "id": pid, "set": {field: {"state": "published"}}}), "cannot be changed")
    new = {"v": 1, "kind": "pack", "op": "create", "id": "slus-20964-zz-test", "set": {}, "new": {"cost": "free", "hosting": "hosted"}}
    f = filed("pack", pack_draft())["sub"]
    new["set"] = f["set"]
    new["set"]["media"] = {"images": [{"storage_key": "packs/someone-elses.tar.zst"}]}
    refused(root, body(new), "stored copy")
    new["set"].pop("media")
    new["set"]["credits"] = [{"creator": "not-a-creator"}]
    refused(root, body(new), "no creator")
    new["set"]["credits"] = []
    refused(root, body(new), "at least one creator")
    new["new"] = {"cost": "free", "hosting": "published"}
    refused(root, body(new), "needs a cost")
    del new["new"]
    refused(root, body(new), "needs a cost")
    assert not (root / path).read_text(encoding="utf-8").startswith("hosting")


@pytest.mark.parametrize("text, expect", [
    ("", "No submission"),
    ("### Submission\n\nnot fenced\n", "No submission"),
    ("### Submission\n\n```json\n{not json\n```\n", "not valid JSON"),
    ("### Submission\n\n```json\n[]\n```\n", "not an object"),
    ("### Submission\n\n```json\n" + "x" * 70000 + "\n```\n", "too large"),
])
def test_text_that_is_not_a_submission_is_refused(root, text, expect):
    refused(root, text, expect)


def test_an_issue_body_with_windows_line_endings_and_extra_sections_is_read(root):
    text = body(GOOD, who="[hi](https://example.com) @someone").replace("\n", "\r\n")
    code, result = apply(root, text)
    assert code == 0 and result["ok"], result


def test_the_workflow_never_puts_issue_text_inside_a_command():
    wf = (ROOT / ".github" / "workflows" / "submission.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(wf)
    for job in doc["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step.get("name")
    assert re.findall(r"github\.event\.issue\.body", wf) == ["github.event.issue.body"]
    assert "ISSUE_BODY: ${{ github.event.issue.body }}" in wf
    assert set(doc["permissions"]) == {"contents", "pull-requests", "issues", "actions"}
    assert doc[True]["issues"]["types"] == ["opened"]


def test_the_issue_template_has_the_fields_the_forms_fill_in():
    t = yaml.safe_load((ROOT / ".github" / "ISSUE_TEMPLATE" / "submission.yml").read_text(encoding="utf-8"))
    ids = {b["id"]: b for b in t["body"] if "id" in b}
    assert t["labels"] == ["submission"] and set(ids) == {"payload", "who"}
    assert ids["payload"]["attributes"]["render"] == "json" and ids["payload"]["type"] == "textarea" and ids["who"]["validations"]["required"]
