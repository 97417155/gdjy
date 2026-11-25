# -*- coding: utf-8 -*-
"""报告导出：Markdown -> Word(.docx) / PDF / 可打印 HTML。

三个导出器共用同一套 Markdown 解析，保证"网页里看到的分页"和"导出的文件"一致：
标题层级、引用块、列表、表格逐块映射，每章（## 级标题）另起一页。

Word 走 python-docx，PDF 走 reportlab（嵌入系统中文字体），
两者都装在仓库内 `_pydeps/`；缺失时降级为 HTML + 浏览器打印，
不会因为依赖问题把报告导出整条链路打断。
"""
from __future__ import annotations

import io
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEPS = os.path.join(ROOT, "_pydeps")
if os.path.isdir(DEPS) and DEPS not in sys.path:
    sys.path.insert(0, DEPS)

try:
    from docx import Document                                    # type: ignore
    from docx.enum.table import WD_TABLE_ALIGNMENT               # type: ignore
    from docx.enum.text import WD_ALIGN_PARAGRAPH                # type: ignore
    from docx.oxml import OxmlElement                            # type: ignore
    from docx.oxml.ns import qn                                  # type: ignore
    from docx.shared import Cm, Pt, RGBColor                     # type: ignore
    DOCX_OK = True
except Exception:                                                # noqa: BLE001
    DOCX_OK = False

try:
    from reportlab.lib import colors                             # type: ignore
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT  # type: ignore
    from reportlab.lib.pagesizes import A4                       # type: ignore
    from reportlab.lib.styles import ParagraphStyle              # type: ignore
    from reportlab.lib.units import cm                           # type: ignore
    from reportlab.pdfbase import pdfmetrics                     # type: ignore
    from reportlab.pdfbase.ttfonts import TTFont                 # type: ignore
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,  # type: ignore
                                    Spacer, Table, TableStyle)
    PDF_OK = True
except Exception:                                                # noqa: BLE001
    PDF_OK = False

FONT_FILES = [
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/simsun.ttc", 0),
    ("C:/Windows/Fonts/simhei.ttf", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
]


def capabilities() -> Dict[str, bool]:
    return {"docx": DOCX_OK, "pdf": PDF_OK, "markdown": True, "html": True}


# ---------------------------------------------------------------------------
# Markdown 解析
# ---------------------------------------------------------------------------

Block = Tuple[str, Any]


def parse(markdown: str) -> List[Block]:
    """把报告 Markdown 拆成块：heading / quote / list / table / para。"""
    blocks: List[Block] = []
    lines = str(markdown).replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            blocks.append(("heading", (level, stripped[level:].strip())))
            i += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            rows: List[List[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                raw = lines[i].strip()
                if not re.match(r"^\|[\s\-:|]+\|$", raw):
                    rows.append([c.strip() for c in raw.strip("|").split("|")])
                i += 1
            if rows:
                blocks.append(("table", rows))
            continue
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip("> ").strip())
                i += 1
            blocks.append(("quote", " ".join(buf)))
            continue
        if re.match(r"^[-*]\s+", stripped):
            items = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            blocks.append(("list", items))
            continue
        buf = []
        while i < n and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|\||>|[-*]\s)", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            blocks.append(("para", " ".join(buf)))
    return blocks


def _plain(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def _is_num(text: str) -> bool:
    """数值单元格右对齐，文字列（判断/分公司/责任部门）保持左对齐。"""
    t = text.strip().replace(",", "")
    return bool(t) and bool(re.match(r"^-?\d+(\.\d+)?%?$", t))


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------

def _set_cjk(run, name: str = "微软雅黑") -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _page_field(paragraph, total: bool = False) -> None:
    run = paragraph.add_run()
    if total:
        instr = "NUMPAGES"
    else:
        instr = "PAGE"
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr_el)
    run._r.append(end)
    _set_cjk(run, "宋体")
    run.font.size = Pt(9)


def to_docx(markdown: str, title: str) -> bytes:
    if not DOCX_OK:
        raise RuntimeError("未安装 python-docx，无法导出 Word（pip install python-docx）")

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.4)
    section.top_margin, section.bottom_margin = Cm(2.2), Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(3)

    # 页脚：第 X 页 / 共 Y 页
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer_p.add_run("第 ")
    _set_cjk(run, "宋体")
    run.font.size = Pt(9)
    _page_field(footer_p)
    run = footer_p.add_run(" 页 / 共 ")
    _set_cjk(run, "宋体")
    run.font.size = Pt(9)
    _page_field(footer_p, total=True)
    run = footer_p.add_run(" 页")
    _set_cjk(run, "宋体")
    run.font.size = Pt(9)

    chapter_seen = False
    title_done = False

    def add_para(text: str, size: float = 10.5, indent: bool = True,
                 color: RGBColor | None = None, bold: bool = False) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74) if indent else Cm(0)
        p.paragraph_format.line_spacing = 1.5
        # 处理 **加粗** 片段
        for idx, seg in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
            if not seg:
                continue
            r = p.add_run(seg)
            _set_cjk(r, "宋体")
            r.font.size = Pt(size)
            if idx % 2 == 1 or bold:
                r.bold = True
            if color is not None:
                r.font.color.rgb = color

    for kind, payload in parse(markdown):
        if kind == "heading":
            level, text = payload
            if level == 1:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = p.add_run(text)
                _set_cjk(r, "微软雅黑")
                r.font.size = Pt(18)
                r.bold = True
                p.paragraph_format.space_after = Pt(10)
                title_done = True
                continue
            if chapter_seen:
                doc.add_page_break()          # 每章另起一页（分页）
            chapter_seen = True
            p = doc.add_paragraph()
            r = p.add_run(text)
            _set_cjk(r, "微软雅黑")
            r.font.size = Pt(14)
            r.bold = True
            r.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            continue
        if kind == "quote":
            add_para(_plain(payload), 9, indent=False, color=RGBColor(0x6B, 0x72, 0x80))
            continue
        if kind == "list":
            for item in payload:
                p = doc.add_paragraph(style="List Bullet")
                for idx, seg in enumerate(re.split(r"\*\*(.+?)\*\*", item)):
                    if not seg:
                        continue
                    r = p.add_run(seg)
                    _set_cjk(r, "宋体")
                    r.font.size = Pt(10.5)
                    if idx % 2 == 1:
                        r.bold = True
            continue
        if kind == "table":
            rows = payload
            cols = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=cols)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for ri, row in enumerate(rows):
                for ci in range(cols):
                    cell = table.cell(ri, ci)
                    text = _plain(row[ci]) if ci < len(row) else ""
                    cell.text = ""
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.15
                    if ci > 0 and _is_num(text):
                        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    r = p.add_run(text)
                    _set_cjk(r, "宋体")
                    r.font.size = Pt(9)
                    if ri == 0:
                        r.bold = True
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if ci == 0 else p.alignment
                        shade = OxmlElement("w:shd")
                        shade.set(qn("w:fill"), "EEF3F9")
                        cell._tc.get_or_add_tcPr().append(shade)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            continue
        add_para(payload)

    if not title_done:
        doc.paragraphs[0].insert_paragraph_before(title)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_pdf_fonts: Dict[str, str] = {}


def _register_pdf_fonts() -> Tuple[str, str]:
    """注册中文字体，返回 (常规字体名, 加粗字体名)。"""
    if _pdf_fonts:
        return _pdf_fonts["regular"], _pdf_fonts["bold"]
    regular = bold = None
    for path, index in FONT_FILES:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("CJK", path, subfontIndex=index))
            regular = "CJK"
            break
        except Exception:                                        # noqa: BLE001
            continue
    for path in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if regular and os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CJKBold", path, subfontIndex=0))
                bold = "CJKBold"
                break
            except Exception:                                    # noqa: BLE001
                continue
    if not regular:
        raise RuntimeError("未找到可嵌入的中文字体，无法生成 PDF")
    _pdf_fonts["regular"] = regular
    _pdf_fonts["bold"] = bold or regular
    return _pdf_fonts["regular"], _pdf_fonts["bold"]


def to_pdf(markdown: str, title: str) -> bytes:
    if not PDF_OK:
        raise RuntimeError("未安装 reportlab，无法导出 PDF（pip install reportlab）")
    font, bold = _register_pdf_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=1.9 * cm, bottomMargin=1.9 * cm,
        title=title, author="广东院经营分析系统",
    )
    styles = {
        "title": ParagraphStyle("t", fontName=bold, fontSize=18, leading=26,
                                alignment=TA_CENTER, spaceAfter=12),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=14, leading=20,
                             spaceBefore=6, spaceAfter=8, textColor=colors.HexColor("#1F4E79")),
        "body": ParagraphStyle("b", fontName=font, fontSize=10.5, leading=18,
                               firstLineIndent=21, alignment=TA_JUSTIFY, spaceAfter=4),
        "quote": ParagraphStyle("q", fontName=font, fontSize=9, leading=14,
                                textColor=colors.HexColor("#6B7280"), spaceAfter=6),
        "bullet": ParagraphStyle("li", fontName=font, fontSize=10.5, leading=17,
                                 leftIndent=12, bulletIndent=2, spaceAfter=2),
        "cell": ParagraphStyle("c", fontName=font, fontSize=8.6, leading=12),
        "cellr": ParagraphStyle("cr", fontName=font, fontSize=8.6, leading=12, alignment=TA_RIGHT),
        "cellh": ParagraphStyle("ch", fontName=bold, fontSize=8.8, leading=12,
                                alignment=TA_CENTER),
    }

    story: List[Any] = []
    chapter_seen = False
    for kind, payload in parse(markdown):
        if kind == "heading":
            level, text = payload
            if level == 1:
                story.append(Paragraph(escape(text), styles["title"]))
                continue
            if chapter_seen:
                story.append(PageBreak())
            chapter_seen = True
            story.append(Paragraph(escape(text), styles["h2"]))
            continue
        if kind == "quote":
            story.append(Paragraph(escape(_plain(payload)), styles["quote"]))
            continue
        if kind == "list":
            for item in payload:
                story.append(Paragraph(escape(_plain(item)), styles["bullet"],
                                       bulletText="•"))
            story.append(Spacer(1, 4))
            continue
        if kind == "table":
            rows = payload
            data: List[List[Any]] = []
            for ri, row in enumerate(rows):
                line = []
                for ci, cell in enumerate(row):
                    if ri == 0:
                        style = styles["cellh"]
                    elif ci > 0 and _is_num(_plain(cell)):
                        style = styles["cellr"]
                    else:
                        style = styles["cell"]
                    line.append(Paragraph(escape(_plain(cell)), style))
                data.append(line)
            cols = max(len(r) for r in data)
            avail = doc.width
            first = avail * (0.30 if cols >= 4 else 0.38)
            rest = (avail - first) / max(1, cols - 1)
            widths = [first] + [rest] * (cols - 1)
            table = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D4E0")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF3F9")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(table)
            story.append(Spacer(1, 7))
            continue
        story.append(Paragraph(escape(_plain(payload)), styles["body"]))

    def on_page(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setFont(font, 8.5)
        canvas.setFillColor(colors.HexColor("#8A94A2"))
        canvas.drawCentredString(A4[0] / 2, 1.1 * cm, "第 %d 页" % canvas.getPageNumber())
        canvas.drawRightString(A4[0] - 2.2 * cm, A4[1] - 1.2 * cm,
                               "广东院经营分析报告 · %s" % datetime.now().strftime("%Y-%m-%d"))
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML（无依赖兜底：浏览器打印成 PDF / 直接预览）
# ---------------------------------------------------------------------------

def to_html(markdown: str, title: str) -> str:
    blocks = parse(markdown)

    def inline(text: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escape(text))

    parts: List[str] = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\" />",
        "<title>%s</title>" % escape(title),
        "<style>",
        "@page { size: A4; margin: 20mm 18mm; }",
        "body { font-family: 'Microsoft YaHei', 'PingFang SC', serif; color: #1B2430;",
        "  font-size: 10.5pt; line-height: 1.75; margin: 0 auto; max-width: 780px; padding: 16px; }",
        "h1 { font-size: 19pt; text-align: center; margin: 8px 0 14px; }",
        "h2 { font-size: 14pt; color: #1F4E79; border-bottom: 1px solid #DCE3EB;",
        "  padding-bottom: 5px; margin: 0 0 10px; page-break-before: always; }",
        "h2:first-of-type { page-break-before: avoid; }",
        "blockquote { margin: 8px 0; padding: 7px 11px; background: #F5F8FB;",
        "  border-left: 3px solid #CFDCEB; color: #5A6675; font-size: 9.5pt; }",
        "p { margin: 0 0 7px; text-align: justify; }",
        "ul { margin: 4px 0 8px; padding-left: 20px; }",
        "table { width: 100%; border-collapse: collapse; margin: 8px 0 12px; font-size: 9pt; }",
        "th, td { border: 1px solid #D3DCE6; padding: 4px 7px; }",
        "th { background: #EEF3F9; font-weight: 600; }",
        ".num { text-align: right; }",
        "thead { display: table-header-group; }",
        "tr { page-break-inside: avoid; }",
        ".print-tip { text-align: center; color: #8A94A2; font-size: 9pt; margin: 10px 0 4px; }",
        "@media print { .print-tip { display: none; } }",
        "</style></head><body>",
        "<div class=\"print-tip\">按 Ctrl+P 可另存为 PDF（已按 A4 分页排版）</div>",
    ]
    for kind, payload in blocks:
        if kind == "heading":
            level, text = payload
            parts.append("<h1>%s</h1>" % inline(text) if level == 1
                         else "<h2>%s</h2>" % inline(text))
        elif kind == "quote":
            parts.append("<blockquote>%s</blockquote>" % inline(payload))
        elif kind == "list":
            parts.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(i) for i in payload))
        elif kind == "table":
            rows = payload

            def td(cell: str) -> str:
                cls = ' class="num"' if _is_num(_plain(cell)) else ""
                return "<td%s>%s</td>" % (cls, inline(cell))

            head = "".join("<th%s>%s</th>" % (' class="num"' if _is_num(_plain(c)) else "",
                                            inline(c)) for c in rows[0])
            body = "".join("<tr>%s</tr>" % "".join(td(c) for c in r) for r in rows[1:])
            parts.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>"
                         % (head, body))
        else:
            parts.append("<p>%s</p>" % inline(payload))
    parts.append("</body></html>")
    return "".join(parts)


def export(markdown: str, title: str, fmt: str) -> Tuple[bytes, str, str]:
    """返回 (内容, 文件名, Content-Type)。"""
    stamp = datetime.now().strftime("%Y%m%d")
    base = re.sub(r"[\\/:*?\"<>|]", "_", title)
    if fmt == "docx":
        return (to_docx(markdown, title), "%s_%s.docx" % (base, stamp),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if fmt == "pdf":
        return (to_pdf(markdown, title), "%s_%s.pdf" % (base, stamp), "application/pdf")
    if fmt == "html":
        return (to_html(markdown, title).encode("utf-8"), "%s_%s.html" % (base, stamp),
                "text/html; charset=utf-8")
    return (markdown.encode("utf-8"), "%s_%s.md" % (base, stamp),
            "text/markdown; charset=utf-8")
