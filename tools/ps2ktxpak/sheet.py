"""Read one tab of an .xlsx by column header, with cell hyperlinks. Standard library only.

The tabs of the Texture Packs Archive do not share a layout (the PS2 tab has no SERIAL column, the
PSOne tab does), so columns are found by their header text, never by position."""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_RID = "{%s}id" % NS["r"]


@dataclass
class Row:
    n: int
    cells: dict[str, tuple[str, str | None]] = field(default_factory=dict)

    def text(self, header: str) -> str:
        return self.cells.get(header, ("", None))[0]

    def link(self, header: str) -> str | None:
        return self.cells.get(header, ("", None))[1]


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _expand(ref: str) -> list[str]:
    """'C3' -> ['C3']; 'C3:C5' -> ['C3', 'C4', 'C5']; a 2-D range is expanded too."""
    if ":" not in ref:
        return [ref]
    a, b = ref.split(":")
    ma, mb = re.match(r"([A-Z]+)(\d+)", a), re.match(r"([A-Z]+)(\d+)", b)
    out = []
    for r in range(int(ma.group(2)), int(mb.group(2)) + 1):
        for c in range(_col(ma.group(1)), _col(mb.group(1)) + 1):
            letters, n = "", c + 1
            while n:
                n, rem = divmod(n - 1, 26)
                letters = chr(65 + rem) + letters
            out.append(f"{letters}{r}")
    return out


def read_tab(xlsx_path, tab: str) -> tuple[list[str], list[Row]]:
    """(headers, rows) for the tab. Headers are upper-cased cell text from the first row that has a
    TITLE cell; rows are every later row, each keyed by header."""
    z = zipfile.ZipFile(xlsx_path)

    def text_of(el):
        return "".join(t.text or "" for t in el.iter("{%s}t" % NS["m"]))

    def rels(path):
        try:
            root = ET.fromstring(z.read(path))
        except KeyError:
            return {}
        return {r.get("Id"): r.get("Target") for r in root.findall("pr:Relationship", NS)}

    shared = [text_of(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)] \
        if "xl/sharedStrings.xml" in z.namelist() else []
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    targets = rels("xl/_rels/workbook.xml.rels")
    sheet = next((s for s in wb.find("m:sheets", NS) if s.get("name") == tab), None)
    if sheet is None:
        raise KeyError(f"no tab named {tab!r}; the workbook has {[s.get('name') for s in wb.find('m:sheets', NS)]}")
    path = "xl/" + targets[sheet.get(_RID)].lstrip("/").removeprefix("xl/")
    root = ET.fromstring(z.read(path))

    links: dict[str, str] = {}
    hl = root.find("m:hyperlinks", NS)
    if hl is not None:
        srels = rels(path.replace("worksheets/", "worksheets/_rels/") + ".rels")
        for h in hl.findall("m:hyperlink", NS):
            if h.get(_RID) in srels:
                for ref in _expand(h.get("ref")):
                    links[ref] = srels[h.get(_RID)]

    raw_rows = []
    for row in root.find("m:sheetData", NS).findall("m:row", NS):
        cells: dict[int, tuple[str, str | None]] = {}
        for c in row.findall("m:c", NS):
            v = c.find("m:v", NS)
            if c.get("t") == "s" and v is not None:
                val = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                val = text_of(c)
            else:
                val = v.text if v is not None else ""
            cells[_col(c.get("r"))] = ((val or "").strip(), links.get(c.get("r")))
        raw_rows.append((int(row.get("r")), cells))

    header_at = next((i for i, (_, cells) in enumerate(raw_rows)
                      if any(t.upper() == "TITLE" for t, _ in cells.values())), None)
    if header_at is None:
        raise ValueError(f"tab {tab!r} has no header row with a TITLE column")
    header_cells = raw_rows[header_at][1]
    headers = {idx: t.upper() for idx, (t, _) in header_cells.items() if t}
    rows = [Row(n, {headers[i]: cell for i, cell in cells.items() if i in headers})
            for n, cells in raw_rows[header_at + 1:]]
    return list(headers.values()), rows
