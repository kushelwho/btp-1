#!/usr/bin/env python3
"""
Minimal HTML -> DOCX converter (Python stdlib only).

Built for the report HTML in this directory: headings, paragraphs, tables,
lists, preformatted blocks, page breaks, and a bordered logo placeholder.
Not a general-purpose converter -- it handles the subset of HTML used here.

Usage:  python3 html2docx.py mse-report.html mse-report.docx
"""

import sys
import zipfile
from html.parser import HTMLParser
from xml.sax.saxutils import escape

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

# ---------------------------------------------------------------- docx parts

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def core_xml(title, authors):
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>{escape(title)}</dc:title><dc:creator>{escape(authors)}</dc:creator>
<cp:lastModifiedBy>{escape(authors)}</cp:lastModifiedBy></cp:coreProperties>"""


APP_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
<Application>html2docx</Application></Properties>"""


def _style(sid, name, size_half_pt, bold, italic, before, after,
           outline=None, based_on="Normal"):
    o = f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else ""
    b = '<w:b/>' if bold else ""
    i = '<w:i/>' if italic else ""
    return (
        f'<w:style w:type="paragraph" w:styleId="{sid}">'
        f'<w:name w:val="{name}"/><w:basedOn w:val="{based_on}"/>'
        f'<w:pPr><w:keepNext/><w:spacing w:before="{before}" w:after="{after}"/>'
        f'<w:jc w:val="left"/>{o}</w:pPr>'
        f'<w:rPr>{b}{i}<w:sz w:val="{size_half_pt}"/><w:szCs w:val="{size_half_pt}"/></w:rPr>'
        f'</w:style>'
    )


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W}>
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
<w:name w:val="Normal"/><w:pPr><w:jc w:val="both"/></w:pPr></w:style>
{_style("Heading1", "heading 1", 32, True, False, 480, 240, 0)}
{_style("Heading2", "heading 2", 28, True, False, 360, 160, 1)}
{_style("Heading3", "heading 3", 24, True, True, 280, 120, 2)}
<w:style w:type="paragraph" w:styleId="Caption">
<w:name w:val="caption"/><w:basedOn w:val="Normal"/>
<w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="240"/></w:pPr>
<w:rPr><w:i/><w:sz w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code">
<w:name w:val="HTML Preformatted"/><w:basedOn w:val="Normal"/>
<w:pPr><w:jc w:val="left"/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
<w:ind w:left="180"/></w:pPr>
<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="17"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>
<w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:color="000000"/><w:left w:val="single" w:sz="4" w:color="000000"/>
<w:bottom w:val="single" w:sz="4" w:color="000000"/><w:right w:val="single" w:sz="4" w:color="000000"/>
<w:insideH w:val="single" w:sz="4" w:color="000000"/><w:insideV w:val="single" w:sz="4" w:color="000000"/>
</w:tblBorders></w:tblPr></w:style>
</w:styles>"""

SECT = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1701" '
        'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr>')


# ---------------------------------------------------------------- converter

class Converter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.runs = []           # pending runs for current paragraph
        self.bold = 0
        self.ital = 0
        self.tag = None          # current block tag
        self.cls = ""            # class of current block
        self.align = None        # forced alignment (title page)
        self.in_body = False
        self.skip = 0            # inside <head>/<style>
        self.swallow = 0         # inside a swallowed div
        self.pre = False
        self.list_type = None
        self.list_n = 0
        # table state
        self.tbl = None
        self.row = None
        self.cell = None

    # ---- helpers

    def run(self, text, bold=False, ital=False, mono=False):
        if not text:
            return ""
        rpr = ""
        if bold or self.bold:
            rpr += "<w:b/>"
        if ital or self.ital:
            rpr += "<w:i/>"
        if mono:
            rpr += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="17"/>'
        rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
        return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'

    def para(self, runs, style=None, align=None, ind=0, size=None, spacing=None):
        ppr = ""
        if style:
            ppr += f'<w:pStyle w:val="{style}"/>'
        if ind:
            ppr += f'<w:ind w:left="{ind}"/>'
        if spacing:
            ppr += spacing
        if align:
            ppr += f'<w:jc w:val="{align}"/>'
        if size:
            ppr += f'<w:rPr><w:sz w:val="{size}"/></w:rPr>'
        ppr = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
        return f"<w:p>{ppr}{''.join(runs)}</w:p>"

    def emit(self, xml):
        if self.cell is not None:
            self.cell.append(xml)
        else:
            self.out.append(xml)

    def flush(self):
        """Close the current block-level element."""
        if not self.runs:
            self.runs = []
            return
        runs, self.runs = self.runs, []
        t, c = self.tag, self.cls

        if t in ("h1", "h2", "h3"):
            self.emit(self.para(runs, style=f"Heading{t[1]}"))
        elif t == "pre":
            for line in "".join(runs).split(" "):
                self.emit(self.para([line] if line else [], style="Code"))
            self.emit(self.para([], spacing='<w:spacing w:after="160"/>'))
        elif t == "li":
            bullet = f"{self.list_n}." if self.list_type == "ol" else "•"
            self.emit(self.para(
                [self.run(bullet + "  ")] + runs,
                align="both", ind=360,
                spacing='<w:spacing w:after="80"/>'))
        elif c == "caption":
            self.emit(self.para(runs, style="Caption"))
        elif c == "maintitle":
            self.emit(self.para(runs, align="center",
                                size="40",
                                spacing='<w:spacing w:before="480" w:after="360"/>'))
        elif c in ("subtitle", "label", "note"):
            self.emit(self.para(runs, align="center" if self.align else "both",
                                spacing='<w:spacing w:before="200" w:after="120"/>'))
        elif t == "p" and self.align == "center":
            self.emit(self.para(runs, align="center"))
        elif t == "p" and "margin-left" in c:
            self.emit(self.para(runs, align="left", ind=360,
                                spacing='<w:spacing w:after="60"/>'))
        elif t == "p":
            self.emit(self.para(runs, align="both"))
        else:
            self.emit(self.para(runs, align=self.align or "both"))
        self.tag, self.cls = None, ""

    # ---- parser callbacks

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        style = a.get("style", "")

        if tag in ("head", "style"):
            self.skip += 1
            return
        if tag in ("title", "meta", "link"):
            return
        if self.skip or self.swallow:
            return
        if tag == "body":
            self.in_body = True
            return
        if not self.in_body:
            return

        if tag == "div":
            if "pagebreak" in cls:
                self.flush()
                self.emit('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            elif "titlepage" in cls:
                self.align = "center"
            elif "logobox" in cls:
                self.flush()
                self.emit(self._logo_box())
                self.swallow += 1       # swallow the placeholder text
            return

        if tag in ("h1", "h2", "h3", "p", "pre", "li"):
            self.flush()
            self.tag = tag
            self.cls = cls + " " + style
            self.pre = (tag == "pre")
            if tag == "li":
                self.list_n += 1
            return

        if tag in ("ul", "ol"):
            self.flush()
            self.list_type = tag
            self.list_n = 0
            return

        if tag in ("b", "strong"):
            self.bold += 1
            return
        if tag in ("i", "em"):
            self.ital += 1
            return

        if tag == "table":
            self.flush()
            self.tbl = {"rows": [], "widths": None}
            return
        if tag == "tr" and self.tbl is not None:
            self.row = []
            return
        if tag in ("td", "th") and self.row is not None:
            self.cell = []
            self.cell_header = (tag == "th")
            self.cell_w = self._width(style)
            return

    def handle_endtag(self, tag):
        if tag in ("head", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in ("title", "meta", "link"):
            return
        if tag == "div" and self.swallow:
            self.swallow -= 1
            self.runs = []
            return
        if self.skip or self.swallow or not self.in_body:
            return

        if tag in ("h1", "h2", "h3", "p", "pre", "li"):
            self.flush()
            self.pre = False
        elif tag in ("ul", "ol"):
            self.flush()
            self.list_type = None
        elif tag in ("b", "strong"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("i", "em"):
            self.ital = max(0, self.ital - 1)
        elif tag == "div":
            self.flush()
            self.align = None
        elif tag in ("td", "th"):
            self.flush()
            self.row.append((self.cell, self.cell_header, self.cell_w))
            self.cell = None
        elif tag == "tr":
            self.tbl["rows"].append(self.row)
            self.row = None
        elif tag == "table":
            self.out.append(self._table_xml(self.tbl))
            self.tbl = None

    def handle_data(self, data):
        if self.skip or self.swallow or not self.in_body:
            return
        if self.pre:
            self.runs.append(" ".join(
                self.run(ln, mono=True) for ln in data.strip("\n").split("\n")))
            return
        text = " ".join(data.split())
        if not text:
            return
        if self.tag is None and self.cell is None:
            return
        if self.runs and not self.runs[-1].endswith(">"):
            pass
        self.runs.append(self.run((" " if self.runs and data[:1].isspace() else "") + text))

    # ---- builders

    @staticmethod
    def _width(style):
        if "width:" in style:
            try:
                return int(float(style.split("width:")[1].split("%")[0].strip()) * 50)
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def _logo_box():
        cell = ('<w:tc><w:tcPr><w:tcW w:w="2600" w:type="dxa"/>'
                '<w:tcBorders>'
                '<w:top w:val="dashed" w:sz="6" w:color="808080"/>'
                '<w:left w:val="dashed" w:sz="6" w:color="808080"/>'
                '<w:bottom w:val="dashed" w:sz="6" w:color="808080"/>'
                '<w:right w:val="dashed" w:sz="6" w:color="808080"/>'
                '</w:tcBorders><w:vAlign w:val="center"/></w:tcPr>'
                '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="1200" w:after="1200"/></w:pPr>'
                '<w:r><w:rPr><w:sz w:val="18"/><w:color w:val="808080"/></w:rPr>'
                '<w:t xml:space="preserve">[ INSERT NSUT LOGO HERE ]</w:t></w:r></w:p>'
                '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="1200"/></w:pPr>'
                '<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="808080"/></w:rPr>'
                '<w:t xml:space="preserve">Replace this box with the official logo</w:t>'
                '</w:r></w:p></w:tc>')
        return ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
                '<w:tblW w:w="2600" w:type="dxa"/><w:jc w:val="center"/>'
                '<w:tblBorders>'
                '<w:top w:val="dashed" w:sz="6" w:color="808080"/>'
                '<w:left w:val="dashed" w:sz="6" w:color="808080"/>'
                '<w:bottom w:val="dashed" w:sz="6" w:color="808080"/>'
                '<w:right w:val="dashed" w:sz="6" w:color="808080"/>'
                '</w:tblBorders></w:tblPr>'
                f'<w:tblGrid><w:gridCol w:w="2600"/></w:tblGrid>'
                f'<w:tr>{cell}</w:tr></w:tbl>'
                '<w:p><w:pPr><w:spacing w:after="0"/></w:pPr></w:p>')

    def _table_xml(self, tbl):
        rows = tbl["rows"]
        if not rows:
            return ""
        ncol = max(len(r) for r in rows)
        widths = [w for (_, _, w) in rows[0]] if rows else []
        total = 9060
        if not widths or any(w is None for w in widths):
            widths = [total // ncol] * ncol
        else:
            scale = total / sum(widths)
            widths = [int(w * scale) for w in widths]

        grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
        body = []
        for r in rows:
            cells = []
            for idx, (content, is_hdr, _) in enumerate(r):
                w = widths[idx] if idx < len(widths) else widths[-1]
                shade = ('<w:shd w:val="clear" w:color="auto" w:fill="E8E8E8"/>'
                         if is_hdr else "")
                paras = "".join(content) or "<w:p/>"
                paras = paras.replace(
                    "<w:p>",
                    '<w:p><w:pPr><w:jc w:val="left"/>'
                    '<w:spacing w:before="40" w:after="40"/>'
                    '<w:rPr><w:sz w:val="20"/></w:rPr></w:pPr>', 1)
                paras = paras.replace('<w:pPr><w:jc w:val="both"/></w:pPr>', "")
                cells.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shade}</w:tcPr>'
                    f'{paras}</w:tc>')
            hdr = '<w:trPr><w:tblHeader/></w:trPr>' if any(h for (_, h, _) in r) else ""
            body.append(f"<w:tr>{hdr}{''.join(cells)}</w:tr>")

        return ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
                '<w:tblW w:w="5000" w:type="pct"/>'
                '<w:tblLayout w:type="fixed"/></w:tblPr>'
                f'<w:tblGrid>{grid}</w:tblGrid>{"".join(body)}</w:tbl>'
                '<w:p><w:pPr><w:spacing w:after="0"/></w:pPr></w:p>')

    def document(self):
        self.flush()
        # tables written at top level land in self.out already
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document {W}><w:body>{"".join(self.out)}{SECT}</w:body></w:document>')


def convert(src, dst, title, authors):
    conv = Converter()
    conv.feed(open(src, encoding="utf-8").read())
    doc = conv.document()

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("docProps/core.xml", core_xml(title, authors))
        z.writestr("docProps/app.xml", APP_XML)
    return len(doc)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "mse-report.html"
    dst = sys.argv[2] if len(sys.argv) > 2 else "mse-report.docx"
    n = convert(
        src, dst,
        "Type-Routed Claim Verification for Hallucination-Resistant "
        "Long-Form Research Synthesis",
        "Krish Garg; Kanishka Yadav; Kushel Rohilla",
    )
    print(f"wrote {dst} ({n:,} bytes of document.xml)")
