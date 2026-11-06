"""不依赖第三方库的 DOCX 导入/导出。

导入是“尽力识别”：读取段落、表格文字，按常见区域标题切分，再映射到
model.py 的白名单字段。复杂排版（分栏、图形、文本框）无法完整还原，
但姓名、联系方式、教育/工作/项目经历、技能、奖项、自我评价等常见内容
可以被提取出来继续编辑。
"""

from __future__ import annotations

import re
import posixpath
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from . import photo
from .model import (
    BASIC_FIELDS,
    ITEM_FIELDS,
    PAPERS,
    SECTION_TITLES,
    blank_resume,
    empty_item,
    get_section,
    section_has_content,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


# ---------------------------------------------------------------------------
# 导入：DOCX -> 段落
# ---------------------------------------------------------------------------


@dataclass
class Paragraph:
    text: str
    bold: bool = False
    size: float = 0.0
    style: str = ""
    bullet: bool = False
    align: str = ""


@dataclass
class ImportResult:
    resume: dict
    warnings: list[str] = field(default_factory=list)


@dataclass
class _PProps:
    bold: bool = False
    size: float = 0.0
    style: str = ""
    bullet: bool = False
    align: str = ""


def _paragraph_text(paragraph: ET.Element) -> str:
    pieces: list[str] = []
    for node in paragraph.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t" and node.text:
            pieces.append(node.text)
        elif tag == "tab":
            pieces.append("\t")
        elif tag in {"br", "cr"}:
            pieces.append("\n")
    return "".join(pieces)


def _paragraph_props(paragraph: ET.Element) -> _PProps:
    props = _PProps()
    ppr = paragraph.find("w:pPr", NS)
    if ppr is not None:
        style = ppr.find("w:pStyle", NS)
        if style is not None:
            props.style = style.get(f"{{{W_NS}}}val", "")
        if ppr.find("w:numPr", NS) is not None:
            props.bullet = True
        jc = ppr.find("w:jc", NS)
        if jc is not None:
            props.align = jc.get(f"{{{W_NS}}}val", "")

    sizes: list[float] = []
    for run in paragraph.findall("w:r", NS):
        rpr = run.find("w:rPr", NS)
        if rpr is None:
            continue
        bold = rpr.find("w:b", NS)
        if bold is not None:
            value = bold.get(f"{{{W_NS}}}val", "true").lower()
            if value not in {"0", "false", "off"}:
                props.bold = True
        sz = rpr.find("w:sz", NS)
        if sz is not None:
            try:
                sizes.append(float(sz.get(f"{{{W_NS}}}val", "0")) / 2.0)
            except ValueError:
                pass
    if sizes:
        props.size = max(sizes)
    if props.style.lower().startswith(("heading", "标题")):
        props.bold = True
        props.bullet = False
    return props


def _paragraph_from_element(paragraph: ET.Element) -> Paragraph:
    props = _paragraph_props(paragraph)
    text = _paragraph_text(paragraph)
    stripped = text.strip()
    is_bullet = props.bullet or bool(re.match(r"^\s*[•●▪◦·*]\s+", stripped))
    return Paragraph(
        text=text,
        bold=props.bold,
        size=props.size,
        style=props.style,
        bullet=is_bullet,
        align=props.align,
    )


def _cell_text(cell: ET.Element) -> str:
    lines = []
    for paragraph in cell.findall(".//w:p", NS):
        text = _paragraph_text(paragraph).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _table_paragraphs(table: ET.Element) -> list[Paragraph]:
    """把表格转换成段落。

    基本信息表格常是“姓名 | 张三 | 电话 | 138...”的形式，这里把相邻的
    标签/值配成“姓名：张三 | 电话：138...”，方便后续识别。
    """
    result: list[Paragraph] = []
    labels = set(_BASIC_LABEL_MAP)
    for row in table.findall("w:tr", NS):
        cells = [_cell_text(tc).strip() for tc in row.findall("w:tc", NS)]
        cells = [c for c in cells if c]
        if not cells:
            continue
        has_basic_label = any(c.rstrip("：:") in labels for c in cells)
        if has_basic_label:
            pieces: list[str] = []
            i = 0
            while i < len(cells):
                if i + 1 < len(cells) and cells[i].rstrip("：:") in labels:
                    pieces.append(f"{cells[i].rstrip('：:')}：{cells[i + 1]}")
                    i += 2
                else:
                    pieces.append(cells[i])
                    i += 1
            result.append(Paragraph(text=" | ".join(pieces)))
        else:
            for cell in cells:
                for line in cell.splitlines():
                    if line.strip():
                        result.append(Paragraph(text=line.strip()))
    return result


def read_docx_paragraphs(path: str | Path) -> list[Paragraph]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("不是有效的 .docx 文件：缺少 word/document.xml") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("无法读取该文件，旧版 .doc 请先另存为 .docx。") from exc

    root = ET.fromstring(xml)
    body = root.find("w:body", NS)
    if body is None:
        return []
    paragraphs: list[Paragraph] = []
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraphs.append(_paragraph_from_element(child))
        elif tag == "tbl":
            paragraphs.extend(_table_paragraphs(child))
    return paragraphs


# ---------------------------------------------------------------------------
# 导入：段落 -> 结构化简历
# ---------------------------------------------------------------------------

_SECTION_ALIASES = {
    "basic": ["基本信息", "个人信息", "联系方式", "个人资料", "基本资料"],
    "education": ["教育经历", "教育背景", "学习经历", "学历背景", "教育"],
    "work": [
        "工作经历",
        "工作经验",
        "职业经历",
        "工作履历",
        "实习经历",
        "工作与实习经历",
        "实习与工作经历",
    ],
    "projects": ["项目经历", "项目经验", "项目实践", "项目"],
    "skills": ["专业技能", "技能特长", "个人技能", "技能清单", "技能"],
    "awards": ["获奖情况", "获奖荣誉", "荣誉奖项", "荣誉证书", "所获奖励", "奖项"],
    "self_eval": ["自我评价", "个人评价", "自我总结", "个人简介", "自我介绍", "个人优势"],
}

_ALIAS_TO_TYPE: dict[str, str] = {}
for _type, _aliases in _SECTION_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_TYPE[_alias] = _type

_HEADING_PREFIX_RE = re.compile(r"^[\s#一二三四五六七八九十0-9.、（）()【】\[\]-]+")

_BASIC_LABEL_MAP = {
    "姓名": "name",
    "名字": "name",
    "求职意向": "job",
    "目标职位": "job",
    "期望职位": "job",
    "应聘职位": "job",
    "意向岗位": "job",
    "电话": "phone",
    "手机": "phone",
    "手机号": "phone",
    "手机号码": "phone",
    "联系电话": "phone",
    "邮箱": "email",
    "电子邮箱": "email",
    "e-mail": "email",
    "email": "email",
    "所在城市": "city",
    "城市": "city",
    "现居": "city",
    "现居地": "city",
    "所在地": "city",
    "地址": "city",
    "个人网站": "website",
    "网站": "website",
    "作品集": "website",
    "主页": "website",
    "博客": "website",
    "github": "website",
}

_BASIC_LABEL_RE = re.compile(
    "(" + "|".join(re.escape(k) for k in sorted(_BASIC_LABEL_MAP, key=len, reverse=True)) + r")\s*[：:]\s*",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d(?:[-\s]?\d){8}(?!\d)")
_URL_RE = re.compile(r"(?i)(?:https?://|www\.|github\.com/|gitee\.com/)[^\s|，,；;]+")
_DATE_TOKEN_RE = re.compile(r"(?:19|20)\d{2}(?:\s*[./年\-]\s*\d{1,2})?(?:\s*月)?")
_DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN_RE.pattern})\s*(?:-|–|—|~|～|至|到|to)\s*"
    rf"(?P<end>{_DATE_TOKEN_RE.pattern}|至今|现在|今|present)",
    re.IGNORECASE,
)
_SINGLE_DATE_RE = re.compile(_DATE_TOKEN_RE.pattern)
_DEGREE_RE = re.compile(r"博士|硕士|研究生|本科|学士|大专|专科|高中|中专|MBA|EMBA", re.I)


def _normalize_heading(text: str) -> str:
    text = text.strip().replace("\u3000", " ")
    text = _HEADING_PREFIX_RE.sub("", text)
    text = re.sub(r"[\s:：]+$", "", text)
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def _detect_heading(paragraph: Paragraph) -> str | None:
    raw = paragraph.text.strip()
    if not raw or len(raw) > 32:
        return None
    normalized = _normalize_heading(raw)
    for alias, section_type in _ALIAS_TO_TYPE.items():
        alias_norm = alias.casefold()
        if normalized == alias_norm:
            return section_type
        if normalized.startswith(alias_norm):
            tail = normalized[len(alias_norm) :]
            # 允许“教育经历 EDUCATION”“工作经历（选填）”这类标题，
            # 但不允许“项目负责人”之类的内容被误判成“项目”标题。
            if tail and (
                re.fullmatch(r"[a-z\s·&/()（）\[\]-]+", tail)
                or tail in {"（选填）", "(选填)", "（必填）", "(必填)"}
            ):
                return section_type
    return None


def _clean_date(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"至今|现在|今|present", value, re.I):
        return "至今"
    match = re.search(r"((?:19|20)\d{2})(?:\s*[./年\-]\s*(\d{1,2}))?", value)
    if not match:
        return value
    year = match.group(1)
    month = match.group(2)
    if month:
        return f"{year}.{int(month):02d}"
    return year


def _extract_dates(text: str) -> tuple[str, str, str, str]:
    """返回 (去掉日期后的文字, 开始时间, 结束时间, 单个日期)。"""
    match = _DATE_RANGE_RE.search(text)
    if match:
        start = _clean_date(match.group("start"))
        end = _clean_date(match.group("end"))
        remains = (text[: match.start()] + " " + text[match.end() :]).strip()
        remains = re.sub(r"^[\s|｜·•,，;；\-–—]+|[\s|｜·•,，;；\-–—]+$", "", remains)
        return remains, start, end, ""
    match = _SINGLE_DATE_RE.search(text)
    if match:
        date = _clean_date(match.group(0))
        remains = (text[: match.start()] + " " + text[match.end() :]).strip()
        remains = re.sub(r"^[\s|｜·•,，;；\-–—]+|[\s|｜·•,，;；\-–—]+$", "", remains)
        return remains, "", "", date
    return text.strip(), "", "", ""


def _strip_bullet(text: str) -> str:
    return re.sub(r"^\s*[•●▪◦·*\-–—]\s+", "", text).strip()


def _split_segments(text: str) -> list[str]:
    if re.search(r"\s*[|｜]\s*", text):
        return [part.strip() for part in re.split(r"\s*[|｜]\s*", text) if part.strip()]
    if re.search(r"\s+·\s+", text):
        return [part.strip() for part in re.split(r"\s+·\s+", text) if part.strip()]
    return [text.strip()]


def _parse_basic(paragraphs: list[Paragraph]) -> tuple[dict[str, str], list[str]]:
    data = {key: "" for key, _ in BASIC_FIELDS}
    warnings: list[str] = []

    def assign(key: str, value: str) -> None:
        value = value.strip(" \t|｜")
        if value and not data.get(key):
            data[key] = value

    def unlabeled(value: str) -> None:
        value = value.strip(" \t|｜")
        if not value:
            return
        if not data["email"] and _EMAIL_RE.search(value):
            assign("email", _EMAIL_RE.search(value).group(0))
            value = _EMAIL_RE.sub("", value).strip(" ·|｜,，;；")
        if not data["phone"] and _PHONE_RE.search(value):
            assign("phone", _PHONE_RE.search(value).group(0).strip())
            value = _PHONE_RE.sub("", value).strip(" ·|｜,，;；")
        if not data["website"] and _URL_RE.search(value):
            assign("website", _URL_RE.search(value).group(0).strip(" ·|｜,，;；"))
            value = _URL_RE.sub("", value).strip(" ·|｜,，;；")
        if not value:
            return
        if not data["name"] and 1 <= len(value) <= 20 and not re.search(r"\d|@", value):
            assign("name", value)
        elif not data["job"] and len(value) <= 40:
            assign("job", value)
        elif not data["city"] and re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", value):
            assign("city", value)
        elif value:
            warnings.append(f"基本信息中有一段未识别内容：{value[:28]}")

    for paragraph in paragraphs:
        text = paragraph.text.replace("\t", " ").strip()
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            segments = _split_segments(line)
            for segment in segments:
                parts = _BASIC_LABEL_RE.split(segment)
                leading = parts[0].strip(" ·|｜,，;；")
                if leading:
                    unlabeled(leading)
                index = 1
                while index + 1 < len(parts):
                    label = parts[index].casefold()
                    value = parts[index + 1].strip()
                    if label == "联系方式":
                        unlabeled(value)
                    else:
                        key = _BASIC_LABEL_MAP.get(label)
                        if key:
                            assign(key, value)
                        elif value:
                            unlabeled(value)
                    index += 2
    return data, warnings


def _new_item(section_type: str) -> dict[str, str]:
    return empty_item(section_type)


def _parse_header_parts(
    section_type: str, title: str, subtitle: str = ""
) -> dict[str, str]:
    item = _new_item(section_type)
    if section_type == "work":
        parts = [p.strip() for p in re.split(r"\s*[|｜]\s*", title) if p.strip()]
        item["company"] = parts[0] if parts else title
        if len(parts) > 1:
            item["position"] = parts[1]
    elif section_type == "education":
        parts = [p.strip() for p in re.split(r"\s*[|｜·]\s*", title) if p.strip()]
        item["school"] = parts[0] if parts else title
        for part in parts[1:]:
            if _DEGREE_RE.search(part):
                item["degree"] = _DEGREE_RE.search(part).group(0)
            elif not item["major"]:
                item["major"] = part
    elif section_type == "projects":
        parts = [p.strip() for p in re.split(r"\s*[|｜]\s*", title) if p.strip()]
        item["name"] = parts[0] if parts else title
        if len(parts) > 1:
            item["role"] = parts[1]
    else:
        item["title"] = title
    if subtitle:
        _apply_subtitle(item, section_type, subtitle)
    return item


def _apply_subtitle(item: dict[str, str], section_type: str, subtitle: str) -> bool:
    subtitle = subtitle.strip()
    if not subtitle:
        return False
    if section_type == "work":
        if not item.get("position") and len(subtitle) <= 40:
            item["position"] = subtitle
            return True
    elif section_type == "education":
        parts = [p.strip() for p in re.split(r"\s*[|｜·]\s*", subtitle) if p.strip()]
        consumed = False
        for part in parts:
            degree_match = _DEGREE_RE.search(part)
            if degree_match and not item.get("degree"):
                item["degree"] = degree_match.group(0)
                consumed = True
            elif not item.get("major") and len(part) <= 40:
                item["major"] = part
                consumed = True
        return consumed
    elif section_type == "projects":
        if not item.get("role") and len(subtitle) <= 40:
            item["role"] = subtitle
            return True
    elif section_type == "awards":
        if not item.get("issuer") and len(subtitle) <= 50:
            item["issuer"] = subtitle
            return True
    return False


def _entry_has_body(item: dict[str, str]) -> bool:
    return bool((item.get("details") or item.get("detail") or "").strip())


def _parse_entry_section(
    paragraphs: list[Paragraph], section_type: str
) -> tuple[list[dict[str, str]], list[str]]:
    entries: list[dict[str, str]] = []
    warnings: list[str] = []
    current: dict[str, str] | None = None
    after_blank = False

    def start(title: str = "", subtitle: str = "") -> dict[str, str]:
        item = _parse_header_parts(section_type, title, subtitle)
        entries.append(item)
        return item

    def add_detail(item: dict[str, str], text: str) -> None:
        text = _strip_bullet(text).strip()
        if not text:
            return
        if section_type == "awards":
            old = item.get("detail", "")
            item["detail"] = f"{old}；{text}" if old else text
        else:
            old = item.get("details", "")
            item["details"] = f"{old}\n{text}" if old else text

    for paragraph in paragraphs:
        raw = paragraph.text.replace("\t", " ").strip()
        if not raw:
            after_blank = True
            continue
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        for line in lines:
            is_bullet = paragraph.bullet or bool(
                re.match(r"^\s*[•●▪◦·*\-–—]\s+", line)
            )
            raw_line = _strip_bullet(line) if is_bullet else line.strip()
            if is_bullet:
                cleaned_no_date = raw_line
                start_date = end_date = single_date = ""
                has_range = False
            else:
                cleaned_no_date, start_date, end_date, single_date = _extract_dates(line)
                cleaned_no_date = _strip_bullet(cleaned_no_date)
                has_range = bool(start_date or end_date)

            date_only = (
                not is_bullet
                and not cleaned_no_date
                and bool(has_range or single_date)
            )
            if date_only:
                if current is not None:
                    if section_type == "awards":
                        if not current.get("date"):
                            current["date"] = single_date or "/".join(
                                p for p in (start_date, end_date) if p
                            )
                    else:
                        if start_date:
                            current["start"] = start_date
                        if end_date:
                            current["end"] = end_date
                        elif single_date and not current.get("start"):
                            current["start"] = single_date
                continue

            bold_header = (
                paragraph.bold
                and not is_bullet
                and len(cleaned_no_date) <= 60
                and bool(cleaned_no_date)
            )
            likely_header = False
            if has_range:
                likely_header = True
            elif bold_header:
                likely_header = True
            elif (
                after_blank
                and current is not None
                and _entry_has_body(current)
                and not is_bullet
                and len(raw_line) <= 50
            ):
                likely_header = True

            if likely_header:
                header_text = (
                    cleaned_no_date
                    if (has_range or (bold_header and single_date))
                    else raw_line
                )
                current = start(header_text)
                if section_type == "awards":
                    current["date"] = single_date or (
                        f"{start_date} – {end_date}" if start_date or end_date else ""
                    )
                else:
                    current["start"] = start_date
                    current["end"] = end_date
                    if not start_date and single_date:
                        current["start"] = single_date
                after_blank = False
                continue

            if current is None:
                current = start(raw_line if not is_bullet and len(raw_line) <= 60 else "")
                if section_type == "awards" and single_date:
                    current["date"] = single_date
                if raw_line and is_bullet:
                    add_detail(current, raw_line)
                after_blank = False
                continue

            if section_type == "awards" and single_date and not current.get("date"):
                if not _entry_has_body(current) and len(cleaned_no_date) <= 50:
                    current["date"] = single_date
                    if cleaned_no_date and _apply_subtitle(
                        current, section_type, cleaned_no_date
                    ):
                        after_blank = False
                        continue

            if (
                not is_bullet
                and not _entry_has_body(current)
                and len(raw_line) <= 50
                and _apply_subtitle(current, section_type, raw_line)
            ):
                after_blank = False
                continue

            add_detail(current, raw_line)
            after_blank = False

    # 如果一个条目也没识别出来，但区域里有文字，则保留为一组“未命名条目”。
    if not entries:
        fallback_lines = [
            _strip_bullet(p.text)
            for p in paragraphs
            if p.text.strip()
        ]
        if fallback_lines:
            item = _new_item(section_type)
            if section_type == "awards":
                item["title"] = fallback_lines[0]
                if len(fallback_lines) > 1:
                    item["detail"] = "；".join(fallback_lines[1:])
            else:
                item["details"] = "\n".join(fallback_lines)
            entries.append(item)
            warnings.append(
                f"“{SECTION_TITLES[section_type]}”未能识别条目结构，已保留为一条记录。"
            )
    return entries, warnings


def _parse_skills(paragraphs: list[Paragraph]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for paragraph in paragraphs:
        for line in paragraph.text.splitlines():
            line = _strip_bullet(line)
            if not line:
                continue
            parts = re.split(r"\s*[：:]\s*", line, maxsplit=1)
            if len(parts) == 2 and 0 < len(parts[0]) <= 20:
                items.append({"name": parts[0].strip(), "detail": parts[1].strip()})
            else:
                items.append({"name": "", "detail": line})
    return items


def _parse_self_eval(paragraphs: list[Paragraph]) -> str:
    pieces: list[str] = []
    for paragraph in paragraphs:
        text = paragraph.text.strip()
        if text:
            pieces.append(text)
    return "\n".join(pieces)


def paragraphs_to_resume(paragraphs: list[Paragraph]) -> ImportResult:
    resume = blank_resume()
    warnings: list[str] = []
    buckets: dict[str, list[Paragraph]] = {t: [] for t in SECTION_TITLES}
    current_type: str | None = None

    for paragraph in paragraphs:
        if not paragraph.text.strip():
            if current_type:
                buckets[current_type].append(Paragraph(text=""))
            continue
        heading = _detect_heading(paragraph)
        if heading:
            current_type = heading
            continue
        target = current_type or "basic"
        buckets[target].append(paragraph)

    basic = get_section(resume, "basic")
    basic_data, basic_warnings = _parse_basic(buckets["basic"])
    basic["data"] = basic_data
    warnings.extend(basic_warnings)

    for section_type in ("education", "work", "projects", "awards"):
        items, item_warnings = _parse_entry_section(buckets[section_type], section_type)
        get_section(resume, section_type)["data"]["items"] = items
        warnings.extend(item_warnings)

    skill_items = _parse_skills(buckets["skills"])
    get_section(resume, "skills")["data"]["items"] = skill_items

    self_eval = _parse_self_eval(buckets["self_eval"])
    get_section(resume, "self_eval")["data"]["content"] = self_eval

    # 空区域在预览中本来就不会绘制，保留 visible=True，
    # 这样用户新增第一条内容后马上能看到效果。
    if not any(section_has_content(s) for s in resume["sections"]):
        raise ValueError(
            "没有从文件中识别出可编辑内容。请确认文件包含“教育经历 / 工作经历 / 项目经历”等常见区域标题。"
        )

    if not basic_data["name"]:
        warnings.append("没有识别到姓名，可在“基本信息”中手动填写。")
    return ImportResult(resume=resume, warnings=list(dict.fromkeys(warnings)))


def _extract_docx_photo(path: str | Path) -> tuple[str, list[str]]:
    """从 Word 中提取唯一的竖版图片作为个人照片。

    只在文档恰好引用一张图片、且图片为竖版时自动采用，避免把公司 logo
    或装饰图误当成头像。多张图片时不自动选择，只给出提示。
    """
    if not photo.HAS_PIL:
        return "", []
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                return "", []
            document = ET.fromstring(archive.read("word/document.xml"))
            rels_name = "word/_rels/document.xml.rels"
            rel_map: dict[str, str] = {}
            if rels_name in names:
                rels = ET.fromstring(archive.read(rels_name))
                for rel in rels.findall(f"{{{rel_ns}}}Relationship"):
                    if (rel.get("Type") or "").endswith("/image"):
                        rel_map[rel.get("Id", "")] = rel.get("Target", "")
            used: list[str] = []
            for node in document.iter():
                if not node.tag.endswith("}blip"):
                    continue
                rel_id = node.get(f"{{{r_ns}}}embed")
                if rel_id and rel_id not in used:
                    used.append(rel_id)
            if not used:
                return "", []
            if len(used) > 1:
                return "", ["文档中包含多张图片，未自动设置个人照片。"]
            target = rel_map.get(used[0], "")
            if not target:
                return "", []
            if target.startswith("/"):
                part_name = target.lstrip("/")
            else:
                part_name = posixpath.normpath(posixpath.join("word", target))
            if part_name not in names:
                return "", []
            raw = archive.read(part_name)
    except Exception:
        return "", []

    size = photo.image_dimensions(raw)
    if size is None:
        return "", []
    width, height = size
    if height < 100 or height < width * 1.05:
        return "", ["文档中的图片不是竖版，未自动设置为个人照片。"]
    try:
        return photo.encode_photo_bytes(raw), []
    except Exception:
        return "", ["文档中的图片无法转换为个人照片。"]


def import_docx(path: str | Path) -> ImportResult:
    result = paragraphs_to_resume(read_docx_paragraphs(path))
    photo_data, photo_warnings = _extract_docx_photo(path)
    if photo_data:
        get_section(result.resume, "basic")["data"][photo.PHOTO_KEY] = photo_data
    if photo_warnings:
        result.warnings = list(
            dict.fromkeys(result.warnings + photo_warnings)
        )
    return result


def import_txt(path: str | Path) -> ImportResult:
    raw = Path(path).read_bytes()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("无法识别文本编码，请将文件保存为 UTF-8 后重试。")
    paragraphs = []
    for line in text.splitlines():
        stripped = line.strip()
        is_bullet = bool(re.match(r"^\s*[•●▪◦·*\-–—]\s+", stripped))
        paragraphs.append(Paragraph(text=line.rstrip(), bullet=is_bullet))
    return paragraphs_to_resume(paragraphs)


# ---------------------------------------------------------------------------
# 导出：结构化简历 -> DOCX
# ---------------------------------------------------------------------------

_TWIPS_PER_MM = 56.692913

_STYLES_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Microsoft YaHei UI" w:hAnsi="Microsoft YaHei UI" w:eastAsia="Microsoft YaHei UI" w:cs="Microsoft YaHei UI"/>
        <w:sz w:val="21"/><w:szCs w:val="21"/>
        <w:lang w:val="en-US" w:eastAsia="zh-CN"/>
      </w:rPr>
    </w:rPrDefault>
    <w:pPrDefault>
      <w:pPr><w:spacing w:line="276" w:lineRule="auto"/></w:pPr>
    </w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:qFormat/>
    <w:pPr><w:spacing w:line="276" w:lineRule="auto"/></w:pPr>
    <w:rPr>
      <w:rFonts w:ascii="Microsoft YaHei UI" w:hAnsi="Microsoft YaHei UI" w:eastAsia="Microsoft YaHei UI"/>
      <w:sz w:val="21"/><w:szCs w:val="21"/>
    </w:rPr>
  </w:style>
</w:styles>
"""


def _xml_text(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _twips(mm: float) -> int:
    return max(0, round(mm * _TWIPS_PER_MM))


def _line_value(spacing: float) -> int:
    return max(240, round(240 * spacing))


def _run_xml(
    text: str,
    *,
    size: float,
    font: str,
    color: str,
    bold: bool = False,
    tab: bool = False,
) -> str:
    if not text and not tab:
        return ""
    font_xml = _xml_text(font)
    color_hex = color.lstrip("#") or "253044"
    props = [
        f'<w:rFonts w:ascii="{font_xml}" w:hAnsi="{font_xml}" w:eastAsia="{font_xml}" w:cs="{font_xml}"/>'
    ]
    if bold:
        props.append("<w:b/><w:bCs/>")
    props.append(f'<w:color w:val="{color_hex}"/>')
    half = max(2, round(size * 2))
    props.append(f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>')
    body = ""
    if text:
        body += f'<w:t xml:space="preserve">{_xml_text(text)}</w:t>'
    if tab:
        body += "<w:tab/>"
    return f"<w:r><w:rPr>{''.join(props)}</w:rPr>{body}</w:r>"


def _border_xml(kind: str, color: str) -> str:
    color_hex = color.lstrip("#")
    if kind == "rule":
        return (
            "<w:pBdr>"
            f'<w:bottom w:val="single" w:sz="6" w:space="3" w:color="{color_hex}"/>'
            "</w:pBdr>"
        )
    if kind == "bar":
        return (
            "<w:pBdr>"
            f'<w:left w:val="single" w:sz="18" w:space="6" w:color="{color_hex}"/>'
            "</w:pBdr>"
        )
    return ""


def _p_xml(
    runs: list[dict],
    *,
    font: str,
    align: str = "left",
    before: float = 0,
    after: float = 0,
    line: float = 1.35,
    keep_next: bool = False,
    border: str = "none",
    border_color: str = "#1D4ED8",
    indent_twips: int = 0,
    hanging_twips: int = 0,
    tab_pos: int | None = None,
) -> str:
    ppr: list[str] = []
    if keep_next:
        ppr.append("<w:keepNext/>")
    if border and border != "none":
        ppr.append(_border_xml(border, border_color))
    if tab_pos is not None:
        ppr.append(
            '<w:tabs><w:tab w:val="right" w:pos="'
            + str(max(1, tab_pos))
            + '"/></w:tabs>'
        )
    ppr.append(
        f'<w:spacing w:before="{_twips(before)}" w:after="{_twips(after)}" '
        f'w:line="{_line_value(line)}" w:lineRule="auto"/>'
    )
    if indent_twips or hanging_twips:
        ppr.append(
            f'<w:ind w:left="{indent_twips}" w:hanging="{hanging_twips}"/>'
        )
    if align in {"left", "center", "right", "both"}:
        ppr.append(f'<w:jc w:val="{align}"/>')

    run_xml = []
    for run in runs:
        run_xml.append(
            _run_xml(
                run.get("text", ""),
                size=run.get("size", 10.5),
                font=run.get("font", font),
                color=run.get("color", "#253044"),
                bold=run.get("bold", False),
                tab=run.get("tab", False),
            )
        )
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{''.join(run_xml)}</w:p>"


def _style_context(resume: dict, section: dict) -> tuple[str, str, str]:
    theme = resume["theme"]
    style = section["style"]
    font = style.get("font") or theme["font"]
    accent = theme["accent"]
    text_color = theme["text_color"]
    muted = theme["muted_color"]
    return font, accent, text_color if not muted else text_color


def _contact_line(data: dict[str, str]) -> str:
    return "  ·  ".join(
        data.get(key, "").strip()
        for key in ("phone", "email", "city", "website")
        if data.get(key, "").strip()
    )


def _section_heading_xml(
    resume: dict,
    section: dict,
    *,
    is_first: bool = False,
) -> str:
    theme = resume["theme"]
    style = section["style"]
    font, accent, text_color = _style_context(resume, section)
    title_color = accent
    return _p_xml(
        [
            {
                "text": section["title"],
                "size": style["title_size"],
                "font": font,
                "color": title_color,
                "bold": style["title_bold"],
            }
        ],
        font=font,
        align="left",
        before=0 if is_first else style["gap"],
        after=1.2,
        line=1.05,
        keep_next=True,
        border=style["decoration"],
        border_color=theme["line_color"] if style["decoration"] == "rule" else accent,
        indent_twips=120 if style["decoration"] == "bar" else 0,
    )


def _entry_header_xml(
    resume: dict,
    section: dict,
    left: str,
    dates: str,
    *,
    before: float = 2.0,
) -> str:
    theme = resume["theme"]
    style = section["style"]
    font, accent, text_color = _style_context(resume, section)
    page = resume["page"]
    content_width_mm = PAPERS[page["paper"]][0] - page["margin_left"] - page["margin_right"]
    runs: list[dict] = [
        {
            "text": left,
            "size": style["body_size"] + 1.0,
            "font": font,
            "color": text_color,
            "bold": True,
        }
    ]
    if dates:
        runs.extend(
            [
                {
                    "text": "",
                    "size": style["body_size"],
                    "font": font,
                    "color": theme["muted_color"],
                    "tab": True,
                },
                {
                    "text": dates,
                    "size": style["body_size"],
                    "font": font,
                    "color": theme["muted_color"],
                },
            ]
        )
    return _p_xml(
        runs,
        font=font,
        align=style["align"],
        before=before,
        after=0.8,
        line=1.2,
        keep_next=True,
        tab_pos=_twips(content_width_mm) if dates else None,
    )


def _subtitle_xml(resume: dict, section: dict, text: str) -> str:
    if not text.strip():
        return ""
    style = section["style"]
    font, accent, text_color = _style_context(resume, section)
    return _p_xml(
        [
            {
                "text": text,
                "size": style["body_size"],
                "font": font,
                "color": resume["theme"]["muted_color"],
            }
        ],
        font=font,
        align=style["align"],
        after=0.8,
        line=style["line_spacing"],
    )


def _bullet_xml(
    resume: dict,
    section: dict,
    text: str,
    *,
    first: bool = True,
    label: str = "",
) -> str:
    if not text.strip() and not label.strip():
        return ""
    style = section["style"]
    font, accent, text_color = _style_context(resume, section)
    runs: list[dict] = [
        {
            "text": "• ",
            "size": style["body_size"],
            "font": font,
            "color": accent,
            "bold": False,
        }
    ]
    if label:
        runs.append(
            {
                "text": label + "：",
                "size": style["body_size"],
                "font": font,
                "color": text_color,
                "bold": True,
            }
        )
    if text:
        runs.append(
            {
                "text": text,
                "size": style["body_size"],
                "font": font,
                "color": text_color,
            }
        )
    return _p_xml(
        runs,
        font=font,
        align=style["align"],
        before=0.8 if first else 0,
        after=0,
        line=style["line_spacing"],
        indent_twips=300,
        hanging_twips=180,
    )


def _paragraph_xml(resume: dict, section: dict, text: str) -> str:
    if not text.strip():
        return ""
    style = section["style"]
    font, accent, text_color = _style_context(resume, section)
    return _p_xml(
        [
            {
                "text": text,
                "size": style["body_size"],
                "font": font,
                "color": text_color,
            }
        ],
        font=font,
        align=style["align"],
        after=0.8,
        line=style["line_spacing"],
    )


PHOTO_REL_ID = "rIdPhoto"
_EMU_PER_MM = 36000


def _photo_drawing_xml() -> str:
    cx = round(photo.PHOTO_WIDTH_MM * _EMU_PER_MM)
    cy = round(photo.PHOTO_HEIGHT_MM * _EMU_PER_MM)
    return (
        "<w:drawing>"
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:docPr id="1" name="个人照片"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic>"
        '<pic:nvPicPr><pic:cNvPr id="1" name="photo.jpg"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{PHOTO_REL_ID}"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
    )


def _basic_text_xml(
    resume: dict, section: dict, *, compact: bool = False
) -> str:
    style = section["style"]
    font, accent, text_color = _style_context(resume, section)
    theme = resume["theme"]
    data = section["data"]
    pieces: list[str] = []
    name = data.get("name", "").strip()
    job = data.get("job", "").strip()
    contact = _contact_line(data)
    if name:
        pieces.append(
            _p_xml(
                [
                    {
                        "text": name,
                        "size": style["title_size"],
                        "font": font,
                        "color": text_color,
                        "bold": True,
                    }
                ],
                font=font,
                align=style["align"],
                after=0.6,
                line=1.05,
            )
        )
    if job:
        pieces.append(
            _p_xml(
                [
                    {
                        "text": job,
                        "size": style["body_size"] + 1.0,
                        "font": font,
                        "color": accent,
                        "bold": True,
                    }
                ],
                font=font,
                align=style["align"],
                after=0.8,
                line=1.15,
            )
        )
    if contact:
        pieces.append(
            _p_xml(
                [
                    {
                        "text": contact,
                        "size": style["body_size"],
                        "font": font,
                        "color": theme["muted_color"],
                    }
                ],
                font=font,
                align=style["align"],
                after=0 if compact else style["gap"],
                line=1.25,
            )
        )
    return "".join(pieces)


def _basic_table_xml(resume: dict, section: dict) -> str:
    page = resume["page"]
    content_width = (
        PAPERS[page["paper"]][0] - page["margin_left"] - page["margin_right"]
    )
    photo_width = min(photo.PHOTO_WIDTH_MM, content_width * 0.42)
    left_width = max(30.0, content_width - photo_width)
    total_tw = _twips(left_width + photo_width)
    left_tw = _twips(left_width)
    photo_tw = _twips(photo_width)
    gap_tw = _twips(photo.PHOTO_GAP_MM)
    text_xml = _basic_text_xml(resume, section, compact=True) or "<w:p/>"
    photo_xml = (
        '<w:p><w:pPr><w:spacing w:before="0" w:after="0" '
        'w:line="240" w:lineRule="auto"/><w:jc w:val="right"/></w:pPr>'
        f"<w:r>{_photo_drawing_xml()}</w:r></w:p>"
    )
    return (
        "<w:tbl>"
        "<w:tblPr>"
        f'<w:tblW w:w="{total_tw}" w:type="dxa"/>'
        "<w:tblBorders>"
        '<w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/>'
        '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/>'
        "</w:tblBorders>"
        '<w:tblLayout w:type="fixed"/>'
        "<w:tblCellMar>"
        '<w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/>'
        "</w:tblCellMar>"
        "</w:tblPr>"
        f'<w:tblGrid><w:gridCol w:w="{left_tw}"/><w:gridCol w:w="{photo_tw}"/></w:tblGrid>'
        "<w:tr><w:trPr><w:cantSplit/></w:trPr>"
        "<w:tc><w:tcPr>"
        f'<w:tcW w:w="{left_tw}" w:type="dxa"/>'
        f'<w:tcMar><w:right w:w="{gap_tw}" w:type="dxa"/></w:tcMar>'
        '<w:vAlign w:val="top"/></w:tcPr>'
        f"{text_xml}</w:tc>"
        "<w:tc><w:tcPr>"
        f'<w:tcW w:w="{photo_tw}" w:type="dxa"/>'
        '<w:vAlign w:val="top"/></w:tcPr>'
        f"{photo_xml}</w:tc>"
        "</w:tr></w:tbl>"
    )


def _section_xml(resume: dict, section: dict, *, is_first: bool) -> str:
    style = section["style"]
    if not style.get("visible", True) or not section_has_content(section):
        return ""
    font, accent, text_color = _style_context(resume, section)
    page = resume["page"]
    theme = resume["theme"]
    section_type = section["type"]
    data = section["data"]
    pieces: list[str] = []

    if section_type == "basic":
        if style.get("show_heading"):
            pieces.append(_section_heading_xml(resume, section, is_first=is_first))
        if photo.docx_payload(data.get(photo.PHOTO_KEY, "")):
            pieces.append(_basic_table_xml(resume, section))
        else:
            pieces.append(_basic_text_xml(resume, section))
        return "".join(pieces)

    if not style.get("show_heading", True) and section_type != "basic":
        # 当前版本区域标题默认显示；保留这个分支便于以后扩展。
        pass
    pieces.append(_section_heading_xml(resume, section, is_first=is_first))

    if section_type in {"education", "work", "projects"}:
        for index, item in enumerate(section["data"].get("items", [])):
            if not any(str(v).strip() for v in item.values()):
                continue
            if section_type == "education":
                left = item.get("school", "")
                subtitle_parts = [
                    item.get("major", "").strip(),
                    item.get("degree", "").strip(),
                ]
                subtitle = "  ·  ".join(p for p in subtitle_parts if p)
            elif section_type == "work":
                left = item.get("company", "")
                subtitle = item.get("position", "")
            else:
                left = item.get("name", "")
                subtitle = item.get("role", "")
            start = item.get("start", "").strip()
            end = item.get("end", "").strip()
            dates = " – ".join(p for p in (start, end) if p)
            pieces.append(
                _entry_header_xml(
                    resume,
                    section,
                    left or "未命名",
                    dates,
                    before=0 if index == 0 else 2.2,
                )
            )
            pieces.append(_subtitle_xml(resume, section, subtitle))
            details = item.get("details", "")
            for line in details.splitlines():
                line = _strip_bullet(line)
                if line:
                    pieces.append(_bullet_xml(resume, section, line))
        return "".join(pieces)

    if section_type == "skills":
        for item in section["data"].get("items", []):
            name = item.get("name", "").strip()
            detail = item.get("detail", "").strip()
            if name or detail:
                pieces.append(_bullet_xml(resume, section, detail, label=name))
        return "".join(pieces)

    if section_type == "awards":
        for index, item in enumerate(section["data"].get("items", [])):
            title = item.get("title", "").strip()
            if not title:
                continue
            pieces.append(
                _entry_header_xml(
                    resume,
                    section,
                    title,
                    item.get("date", "").strip(),
                    before=0 if index == 0 else 2.2,
                )
            )
            pieces.append(_subtitle_xml(resume, section, item.get("issuer", "").strip()))
            detail = item.get("detail", "").strip()
            if detail:
                pieces.append(_paragraph_xml(resume, section, detail))
        return "".join(pieces)

    if section_type == "self_eval":
        for paragraph in data.get("content", "").split("\n"):
            if paragraph.strip():
                pieces.append(_paragraph_xml(resume, section, paragraph.strip()))
        return "".join(pieces)

    return "".join(pieces)


def _document_xml(resume: dict) -> str:
    page = resume["page"]
    width_mm, height_mm = PAPERS[page["paper"]]
    content = "".join(
        _section_xml(resume, section, is_first=index == 0)
        for index, section in enumerate(resume["sections"])
    )
    sect_pr = (
        "<w:sectPr>"
        f'<w:pgSz w:w="{_twips(width_mm)}" w:h="{_twips(height_mm)}"/>'
        f'<w:pgMar w:top="{_twips(page["margin_top"])}" '
        f'w:right="{_twips(page["margin_right"])}" '
        f'w:bottom="{_twips(page["margin_bottom"])}" '
        f'w:left="{_twips(page["margin_left"])}" '
        'w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f"<w:body>{content}{sect_pr}</w:body></w:document>"
    )


def export_docx(resume: dict, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".docx":
        path = path.with_suffix(".docx")
    document_xml = _document_xml(resume)
    basic_photo = get_section(resume, "basic")["data"].get(photo.PHOTO_KEY, "")
    photo_payload = photo.docx_payload(basic_photo)
    photo_default = ""
    photo_rel = ""
    if photo_payload is not None:
        _, photo_ext, photo_mime = photo_payload
        photo_default = (
            f'  <Default Extension="{photo_ext}" ContentType="{photo_mime}"/>\n'
        )
        photo_rel = (
            f'  <Relationship Id="{PHOTO_REL_ID}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            f'Target="media/photo.{photo_ext}"/>\n'
        )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        f"{photo_default}"
        '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        '  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>\n'
        "</Types>"
    )
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>\n'
        f"{photo_rel}"
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", _STYLES_XML)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        if photo_payload is not None:
            image_bytes, photo_ext, _ = photo_payload
            archive.writestr(f"word/media/photo.{photo_ext}", image_bytes)
    return path
