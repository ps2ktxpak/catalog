"""Shared helpers: paths, YAML and JSON I/O, name normalisation, vocabulary maps."""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = ROOT / "cache"
DIST = ROOT / "dist"
SCHEMA_DIR = ROOT / "schema"

CREATORS_DIR = DATA / "creators"
PACKS_DIR = DATA / "packs"
ARCHIVES_DIR = DATA / "archives"
LISTINGS_FILE = DATA / "listings" / "sad-origami-ps2.jsonl"
RESOLUTION_DIR = DATA / "resolution"
MATCHES_FILE = DATA / "links" / "listing-pack.jsonl"
CORRECTIONS_FILE = DATA / "overrides" / "hand-corrections.yaml"
TITLE_ALIASES_FILE = DATA / "overrides" / "title-aliases.yaml"

USER_AGENT = "ps2ktxpak/0.1 (+https://github.com/ARMSX2; texture pack catalog tooling)"


# ---- YAML and JSON -------------------------------------------------------------------------------

class _Loader(yaml.SafeLoader):
    """SafeLoader that leaves 2026-10-03 as a string, so dates round-trip and validate as text."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):  # no &anchors in files people edit by hand
        return True


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=_Loader)


def dump_yaml(obj) -> str:
    return yaml.dump(obj, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False, width=1000)


def write_yaml(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(obj), encoding="utf-8")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj, *, indent=2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def ordered(rec: dict, order: list[str], keep: tuple[str, ...] = ()) -> dict:
    """rec with its keys in `order` first (unknown keys after), and empty values dropped, except
    for the keys in `keep`, where empty is a statement ("no one is credited"), not an absence."""
    def drop(k, v):
        return v in (None, "", [], {}) and k not in keep
    out = {k: rec[k] for k in order if k in rec and not drop(k, rec[k])}
    out.update({k: v for k, v in rec.items() if k not in out and not drop(k, v)})
    return out


def today() -> str:
    return datetime.date.today().isoformat()


# ---- names and titles ----------------------------------------------------------------------------

def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


def name_key(s: str) -> str:
    """A creator name reduced to what must match: lower-case letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def title_key(t: str) -> str:
    """A game title reduced to what must match: no accents, 'the', punctuation or case."""
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " and ")
    t = re.sub(r"\bthe\b", " ", t)
    return re.sub(r"[^a-z0-9]", "", t)


ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii"}


def numbers_in(title: str) -> set[str]:
    """Numbers in a title, arabic or roman: two titles that differ only here are different games."""
    return {w for w in re.findall(r"[a-z]+|\d+", title.lower()) if w.isdigit() or w in ROMAN}


def sha1_short(text: str, n: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def region_of_serial(serial: str) -> str | None:
    p = serial[:4]
    if p in ("SLUS", "SCUS", "SLUD", "SCUD"):
        return "NTSC-U"
    if p in ("SLES", "SCES", "SCED", "SLED"):
        return "PAL"
    if p in ("SLPS", "SLPM", "SCPS", "SCAJ", "SLAJ", "SCPM", "SLPN"):
        return "NTSC-J"
    if p in ("SLKA", "SCKA"):
        return "NTSC-K"
    return None


# ---- URLs ----------------------------------------------------------------------------------------

def https(url: str | None) -> str | None:
    """The link as https, or None. Nothing else is ever opened or stored."""
    if not url:
        return None
    url = url.strip()
    if url.lower().startswith("http://"):
        url = "https://" + url[7:]
    return url if url.lower().startswith("https://") and " " not in url else None


def host_of(url: str) -> str:
    return re.sub(r"^www\.", "", urlparse(url).netloc.lower())


def _host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


_LINK_KINDS = [
    ("gbatemp.net", "gbatemp"), ("youtube.com", "youtube"), ("youtu.be", "youtube"),
    ("patreon.com", "patreon"), ("ko-fi.com", "kofi"), ("github.com", "github"),
    ("discord.gg", "discord"), ("discord.com", "discord"), ("twitter.com", "x"), ("x.com", "x"),
    ("bsky.app", "bluesky"), ("facebook.com", "facebook"), ("twitch.tv", "twitch"),
    ("paypal.com", "paypal"), ("paypal.me", "paypal"), ("buymeacoffee.com", "buymeacoffee"),
    ("mediafire.com", "mediafire"),
]


def link_kind(url: str) -> str:
    """Kind label for a creator's tip or social link."""
    h = host_of(url)
    for domain, kind in _LINK_KINDS:
        if _host_is(h, domain):
            return kind
    return "website"


def source_kind(url: str) -> str:
    """Kind of a pack's source page."""
    h, path = host_of(url), urlparse(url).path
    if _host_is(h, "gbatemp.net"):
        return "forum_thread" if "/threads/" in path else "creator_page"
    if _host_is(h, "ko-fi.com") and path.startswith("/s/"):
        return "shop"
    if any(_host_is(h, d) for d in ("patreon.com", "ko-fi.com")):
        return "creator_page"
    if _host_is(h, "github.com"):
        return "repository"
    if any(_host_is(h, d) for d in ("archive.org", "mediafire.com", "4pda.to")):
        return "mirror"
    if _host_is(h, "youtube.com") or _host_is(h, "youtu.be"):
        return "video"
    return "other"


_DOWNLOAD_HOSTS = {
    "drive.google.com": "gdrive", "docs.google.com": "gdrive", "drive.usercontent.google.com": "gdrive",
    "mega.nz": "mega", "mega.co.nz": "mega", "mediafire.com": "mediafire",
    "1024terabox.com": "terabox", "terabox.com": "terabox", "teraboxapp.com": "terabox",
    "dropbox.com": "dropbox", "github.com": "github", "archive.org": "archive_org",
    "pixeldrain.com": "pixeldrain", "gofile.io": "gofile", "ko-fi.com": "kofi", "patreon.com": "patreon",
    "youtube.com": "youtube", "youtu.be": "youtube", "discord.gg": "discord", "discord.com": "discord",
    "imgur.com": "imgur",
}


def classify_link(url: str) -> tuple[str, str]:
    """(host, kind) for a link found in a thread: where the file lives and what the link points at."""
    h, path, frag = host_of(url), urlparse(url).path, urlparse(url).fragment
    host = next((v for d, v in _DOWNLOAD_HOSTS.items() if _host_is(h, d)), "other")
    kind = "unknown"
    if host == "gdrive":
        kind = "folder" if "/folders/" in path else "file" if ("/file/" in path or "/uc" in path or "/open" in path) else "unknown"
    elif host == "mega":
        kind = "folder" if ("/folder/" in path or frag.startswith("F!")) else "file" if ("/file/" in path or frag.startswith("!")) else "unknown"
    elif host == "kofi":
        kind = "shop" if path.startswith("/s/") else "page"
    elif host in ("github",):
        kind = "file" if "/releases/" in path or "/archive/" in path else "page"
    elif host in ("mediafire", "dropbox", "pixeldrain", "gofile", "terabox", "archive_org"):
        kind = "folder" if ("folder" in path or "/folder" in url) else "file"
    elif host == "patreon":
        kind = "page"
    return host, kind


# ---- vocabulary: the sheet's wording -> our enums -------------------------------------------------

TYPE_MAP = {
    "ai upscale": "ai_upscale", "handcrafted": "handcrafted", "mixed": "mixed", "port": "port",
    "button replacement": "button_replacement", "unknown": "unknown",
}
TYPE_LABEL = {
    "ai_upscale": "AI Upscale", "handcrafted": "Handcrafted", "mixed": "Mixed", "port": "Port",
    "button_replacement": "Button Replacement", "unknown": "Unknown",
}
STATUS_MAP = {
    "complete": "complete", "completed": "complete", "in-progress": "in_progress",
    "incomplete": "incomplete", "partial": "partial", "unknown": "unknown", "tbd": "unknown",
    "tba": "unknown", "": "unknown",
}
STATUS_LABEL = {
    "complete": "Complete", "in_progress": "In-Progress", "incomplete": "Incomplete",
    "partial": "Partial", "unknown": "Unknown",
}
REGION_MAP = {
    "ntsc-u": ["NTSC-U"], "pal": ["PAL"], "ntsc-j": ["NTSC-J"], "ntsc-k": ["NTSC-K"],
    "ntsc/pal": ["NTSC-U", "PAL"], "multi": ["multi"], "all": ["multi"],
}


def norm_type(raw: str) -> str:
    return TYPE_MAP.get((raw or "").strip().lower(), "unknown")


def norm_status(raw: str) -> str:
    return STATUS_MAP.get((raw or "").strip().lower(), "unknown")


def norm_regions(raw: str) -> list[str]:
    return list(REGION_MAP.get((raw or "").strip().lower(), []))


def access_from_restriction(raw: str) -> dict:
    """The sheet's Restriction column as {cost, restriction_raw[, host_hint]}.

    Cost is what the public pays at the creator's own distribution point. It says nothing about
    whether we may host a copy: that is `permission` on the pack."""
    r = (raw or "").strip().lower()
    cost = {"paywall": "paid", "ads": "free_with_ads", "n/a": "free", "mega": "free", "telegram": "free"}.get(r, "unknown")
    out = {"cost": cost, "restriction_raw": (raw or "").strip()}
    if r in ("mega", "telegram"):
        out["host_hint"] = r
    return out


def parse_size_bytes(text: str) -> int | None:
    m = re.match(r"\s*([\d.,]+)\s*(KB|MB|GB|TB)\b", text or "", re.I)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return int(n * {"kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}[m.group(2).lower()])
