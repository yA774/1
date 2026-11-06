"""PDF 导出。

使用 ReportLab 生成矢量文字 PDF，支持中文、主题色、页边距和个人照片。
PDF 会自然分页；预览仍然保持单页提示。
"""

from __future__ import annotations

import os
import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from . import photo
from .model import PAPERS, section_has_content

try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4, LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        HRFlowable,
        Image,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False

_FONT_CACHE: dict[str, tuple[str, str]] = {}
_FONT_FILES = {
    "microsoft yahei": ("msyh.ttc", "msyhbd.ttc"),
    "microsoft yahei ui": ("msyh.ttc", "msyhbd.ttc"),
    "微软雅黑": ("msyh.ttc", "msyhbd.ttc"),
    "simsun": ("simsun.ttc", "simsun.ttc"),
    "宋体": ("simsun.ttc", "simsun.ttc"),
    "simhei": ("simhei.ttf", "simhei.ttf"),
    "黑体": ("simhei.ttf", "simhei.ttf"),
    "dengxian": ("Deng.ttf", "Dengb.ttf"),
    "等线": ("Deng.ttf", "Dengb.ttf"),
    "kaiti": ("simkai.ttf", "simkai.ttf"),
    "楷体": ("simkai.ttf", "simkai.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf"),
    "times new roman": ("times.ttf", "timesbd.ttf"),
    "georgia": ("georgia.ttf", "georgiab.ttf"),
}
_FONT_ALIASES = {"times new roman": "TimesNewRoman", "microsoft yahei ui": "MicrosoftYaHei"}
_ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}


def _font_files_for(name: str) -> tuple[Path, Path] | None:
    folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    key = (name or "").strip().lower()
    candidates = [_FONT_FILES.get(key)]
    if key not in _FONT_FILES:
        candidates.append(_FONT_FILES["microsoft yahei"])
    for entry in candidates:
        if not entry:
            continue
        regular = folder / entry[0]
        bold = folder / entry[1]
        if regular.is_file():
            return regular, bold if bold.is_file() else regular
    return None


def _register_font(theme_font: str) -> tuple[str, str]:
    key = (theme_font or "Microsoft YaHei").strip().lower()
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    files = _font_files_for(theme_font)
    if files:
        regular_path, bold_path = files
        alias = "ResumeFont" + str(len(_FONT_CACHE))
        bold_alias = alias + "-Bold"
        try:
            pdfmetrics.registerFont(
                TTFont(alias, str(regular_path), subfontIndex=0)
            )
            pdfmetrics.registerFont(
                TTFont(bold_alias, str(bold_path), subfontIndex=0)
            )
            pdfmetrics.registerFontFamily(
                alias,
                normal=alias,
                bold=bold_alias,
                italic=alias,
                boldItalic=bold_alias,
            )
            _FONT_CACHE[key] = (alias, bold_alias)
            return alias, bold_alias
        except Exception:
            pass

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdfmetrics.registerFontFamily(
        "ResumeCID",
        normal="STSong-Light",
        bold="STSong-Light",
        italic="STSong-Light",
        boldItalic="STSong-Light",
    )
    _FONT_CACHE[key] = ("ResumeCID", "ResumeCID")
    return "ResumeCID", "ResumeCID"


def _esc(text: str) -> str:
    return xml_escape(str(text or ""))


def _strip_bullet(text: str) -> str:
    return re.sub(r"^\s*[•●▪◦·*\-–—]\s+", "", str(text or "")).strip()


def _hex(value: str, fallback: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        return value.strip()
    return fallback


def _page_background(canvas, doc, color: str) -> None:
    canvas.saveState()
    canvas.setFillColor(HexColor(color))
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], stroke=0, fill=1)
    canvas.restoreState()


def _photo_flowable(data: str, width: float, height: float):
    parsed = photo.parse_data_uri(data)
    if parsed is None:
        return None
    try:
        return Image(BytesIO(parsed[1]), width=width, height=height)
    except Exception:
        return None


def _base_style(
    name: str,
    *,
    font_name: str,
    size: float,
    color: str,
    leading: float | None = None,
    align: str = "left",
    space_before: float = 0,
    space_after: float = 0,
    left_indent: float = 0,
) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName=font_name,
        fontSize=size,
        leading=leading if leading is not None else size * 1.35,
        textColor=HexColor(_hex(color, "#172033")),
        alignment=_ALIGN.get(align, TA_LEFT),
        spaceBefore=space_before,
        spaceAfter=space_after,
        leftIndent=left_indent,
    )


def _fonts(resume: dict, section: dict) -> tuple[str, str]:
    family = section.get("style", {}).get("font") or resume["theme"]["font"]
    return _register_font(family)


def _heading_flowables(resume: dict, section: dict, *, first: bool) -> list:
    style = section["style"]
    theme = resume["theme"]
    font, bold = _fonts(resume, section)
    accent = _hex(theme["accent"], "#1D4ED8")
    title = _esc(section["title"])
    if style.get("decoration") == "bar":
        title = f'<font color="{accent}">▍</font> {title}'
    style_obj = _base_style(
        "Heading" + section["type"],
        font_name=bold if style.get("title_bold", True) else font,
        size=style["title_size"],
        color=accent,
        leading=style["title_size"] * 1.12,
        space_before=0 if first else style["gap"] * mm,
        space_after=0.8 * mm,
    )
    items = [Paragraph(title, style_obj)]
    if style.get("decoration") == "rule":
        items.append(
            HRFlowable(
                width="100%",
                thickness=0.6,
                color=HexColor(_hex(theme["line_color"], "#D7E0EC")),
                spaceBefore=0,
                spaceAfter=1.8 * mm,
            )
        )
    return items


def _no_padding_table(rows: list, widths: list, *, extra: list | None = None) -> Table:
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if extra:
        style.extend(extra)
    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle(style))
    return table


def _basic_flowables(resume: dict, section: dict, *, first: bool) -> list:
    style = section["style"]
    theme = resume["theme"]
    if not style.get("visible", True) or not section_has_content(section):
        return []
    font, bold = _fonts(resume, section)
    align = style["align"]
    accent = _hex(theme["accent"], "#1D4ED8")
    text_color = _hex(theme["text_color"], "#172033")
    muted = _hex(theme["muted_color"], "#667085")
    page = resume["page"]
    content_w = (
        PAPERS[page["paper"]][0] - page["margin_left"] - page["margin_right"]
    ) * mm
    data = section["data"]
    out: list = []
    if style.get("show_heading"):
        out.extend(_heading_flowables(resume, section, first=first))

    name = str(data.get("name", "")).strip()
    job = str(data.get("job", "")).strip()
    contact = "  ·  ".join(
        str(data.get(key, "")).strip()
        for key in ("phone", "email", "city", "website")
        if str(data.get(key, "")).strip()
    )
    name_style = _base_style(
        "BasicName",
        font_name=bold,
        size=style["title_size"],
        color=text_color,
        leading=style["title_size"] * 1.1,
        align=align,
        space_after=0.6 * mm,
    )
    job_style = _base_style(
        "BasicJob",
        font_name=bold,
        size=style["body_size"] + 2,
        color=accent,
        leading=(style["body_size"] + 2) * 1.2,
        align=align,
        space_before=0.4 * mm,
        space_after=0.8 * mm,
    )
    contact_style = _base_style(
        "BasicContact",
        font_name=font,
        size=style["body_size"],
        color=muted,
        leading=style["body_size"] * 1.3,
        align=align,
    )
    text_parts = []
    if name:
        text_parts.append(Paragraph(_esc(name), name_style))
    if job:
        text_parts.append(Paragraph(_esc(job), job_style))
    if contact:
        text_parts.append(Paragraph(_esc(contact), contact_style))

    photo_data = str(data.get(photo.PHOTO_KEY, ""))
    photo_w = photo.PHOTO_WIDTH_MM * mm
    photo_h = photo.PHOTO_HEIGHT_MM * mm
    gap = photo.PHOTO_GAP_MM * mm
    image = _photo_flowable(photo_data, photo_w, photo_h) if photo_data else None
    if image is not None:
        text_w = max(20 * mm, content_w - photo_w - gap)
        inner = _no_padding_table(
            [[part] for part in text_parts] or [[""]],
            [text_w],
        )
        outer = _no_padding_table(
            [[inner, image]],
            [text_w + gap, photo_w],
            extra=[("RIGHTPADDING", (0, 0), (0, 0), gap)],
        )
        out.append(KeepTogether(outer))
    else:
        out.extend(text_parts)
    return out


def _entry_header(resume: dict, section: dict, left: str, dates: str, *, before: float) -> list:
    style = section["style"]
    theme = resume["theme"]
    font, bold = _fonts(resume, section)
    page = resume["page"]
    content_w = (
        PAPERS[page["paper"]][0] - page["margin_left"] - page["margin_right"]
    ) * mm
    left_style = _base_style(
        "EntryLeft",
        font_name=bold,
        size=style["body_size"] + 1,
        color=theme["text_color"],
        leading=(style["body_size"] + 1) * 1.2,
        align="left",
        space_before=before,
    )
    left_para = Paragraph(_esc(left), left_style)
    if not dates:
        return [left_para]
    date_w = min(40 * mm, content_w * 0.35)
    right_style = _base_style(
        "EntryDate",
        font_name=font,
        size=style["body_size"],
        color=theme["muted_color"],
        leading=style["body_size"] * 1.2,
        align="right",
        space_before=before,
    )
    table = _no_padding_table(
        [[left_para, Paragraph(_esc(dates), right_style)]],
        [content_w - date_w, date_w],
    )
    return [table]


def _subtitle(resume: dict, section: dict, text: str) -> list:
    if not text.strip():
        return []
    style = section["style"]
    theme = resume["theme"]
    font, _bold = _fonts(resume, section)
    return [
        Paragraph(
            _esc(text),
            _base_style(
                "Subtitle",
                font_name=font,
                size=style["body_size"],
                color=theme["muted_color"],
                leading=style["body_size"] * 1.35,
                align=style["align"],
                space_after=0.7 * mm,
            ),
        )
    ]


def _bullet(resume: dict, section: dict, text: str, *, label: str = "", before: float = 0.3) -> list:
    if not text.strip() and not label.strip():
        return []
    style = section["style"]
    theme = resume["theme"]
    font, _bold = _fonts(resume, section)
    body = _esc(text)
    if label.strip():
        body = f"<b>{_esc(label)}：</b>{body}"
    body_style = _base_style(
        "Bullet",
        font_name=font,
        size=style["body_size"],
        color=theme["text_color"],
        leading=style["body_size"] * style["line_spacing"],
        align=style["align"],
        space_before=before * mm,
        left_indent=4 * mm,
    )
    body_style.bulletFontName = font
    body_style.bulletFontSize = style["body_size"]
    body_style.bulletColor = HexColor(_hex(theme["accent"], "#1D4ED8"))
    body_style.bulletIndent = 0
    return [Paragraph(body, body_style, bulletText="•")]


def _section_flowables(resume: dict, section: dict, *, first: bool) -> list:
    style = section["style"]
    if not style.get("visible", True) or not section_has_content(section):
        return []
    section_type = section["type"]
    out: list = []
    if section_type == "basic":
        return _basic_flowables(resume, section, first=first)
    if style.get("show_heading", True):
        out.extend(_heading_flowables(resume, section, first=first))
    else:
        out.append(Spacer(1, style["gap"] * mm))

    data = section["data"]
    if section_type in {"education", "work", "projects"}:
        for index, item in enumerate(data.get("items", [])):
            if not any(str(v).strip() for v in item.values()):
                continue
            if section_type == "education":
                left = str(item.get("school", ""))
                subtitle = "  ·  ".join(
                    part
                    for part in (
                        str(item.get("major", "")).strip(),
                        str(item.get("degree", "")).strip(),
                    )
                    if part
                )
            elif section_type == "work":
                left = str(item.get("company", ""))
                subtitle = str(item.get("position", ""))
            else:
                left = str(item.get("name", ""))
                subtitle = str(item.get("role", ""))
            dates = " – ".join(
                part
                for part in (item.get("start", "").strip(), item.get("end", "").strip())
                if part
            )
            header = _entry_header(
                resume,
                section,
                left or "未命名",
                dates,
                before=0 if index == 0 else 2.2 * mm,
            )
            sub = _subtitle(resume, section, subtitle)
            out.append(KeepTogether(header + sub))
            for line in str(item.get("details", "")).splitlines():
                line = _strip_bullet(line)
                if line:
                    out.extend(_bullet(resume, section, line, before=0.2))
        return out

    if section_type == "skills":
        for item in data.get("items", []):
            name = str(item.get("name", "")).strip()
            detail = str(item.get("detail", "")).strip()
            if name or detail:
                out.extend(_bullet(resume, section, detail, label=name, before=0.3))
        return out

    if section_type == "awards":
        for index, item in enumerate(data.get("items", [])):
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            header = _entry_header(
                resume,
                section,
                title,
                str(item.get("date", "")).strip(),
                before=0 if index == 0 else 2.2 * mm,
            )
            issuer = _subtitle(resume, section, str(item.get("issuer", "")).strip())
            out.append(KeepTogether(header + issuer))
            detail = str(item.get("detail", "")).strip()
            if detail:
                font, _bold = _fonts(resume, section)
                out.append(
                    Paragraph(
                        _esc(detail),
                        _base_style(
                            "AwardDetail",
                            font_name=font,
                            size=style["body_size"],
                            color=resume["theme"]["text_color"],
                            leading=style["body_size"] * style["line_spacing"],
                            align=style["align"],
                            space_before=0.3 * mm,
                        ),
                    )
                )
        return out

    if section_type == "self_eval":
        theme = resume["theme"]
        font, _bold = _fonts(resume, section)
        for line in str(data.get("content", "")).splitlines():
            if not line.strip():
                out.append(Spacer(1, style["body_size"] * 0.6))
                continue
            out.append(
                Paragraph(
                    _esc(line.strip()),
                    _base_style(
                        "SelfEval",
                        font_name=font,
                        size=style["body_size"],
                        color=theme["text_color"],
                        leading=style["body_size"] * style["line_spacing"],
                        align=style["align"],
                        space_after=1.2 * mm,
                    ),
                )
            )
        return out
    return out


def export_pdf(resume: dict, path: str | Path) -> Path:
    if not HAS_REPORTLAB:
        raise RuntimeError(
            "PDF 导出需要 ReportLab。请先运行：python -m pip install reportlab"
        )
    target = Path(path)
    if target.suffix.lower() != ".pdf":
        target = target.with_suffix(".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)

    page = resume["page"]
    width_mm, height_mm = PAPERS.get(page["paper"], PAPERS["A4"])
    page_size = (width_mm * mm, height_mm * mm)
    doc = SimpleDocTemplate(
        str(target),
        pagesize=page_size,
        leftMargin=page["margin_left"] * mm,
        rightMargin=page["margin_right"] * mm,
        topMargin=page["margin_top"] * mm,
        bottomMargin=page["margin_bottom"] * mm,
        title=f"{resume.get('sections', [{}])[0].get('data', {}).get('name', '简历')} - 简历",
        author="简历工坊",
    )
    story: list = []
    for index, section in enumerate(resume["sections"]):
        story.extend(_section_flowables(resume, section, first=index == 0))
    if not story:
        story.append(Spacer(1, 1))
    bg = _hex(page.get("background", "#FFFFFF"), "#FFFFFF")
    doc.build(
        story,
        onFirstPage=lambda canvas, doc: _page_background(canvas, doc, bg),
        onLaterPages=lambda canvas, doc: _page_background(canvas, doc, bg),
    )
    return target
