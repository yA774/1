"""简历数据模型、字段白名单与示例数据。

这个雏形使用“固定区域 + 固定字段”的方式：
- 区域类型固定，区域内的字段也在 SCHEMA 中声明；
- 导入时只接收白名单字段，未知字段会被忽略；
- UI 只根据 schema 生成表单，因此无法在某个区域里塞入其它区域的内容。
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .photo import PHOTO_KEY, normalize_photo

SCHEMA_VERSION = 1
SCHEMA_NAME = "resume-editor/prototype"

PAPERS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
}

SECTION_ORDER = [
    "basic",
    "education",
    "work",
    "projects",
    "skills",
    "awards",
    "self_eval",
]

SECTION_TITLES = {
    "basic": "基本信息",
    "education": "教育经历",
    "work": "工作经历",
    "projects": "项目经历",
    "skills": "专业技能",
    "awards": "获奖荣誉",
    "self_eval": "自我评价",
}

SECTION_ICONS = {
    "basic": "基",
    "education": "教",
    "work": "工",
    "projects": "项",
    "skills": "技",
    "awards": "奖",
    "self_eval": "评",
}

LIST_SECTIONS = ["education", "work", "projects", "skills", "awards"]

# 每个区域允许出现的字段。导入时严格按这个表接收，未声明字段直接丢弃。
BASIC_FIELDS: list[tuple[str, str]] = [
    ("name", "姓名"),
    ("job", "求职意向"),
    ("phone", "电话"),
    ("email", "邮箱"),
    ("city", "所在城市"),
    ("website", "个人网站 / 作品集"),
]

# 基本信息区域除了文本字段，还允许一张竖版个人照片。
BASIC_DATA_KEYS = [key for key, _ in BASIC_FIELDS] + [PHOTO_KEY]

ITEM_FIELDS: dict[str, list[tuple[str, str]]] = {
    "education": [
        ("school", "学校"),
        ("major", "专业"),
        ("degree", "学历"),
        ("start", "开始时间"),
        ("end", "结束时间"),
        ("details", "经历描述"),
    ],
    "work": [
        ("company", "公司"),
        ("position", "职位"),
        ("start", "开始时间"),
        ("end", "结束时间"),
        ("details", "工作内容"),
    ],
    "projects": [
        ("name", "项目名称"),
        ("role", "担任角色"),
        ("start", "开始时间"),
        ("end", "结束时间"),
        ("details", "项目描述"),
    ],
    "skills": [
        ("name", "技能分类"),
        ("detail", "技能详情"),
    ],
    "awards": [
        ("title", "奖项名称"),
        ("issuer", "颁发机构"),
        ("date", "获得时间"),
        ("detail", "补充说明"),
    ],
}

MULTILINE_FIELDS = {
    "details": "每行一条，预览时自动生成项目符号",
    "content": "支持多段文字，换行会保留",
}

FIELD_HINTS = {
    "email": "例如 name@example.com",
    "phone": "例如 138 0000 0000",
    "website": "例如 github.com/yourname",
    "start": "例如 2021.03",
    "end": "例如 2024.06 / 至今",
    "detail": "一句话说明掌握程度",
    "date": "例如 2023.12",
}

ITEM_TITLE_KEYS = {
    "education": "school",
    "work": "company",
    "projects": "name",
    "skills": "name",
    "awards": "title",
}

SECTION_HINTS = {
    "basic": "姓名、联系方式与照片；不混入经历类字段。",
    "education": "仅可填写学校、专业、学历、时间与在校经历。",
    "work": "仅可填写公司、职位、时间与工作内容。",
    "projects": "仅可填写项目名称、角色、时间与项目描述。",
    "skills": "按技能分类填写，每类一条。",
    "awards": "仅可填写奖项、颁发机构、时间与说明。",
    "self_eval": "仅可填写一段自我评价正文。",
}

DEFAULT_STYLE: dict[str, Any] = {
    "font": "",
    "title_size": 13.0,
    "body_size": 10.5,
    "align": "left",
    "line_spacing": 1.35,
    "gap": 4.0,
    "decoration": "rule",
    "title_bold": True,
    "show_heading": True,
    "visible": True,
}

DEFAULT_PAGE: dict[str, Any] = {
    "paper": "A4",
    "margin_top": 16.0,
    "margin_right": 16.0,
    "margin_bottom": 16.0,
    "margin_left": 16.0,
    "background": "#FFFFFF",
}

DEFAULT_THEME: dict[str, Any] = {
    "font": "Microsoft YaHei UI",
    "text_color": "#253044",
    "muted_color": "#667085",
    "accent": "#1D4ED8",
    "line_color": "#D7E0EC",
}

HEX_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------------
# 基础构造
# ---------------------------------------------------------------------------


def _style_for(section_type: str) -> dict[str, Any]:
    style = copy.deepcopy(DEFAULT_STYLE)
    if section_type == "basic":
        style.update(
            {
                "title_size": 25.0,
                "body_size": 10.5,
                "decoration": "none",
                "show_heading": False,
                "gap": 3.0,
            }
        )
    elif section_type == "self_eval":
        style.update({"gap": 2.0})
    return style


def blank_section(section_type: str) -> dict[str, Any]:
    data: dict[str, Any]
    if section_type == "basic":
        data = {key: "" for key in BASIC_DATA_KEYS}
    elif section_type == "self_eval":
        data = {"content": ""}
    else:
        data = {"items": []}
    return {
        "type": section_type,
        "title": SECTION_TITLES[section_type],
        "data": data,
        "style": _style_for(section_type),
    }


def blank_resume() -> dict[str, Any]:
    return {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "page": copy.deepcopy(DEFAULT_PAGE),
        "theme": copy.deepcopy(DEFAULT_THEME),
        "sections": [blank_section(t) for t in SECTION_ORDER],
    }


def empty_item(section_type: str) -> dict[str, str]:
    return {key: "" for key, _ in ITEM_FIELDS[section_type]}


def sample_resume() -> dict[str, Any]:
    resume = blank_resume()
    by_type = {s["type"]: s for s in resume["sections"]}

    by_type["basic"]["data"].update(
        {
            "name": "林清越",
            "job": "高级产品经理 / 数据产品",
            "phone": "138 0013 8000",
            "email": "lin.qingyue@example.com",
            "city": "上海",
            "website": "github.com/qingyue",
        }
    )

    by_type["education"]["data"]["items"] = [
        {
            "school": "复旦大学",
            "major": "信息管理与信息系统",
            "degree": "本科",
            "start": "2016.09",
            "end": "2020.06",
            "details": "主修课程：数据库、统计学、人机交互\nGPA 3.8/4.0，校级优秀毕业生",
        }
    ]

    by_type["work"]["data"]["items"] = [
        {
            "company": "云舟科技",
            "position": "产品经理",
            "start": "2022.03",
            "end": "至今",
            "details": (
                "负责企业数据看板从 0 到 1 的设计与迭代，覆盖 12 个业务线、3,000+ 日活用户\n"
                "通过漏斗分析重构核心流程，关键任务完成率提升 28%\n"
                "协同设计、研发、销售团队，主导 4 次版本发布"
            ),
        }
    ]

    by_type["projects"]["data"]["items"] = [
        {
            "name": "星图数据平台",
            "role": "项目负责人",
            "start": "2023.05",
            "end": "2023.12",
            "details": (
                "定义指标口径与自助分析路径，支持业务团队独立完成 80% 日常取数\n"
                "设计权限与数据质量监控方案，线上数据事故下降 45%"
            ),
        }
    ]

    by_type["skills"]["data"]["items"] = [
        {"name": "产品设计", "detail": "需求分析、用户研究、Figma、Axure"},
        {"name": "数据分析", "detail": "SQL、Python、Tableau、A/B 实验"},
        {"name": "协作沟通", "detail": "跨团队项目推进、英文工作沟通"},
    ]

    by_type["awards"]["data"]["items"] = [
        {
            "title": "年度优秀员工",
            "issuer": "云舟科技",
            "date": "2023.12",
            "detail": "从 600+ 名员工中评选，年度绩效前 5%",
        }
    ]

    by_type["self_eval"]["data"]["content"] = (
        "五年数据产品经验，擅长把模糊的业务问题拆解成可验证的产品方案。"
        "习惯用数据复盘决策，也愿意深入一线理解用户。"
    )

    return resume


# ---------------------------------------------------------------------------
# 规范化与白名单
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(_text(v) for v in value)
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "是"}:
            return True
        if lowered in {"0", "false", "no", "off", "否"}:
            return False
    return default


def _number(value: Any, default: float, low: float, high: float, digits: int = 1) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    number = max(low, min(high, number))
    if digits <= 0:
        return round(number)
    return round(number, digits)


def _color(value: Any, default: str) -> str:
    if isinstance(value, str) and HEX_RE.match(value.strip()):
        color = value.strip()
        if not color.startswith("#"):
            color = "#" + color
        if len(color) == 4:
            color = "#" + "".join(ch * 2 for ch in color[1:])
        return color.upper()
    return default


def _font(value: Any, default: str, allow_inherit: bool = False) -> str:
    if allow_inherit and value in ("", None):
        return ""
    if isinstance(value, str) and value.strip():
        return value.strip()[:100]
    return default


def normalize_style(raw: Any, section_type: str) -> dict[str, Any]:
    style = _style_for(section_type)
    if not isinstance(raw, dict):
        return style
    style["font"] = _font(raw.get("font", ""), "", allow_inherit=True)
    style["title_size"] = _number(raw.get("title_size"), style["title_size"], 9, 40, 1)
    style["body_size"] = _number(raw.get("body_size"), style["body_size"], 7, 20, 1)
    align = raw.get("align", style["align"])
    if align in {"left", "center", "right"}:
        style["align"] = align
    style["line_spacing"] = _number(raw.get("line_spacing"), style["line_spacing"], 1.0, 2.4, 2)
    style["gap"] = _number(raw.get("gap"), style["gap"], 0, 30, 1)
    decoration = raw.get("decoration", style["decoration"])
    if decoration in {"rule", "bar", "none"}:
        style["decoration"] = decoration
    style["title_bold"] = _as_bool(raw.get("title_bold", style["title_bold"]), style["title_bold"])
    style["show_heading"] = _as_bool(raw.get("show_heading", style["show_heading"]), style["show_heading"])
    style["visible"] = _as_bool(raw.get("visible", style["visible"]), style["visible"])
    return style


def normalize_resume(raw: Any, warnings: list[str] | None = None) -> dict[str, Any]:
    """把外部 JSON 规范化为当前 schema。

    只保留白名单字段。返回值始终包含全部固定区域。
    """
    if not isinstance(raw, dict):
        raise ValueError("简历文件格式不正确：顶层应为 JSON 对象。")

    warn = warnings if warnings is not None else []
    base = blank_resume()

    raw_page = raw.get("page")
    if isinstance(raw_page, dict):
        paper = raw_page.get("paper", base["page"]["paper"])
        if paper in PAPERS:
            base["page"]["paper"] = paper
        for key in ("margin_top", "margin_right", "margin_bottom", "margin_left"):
            base["page"][key] = _number(raw_page.get(key), base["page"][key], 5, 40, 1)
        base["page"]["background"] = _color(
            raw_page.get("background"), base["page"]["background"]
        )

    raw_theme = raw.get("theme")
    if isinstance(raw_theme, dict):
        theme = base["theme"]
        theme["font"] = _font(raw_theme.get("font"), theme["font"])
        for key in ("text_color", "muted_color", "accent", "line_color"):
            theme[key] = _color(raw_theme.get(key), theme[key])

    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list):
        warn.append("文件中没有 sections，已载入空白模板。")
        return base

    by_type: dict[str, dict[str, Any]] = {}
    for entry in raw_sections:
        if not isinstance(entry, dict):
            continue
        section_type = entry.get("type")
        if section_type not in SECTION_TITLES:
            warn.append("已忽略未知区域。")
            continue
        if section_type in by_type:
            warn.append(f"“{SECTION_TITLES[section_type]}”区域重复，已保留第一个。")
            continue
        by_type[section_type] = entry

    allowed_types = set(SECTION_TITLES)
    for section_type in allowed_types:
        raw_section = by_type.get(section_type)
        if raw_section is None:
            continue
        target = next(s for s in base["sections"] if s["type"] == section_type)
        target["style"] = normalize_style(raw_section.get("style"), section_type)
        data = raw_section.get("data")
        if not isinstance(data, dict):
            data = raw_section.get("content") if section_type == "self_eval" else None
        if not isinstance(data, dict):
            warn.append(f"“{SECTION_TITLES[section_type]}”缺少 data，已跳过。")
            continue

        if section_type == "basic":
            unknown = set(data) - set(BASIC_DATA_KEYS)
            if unknown:
                warn.append(f"基本信息中已忽略 {len(unknown)} 个非白名单字段。")
            basic_data = {
                key: _text(data.get(key, "")) for key, _ in BASIC_FIELDS
            }
            raw_photo = data.get(PHOTO_KEY, "")
            photo_data = normalize_photo(raw_photo)
            if raw_photo and not photo_data:
                warn.append("个人照片数据无法识别，已移除。")
            basic_data[PHOTO_KEY] = photo_data
            target["data"] = basic_data
        elif section_type == "self_eval":
            if "content" not in data:
                warn.append("自我评价缺少 content。")
            target["data"] = {"content": _text(data.get("content", ""))}
        else:
            raw_items = data.get("items", [])
            if not isinstance(raw_items, list):
                warn.append(f"“{SECTION_TITLES[section_type]}”的 items 不是列表，已清空。")
                raw_items = []
            allowed = [key for key, _ in ITEM_FIELDS[section_type]]
            items: list[dict[str, str]] = []
            for raw_item in raw_items[:50]:
                if not isinstance(raw_item, dict):
                    continue
                unknown = set(raw_item) - set(allowed)
                if unknown:
                    warn.append(
                        f"“{SECTION_TITLES[section_type]}”中已忽略 {len(unknown)} 个非白名单字段。"
                    )
                item = {key: _text(raw_item.get(key, "")) for key in allowed}
                if any(item.values()):
                    items.append(item)
            target["data"] = {"items": items}

    # 合并重复提示，避免导入一个字段很多的文件后弹出几十条。
    if warnings is not None:
        unique = list(dict.fromkeys(warnings))
        warnings[:] = unique
    return base


# ---------------------------------------------------------------------------
# 查询辅助
# ---------------------------------------------------------------------------


def get_section(resume: dict[str, Any], section_type: str) -> dict[str, Any]:
    for section in resume["sections"]:
        if section["type"] == section_type:
            return section
    raise KeyError(section_type)


def section_items(section: dict[str, Any]) -> list[dict[str, str]]:
    return section.get("data", {}).get("items", [])


def section_has_content(section: dict[str, Any]) -> bool:
    section_type = section["type"]
    if section_type == "basic":
        return any(v.strip() for v in section["data"].values())
    if section_type == "self_eval":
        return bool(section["data"].get("content", "").strip())
    return any(any(v.strip() for v in item.values()) for item in section_items(section))


def section_summary(section: dict[str, Any]) -> str:
    if not section["style"].get("visible", True):
        return "已隐藏"
    if not section_has_content(section):
        return "待填写"
    if section["type"] == "basic":
        value = section["data"].get("job") or section["data"].get("name") or "已填写"
        return value
    if section["type"] == "self_eval":
        text = section["data"].get("content", "").replace("\n", " ")
        return text[:16] + ("…" if len(text) > 16 else "")
    count = len(section_items(section))
    return f"{count} 条内容"


def person_name(resume: dict[str, Any]) -> str:
    name = get_section(resume, "basic")["data"].get("name", "").strip()
    return name or "未命名简历"


def file_stem(resume: dict[str, Any]) -> str:
    name = person_name(resume)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "我的简历"
    return f"{safe}-简历"


def character_count(resume: dict[str, Any]) -> int:
    total = 0
    for section in resume["sections"]:
        if section["type"] == "basic":
            total += sum(
                len(value)
                for key, value in section["data"].items()
                if key != PHOTO_KEY
            )
        elif section["type"] == "self_eval":
            total += len(section["data"].get("content", ""))
        else:
            for item in section_items(section):
                total += sum(len(v) for v in item.values())
    return total


def clone_resume(resume: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(resume)
