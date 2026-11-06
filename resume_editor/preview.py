"""A4 实时预览画布。

雏形采用单页预览：内容超出一页时会在页面上方提示，避免悄悄截断内容。
分页、拖拽排序等可以在下一阶段继续扩展。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable

from . import photo
from .model import PAPERS, SECTION_TITLES, get_section, section_has_content
from .theme import (
    ACCENT,
    BORDER,
    BORDER_STRONG,
    CHIP_BG,
    FAINT,
    HOVER_BG,
    MUTED,
    PANEL_BG,
    PREVIEW_BG,
    UI_FONT,
    UI_FONT_SIZE,
    WARNING,
)

PX_PER_MM = 96.0 / 25.4
PT_TO_PX = 96.0 / 72.0
OUTER_SIDE = 40
OUTER_TOP = 52
OUTER_BOTTOM = 36


def _wrap_text(text: str, font: tkfont.Font, max_width: float) -> list[str]:
    """按像素宽度换行，兼顾英文单词与中文逐字断行。"""
    if not text:
        return [""]
    max_width = max(1.0, max_width)
    lines: list[str] = []
    for paragraph in text.replace("\t", "    ").split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        tokens: list[str] = []
        buffer = ""
        for char in paragraph:
            if char.isspace():
                if buffer:
                    tokens.append(buffer)
                    buffer = ""
                tokens.append(" ")
            elif ord(char) < 128 and (
                char.isalnum() or char in "-_/.@+%#&?=:;,'\"()[]{}<>"
            ):
                buffer += char
            else:
                if buffer:
                    tokens.append(buffer)
                    buffer = ""
                tokens.append(char)
        if buffer:
            tokens.append(buffer)

        current = ""
        for token in tokens:
            if token == " " and not current:
                continue
            candidate = current + token
            if font.measure(candidate) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current.rstrip())
                current = ""
            if token == " ":
                continue
            if font.measure(token) <= max_width:
                current = token
                continue
            # 极端情况下，单个英文单词也超宽，逐字符断开。
            for char in token:
                if current and font.measure(current + char) > max_width:
                    lines.append(current)
                    current = char
                else:
                    current += char
        lines.append(current.rstrip() if current else "")
    return lines or [""]


def _fit_text(text: str, font: tkfont.Font, max_width: float) -> str:
    if font.measure(text) <= max_width:
        return text
    ellipsis = "…"
    if font.measure(ellipsis) > max_width:
        return ""
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if font.measure(text[:mid] + ellipsis) <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + ellipsis


class _MeasureCanvas:
    """只用于 100% 缩放下的版面测量，不真正创建画布元素。"""

    def create_text(self, *args, **kwargs):
        return 1

    def create_rectangle(self, *args, **kwargs):
        return 1

    def create_line(self, *args, **kwargs):
        return 1

    def create_image(self, *args, **kwargs):
        return 1

    def bbox(self, *args, **kwargs):
        return None


class _PageRenderer:
    def __init__(
        self,
        canvas: tk.Canvas,
        resume: dict,
        scale: float,
        selected: str,
        page_x: float,
        page_y: float,
        page_w: float,
        page_h: float,
        font_cache: dict,
        photo_cache: dict | None = None,
        draw_images: bool = True,
    ) -> None:
        self.canvas = canvas
        self.resume = resume
        self.scale = scale
        self.selected = selected
        self.page_x = page_x
        self.page_y = page_y
        self.page_w = page_w
        self.page_h = page_h
        self.font_cache = font_cache
        self.photo_cache = photo_cache if photo_cache is not None else {}
        self.draw_images = draw_images
        self.photo_count = 0
        page = resume["page"]
        self.margin_l = page["margin_left"] * PX_PER_MM * scale
        self.margin_r = page["margin_right"] * PX_PER_MM * scale
        self.margin_t = page["margin_top"] * PX_PER_MM * scale
        self.margin_b = page["margin_bottom"] * PX_PER_MM * scale
        self.x = page_x + self.margin_l
        self.y = page_y + self.margin_t
        self.width = page_w - self.margin_l - self.margin_r
        self.bottom = page_y + page_h - self.margin_b
        self.overflow = False
        self.stop = False
        self._ui_font = tkfont.Font(family=UI_FONT, size=-13)
        self._ui_font_bold = tkfont.Font(family=UI_FONT, size=-13, weight="bold")

    # -- 测量 ---------------------------------------------------------
    def font(self, family: str, pt: float, bold: bool = False) -> tkfont.Font:
        px = max(6, round(pt * PT_TO_PX * self.scale))
        key = (family, px, bool(bold))
        if key not in self.font_cache:
            self.font_cache[key] = tkfont.Font(
                family=family,
                size=-px,
                weight="bold" if bold else "normal",
            )
        return self.font_cache[key]

    def mm(self, value: float) -> float:
        return value * PX_PER_MM * self.scale

    def line_height(self, font: tkfont.Font, spacing: float) -> float:
        return max(1, round(font.metrics("linespace") * spacing))

    def _tags(self, section_type: str) -> tuple[str, ...]:
        return (f"sec_{section_type}",)

    def _ensure(self, height: float) -> bool:
        if self.y + height > self.bottom + 0.5:
            self.overflow = True
            self.stop = True
            return False
        return True

    def space(self, height: float) -> None:
        if height <= 0:
            return
        if self.y + height > self.bottom:
            self.overflow = True
            self.stop = True
            return
        self.y += height

    # -- 基础绘制 -----------------------------------------------------
    def draw_text(
        self,
        text: str,
        font: tkfont.Font,
        color: str,
        *,
        section_type: str,
        spacing: float = 1.35,
        pad_top: float = 0,
        width: float | None = None,
        indent: float = 0,
        align: str = "left",
        bullet: bool = False,
        bullet_color: str = ACCENT,
        extra_tags: tuple[str, ...] = (),
    ) -> bool:
        if self.stop:
            return False
        available = (width if width is not None else self.width) - indent
        lines = _wrap_text(text, font, available)
        line_h = self.line_height(font, spacing)
        height = pad_top + len(lines) * line_h
        if not self._ensure(height):
            return False

        tags = self._tags(section_type) + extra_tags
        text_x = self.x + indent
        for index, line in enumerate(lines):
            line_y = self.y + pad_top + index * line_h
            if bullet and index == 0:
                self.canvas.create_text(
                    self.x + 1,
                    line_y,
                    text="•",
                    font=font,
                    fill=bullet_color,
                    anchor="nw",
                    tags=tags,
                )
            if align == "center":
                anchor, x = "n", text_x + available / 2
            elif align == "right":
                anchor, x = "ne", text_x + available
            else:
                anchor, x = "nw", text_x
            self.canvas.create_text(
                x,
                line_y,
                text=line,
                font=font,
                fill=color,
                anchor=anchor,
                tags=tags,
            )
        self.y += height
        return True

    def draw_heading(self, section: dict, *, pad_top: float = 0) -> bool:
        if self.stop:
            return False
        style = section["style"]
        theme = self.resume["theme"]
        family = style["font"] or theme["font"]
        font = self.font(family, style["title_size"], style["title_bold"])
        line_h = self.line_height(font, 1.08)
        deco = style["decoration"]
        extra = 5.0 if deco in {"rule", "bar"} else 1.0
        if not self._ensure(pad_top + line_h + extra):
            return False
        accent = theme["accent"]
        y = self.y + pad_top
        x_text = self.x
        if deco == "bar":
            self.canvas.create_rectangle(
                self.x,
                y + 2,
                self.x + 3,
                y + line_h - 3,
                fill=accent,
                outline="",
                tags=self._tags(section["type"]),
            )
            x_text = self.x + 11
        self.canvas.create_text(
            x_text,
            y,
            text=section["title"],
            font=font,
            fill=accent,
            anchor="nw",
            tags=self._tags(section["type"]),
        )
        if deco == "rule":
            self.canvas.create_line(
                self.x,
                y + line_h + 2,
                self.x + self.width,
                y + line_h + 2,
                fill=theme["line_color"],
                width=1,
                tags=self._tags(section["type"]),
            )
        self.y = y + line_h + extra
        return True

    def draw_entry_header(
        self,
        section: dict,
        left: str,
        dates: str,
        *,
        pad_top: float,
    ) -> bool:
        if self.stop:
            return False
        style = section["style"]
        theme = self.resume["theme"]
        family = style["font"] or theme["font"]
        left_font = self.font(family, style["body_size"] + 1, True)
        date_font = self.font(family, style["body_size"], False)
        line_h = max(
            self.line_height(left_font, 1.2),
            self.line_height(date_font, 1.2),
        )
        if not self._ensure(pad_top + line_h):
            return False
        tags = self._tags(section["type"])
        date_width = date_font.measure(dates) if dates else 0
        gap = 12 * self.scale if dates else 0
        title_width = max(20, self.width - date_width - gap)
        title = _fit_text(left or "未命名", left_font, title_width)
        y = self.y + pad_top
        self.canvas.create_text(
            self.x,
            y,
            text=title,
            font=left_font,
            fill=theme["text_color"],
            anchor="nw",
            tags=tags,
        )
        if dates:
            self.canvas.create_text(
                self.x + self.width,
                y,
                text=dates,
                font=date_font,
                fill=theme["muted_color"],
                anchor="ne",
                tags=tags,
            )
        self.y += pad_top + line_h
        return True

    # -- 各区域 -------------------------------------------------------
    def render(self) -> None:
        for section in self.resume["sections"]:
            if self.stop:
                break
            if section["type"] == "basic":
                self.draw_basic(section)
            else:
                self.draw_section(section)
        if self.selected:
            self.draw_selection()

    def draw_basic(self, section: dict) -> None:
        style = section["style"]
        if not style.get("visible", True):
            return
        theme = self.resume["theme"]
        data = section["data"]
        family = style["font"] or theme["font"]
        if style.get("show_heading"):
            self.draw_heading(section, pad_top=0)
        elif self.y == self.page_y + self.margin_t:
            # 顶部留出一点呼吸空间
            self.space(1.5 * self.scale)

        start_y = self.y
        photo_data = data.get(photo.PHOTO_KEY, "").strip()
        has_photo = bool(photo_data)
        photo_w = self.mm(photo.PHOTO_WIDTH_MM) if has_photo else 0.0
        gap = self.mm(photo.PHOTO_GAP_MM) if has_photo else 0.0
        text_width = max(self.mm(30), self.width - photo_w - gap)
        has_content = section_has_content(section)
        align = style["align"]
        if has_content:
            name = data.get("name", "").strip()
            job = data.get("job", "").strip()
            contact = "   ·   ".join(
                data.get(key, "").strip()
                for key in ("phone", "email", "city", "website")
                if data.get(key, "").strip()
            )
            if name:
                name_font = self.font(family, style["title_size"], True)
                self.draw_text(
                    name,
                    name_font,
                    theme["text_color"],
                    section_type="basic",
                    spacing=1.08,
                    pad_top=0,
                    align=align,
                    width=text_width,
                )
            if job:
                job_font = self.font(family, style["body_size"] + 2, True)
                self.draw_text(
                    job,
                    job_font,
                    theme["accent"],
                    section_type="basic",
                    spacing=1.15,
                    pad_top=2 * self.scale,
                    align=align,
                    width=text_width,
                )
            if contact:
                contact_font = self.font(family, style["body_size"], False)
                self.draw_text(
                    contact,
                    contact_font,
                    theme["muted_color"],
                    section_type="basic",
                    spacing=1.25,
                    pad_top=3 * self.scale,
                    align=align,
                    width=text_width,
                )
        else:
            placeholder_font = self.font(family, style["body_size"], False)
            self.draw_text(
                "点击左侧“基本信息”，填写姓名、求职意向和联系方式",
                placeholder_font,
                FAINT,
                section_type="basic",
                spacing=1.35,
                pad_top=1 * self.scale,
                align=align,
                width=text_width,
            )

        if has_photo and not self.stop:
            photo_h = self.mm(photo.PHOTO_HEIGHT_MM)
            if start_y + photo_h > self.bottom + 0.5:
                self.overflow = True
                self.stop = True
                return
            self.draw_photo(
                photo_data,
                self.x + self.width - photo_w,
                start_y,
                photo_w,
                photo_h,
            )
            self.y = max(self.y, start_y + photo_h + 2 * self.scale)

    def draw_photo(
        self, data: str, x: float, y: float, width: float, height: float
    ) -> None:
        """在基本信息顶部绘制照片，按 25:32 比例裁剪。"""
        self.photo_count += 1
        if not self.draw_images:
            return
        pixel_w = max(12, int(round(width)))
        pixel_h = max(16, int(round(height)))
        key = (hash(data), pixel_w, pixel_h)
        image = self.photo_cache.get(key)
        if image is None:
            image = photo.make_preview_image(data, pixel_w, pixel_h)
            if image is not None:
                self.photo_cache[key] = image
        tags = ("sec_basic", "photo")
        if image is not None:
            self.canvas.create_image(
                x,
                y,
                image=image,
                anchor="nw",
                tags=tags,
            )
        else:
            self.canvas.create_rectangle(
                x,
                y,
                x + width,
                y + height,
                fill="#EEF2F7",
                outline="",
                tags=tags,
            )
            self.canvas.create_text(
                x + width / 2,
                y + height / 2,
                text="照片",
                fill=FAINT,
                font=self._ui_font,
                anchor="center",
                tags=tags,
            )
        self.canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            outline=BORDER_STRONG,
            width=1,
            tags=tags,
        )

    def draw_section(self, section: dict) -> None:
        style = section["style"]
        if not style.get("visible", True):
            return
        has_content = section_has_content(section)
        has_items = bool(section["data"].get("items"))
        # 空白条目本身不进入正式简历；但选中该区域时给一个占位提示，
        # 避免“刚点添加，页面就全白”的错觉。
        if not has_content and not (has_items and self.selected == section["type"]):
            return
        if not self.draw_heading(section, pad_top=self.mm(style["gap"])):
            return

        section_type = section["type"]
        if section_type == "education":
            self.draw_entries(
                section,
                title_key="school",
                subtitle=lambda item: "  ·  ".join(
                    part
                    for part in (item.get("major", ""), item.get("degree", ""))
                    if part.strip()
                ),
            )
        elif section_type == "work":
            self.draw_entries(section, title_key="company", subtitle=lambda item: item.get("position", ""))
        elif section_type == "projects":
            self.draw_entries(section, title_key="name", subtitle=lambda item: item.get("role", ""))
        elif section_type == "skills":
            self.draw_skills(section)
        elif section_type == "awards":
            self.draw_awards(section)
        elif section_type == "self_eval":
            self.draw_self_eval(section)

    def draw_empty_note(self, section: dict, font: tkfont.Font) -> None:
        self.draw_text(
            "新增条目待填写 · 请在右侧补全",
            font,
            FAINT,
            section_type=section["type"],
            spacing=1.35,
            pad_top=2.2 * self.scale,
        )

    def draw_entries(self, section: dict, *, title_key: str, subtitle: Callable) -> None:
        style = section["style"]
        theme = self.resume["theme"]
        family = style["font"] or theme["font"]
        body_font = self.font(family, style["body_size"], False)
        muted_font = self.font(family, style["body_size"], False)
        if not section_has_content(section):
            self.draw_empty_note(section, body_font)
            return
        for index, item in enumerate(section["data"].get("items", [])):
            if not any(str(value).strip() for value in item.values()):
                continue
            start = item.get("start", "").strip()
            end = item.get("end", "").strip()
            dates = " – ".join(part for part in (start, end) if part)
            self.draw_entry_header(
                section,
                item.get(title_key, ""),
                dates,
                pad_top=1.1 * self.scale if index == 0 else self.mm(2.2),
            )
            subtitle_text = subtitle(item).strip()
            if subtitle_text:
                self.draw_text(
                    subtitle_text,
                    muted_font,
                    theme["muted_color"],
                    section_type=section["type"],
                    spacing=1.2,
                    pad_top=1 * self.scale,
                    align=style["align"],
                )
            details = item.get("details", "")
            for line in details.splitlines():
                if line.strip():
                    if not self.draw_text(
                        line,
                        body_font,
                        theme["text_color"],
                        section_type=section["type"],
                        spacing=style["line_spacing"],
                        pad_top=1.1 * self.scale,
                        indent=14 * self.scale,
                        bullet=True,
                        align="left",
                    ):
                        return

    def draw_skills(self, section: dict) -> None:
        style = section["style"]
        theme = self.resume["theme"]
        family = style["font"] or theme["font"]
        body_font = self.font(family, style["body_size"], False)
        if not section_has_content(section):
            self.draw_empty_note(section, body_font)
            return
        for item in section["data"].get("items", []):
            name = item.get("name", "").strip()
            detail = item.get("detail", "").strip()
            if not name and not detail:
                continue
            text = f"{name}：{detail}" if name and detail else (name or detail)
            if not self.draw_text(
                text,
                body_font,
                theme["text_color"],
                section_type="skills",
                spacing=style["line_spacing"],
                pad_top=1.2 * self.scale,
                indent=14 * self.scale,
                bullet=True,
                align="left",
            ):
                return

    def draw_awards(self, section: dict) -> None:
        style = section["style"]
        theme = self.resume["theme"]
        family = style["font"] or theme["font"]
        body_font = self.font(family, style["body_size"], False)
        if not section_has_content(section):
            self.draw_empty_note(section, body_font)
            return
        for index, item in enumerate(section["data"].get("items", [])):
            title = item.get("title", "").strip()
            if not title:
                continue
            self.draw_entry_header(
                section,
                title,
                item.get("date", "").strip(),
                pad_top=1.1 * self.scale if index == 0 else self.mm(2.2),
            )
            issuer = item.get("issuer", "").strip()
            if issuer:
                self.draw_text(
                    issuer,
                    body_font,
                    theme["muted_color"],
                    section_type="awards",
                    spacing=1.2,
                    pad_top=0.8 * self.scale,
                    align=style["align"],
                )
            detail = item.get("detail", "").strip()
            if detail:
                self.draw_text(
                    detail,
                    body_font,
                    theme["text_color"],
                    section_type="awards",
                    spacing=style["line_spacing"],
                    pad_top=1 * self.scale,
                    align=style["align"],
                )

    def draw_self_eval(self, section: dict) -> None:
        style = section["style"]
        theme = self.resume["theme"]
        family = style["font"] or theme["font"]
        body_font = self.font(family, style["body_size"], False)
        content = section["data"].get("content", "")
        for line in content.splitlines():
            if not line.strip():
                self.space(self.line_height(body_font, 0.65))
                continue
            if not self.draw_text(
                line.strip(),
                body_font,
                theme["text_color"],
                section_type="self_eval",
                spacing=style["line_spacing"],
                pad_top=1.4 * self.scale,
                align=style["align"],
            ):
                return

    def draw_selection(self) -> None:
        tag = f"sec_{self.selected}"
        bbox = self.canvas.bbox(tag)
        if not bbox:
            return
        left, top, right, bottom = bbox
        pad = 4 * self.scale
        x0 = min(left - pad, self.page_x + 2)
        y0 = max(self.page_y + 2, top - pad)
        x1 = min(right + pad, self.page_x + self.page_w - 2)
        y1 = min(self.page_y + self.page_h - 2, bottom + pad)
        self.canvas.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            outline="#AFC6F7",
            width=1,
            dash=(3, 2),
            tags=("selection_outline",),
        )
        self.canvas.create_rectangle(
            self.page_x + max(1, self.margin_l - 10),
            y0 + 2,
            self.page_x + max(3, self.margin_l - 6),
            min(y1 - 2, y0 + 70),
            fill=ACCENT,
            outline="",
            tags=("selection_outline",),
        )


class ResumePreview(tk.Frame):
    def __init__(
        self,
        master,
        *,
        on_select: Callable[[str], None],
        on_layout: Callable[[dict], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, bg=PREVIEW_BG, **kwargs)
        self.resume: dict | None = None
        self.selected = "basic"
        self.zoom = 0.8
        self.fit_mode = True
        self._render_job = None
        self._resize_job = None
        self._font_cache: dict = {}
        self._photo_cache: dict = {}
        self._last_overflow = False
        self._initial_job = None
        self.on_select = on_select
        self.on_layout = on_layout
        self._build_toolbar()
        self._build_canvas()
        self._initial_job = self.after(80, self._initial_fit)

    # -- UI -----------------------------------------------------------
    def _build_toolbar(self) -> None:
        self.toolbar = tk.Frame(self, bg=PANEL_BG, height=46)
        self.toolbar.pack(fill="x")
        self.toolbar.pack_propagate(False)

        left = tk.Frame(self.toolbar, bg=PANEL_BG)
        left.pack(side="left", padx=16, pady=9)
        tk.Label(
            left,
            text="实时预览",
            bg=PANEL_BG,
            fg="#273246",
            font=(UI_FONT, UI_FONT_SIZE, "bold"),
        ).pack(side="left")
        self.meta_label = tk.Label(
            left,
            text="A4 · 1 页",
            bg=CHIP_BG,
            fg=MUTED,
            font=(UI_FONT, 8),
            padx=7,
            pady=2,
        )
        self.meta_label.pack(side="left", padx=(9, 0))

        right = tk.Frame(self.toolbar, bg=PANEL_BG)
        right.pack(side="right", padx=14, pady=7)
        self._tool_button(right, "−", lambda: self.step_zoom(-1)).pack(side="left")
        self.zoom_label = tk.Label(
            right,
            text="80%",
            bg=PANEL_BG,
            fg="#344054",
            width=5,
            font=(UI_FONT, 9),
        )
        self.zoom_label.pack(side="left", padx=1)
        self._tool_button(right, "+", lambda: self.step_zoom(1)).pack(side="left")
        self.fit_button = self._tool_button(
            right, "适应宽度", self.fit_width, padx=10
        )
        self.fit_button.pack(side="left", padx=(8, 0))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    def _tool_button(self, parent, text: str, command, padx: int = 7) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=PANEL_BG,
            fg="#475467",
            activebackground=HOVER_BG,
            activeforeground="#1D2939",
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=padx,
            pady=2,
            font=(UI_FONT, 9),
            cursor="hand2",
        )

    def _build_canvas(self) -> None:
        wrapper = tk.Frame(self, bg=PREVIEW_BG)
        wrapper.pack(fill="both", expand=True)
        wrapper.grid_rowconfigure(0, weight=1)
        wrapper.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            wrapper,
            bg=PREVIEW_BG,
            highlightthickness=0,
            bd=0,
            yscrollincrement=24,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar = ttk.Scrollbar(wrapper, orient="vertical", command=self.canvas.yview)
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar = ttk.Scrollbar(wrapper, orient="horizontal", command=self.canvas.xview)
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.hbar.grid_remove()
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

    # -- 交互 ---------------------------------------------------------
    def set_resume(self, resume: dict) -> None:
        self.resume = resume
        self._photo_cache.clear()
        self.refresh()

    def set_selected(self, section_type: str) -> None:
        if self.selected == section_type:
            return
        self.selected = section_type
        self.refresh(immediate=True)

    def refresh(self, immediate: bool = False) -> None:
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except tk.TclError:
                pass
            self._render_job = None
        delay = 5 if immediate else 90
        self._render_job = self.after(delay, self._render)

    def step_zoom(self, direction: int) -> None:
        self.fit_mode = False
        self.set_zoom(self.zoom + 0.08 * direction)

    def set_zoom(self, value: float) -> None:
        value = max(0.42, min(1.35, round(value, 3)))
        if abs(value - self.zoom) < 0.0005:
            return
        self.zoom = value
        self._update_zoom_label()
        self.refresh(immediate=True)

    def fit_width(self) -> None:
        self.fit_mode = True
        self._apply_fit_width(force=True)
        self.refresh(immediate=True)

    def _initial_fit(self) -> None:
        self._initial_job = None
        if self.fit_mode:
            self._apply_fit_width(force=True)
            self.refresh(immediate=True)

    def _apply_fit_width(self, force: bool = False) -> bool:
        if not self.resume:
            return False
        available = self.canvas.winfo_width() - OUTER_SIDE * 2
        if available < 120:
            return False
        page_w = PAPERS[self.resume["page"]["paper"]][0] * PX_PER_MM
        value = max(0.42, min(1.15, available / page_w))
        value = round(value, 3)
        if force or abs(value - self.zoom) > 0.002:
            self.zoom = value
            self._update_zoom_label()
            return True
        return False

    def _update_zoom_label(self) -> None:
        self.zoom_label.configure(text=f"{round(self.zoom * 100)}%")

    def _on_canvas_configure(self, _event) -> None:
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(140, self._handle_resize)

    def _handle_resize(self) -> None:
        self._resize_job = None
        changed = False
        if self.fit_mode:
            changed = self._apply_fit_width()
        if changed:
            self.refresh(immediate=True)
        else:
            self.refresh()

    def _on_click(self, _event) -> None:
        item_ids = self.canvas.find_withtag("current")
        if not item_ids:
            return
        for tag in self.canvas.gettags(item_ids[0]):
            if tag.startswith("sec_"):
                section_type = tag[4:]
                if section_type in SECTION_TITLES and section_type != self.selected:
                    self.on_select(section_type)
                return

    def _on_motion(self, _event) -> None:
        item_ids = self.canvas.find_withtag("current")
        cursor = ""
        if item_ids:
            if any(tag.startswith("sec_") for tag in self.canvas.gettags(item_ids[0])):
                cursor = "hand2"
        self.canvas.configure(cursor=cursor)

    def _on_mousewheel(self, event) -> str:
        steps = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(steps * 3, "units")
        return "break"

    def _on_shift_mousewheel(self, event) -> str:
        steps = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(steps * 3, "units")
        return "break"

    # -- 渲染 ---------------------------------------------------------
    def _render(self) -> None:
        self._render_job = None
        if not self.resume:
            self.canvas.delete("all")
            return
        canvas_w = self.canvas.winfo_width()
        if canvas_w < 120:
            self._render_job = self.after(80, self._render)
            return

        if self.fit_mode:
            self._apply_fit_width()

        page_model = self.resume["page"]
        paper_w_mm, paper_h_mm = PAPERS[page_model["paper"]]
        page_w = paper_w_mm * PX_PER_MM * self.zoom
        page_h = paper_h_mm * PX_PER_MM * self.zoom
        needs_hbar = page_w + OUTER_SIDE * 2 > canvas_w
        if needs_hbar:
            self.hbar.grid()
        else:
            self.hbar.grid_remove()

        available_w = self.canvas.winfo_width()
        if page_w + OUTER_SIDE * 2 <= available_w:
            page_x = (available_w - page_w) / 2
        else:
            page_x = OUTER_SIDE
        page_y = OUTER_TOP

        first_fraction = self.canvas.yview()[0] if self.canvas.find_all() else 0.0
        self.canvas.delete("all")
        bg = page_model.get("background", "#FFFFFF")
        # 纸张阴影
        self.canvas.create_rectangle(
            page_x + 8,
            page_y + 9,
            page_x + page_w + 8,
            page_y + page_h + 9,
            fill="#D8E0EA",
            outline="",
        )
        self.canvas.create_rectangle(
            page_x + 3,
            page_y + 3,
            page_x + page_w + 3,
            page_y + page_h + 3,
            fill="#E3E9F1",
            outline="",
        )
        self.canvas.create_rectangle(
            page_x,
            page_y,
            page_x + page_w,
            page_y + page_h,
            fill=bg,
            outline="#D5DEEA",
            width=1,
        )

        page_label = f"{page_model['paper']}  ·  第 1 页"
        self.canvas.create_text(
            page_x,
            page_y - 24,
            text=page_label,
            anchor="nw",
            fill=MUTED,
            font=(UI_FONT, 9),
        )

        # 用 100% 字号独立测量一次，避免缩放时字体像素取整造成
        # “同一份简历在某个缩放级别突然超页”的误判。
        measure_renderer = _PageRenderer(
            _MeasureCanvas(),
            self.resume,
            1.0,
            "",
            0,
            0,
            paper_w_mm * PX_PER_MM,
            paper_h_mm * PX_PER_MM,
            self._font_cache,
            {},
            draw_images=False,
        )
        measure_renderer.render()
        canonical_overflow = measure_renderer.overflow

        renderer = _PageRenderer(
            self.canvas,
            self.resume,
            self.zoom,
            self.selected,
            page_x,
            page_y,
            page_w,
            page_h,
            self._font_cache,
            self._photo_cache,
        )
        if not canonical_overflow:
            # 排版在 100% 下不超页时，允许缩放取整造成的几像素误差落到
            # 下边距内，避免预览把最后一行裁掉。
            renderer.bottom = page_y + page_h - 2
        renderer.render()
        self._last_overflow = canonical_overflow

        if canonical_overflow:
            self.canvas.create_text(
                page_x + page_w,
                page_y - 24,
                text="内容超出一页",
                anchor="ne",
                fill=WARNING,
                font=(UI_FONT, 9, "bold"),
            )
            self.meta_label.configure(text=f"{page_model['paper']} · 内容超页")
        else:
            self.meta_label.configure(text=f"{page_model['paper']} · 单页预览")

        content_h = page_y + page_h + OUTER_BOTTOM
        scroll_w = max(page_x + page_w + OUTER_SIDE, self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, scroll_w, content_h))
        if first_fraction:
            self.canvas.yview_moveto(first_fraction)

        if self.on_layout:
            self.on_layout(
                {
                    "overflow": canonical_overflow,
                    "page_count": 1,
                    "zoom": self.zoom,
                }
            )

    def destroy(self) -> None:
        for job in (self._render_job, self._resize_job, self._initial_job):
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._render_job = None
        self._resize_job = None
        self._initial_job = None
        super().destroy()
