"""Build a tiny .xlsx by hand, with the features the real sheet uses: shared strings, a banner row
above the header, and hyperlinks on cells."""
import zipfile
from xml.sax.saxutils import escape

BANNER = "- Free Mirrors now require a login -"


def build(path, tab, header, rows, links=None):
    """header and rows are lists of cell text (None = empty cell); row 1 is a banner, row 2 the header,
    data from row 3. links: {'C3': 'https://...'} puts a hyperlink on that cell."""
    links = links or {}
    strings: list[str] = []

    def sid(text):
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def col(i):
        return chr(65 + i)

    cells_xml = []
    for r, row in enumerate([[BANNER], header] + rows, start=1):
        cs = "".join(f'<c r="{col(c)}{r}" t="s"><v>{sid(t)}</v></c>' for c, t in enumerate(row) if t is not None)
        cells_xml.append(f'<row r="{r}">{cs}</row>')

    rels = "".join(f'<Relationship Id="rId{i + 1}" Type="hyperlink" Target="{escape(u)}" TargetMode="External"/>'
                   for i, u in enumerate(links.values()))
    hl = "".join(f'<hyperlink ref="{ref}" r:id="rId{i + 1}"/>' for i, ref in enumerate(links))
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
             'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
             f'<sheetData>{"".join(cells_xml)}</sheetData>' + (f"<hyperlinks>{hl}</hyperlinks>" if hl else "") + "</worksheet>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets><sheet name="{tab}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        if rels:
            z.writestr("xl/worksheets/_rels/sheet1.xml.rels",
                       '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       + rels + "</Relationships>")
    return path
