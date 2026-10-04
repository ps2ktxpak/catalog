from ps2ktxpak import resolve
from ps2ktxpak.import_legacy import catalog_names

OP_HTML = '''
<article class="message    message-threadStarterPost message--post   js-post js-inlineModContainer   " data-author="mvp899">
<div class="bbWrapper">Pack for Dead to Rights 2. <a href="https://mega.nz/file/abc#key">Download here</a>
 and <a href="https://i.imgur.com/x.png">a screenshot</a><br />
<blockquote class="bbCodeBlock"><div>quoted: <a href="https://evil.example/old">old link</a></div></blockquote>
<span data-s9e-mediaembed="youtube"><span style="background:url(https://i.ytimg.com/vi/aPoUWnktTc4/hqdefault.jpg)"></span></span>
</div><div class="js-selectToQuoteEnd">&nbsp;</div></article>
<article class="message   message--post   js-post js-inlineModContainer   " data-author="mvp899">
<div class="bbWrapper">Update: <a href="https://drive.google.com/file/d/1abc/view">new version</a></div><div class="js-selectToQuoteEnd">&nbsp;</div></article>
<article class="message   message--post   js-post js-inlineModContainer   " data-author="someone">
<div class="bbWrapper">Mirror: <a href="https://www.mediafire.com/file/zzz">here</a></div><div class="js-selectToQuoteEnd">&nbsp;</div></article>
'''


def test_posts_parse_into_author_links_context_and_videos():
    posts = resolve.parse_posts(OP_HTML)
    assert [p["author"] for p in posts] == ["mvp899", "mvp899", "someone"]
    assert posts[0]["is_op"] and not posts[1]["is_op"]
    urls = [l["url"] for l in posts[0]["links"]]
    assert "https://mega.nz/file/abc#key" in urls
    assert "https://evil.example/old" not in urls          # links inside a quoted post are not the author's
    mega = next(l for l in posts[0]["links"] if "mega.nz" in l["url"])
    assert "Pack for Dead to Rights 2" in mega["context"]
    assert posts[0]["videos"] == [{"id": "aPoUWnktTc4", "title": ""}]


def test_found_links_skip_social_and_image_hosts_and_classify_the_rest():
    assert resolve._found("https://i.imgur.com/x.png", "op", "") is None
    assert resolve._found("https://twitter.com/x", "op", "") is None
    f = resolve._found("https://mega.nz/folder/a#b", "op", "ctx")
    assert (f["host"], f["kind"], f["where"]) == ("mega", "folder", "op")


def _decide(listings, candidates, videos=(), status="ok", http=None):
    fetched = {"at": "2026-10-03", "status": status, **({"http": http} if http else {})}
    return resolve._decide("https://gbatemp.net/threads/x.1/", listings, fetched, candidates, list(videos), "2026-10-03")


def test_one_file_host_link_in_the_opening_post_is_resolved_with_medium_confidence():
    c = resolve._found("https://mega.nz/file/a#b", "op", "")
    [d] = _decide([{"id": "l-aaaaaaaaaa"}], [c])
    assert d["status"] == "resolved" and d["base_url"] == c["url"] and d["confidence"] == "medium"
    assert d["decided_by"]["method"] == "deterministic"


def test_two_candidates_or_a_library_page_are_left_for_judgement():
    a, b = resolve._found("https://mega.nz/file/a#b", "op", ""), resolve._found("https://drive.google.com/file/d/1/view", "op", "")
    assert _decide([{"id": "l-aaaaaaaaaa"}], [a, b]) == []
    assert _decide([{"id": "l-aaaaaaaaaa"}, {"id": "l-bbbbbbbbbb"}], [a]) == []


def test_a_reply_by_someone_else_is_never_decided_automatically():
    c = resolve._found("https://mega.nz/file/a#b", "reply_by_other", "")
    assert _decide([{"id": "l-aaaaaaaaaa"}], [c]) == []


def test_a_video_link_counts_only_when_the_uploader_posted_it():
    own = resolve._found("https://ko-fi.com/s/abc", "video_pinned_comment", "", True)
    other = resolve._found("https://mega.nz/file/z#k", "video_comment", "", False)
    [d] = _decide([{"id": "l-aaaaaaaaaa"}], [], [{"id": "aPoUWnktTc4", "links": [own, other]}])
    assert d["base_url"] == "https://ko-fi.com/s/abc"


def test_a_missing_page_is_marked_dead():
    [d] = _decide([{"id": "l-aaaaaaaaaa"}], [], status="http_error", http=404)
    assert d["status"] == "dead"


def test_catalog_credit_text_is_read_into_names():
    e = lambda *a: {"authors": list(a)}
    assert catalog_names(e("Texture pack credited to Beto818 by the curated PCSX2 HD Texture Project list; original archive filename x")) == ["Beto818"]
    assert catalog_names(e("AI-upscaled HD texture pack created", "maintained by ckiscxrsed.")) == ["ckiscxrsed"]
    assert catalog_names(e("Original texture creator is not identified in the public mirror; preserved by the community")) == []
    assert catalog_names(e("Bl4ckH4nd", "SomberShroud")) == ["Bl4ckH4nd", "SomberShroud"]
    assert catalog_names(e("KevinMI Upscales: SomberShroud")) == ["KevinMI Upscales", "SomberShroud"]


def test_an_agent_never_overwrites_a_persons_decision_but_can_fill_the_rest(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(resolve, "RESOLUTION_DIR", tmp_path)
    url = "https://gbatemp.net/threads/x.1/"
    doc = {"source_url": url, "listings": ["l-aaaaaaaaaa", "l-bbbbbbbbbb"],
           "fetched": {"at": "2026-10-03", "status": "ok"}, "candidates": [],
           "decisions": [{"listing": "l-aaaaaaaaaa", "status": "resolved", "base_url": "https://mega.nz/file/h#k",
                          "host": "mega", "kind": "file", "confidence": "high", "reason": "checked by hand",
                          "decided_by": {"method": "human", "date": "2026-10-03"}}]}
    resolve.resolution_path(url).write_text(json.dumps(doc))
    agent = tmp_path / "agent.json"
    agent.write_text(json.dumps([
        {"source_url": url, "listing": "l-aaaaaaaaaa", "status": "dead", "reason": "agent disagrees"},
        {"source_url": url, "listing": "l-bbbbbbbbbb", "status": "resolved", "base_url": "https://drive.google.com/file/d/1/view",
         "host": "gdrive", "kind": "file", "confidence": "medium", "reason": "only link"},
        {"source_url": url, "listing": "l-cccccccccc", "status": "dead"},           # not on this page
        {"source_url": url, "listing": "l-bbbbbbbbbb", "status": "resolved"},       # resolved with no link: refused
    ]))
    assert resolve.apply_decisions(agent, model="haiku", retrieved="2026-10-04") == 0
    out = {d["listing"]: d for d in json.loads(resolve.resolution_path(url).read_text())["decisions"]}
    assert out["l-aaaaaaaaaa"]["decided_by"]["method"] == "human" and out["l-aaaaaaaaaa"]["status"] == "resolved"
    assert out["l-bbbbbbbbbb"]["decided_by"] == {"method": "agent", "model": "haiku", "date": "2026-10-04"}
    assert out["l-bbbbbbbbbb"]["base_url"].startswith("https://drive.google.com")
    assert "l-cccccccccc" not in out


EMBED_HTML = '''
<article class="message    message-threadStarterPost message--post   js-post   " data-author="creator">
<div class="bbWrapper">Download links:<br />16:9<br />
<span data-s9e-mediaembed="googledrive"><span style="padding-bottom:75%"><span data-s9e-mediaembed-iframe='["allowfullscreen","","scrolling","no","src","\\/\\/drive.google.com\\/file\\/d\\/1MyUz-p_D4\\/preview"]'></span></span></span>
Mirror: mega.nz/file/weJRHCBB#SWlEMnp0cO-ko6Ob6 and also <a href="https://www.mediafire.com/file/abc/x.zip/file">https://www.mediafire.com/file/abc/x.zip/file</a>
</div><div class="js-selectToQuoteEnd">&nbsp;</div></article>
'''


def test_a_pasted_drive_link_arrives_as_an_embedded_player_and_is_still_found():
    [post] = resolve.parse_posts(EMBED_HTML)
    urls = [l["url"] for l in post["links"]]
    assert "https://drive.google.com/file/d/1MyUz-p_D4/view" in urls


def test_a_file_host_link_typed_without_https_is_found_once():
    [post] = resolve.parse_posts(EMBED_HTML)
    urls = [l["url"] for l in post["links"]]
    assert "https://mega.nz/file/weJRHCBB#SWlEMnp0cO-ko6Ob6" in urls
    assert sum("mediafire.com" in u for u in urls) == 1      # the anchor and its visible text are one link
    drive = next(l for l in post["links"] if "drive.google.com" in l["url"])
    assert "Download links" in drive["context"]


def test_an_ad_gating_shortener_is_flagged_by_the_validator_list():
    from ps2ktxpak.validate import SHORTENERS
    assert "ouo.io" in SHORTENERS and "bit.ly" in SHORTENERS


LIBRARY_HTML = '''
<article class="message    message-threadStarterPost message--post   js-post   " data-author="creator">
<div class="bbWrapper"><div class="bbCodeSpoiler"><button><span class="button-text"><span>Spoiler: <span class="bbCodeSpoiler-button-title">Jak II</span></span></span></button>
<div class="bbCodeSpoiler-content"><span data-s9e-mediaembed="youtube"><span><span style="background:url(https://i.ytimg.com/vi/AAAAAAAAAAA/hqdefault.jpg)"></span></span></span></div></div>
<div class="bbCodeSpoiler"><button><span class="button-text"><span>Spoiler: <span class="bbCodeSpoiler-button-title">Ape Escape 2 &amp; More</span></span></span></button>
<div class="bbCodeSpoiler-content"><span data-s9e-mediaembed="youtube"><span><span style="background:url(https://i.ytimg.com/vi/BBBBBBBBBBB/hqdefault.jpg)"></span></span></span></div></div>
</div><div class="js-selectToQuoteEnd">&nbsp;</div></article>
'''


def test_each_video_in_a_library_thread_keeps_the_game_title_it_sits_under():
    [post] = resolve.parse_posts(LIBRARY_HTML)
    assert post["videos"] == [{"id": "AAAAAAAAAAA", "title": "Jak II"}, {"id": "BBBBBBBBBBB", "title": "Ape Escape 2 & More"}]


def test_title_match_is_strict_about_numbers():
    assert resolve._title_match("Jak II", "Jak II") and resolve._title_match("Ratchet & Clank", "Ratchet and Clank")
    assert not resolve._title_match("Final Fantasy XII", "Final Fantasy X-2")
    assert not resolve._title_match("Tony Hawk's Pro Skater 3", "Tony Hawk's Pro Skater 4")


def test_a_library_game_is_decided_only_when_its_video_gives_exactly_one_file_link():
    def vid(title, *urls, by=True):
        return {"id": "x" * 11, "title": title,
                "links": [resolve._found(u, "video_pinned_comment", "", by) for u in urls]}
    listings = [{"id": "l-aaaaaaaaaa", "title": "Jak II"}, {"id": "l-bbbbbbbbbb", "title": "Jak 3"},
                {"id": "l-cccccccccc", "title": "Ape Escape 2"}, {"id": "l-dddddddddd", "title": "Scarface"}]
    videos = [vid("Jak II", "https://mega.nz/file/a#k"),
              vid("Jak 3", "https://mega.nz/file/b#k", "https://drive.google.com/file/d/1/view"),   # two links: left alone
              vid("Ape Escape 2", "https://mega.nz/file/c#k", by=False)]                               # not the uploader's
    fetched = {"at": "2026-10-03", "status": "ok"}
    out = resolve._decide("https://gbatemp.net/threads/lib.1/", listings, fetched, [], videos, "2026-10-03")
    assert [d["listing"] for d in out] == ["l-aaaaaaaaaa"] and out[0]["base_url"] == "https://mega.nz/file/a#k"


def test_a_decision_is_filed_by_its_listing_even_when_the_agent_mistypes_the_page_url(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(resolve, "RESOLUTION_DIR", tmp_path)
    url = "https://gbatemp.net/threads/ps2-heartbeat-boxing-sles-51865-europe.683545/"
    doc = {"source_url": url, "listings": ["l-aaaaaaaaaa"], "fetched": {"at": "2026-10-03", "status": "ok"},
           "candidates": [], "decisions": []}
    resolve.resolution_path(url).write_text(json.dumps(doc))
    agent = tmp_path / "agent.json"
    agent.write_text(json.dumps([{"source_url": "https://gbatemp.net/threads/heartbeat-boxing-sles-51865-europe.683545/",
                                  "listing": "l-aaaaaaaaaa", "status": "resolved", "base_url": "https://example.github.io/x/",
                                  "host": "other", "kind": "page", "confidence": "high", "reason": "labelled download"}]))
    resolve.apply_decisions(agent, model="haiku", retrieved="2026-10-04")
    [d] = json.loads(resolve.resolution_path(url).read_text())["decisions"]
    assert d["listing"] == "l-aaaaaaaaaa" and d["decided_by"]["model"] == "haiku"


def test_a_stray_na_in_an_enum_field_is_dropped_not_fatal(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(resolve, "RESOLUTION_DIR", tmp_path)
    url = "https://gbatemp.net/threads/x.1/"
    resolve.resolution_path(url).write_text(json.dumps({"source_url": url, "listings": ["l-aaaaaaaaaa"],
        "fetched": {"at": "2026-10-03", "status": "ok"}, "candidates": [], "decisions": []}))
    agent = tmp_path / "agent.json"
    agent.write_text(json.dumps([{"source_url": url, "listing": "l-aaaaaaaaaa", "status": "not_found",
                                  "confidence": "N/A", "host": "N/A", "reason": "no link"}]))
    resolve.apply_decisions(agent, model="haiku", retrieved="2026-10-04")
    [d] = json.loads(resolve.resolution_path(url).read_text())["decisions"]
    assert d["status"] == "not_found" and "confidence" not in d and "host" not in d
