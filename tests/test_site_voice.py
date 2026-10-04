"""The published site speaks in the passive and owns no intent: no 'we', 'you', 'our', 'your'.
A list of packs that exist somewhere, with nobody speaking. Comments marked TODO are for the maintainers
and are not published, so they are exempt."""
import re

from ps2ktxpak.common import ROOT

SITE = ROOT / "site"
PRONOUNS = re.compile(r"\b(we|we're|we've|we'll|us|our|ours|ourselves|you|you're|you've|you'll|your|yours|yourself|let's)\b", re.I)


def _strip_comments(text):
    text = re.sub(r"\{/\*.*?\*/\}", "", text, flags=re.S)          # MDX / Astro comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)             # HTML comments
    return text


def _published_text(path):
    return _strip_comments(path.read_text(encoding="utf-8"))


def test_the_detector_flags_pronouns_and_ignores_todo_comments():
    assert PRONOUNS.findall(_strip_comments("Packs we host. Your name. {/* TODO: you decide */} <!-- our note -->")) == ["we", "Your"]
    assert not PRONOUNS.findall(_strip_comments("Packs are hosted. Names as spelled by creators."))


def test_no_first_or_second_person_in_published_pages():
    files = [*(SITE / "src" / "content" / "docs").glob("*.md*"), *(SITE / "src" / "pages").rglob("*.astro"),
             *(SITE / "src" / "components").glob("*.astro"), SITE / "astro.config.mjs"]
    assert files
    found = {}
    for f in files:
        hits = [m.group(0) for m in PRONOUNS.finditer(_published_text(f))]
        if hits:
            found[str(f.relative_to(ROOT))] = hits
    assert not found, found
