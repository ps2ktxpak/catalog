"""Download a pack's files from the host its `download` block names.

`list_link` says what a link holds (files, sizes) without downloading; `fetch` downloads it. Failures
are sorted by what to do next: `Gone` means the host says the file no longer exists
(do not retry), `Unsupported` means this code cannot fetch from that host or link shape, and any
other exception is worth retrying later (quota, rate limit, network)."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MEGATOOLS = os.environ.get("MEGATOOLS", "megatools")
MEGARC = os.environ.get("MEGARC")  # a megatools config file with a [Login] section
# MediaFire puts its file pages behind a browser check; a signed-in account gets direct links from the API.
MEDIAFIRE_EMAIL = os.environ.get("MEDIAFIRE_EMAIL")
MEDIAFIRE_PASSWORD = os.environ.get("MEDIAFIRE_PASSWORD")


class Gone(Exception):
    """The host says the file was removed or never existed."""


class Unsupported(Exception):
    """No downloader for this host or link shape."""


class TooLarge(Exception):
    """The file would not fit in the space we have."""


def get_text(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise Gone(f"{url}: HTTP {e.code}") from e
        raise


def get_json(url: str, **kw):
    return json.loads(get_text(url, **kw))


def curl(url: str, dest: Path, limit: int | None = None, headers: dict | None = None) -> Path:
    """Download one URL to `dest` (a file path), resuming a partial file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # A download slower than 10 kB/s for five minutes is given up, and resumed by the retry.
    argv = ["curl", "-sS", "-L", "--fail-with-body", "--retry", "5", "--retry-delay", "10",
            "--speed-limit", "10240", "--speed-time", "300",
            "-A", UA, "-C", "-", "-o", str(dest), "-w", "%{content_type} %{http_code}"]
    if limit:
        argv += ["--max-filesize", str(limit)]
    for k, v in (headers or {}).items():
        argv += ["-H", f"{k}: {v}"]
    p = subprocess.run(argv + [url], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode == 63:
        dest.unlink(missing_ok=True)
        raise TooLarge(f"{url} is larger than {limit} bytes")
    if p.returncode == 33:  # range not satisfiable: a finished file, or a server without ranges
        dest.unlink(missing_ok=True)
        return curl(url, dest, limit, headers)
    if p.returncode != 0:
        code = p.stdout.rsplit(" ", 1)[-1]
        if code in ("404", "410"):
            dest.unlink(missing_ok=True)
            raise Gone(f"{url}: HTTP {code}")
        raise RuntimeError(f"curl {url}: exit {p.returncode} {p.stderr.strip()[-300:]}")
    if p.stdout.startswith("text/html"):
        head = dest.read_text("utf-8", "replace")[:4000]
        dest.unlink(missing_ok=True)
        if re.search(r"quota|too many users|exceeded", head, re.I):
            text = re.sub(r"<[^>]+>|\s+", " ", head)[:200]
            raise RuntimeError(f"{url}: the host refused for quota: {text}")
        raise RuntimeError(f"{url}: got a web page, not a file")
    return dest


def _name_from_url(url: str, fallback: str) -> str:
    name = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    return _safe(name) or fallback


def _safe(name: str) -> str:
    name = re.sub(r"[\x00-\x1f/\\]", "_", name).strip(" .")
    return name[:200]


# ---- what a link holds --------------------------------------------------------------------------
#
# Each host function turns a link into a list of entries, without downloading anything. A folder
# link may hold one pack in several files, or a whole library with one archive per game; `pick`
# keeps the files named for the game we want, and the sizes are checked before the first byte.

@dataclass
class Entry:
    name: str             # path inside the link, used as the file name we store
    size: int | None      # None when the host does not say
    get: Callable[[Path, int | None], Path]  # download to this path
    sole: bool = False    # the link is this one file, though the host would not say its name just now


@dataclass
class Want:
    title: str
    serials: list = field(default_factory=list)


def _curl_entry(name: str, size: int | None, link: str, headers: dict | None = None) -> Entry:
    return Entry(name, size, lambda dest, limit: curl(link, dest, limit, headers))


def mega(url: str) -> list[Entry]:
    """megatools fetches a whole link; Mega lists a folder only to a logged-in session we do not need."""
    def get(dest: Path, limit: int | None) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        argv = [MEGATOOLS, "dl", "--no-progress", "--path", str(dest)]
        if MEGARC:
            argv += ["--config", MEGARC]
        p = subprocess.run(argv + [url], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        err = p.stderr.strip()
        if p.returncode != 0 or "ERROR" in err:
            if re.search(r"\b(ENOENT|EBLOCKED)\b", err):
                raise Gone(f"mega: {err[-200:]}")
            raise RuntimeError(f"mega: {err[-300:]}")
        if not any(p.is_file() for p in dest.rglob("*")):  # megatools says nothing about an empty folder
            raise Gone(f"mega: {url} holds no files")
        return dest
    return [Entry("", None, get)]


def mediafire(url: str) -> list[Entry]:
    if m := re.search(r"mediafire\.com/folder/([a-z0-9]+)[^#]*(?:#([a-z0-9]+))?", url):
        return _mediafire_folder(m.group(2) or m.group(1), "")
    return [Entry(_name_from_url(url.removesuffix("/file"), "download"), None,
                  lambda dest, limit: _mediafire_file(url, dest, limit))]


MEDIAFIRE_API = "https://www.mediafire.com/api/1.5/"
MEDIAFIRE_APP = "42511"  # the API's public application id, which needs no key


def _mediafire_api(call: str, **params) -> dict:
    data = urllib.parse.urlencode({**params, "response_format": "json"}).encode()
    req = urllib.request.Request(MEDIAFIRE_API + call, data=data, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["response"]
    except urllib.error.HTTPError as e:  # errors come back as JSON with a 4xx status
        return json.loads(e.read().decode("utf-8", "replace"))["response"]


def _mediafire_direct(key: str) -> str:
    # A session token lasts ten minutes, so each file signs in afresh.
    sig = hashlib.sha1((MEDIAFIRE_EMAIL + MEDIAFIRE_PASSWORD + MEDIAFIRE_APP).encode()).hexdigest()
    r = _mediafire_api("user/get_session_token.php", email=MEDIAFIRE_EMAIL, password=MEDIAFIRE_PASSWORD,
                       application_id=MEDIAFIRE_APP, signature=sig, token_version=1)
    if r.get("result") != "Success":
        raise RuntimeError(f"mediafire: could not sign in: {r.get('message')}")
    r = _mediafire_api("file/get_links.php", session_token=r["session_token"], quick_key=key,
                       link_type="direct_download")
    if r.get("result") != "Success":
        raise RuntimeError(f"mediafire: {key}: {r.get('message')}")
    link = r["links"][0]
    if link.get("error") == "Invalid QuickKey":  # how it answers for a removed file
        raise Gone(f"mediafire: {key} was removed")
    if "direct_download" not in link:
        raise RuntimeError(f"mediafire: {key}: {link.get('direct_download_error_message')}")
    return link["direct_download"]


def _mediafire_file(url: str, dest: Path, limit: int | None) -> Path:
    if MEDIAFIRE_EMAIL and (m := re.search(r"mediafire\.com/(?:file(?:_premium)?/|\?|download/)([a-z0-9]+)", url)):
        return curl(_mediafire_direct(m.group(1)), dest, limit)
    # The file's page links to the file, except when MediaFire sends the file itself straight away.
    dest.parent.mkdir(parents=True, exist_ok=True)
    page_file = dest.with_name(dest.name + ".page")
    p = subprocess.run(["curl", "-sS", "-L", "-A", UA, "-o", str(page_file), "-w", "%{content_type}",
                        *(["--max-filesize", str(limit)] if limit else []), url],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode == 63:
        page_file.unlink(missing_ok=True)
        raise TooLarge(f"{url} is larger than {limit} bytes")
    if p.returncode != 0:
        raise RuntimeError(f"mediafire: curl exit {p.returncode} {p.stderr.strip()[-200:]}")
    if not p.stdout.startswith("text/html"):
        page_file.rename(dest)
        return dest
    page = page_file.read_text("utf-8", "replace")
    page_file.unlink()
    m = re.search(r'href="(https://download\d*\.mediafire\.com/[^"]+)"', page)
    if not m:
        if re.search(r"file (was )?removed|invalid or deleted|no longer available|Dangerous file|error\.php", page, re.I):
            raise Gone(f"mediafire: {url} was removed")
        raise RuntimeError(f"mediafire: no download link on {url}")
    return curl(html.unescape(m.group(1)), dest, limit)


def _mediafire_folder(key: str, prefix: str) -> list[Entry]:
    api = "https://www.mediafire.com/api/1.5/folder/get_content.php?response_format=json&chunk_size=1000&folder_key="
    entries = []
    for kind in ("files", "folders"):
        r = get_json(f"{api}{key}&content_type={kind}")["response"]
        if r.get("result") != "Success":
            raise Gone(f"mediafire folder {key}: {r.get('message')}")
        for item in r["folder_content"].get(kind, []):
            if kind == "files":
                link = item["links"]["normal_download"]
                entries.append(Entry(prefix + _safe(item["filename"]), int(item["size"]),
                                     lambda dest, limit, link=link: _mediafire_file(link, dest, limit)))
            else:
                entries += _mediafire_folder(item["folderkey"], prefix + _safe(item["name"]) + "/")
    return entries


def _gdrive_id(url: str) -> tuple[str, str]:
    if m := re.search(r"/folders/([\w-]+)", url):
        return "folder", m.group(1)
    if m := re.search(r"/file/(?:u/\d+/)?d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url):
        return "file", m.group(1)
    raise Unsupported(f"gdrive: no file or folder id in {url}")


def _gdrive_link(gid: str) -> str:
    return f"https://drive.usercontent.google.com/download?id={gid}&export=download&confirm=t"


def gdrive(url: str) -> list[Entry]:
    kind, gid = _gdrive_id(url)
    if kind == "folder":
        return _gdrive_folder(gid, "")
    name = _gdrive_name(gid)  # None while the file is over Google's download quota
    e = _curl_entry(name or gid, None, _gdrive_link(gid))
    e.sole = name is None
    return [e]


def _gdrive_name(gid: str) -> str | None:
    p = subprocess.run(["curl", "-sSIL", "-A", UA, _gdrive_link(gid)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    m = re.findall(r'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)', p.stdout, re.I)
    return _safe(urllib.parse.unquote(m[-1])) if m else None


def _gdrive_folder(fid: str, prefix: str) -> list[Entry]:
    page = get_text(f"https://drive.google.com/embeddedfolderview?id={fid}")
    entries = []
    for e in re.finditer(r'<a href="([^"]+)"[^>]*>.*?<div class="flip-entry-title">([^<]*)</div>', page, re.S):
        link, title = html.unescape(e.group(1)), html.unescape(e.group(2))
        kind, gid = _gdrive_id(link)
        if kind == "folder":
            entries += _gdrive_folder(gid, prefix + _safe(title) + "/")
        else:
            entries.append(_curl_entry(prefix + (_safe(title) or gid), None, _gdrive_link(gid)))
    if not entries and not prefix:
        raise Gone(f"gdrive folder {fid} lists no files, or is not public")
    return entries


def archive_org(url: str) -> list[Entry]:
    m = re.search(r"archive\.org/(?:details|download)/([^/?#]+)(?:/([^?#]+))?", url)
    if not m:
        raise Unsupported(f"archive.org: no item in {url}")
    item, path = m.group(1), m.group(2)
    meta = get_json(f"https://archive.org/metadata/{item}")
    if not meta.get("files"):
        raise Gone(f"archive.org item {item} has no files")
    files = [f for f in meta["files"] if f.get("source") == "original"
             and (f["name"] == urllib.parse.unquote(path) if path else ARCHIVE_NAME.search(f["name"]))]
    if not files:
        raise Unsupported(f"archive.org item {item} has no archive among its files")
    return [_curl_entry(_safe(f["name"]), int(f["size"]) if f.get("size") else None,
                        f"https://archive.org/download/{item}/{urllib.parse.quote(f['name'])}") for f in files]


def github(url: str) -> list[Entry]:
    """A release page: its assets. A repository page: its latest release's assets."""
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)(?:/releases(?:/tag/([^/#?]+))?)?", url)
    if not m:
        raise Unsupported(f"github: a user page, not a repository: {url}")
    owner, repo, tag = m.groups()
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
    headers = {"Accept": "application/vnd.github+json"}
    try:
        rel = get_json(api, headers=headers)
    except Gone:
        raise Gone(f"github: {owner}/{repo} has no release {tag or '(latest)'}")
    assets = [a for a in rel.get("assets", []) if ARCHIVE_NAME.search(a["name"])]
    if not assets:
        raise Unsupported(f"github: release {rel.get('tag_name')} of {owner}/{repo} has no archive asset")
    return [_curl_entry(_safe(a["name"]), a["size"], a["browser_download_url"]) for a in assets]


def pixeldrain(url: str) -> list[Entry]:
    if m := re.search(r"pixeldrain\.com/u/(\w+)", url):
        info = get_json(f"https://pixeldrain.com/api/file/{m.group(1)}/info")
        return [_curl_entry(_safe(info["name"]), info.get("size"), f"https://pixeldrain.com/api/file/{m.group(1)}?download")]
    if m := re.search(r"pixeldrain\.com/l/(\w+)", url):
        lst = get_json(f"https://pixeldrain.com/api/list/{m.group(1)}")
        return [_curl_entry(_safe(f["name"]), f.get("size"), f"https://pixeldrain.com/api/file/{f['id']}?download")
                for f in lst["files"]]
    raise Unsupported(f"pixeldrain: {url}")


def dropbox(url: str) -> list[Entry]:
    link = re.sub(r"([?&])dl=0", r"\1dl=1", url)
    if "dl=1" not in link:
        link += ("&" if "?" in link else "?") + "dl=1"
    return [_curl_entry(_name_from_url(url, "download"), None, link)]


def yandex(url: str) -> list[Entry]:
    q = urllib.parse.quote(url, safe="")
    meta = get_json(f"https://cloud-api.yandex.net/v1/disk/public/resources?public_key={q}&limit=1000")
    if meta.get("type") == "dir":
        return [_curl_entry(_safe(i["name"]), i.get("size"), i["file"]) for i in meta["_embedded"]["items"] if i["type"] == "file"]
    href = get_json(f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={q}")["href"]
    return [_curl_entry(_safe(meta.get("name") or "download"), meta.get("size"), href)]


def onedrive(url: str) -> list[Entry]:
    """Through the guest token OneDrive's own web viewer uses for a public share. Microsoft refuses
    it for old-style `s!` links since their move to SharePoint, and the old share API wants a login."""
    tok = get_json("https://api-badgerp.svc.ms/v1.0/token", data=json.dumps({"appId": ONEDRIVE_APP}).encode(),
                   headers={"Content-Type": "application/json"})["token"]
    share = "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    try:
        info = get_json(f"https://my.microsoftpersonalcontent.com/_api/v2.0/shares/{share}/driveitem"
                        "?$select=name,size,folder,@content.downloadUrl",
                        headers={"Authorization": f"Badger {tok}", "Prefer": "autoredeem"})
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise Unsupported(f"onedrive: Microsoft refuses an anonymous download of {url} (HTTP {e.code})") from e
        raise
    if "folder" in info:
        raise Unsupported("onedrive: shared folders are not handled")
    return [_curl_entry(_safe(info["name"]), info.get("size"), info["@content.downloadUrl"])]


def mailru(url: str) -> list[Entry]:
    """cloud.mail.ru: its public API lists a link's files; a file is served from the dispatcher's host."""
    m = re.search(r"cloud\.mail\.ru/public/([^?#]+)", url)
    if not m:
        raise Unsupported(f"cloud.mail.ru: {url}")
    base = get_json("https://cloud.mail.ru/api/v2/dispatcher")["body"]["weblink_get"][0]["url"]

    def walk(weblink: str, prefix: str) -> list[Entry]:
        body = get_json(f"https://cloud.mail.ru/api/v2/folder?weblink={urllib.parse.quote(weblink)}")["body"]
        entries = []
        for item in body.get("list", []):
            if item["type"] == "folder":
                entries += walk(item["weblink"], prefix + _safe(item["name"]) + "/")
            else:
                entries.append(_curl_entry(prefix + _safe(item["name"]), item.get("size"),
                                           f"{base}/{urllib.parse.quote(item['weblink'])}"))
        return entries

    return walk(m.group(1).rstrip("/"), "")


ONEDRIVE_APP = "5cbed6ac-a083-4e14-b191-b4ba07653de2"  # the OneDrive web viewer's public app id


HOSTS = ((r"(^|\.)mega\.(nz|co\.nz)$", mega), (r"mediafire\.com$", mediafire),
         (r"(drive|docs|drive\.usercontent)\.google\.com$", gdrive), (r"archive\.org$", archive_org),
         (r"^github\.com$", github), (r"pixeldrain\.com$", pixeldrain), (r"dropbox\.com$", dropbox),
         (r"disk\.yandex\.\w+$", yandex), (r"^cloud\.mail\.ru$", mailru), (r"^(1drv\.ms|onedrive\.live\.com)$", onedrive))
ARCHIVE_NAME = re.compile(r"\.(zip|7z|rar|tar|tgz|gz|zst)(\.\d+)?$|\.part\d+\.rar$|\.r\d\d$", re.I)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\bthe\b", "", (text or "").lower()))


STOPWORDS = {"the", "of", "and", "a", "an", "in", "to", "for", "ps2", "pcsx2", "hd", "pack"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOPWORDS}


def _overlap(title: str, name: str) -> float:
    want, have = _words(title), _words(Path(name).stem)
    return len(want & have) / len(want) if want else 0.0


def pick(entries: list[Entry], want: Want | None) -> list[Entry]:
    """From a folder of several games, the files named for this one. A folder whose files name no
    game we can tell apart is taken whole only when it is small enough to be one pack."""
    if not want or len(entries) <= 1:
        return entries
    title = _key(want.title)
    serials = [_key(s) for s in want.serials]
    named = [e for e in entries if (len(title) >= 4 and title in _key(e.name))
             or any(s and s in _key(e.name) for s in serials)]
    if named:
        return named
    # Spelled differently ("Chou Aniki" for "Cho Aniki", a subtitle left out): the one file sharing
    # most of the title's words, if it clearly beats the rest.
    scored = sorted(((_overlap(want.title, e.name), i) for i, e in enumerate(entries)), reverse=True)
    if scored[0][0] >= 0.6 and scored[0][0] > scored[1][0]:
        return [entries[scored[0][1]]]
    archives = [e for e in entries if ARCHIVE_NAME.search(e.name)]
    if len(archives) > 3 and len({re.sub(r"\.(part\d+|\d+)$", "", Path(a.name).stem) for a in archives}) > 3:
        raise Unsupported(f"a folder of {len(archives)} archives, none named for {want.title!r}")
    return entries


def list_link(url: str, want: Want | None = None) -> list[Entry]:
    host = urllib.parse.urlparse(url).netloc.lower()
    fn = next((fn for pattern, fn in HOSTS if re.search(pattern, host)), None)
    if fn is None:
        raise Unsupported(f"no downloader for {host}")
    entries = pick(fn(url), want)
    if not entries:
        raise Gone(f"{url} holds no files")
    return entries


def fetch(url: str, out: Path, limit: int | None = None, want: Want | None = None) -> list[Path]:
    """Download what the link holds for this pack into `out`. Returns the files."""
    entries = list_link(url, want)
    known = sum(e.size or 0 for e in entries)
    if limit and known > limit:
        raise TooLarge(f"{url}: {known} bytes, more than {limit}")
    out.mkdir(parents=True, exist_ok=True)
    for e in entries:
        e.get(out / e.name if e.name else out, limit)
    files = [f for f in out.rglob("*") if f.is_file()]
    if not files:
        raise RuntimeError(f"{url}: nothing was downloaded")
    return files
