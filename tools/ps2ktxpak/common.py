"""Shared helpers: paths, YAML and JSON I/O, and the labels the compiled catalog uses."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DIST = ROOT / "dist"
SCHEMA_DIR = ROOT / "schema"

CREATORS_DIR = DATA / "creators"
PACKS_DIR = DATA / "packs"


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



# ---- URLs ----------------------------------------------------------------------------------------

def host_of(url: str) -> str:
    return re.sub(r"^www\.", "", urlparse(url).netloc.lower())


# ---- labels the compiled catalog uses for the pack's type and completeness ------------------------

TYPE_LABEL = {
    "ai_upscale": "AI Upscale", "handcrafted": "Handcrafted", "mixed": "Mixed", "port": "Port",
    "button_replacement": "Button Replacement", "unknown": "Unknown",
}
STATUS_LABEL = {
    "complete": "Complete", "in_progress": "In-Progress", "incomplete": "Incomplete",
    "partial": "Partial", "unknown": "Unknown",
}
