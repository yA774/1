"""Tkinter 主界面。

界面分三栏：
- 左侧：区域导航（区域由 schema 固定）
- 中间：A4 实时预览，点击区域可直接切换
- 右侧：当前区域的内容 / 排版设置

每个区域的内容表单完全由 model.py 的字段白名单生成。
"""

from __future__ import annotations

import copy
import ctypes
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Callable

from . import photo, theme
from .docx_io import export_docx
from .library import default_library_path, load_library, make_entry, save_library
from .pdf_io import export_pdf as export_pdf_file
from .model import (
    DEFAULT_THEME,
    ITEM_FIELDS,
    ITEM_TITLE_KEYS,
    PAPERS,
    SECTION_HINTS,
    SECTION_ICONS,
    SECTION_TITLES,
    blank_resume,
    blank_section,
    character_count,
    empty_item,
    file_stem,
    get_section,
    person_name,
    sample_resume,
    section_has_content,
    section_items,
    section_summary,
)
from .preview import ResumePreview
from .storage import import_resume, save_project

APP_TITLE = "简历工坊"


# ---------------------------------------------------------------------------
# ttk 样式与基础控件
# ---------------------------------------------------------------------------


def configure_styles(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    root.option_add("*TCombobox*Listbox.font", (theme.UI_FONT, 10))
    root.option_add("*TCombobox*Listbox.background", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", theme.ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

    style.configure(
        ".",
        font=(theme.UI_FONT, theme.UI_FONT_SIZE),
        background=theme.PANEL_BG,
        foreground=theme.TEXT,
    )
    style.configure("TFrame", background=theme.PANEL_BG)
    style.configure(
        "TNotebook",
        background=theme.PANEL_BG,
        borderwidth=0,
        tabmargins=(0, 6, 0, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background="#F3F5F9",
        foreground=theme.MUTED,
        padding=(16, 7),
        font=(theme.UI_FONT, 9),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", theme.PANEL_BG), ("active", "#F7F9FC")],
        foreground=[("selected", theme.ACCENT), ("active", theme.TEXT)],
    )
    style.configure(
        "Field.TEntry",
        fieldbackground="#FFFFFF",
        foreground=theme.TEXT,
        bordercolor=theme.BORDER,
        lightcolor=theme.BORDER,
        darkcolor=theme.BORDER,
        insertcolor=theme.TEXT,
        padding=(8, 6),
    )
    style.map(
        "Field.TEntry",
        bordercolor=[("focus", theme.ACCENT)],
        lightcolor=[("focus", theme.ACCENT)],
        darkcolor=[("focus", theme.ACCENT)],
    )
    style.configure(
        "Field.TSpinbox",
        fieldbackground="#FFFFFF",
        foreground=theme.TEXT,
        bordercolor=theme.BORDER,
        lightcolor=theme.BORDER,
        darkcolor=theme.BORDER,
        insertcolor=theme.TEXT,
        padding=(7, 5),
        arrowsize=13,
    )
    style.map(
        "Field.TSpinbox",
        bordercolor=[("focus", theme.ACCENT)],
        lightcolor=[("focus", theme.ACCENT)],
        darkcolor=[("focus", theme.ACCENT)],
    )
    style.configure(
        "Field.TCombobox",
        fieldbackground="#FFFFFF",
        background="#FFFFFF",
        foreground=theme.TEXT,
        bordercolor=theme.BORDER,
        lightcolor=theme.BORDER,
        darkcolor=theme.BORDER,
        arrowcolor=theme.MUTED,
        padding=(7, 5),
        arrowsize=14,
    )
    style.map(
        "Field.TCombobox",
        fieldbackground=[("readonly", "#FFFFFF")],
        foreground=[("readonly", theme.TEXT)],
        bordercolor=[("focus", theme.ACCENT)],
        lightcolor=[("focus", theme.ACCENT)],
        darkcolor=[("focus", theme.ACCENT)],
        selectbackground=[("readonly", "#FFFFFF")],
        selectforeground=[("readonly", theme.TEXT)],
    )
    style.configure(
        "TScrollbar",
        background="#CBD5E1",
        troughcolor="#F4F7FB",
        bordercolor="#F4F7FB",
        darkcolor="#CBD5E1",
        lightcolor="#CBD5E1",
        arrowcolor="#667085",
        gripcount=0,
        width=10,
    )
    style.map("TScrollbar", background=[("active", "#94A3B8")])
    style.configure(
        "Vertical.TScrollbar",
        background="#CBD5E1",
        troughcolor="#F4F7FB",
        bordercolor="#F4F7FB",
        arrowcolor="#667085",
        gripcount=0,
        width=10,
    )
    style.configure(
        "Horizontal.TScrollbar",
        background="#CBD5E1",
        troughcolor="#F4F7FB",
        bordercolor="#F4F7FB",
        arrowcolor="#667085",
        gripcount=0,
    )


class ScrollArea(tk.Frame):
    """带竖向滚动条的白色表单容器。"""

    def __init__(self, master, *, bg: str = theme.PANEL_BG, **kwargs) -> None:
        super().__init__(master, bg=bg, **kwargs)
        self.canvas = tk.Canvas(
            self,
            bg=bg,
            highlightthickness=0,
            bd=0,
            yscrollincrement=20,
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.vbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    def _on_inner_configure(self, _event=None) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)

    def _on_wheel(self, event) -> str:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def scroll_to_bottom(self) -> None:
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def bind_wheel_tree(self) -> None:
        """让鼠标停在表单控件上也能滚动整个表单。"""

        def walk(widget) -> None:
            if isinstance(widget, (tk.Text, ttk.Combobox, ttk.Spinbox)):
                pass
            else:
                try:
                    widget.bind("<MouseWheel>", self._on_wheel, add="+")
                except tk.TclError:
                    pass
            for child in widget.winfo_children():
                walk(child)

        walk(self.inner)
        self.canvas.bind("<MouseWheel>", self._on_wheel, add="+")


# ---------------------------------------------------------------------------
# 左侧区域导航
# ---------------------------------------------------------------------------


class SidebarRow(tk.Canvas):
    def __init__(
        self,
        master,
        *,
        key: str,
        title: str,
        meta: str,
        icon: str,
        selected: bool,
        on_click: Callable[[str], None],
    ) -> None:
        super().__init__(
            master,
            height=55,
            bg=theme.SIDEBAR_BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.key = key
        self.title = title
        self.meta = meta
        self.icon = icon
        self.selected = selected
        self.on_click = on_click
        self._hover = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", lambda _event: self.on_click(self.key))

    def _enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width <= 1:
            return
        if self.selected:
            bg = theme.ACCENT_SOFT
        elif self._hover:
            bg = "#F1F5FA"
        else:
            bg = theme.SIDEBAR_BG
        self.create_rectangle(5, 5, width - 5, 50, fill=bg, outline="")
        if self.selected:
            self.create_rectangle(5, 12, 8, 43, fill=theme.ACCENT, outline="")
        if self.selected:
            icon_fill = theme.ACCENT
            icon_fg = "#FFFFFF"
            title_fg = theme.ACCENT
        else:
            icon_fill = "#EAF1FF"
            icon_fg = theme.ACCENT
            title_fg = theme.TEXT if self.meta != "已隐藏" else theme.FAINT
        self.create_oval(19, 14, 45, 40, fill=icon_fill, outline="")
        self.create_text(
            32,
            27,
            text=self.icon,
            fill=icon_fg,
            font=(theme.UI_FONT, 10, "bold"),
        )
        self.create_text(
            56,
            12,
            text=self.title,
            anchor="nw",
            fill=title_fg,
            font=(theme.UI_FONT, 10, "bold"),
        )
        self.create_text(
            56,
            31,
            text=self.meta,
            anchor="nw",
            fill=theme.MUTED,
            font=(theme.UI_FONT, 8),
        )


class ToggleSwitch(tk.Canvas):
    """自绘开关，避免 clam 主题把勾选框画成一个小叉。"""

    def __init__(
        self,
        master,
        *,
        value: bool,
        command: Callable[[bool], None],
        bg: str = theme.PANEL_BG,
    ) -> None:
        super().__init__(
            master,
            width=38,
            height=22,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.value = bool(value)
        self.command = command
        self._bg = bg
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        track = theme.ACCENT if self.value else "#CBD5E1"
        self.create_oval(2, 4, 16, 20, fill=track, outline="")
        self.create_rectangle(9, 4, 29, 20, fill=track, outline="")
        self.create_oval(22, 4, 36, 20, fill=track, outline="")
        knob_x = 20 if self.value else 4
        self.create_oval(
            knob_x,
            6,
            knob_x + 14,
            18,
            fill="#FFFFFF",
            outline="",
        )

    def _toggle(self, _event=None) -> None:
        self.value = not self.value
        self._draw()
        self.command(self.value)


class Sidebar(tk.Frame):
    def __init__(self, master, *, on_select: Callable[[str], None]) -> None:
        super().__init__(master, bg=theme.SIDEBAR_BG, width=232)
        self.on_select = on_select
        self.pack_propagate(False)
        self.resume: dict | None = None
        self.selected = "basic"
        self._build_header()
        self.list_frame = tk.Frame(self, bg=theme.SIDEBAR_BG)
        self.list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._build_footer()

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=theme.SIDEBAR_BG)
        header.pack(fill="x", padx=18, pady=(18, 12))
        tk.Label(
            header,
            text="简历结构",
            bg=theme.SIDEBAR_BG,
            fg=theme.TEXT,
            font=(theme.UI_FONT, 14, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            header,
            text="点击区域编辑，字段按区域隔离",
            bg=theme.SIDEBAR_BG,
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

    def _build_footer(self) -> None:
        footer = tk.Frame(self, bg=theme.SIDEBAR_BG)
        footer.pack(side="bottom", fill="x", padx=16, pady=14)
        tk.Frame(footer, bg=theme.BORDER, height=1).pack(fill="x", pady=(0, 10))
        tk.Label(
            footer,
            text="每个区域只映射自己的字段。\n例如“教育经历”不能写入工作内容。",
            bg=theme.SIDEBAR_BG,
            fg=theme.FAINT,
            font=(theme.UI_FONT, 8),
            justify="left",
            anchor="w",
        ).pack(fill="x")

    def set_state(self, resume: dict, selected: str) -> None:
        self.resume = resume
        self.selected = selected
        self.rebuild()

    def rebuild(self) -> None:
        if self.resume is None:
            return
        for child in self.list_frame.winfo_children():
            child.destroy()

        page = self.resume["page"]
        page_meta = f"{page['paper']} · {page['margin_left']:g}/{page['margin_right']:g} mm"
        page_row = SidebarRow(
            self.list_frame,
            key="page",
            title="页面设置",
            meta=page_meta,
            icon="页",
            selected=self.selected == "page",
            on_click=self.on_select,
        )
        page_row.pack(fill="x")
        tk.Frame(self.list_frame, bg=theme.BORDER, height=1).pack(
            fill="x", padx=12, pady=(6, 8)
        )
        tk.Label(
            self.list_frame,
            text="内容区域",
            bg=theme.SIDEBAR_BG,
            fg=theme.FAINT,
            font=(theme.UI_FONT, 8),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 3))

        for section in self.resume["sections"]:
            row = SidebarRow(
                self.list_frame,
                key=section["type"],
                title=SECTION_TITLES[section["type"]],
                meta=section_summary(section),
                icon=SECTION_ICONS[section["type"]],
                selected=self.selected == section["type"],
                on_click=self.on_select,
            )
            row.pack(fill="x", pady=1)


# ---------------------------------------------------------------------------
# 右侧检查器
# ---------------------------------------------------------------------------

CARD_BG = "#F8FAFC"
CARD_BORDER = "#E4EAF2"
THEME_PRESETS = [
    ("商务蓝", "#1D4ED8"),
    ("墨绿", "#0F766E"),
    ("酒红", "#9F1239"),
    ("紫罗兰", "#6D28D9"),
    ("暖橙", "#C2410C"),
    ("青灰", "#0E7490"),
    ("石墨", "#334155"),
]
ALIGN_OPTIONS = [("左对齐", "left"), ("居中", "center"), ("右对齐", "right")]
ALIGN_LABELS = {value: label for label, value in ALIGN_OPTIONS}
DECORATION_OPTIONS = [
    ("细下划线", "rule"),
    ("左侧色条", "bar"),
    ("无装饰", "none"),
]
DECORATION_LABELS = {value: label for label, value in DECORATION_OPTIONS}
LINE_SPACINGS = [1.0, 1.15, 1.25, 1.35, 1.45, 1.6, 1.75, 2.0]


def _num_text(value: float) -> str:
    return str(int(value)) if abs(value - round(value)) < 0.001 else f"{value:.1f}"


class Inspector(tk.Frame):
    def __init__(
        self,
        master,
        *,
        resume: dict,
        fonts: list[str],
        on_change: Callable[..., None],
    ) -> None:
        super().__init__(master, bg=theme.PANEL_BG, width=356)
        self.pack_propagate(False)
        self.resume = resume
        self.fonts = fonts
        self.on_change = on_change
        self.selected = "basic"
        self.current_tab = 0
        self._scroll_to_bottom = False
        self._focus_new_item = False
        self._photo_thumb = None
        self._build_header()
        self.body = tk.Frame(self, bg=theme.PANEL_BG)
        self.body.pack(fill="both", expand=True)
        self.show("basic")

    # -- 头部 ---------------------------------------------------------
    def _build_header(self) -> None:
        self.header = tk.Frame(self, bg=theme.PANEL_BG, height=100)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        self.icon_canvas = tk.Canvas(
            self.header,
            width=40,
            height=40,
            bg=theme.PANEL_BG,
            highlightthickness=0,
        )
        self.icon_canvas.pack(side="left", padx=(18, 12), pady=23)
        self.badge = tk.Label(
            self.header,
            text="字段受控",
            bg=theme.ACCENT_SOFT,
            fg=theme.ACCENT,
            font=(theme.UI_FONT, 8),
            padx=7,
            pady=2,
        )
        self.badge.pack(side="right", padx=(6, 14), pady=(26, 0), anchor="n")
        text_box = tk.Frame(self.header, bg=theme.PANEL_BG)
        text_box.pack(side="left", fill="both", expand=True, pady=(17, 10))
        self.title_label = tk.Label(
            text_box,
            text="基本信息",
            bg=theme.PANEL_BG,
            fg=theme.TEXT,
            font=(theme.UI_FONT, 15, "bold"),
            anchor="w",
        )
        self.title_label.pack(fill="x")
        self.subtitle_label = tk.Label(
            text_box,
            text="",
            bg=theme.PANEL_BG,
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
            anchor="w",
            justify="left",
            wraplength=190,
        )
        self.subtitle_label.pack(fill="x", pady=(4, 0))
        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x")

    def _set_header(self, title: str, subtitle: str, icon: str, badge: str) -> None:
        self.title_label.configure(text=title)
        self.subtitle_label.configure(text=subtitle)
        self.badge.configure(text=badge)
        self.icon_canvas.delete("all")
        self.icon_canvas.create_oval(
            1,
            1,
            39,
            39,
            fill=theme.ACCENT_SOFT,
            outline="",
        )
        self.icon_canvas.create_text(
            20,
            20,
            text=icon,
            fill=theme.ACCENT,
            font=(theme.UI_FONT, 12, "bold"),
        )

    def set_resume(self, resume: dict) -> None:
        self.resume = resume

    # -- 页面切换 -----------------------------------------------------
    def show(self, target: str, *, tab_index: int = 0) -> None:
        self.selected = target
        self.current_tab = tab_index
        for child in self.body.winfo_children():
            child.destroy()
        self._content_scroll: ScrollArea | None = None

        if target == "page":
            self._set_header(
                "页面设置",
                "纸张、页边距与整份简历的默认字体、主题颜色。",
                "页",
                "整份简历",
            )
            self._build_page_tabs(tab_index)
        elif target in SECTION_TITLES:
            section = get_section(self.resume, target)
            self._set_header(
                SECTION_TITLES[target],
                SECTION_HINTS.get(target, ""),
                SECTION_ICONS[target],
                "字段受控",
            )
            self._build_section_tabs(section, tab_index)

    def _notebook(self) -> ttk.Notebook:
        notebook = ttk.Notebook(self.body)
        notebook.pack(fill="both", expand=True, padx=0, pady=(2, 0))
        return notebook

    def _tab(self, notebook: ttk.Notebook, label: str) -> tuple[ScrollArea, tk.Frame]:
        scroll = ScrollArea(notebook)
        notebook.add(scroll, text=label)
        content = tk.Frame(scroll.inner, bg=theme.PANEL_BG)
        content.pack(fill="both", expand=True, padx=16, pady=14)
        return scroll, content

    def _build_section_tabs(self, section: dict, tab_index: int) -> None:
        notebook = self._notebook()
        content_scroll, content = self._tab(notebook, "内容")
        style_scroll, style_content = self._tab(notebook, "排版")
        self._content_scroll = content_scroll

        self._build_section_content(content, section)
        self._build_section_style(style_content, section)

        notebook.select(min(max(0, tab_index), 1))
        content_scroll.bind_wheel_tree()
        style_scroll.bind_wheel_tree()
        if tab_index == 0 and self._scroll_to_bottom:
            self._scroll_to_bottom = False
            self.after(30, content_scroll.scroll_to_bottom)

    def _build_page_tabs(self, tab_index: int) -> None:
        notebook = self._notebook()
        page_scroll, page_content = self._tab(notebook, "页面")
        theme_scroll, theme_content = self._tab(notebook, "主题")
        self._build_page_settings(page_content)
        self._build_theme_settings(theme_content)
        notebook.select(min(max(0, tab_index), 1))
        page_scroll.bind_wheel_tree()
        theme_scroll.bind_wheel_tree()

    # -- 通用小控件 ---------------------------------------------------
    def _group_title(self, parent, text: str, *, bg: str = theme.PANEL_BG) -> None:
        tk.Label(
            parent,
            text=text,
            bg=bg,
            fg=theme.TEXT,
            font=(theme.UI_FONT, 10, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(16, 7))

    def _hint(self, parent, text: str, *, bg: str = theme.PANEL_BG) -> None:
        tk.Label(
            parent,
            text=text,
            bg=bg,
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
            justify="left",
            anchor="w",
            wraplength=305,
        ).pack(fill="x", pady=(2, 0))

    def _label(self, parent, text: str, *, bg: str = theme.PANEL_BG) -> None:
        tk.Label(
            parent,
            text=text,
            bg=bg,
            fg="#475467",
            font=(theme.UI_FONT, 8),
            anchor="w",
        ).pack(fill="x", pady=(8, 3))

    def _entry_field(
        self,
        parent,
        label: str,
        value: str,
        callback: Callable[[str], None],
        *,
        bg: str = theme.PANEL_BG,
        hint: str = "",
        manage: bool = True,
    ) -> tk.Frame:
        box = tk.Frame(parent, bg=bg)
        if manage:
            box.pack(fill="x")
        self._label(box, label, bg=bg)
        var = tk.StringVar(value=value)
        entry = ttk.Entry(
            box,
            textvariable=var,
            style="Field.TEntry",
            font=(theme.UI_FONT, 10),
        )
        entry.pack(fill="x")
        var.trace_add("write", lambda *_: callback(var.get()))
        if hint:
            tk.Label(
                box,
                text=hint,
                bg=bg,
                fg=theme.FAINT,
                font=(theme.UI_FONT, 7),
                anchor="w",
            ).pack(fill="x", pady=(2, 0))
        return box

    def _field_pair(
        self,
        parent,
        left: tuple[str, str, Callable[[str], None]],
        right: tuple[str, str, Callable[[str], None]],
        *,
        bg: str = theme.PANEL_BG,
    ) -> None:
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x")
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        left_box = self._entry_field(
            row, left[0], left[1], left[2], bg=bg, manage=False
        )
        left_box.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=0)
        right_box = self._entry_field(
            row, right[0], right[1], right[2], bg=bg, manage=False
        )
        right_box.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=0)

    def _text_field(
        self,
        parent,
        label: str,
        value: str,
        callback: Callable[[str], None],
        *,
        bg: str = theme.PANEL_BG,
        height: int = 4,
        hint: str = "",
    ) -> tk.Text:
        box = tk.Frame(parent, bg=bg)
        box.pack(fill="x")
        self._label(box, label, bg=bg)
        text = tk.Text(
            box,
            height=height,
            wrap="word",
            undo=True,
            maxundo=80,
            font=(theme.UI_FONT, 10),
            bg="#FFFFFF",
            fg=theme.TEXT,
            insertbackground=theme.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT,
            padx=8,
            pady=7,
        )
        text.pack(fill="x")
        text.insert("1.0", value)
        text.edit_modified(False)

        def on_modified(event=None) -> None:
            if text.edit_modified():
                text.edit_modified(False)
                callback(text.get("1.0", "end-1c"))

        text.bind("<<Modified>>", on_modified)
        if hint:
            tk.Label(
                box,
                text=hint,
                bg=bg,
                fg=theme.FAINT,
                font=(theme.UI_FONT, 7),
                anchor="w",
            ).pack(fill="x", pady=(3, 0))
        return text

    def _primary_button(
        self, parent, text: str, command, *, bg: str = theme.ACCENT
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg="#FFFFFF",
            activebackground=theme.ACCENT_HOVER,
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=14,
            pady=8,
            font=(theme.UI_FONT, 9),
            cursor="hand2",
        )
        return button

    def _soft_button(
        self,
        parent,
        text: str,
        command,
        *,
        fg: str = theme.ACCENT,
        bg: str = theme.ACCENT_SOFT,
        padx: int = 10,
        pady: int = 6,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground="#E3ECFF",
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=padx,
            pady=pady,
            font=(theme.UI_FONT, 9),
            cursor="hand2",
        )

    def _separator(self, parent, *, pady: int = 10) -> None:
        tk.Frame(parent, bg=theme.BORDER, height=1).pack(fill="x", pady=pady)

    # -- 区域内容 -----------------------------------------------------
    def _build_section_content(self, parent, section: dict) -> None:
        section_type = section["type"]
        self._info_banner(parent, SECTION_HINTS.get(section_type, ""))
        if section_type == "basic":
            self._build_basic_form(parent, section)
        elif section_type == "self_eval":
            self._build_self_eval(parent, section)
        else:
            self._build_list_form(parent, section)

    def _info_banner(self, parent, text: str) -> None:
        box = tk.Frame(parent, bg="#F3F7FF")
        box.pack(fill="x", pady=(0, 4))
        tk.Frame(box, bg=theme.ACCENT, width=3).pack(side="left", fill="y")
        tk.Label(
            box,
            text=text,
            bg="#F3F7FF",
            fg="#475467",
            font=(theme.UI_FONT, 8),
            justify="left",
            anchor="w",
            wraplength=280,
            padx=10,
            pady=8,
        ).pack(side="left", fill="x", expand=True)

    def _build_basic_form(self, parent, section: dict) -> None:
        data = section["data"]
        self._photo_field(parent, data)

        def callback(key: str, value: str) -> None:
            data[key] = value
            self._notify()

        self._entry_field(
            parent,
            "姓名",
            data.get("name", ""),
            lambda v: callback("name", v),
        )
        self._entry_field(
            parent,
            "求职意向",
            data.get("job", ""),
            lambda v: callback("job", v),
        )
        self._field_pair(
            parent,
            ("电话", data.get("phone", ""), lambda v: callback("phone", v)),
            ("所在城市", data.get("city", ""), lambda v: callback("city", v)),
        )
        self._entry_field(
            parent,
            "邮箱",
            data.get("email", ""),
            lambda v: callback("email", v),
            hint="例如 name@example.com",
        )
        self._entry_field(
            parent,
            "个人网站 / 作品集",
            data.get("website", ""),
            lambda v: callback("website", v),
            hint="可填写 GitHub、博客或作品集链接",
        )
        self._hint(
            parent,
            "联系方式会合并显示在姓名下方；不同字段之间会生成分隔点。",
        )

    def _photo_field(self, parent, data: dict) -> None:
        value = data.get(photo.PHOTO_KEY, "")
        card = tk.Frame(
            parent,
            bg=CARD_BG,
            highlightbackground=CARD_BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(4, 10))
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="x", padx=12, pady=12)

        thumb_box = tk.Frame(
            inner,
            width=74,
            height=94,
            bg="#E9EEF5",
            highlightbackground=theme.BORDER_STRONG,
            highlightthickness=1,
        )
        thumb_box.pack(side="left")
        thumb_box.pack_propagate(False)
        thumb = photo.make_thumbnail(value, 72, 92) if value else None
        if thumb is not None:
            self._photo_thumb = thumb
            tk.Label(
                thumb_box,
                image=thumb,
                bg="#E9EEF5",
                bd=0,
                highlightthickness=0,
            ).pack(fill="both", expand=True)
        else:
            self._photo_thumb = None
            tk.Label(
                thumb_box,
                text="未设置\n照片" if not value else "无法\n预览",
                bg="#E9EEF5",
                fg=theme.FAINT,
                font=(theme.UI_FONT, 8),
                justify="center",
            ).pack(fill="both", expand=True)

        right = tk.Frame(inner, bg=CARD_BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(
            right,
            text="个人照片",
            bg=CARD_BG,
            fg=theme.TEXT,
            font=(theme.UI_FONT, 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            right,
            text="JPG / PNG，自动裁剪为 25 × 32 mm。",
            bg=CARD_BG,
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
            justify="left",
            anchor="w",
            wraplength=178,
        ).pack(fill="x", pady=(4, 0))
        if not photo.HAS_PIL:
            tk.Label(
                right,
                text="当前环境未安装 Pillow，照片功能不可用。",
                bg=CARD_BG,
                fg=theme.DANGER,
                font=(theme.UI_FONT, 7),
                justify="left",
                anchor="w",
                wraplength=178,
            ).pack(fill="x", pady=(4, 0))

        actions = tk.Frame(right, bg=CARD_BG)
        actions.pack(fill="x", pady=(9, 0))
        self._soft_button(
            actions,
            "更换图片" if value else "选择图片",
            lambda: self._choose_photo(data),
            padx=8,
            pady=5,
        ).pack(side="left")
        if value:
            self._soft_button(
                actions,
                "移除",
                lambda: self._remove_photo(data),
                fg=theme.DANGER,
                bg="#FEF3F2",
                padx=8,
                pady=5,
            ).pack(side="left", padx=(6, 0))

    def _choose_photo(self, data: dict) -> None:
        if not photo.HAS_PIL:
            messagebox.showerror(
                "需要 Pillow",
                "添加个人照片需要 Pillow。\n\n"
                "请在项目目录运行：\npython -m pip install Pillow",
                parent=self.winfo_toplevel(),
            )
            return
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="选择个人照片",
            filetypes=[
                ("图片", "*.jpg *.jpeg *.png *.webp *.bmp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            data[photo.PHOTO_KEY] = photo.load_photo_file(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "照片读取失败", str(exc), parent=self.winfo_toplevel()
            )
            return
        self._notify()
        self.show("basic", tab_index=0)

    def _remove_photo(self, data: dict) -> None:
        data[photo.PHOTO_KEY] = ""
        self._notify()
        self.show("basic", tab_index=0)

    def _build_self_eval(self, parent, section: dict) -> None:
        content = section["data"]

        def callback(value: str) -> None:
            content["content"] = value
            self._notify()

        self._text_field(
            parent,
            "自我评价",
            content.get("content", ""),
            callback,
            height=12,
            hint="建议 2–4 句话，突出经验、能力和求职动机。",
        )

    def _build_list_form(self, parent, section: dict) -> None:
        section_type = section["type"]
        items = section["data"].setdefault("items", [])
        if not items:
            empty = tk.Frame(
                parent,
                bg=CARD_BG,
                highlightbackground=CARD_BORDER,
                highlightthickness=1,
            )
            empty.pack(fill="x", pady=(8, 6))
            tk.Label(
                empty,
                text=f"还没有{SECTION_TITLES[section_type]}内容",
                bg=CARD_BG,
                fg=theme.TEXT,
                font=(theme.UI_FONT, 10, "bold"),
                anchor="w",
            ).pack(fill="x", padx=14, pady=(16, 4))
            tk.Label(
                empty,
                text="添加一条记录，只会出现该区域允许的字段。",
                bg=CARD_BG,
                fg=theme.MUTED,
                font=(theme.UI_FONT, 8),
                justify="left",
                anchor="w",
                wraplength=270,
            ).pack(fill="x", padx=14, pady=(0, 12))
            self._primary_button(
                empty,
                f"+ 添加第一条",
                lambda: self._add_item(section_type),
            ).pack(fill="x", padx=14, pady=(0, 14))
            return

        for index, item in enumerate(items):
            self._build_item_card(parent, section, item, index)
        self._soft_button(
            parent,
            f"+ 添加一条{SECTION_TITLES[section_type]}",
            lambda: self._add_item(section_type),
        ).pack(fill="x", pady=(8, 12))
        if self._focus_new_item and items:
            self._focus_new_item = False
            cards = [
                child
                for child in parent.winfo_children()
                if isinstance(child, tk.Frame)
            ]
            if cards:
                first = self._first_input(cards[-1])
                if first is not None:
                    self.after(80, lambda widget=first: self._focus_widget(widget))

    @staticmethod
    def _first_input(widget) -> tk.Widget | None:
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Entry, tk.Entry, tk.Text)):
                return child
            found = Inspector._first_input(child)
            if found is not None:
                return found
        return None

    @staticmethod
    def _focus_widget(widget) -> None:
        try:
            if widget.winfo_exists():
                widget.focus_set()
        except tk.TclError:
            pass

    def _build_item_card(self, parent, section: dict, item: dict, index: int) -> None:
        section_type = section["type"]
        card = tk.Frame(
            parent,
            bg=CARD_BG,
            highlightbackground=CARD_BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(6, 4))
        header = tk.Frame(card, bg=CARD_BG)
        header.pack(fill="x", padx=11, pady=(9, 0))
        title_key = ITEM_TITLE_KEYS.get(section_type, "")
        title_value = item.get(title_key, "").strip() if title_key else ""
        if not title_value:
            title_value = "未填写"
        if len(title_value) > 13:
            title_value = title_value[:13] + "…"
        tk.Label(
            header,
            text=f"{index + 1:02d}",
            bg=CARD_BG,
            fg=theme.ACCENT,
            font=(theme.UI_FONT, 8, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text=title_value,
            bg=CARD_BG,
            fg=theme.TEXT,
            font=(theme.UI_FONT, 9, "bold"),
            anchor="w",
        ).pack(side="left", padx=(6, 0), fill="x", expand=True)

        for text, command, fg, enabled in (
            ("↑", lambda i=index: self._move_item(section_type, i, -1), theme.MUTED, index > 0),
            (
                "↓",
                lambda i=index: self._move_item(section_type, i, 1),
                theme.MUTED,
                index < len(section["data"]["items"]) - 1,
            ),
            ("删", lambda i=index: self._delete_item(section_type, i), theme.DANGER, True),
        ):
            button = tk.Button(
                header,
                text=text,
                command=command,
                state="normal" if enabled else "disabled",
                bg=CARD_BG,
                fg=fg,
                disabledforeground="#C7CED9",
                activebackground="#EEF2F7",
                activeforeground=fg,
                relief="flat",
                bd=0,
                highlightthickness=0,
                padx=5,
                pady=0,
                font=(theme.UI_FONT, 8),
                cursor="hand2" if enabled else "arrow",
            )
            button.pack(side="right", padx=(2, 0))

        form = tk.Frame(card, bg=CARD_BG)
        form.pack(fill="x", padx=11, pady=(4, 12))

        def bind_field(key: str) -> Callable[[str], None]:
            def set_value(value: str) -> None:
                item[key] = value
                self._notify()

            return set_value

        if section_type == "education":
            self._entry_field(
                form, "学校", item.get("school", ""), bind_field("school"), bg=CARD_BG
            )
            self._field_pair(
                form,
                ("专业", item.get("major", ""), bind_field("major")),
                ("学历", item.get("degree", ""), bind_field("degree")),
                bg=CARD_BG,
            )
            self._field_pair(
                form,
                ("开始时间", item.get("start", ""), bind_field("start")),
                ("结束时间", item.get("end", ""), bind_field("end")),
                bg=CARD_BG,
            )
            self._text_field(
                form,
                "在校经历",
                item.get("details", ""),
                bind_field("details"),
                bg=CARD_BG,
                height=3,
                hint="每行一条，预览时自动生成项目符号。",
            )
        elif section_type == "work":
            self._entry_field(
                form, "公司", item.get("company", ""), bind_field("company"), bg=CARD_BG
            )
            self._entry_field(
                form,
                "职位",
                item.get("position", ""),
                bind_field("position"),
                bg=CARD_BG,
            )
            self._field_pair(
                form,
                ("开始时间", item.get("start", ""), bind_field("start")),
                ("结束时间", item.get("end", ""), bind_field("end")),
                bg=CARD_BG,
            )
            self._text_field(
                form,
                "工作内容",
                item.get("details", ""),
                bind_field("details"),
                bg=CARD_BG,
                height=4,
                hint="每行一条成果，预览时自动生成项目符号。",
            )
        elif section_type == "projects":
            self._entry_field(
                form, "项目名称", item.get("name", ""), bind_field("name"), bg=CARD_BG
            )
            self._entry_field(
                form, "担任角色", item.get("role", ""), bind_field("role"), bg=CARD_BG
            )
            self._field_pair(
                form,
                ("开始时间", item.get("start", ""), bind_field("start")),
                ("结束时间", item.get("end", ""), bind_field("end")),
                bg=CARD_BG,
            )
            self._text_field(
                form,
                "项目描述",
                item.get("details", ""),
                bind_field("details"),
                bg=CARD_BG,
                height=4,
                hint="建议写清问题、动作和结果。每行一条。",
            )
        elif section_type == "skills":
            self._entry_field(
                form, "技能分类", item.get("name", ""), bind_field("name"), bg=CARD_BG
            )
            self._entry_field(
                form,
                "技能详情",
                item.get("detail", ""),
                bind_field("detail"),
                bg=CARD_BG,
                hint="例如 SQL、Python、Tableau",
            )
        elif section_type == "awards":
            self._entry_field(
                form, "奖项名称", item.get("title", ""), bind_field("title"), bg=CARD_BG
            )
            self._field_pair(
                form,
                ("颁发机构", item.get("issuer", ""), bind_field("issuer")),
                ("获得时间", item.get("date", ""), bind_field("date")),
                bg=CARD_BG,
            )
            self._text_field(
                form,
                "补充说明",
                item.get("detail", ""),
                bind_field("detail"),
                bg=CARD_BG,
                height=3,
            )

    # -- 区域排版 -----------------------------------------------------
    def _build_section_style(self, parent, section: dict) -> None:
        style = section["style"]
        section_type = section["type"]
        self._info_banner(
            parent,
            "这些设置只作用于当前区域。字号单位是 pt，间距单位是 mm。",
        )

        self._toggle_row(
            parent,
            "在简历中显示此区域",
            style.get("visible", True),
            lambda value: self._set_style_visible(section, value),
        )

        self._separator(parent, pady=8)
        self._group_title(parent, "字体与字号")
        font_values = ["跟随页面字体"] + self.fonts
        current_font = style.get("font") or "跟随页面字体"
        if current_font not in font_values:
            font_values.append(current_font)
        font_var = tk.StringVar(value=current_font)
        font_box = ttk.Combobox(
            parent,
            textvariable=font_var,
            values=font_values,
            state="readonly",
            style="Field.TCombobox",
            font=(theme.UI_FONT, 10),
        )
        font_box.pack(fill="x")
        font_box.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._change(
                lambda: style.__setitem__(
                    "font", "" if font_var.get() == "跟随页面字体" else font_var.get()
                )
            ),
        )
        self._hint(parent, "“跟随页面字体”会随页面设置里的默认字体变化。")

        sizes = tk.Frame(parent, bg=theme.PANEL_BG)
        sizes.pack(fill="x", pady=(8, 0))
        sizes.grid_columnconfigure(0, weight=1)
        sizes.grid_columnconfigure(1, weight=1)
        self._number_field(
            sizes,
            "标题字号",
            style["title_size"],
            9,
            40,
            0.5,
            lambda value: self._change(lambda: style.__setitem__("title_size", value)),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self._number_field(
            sizes,
            "正文字号",
            style["body_size"],
            7,
            20,
            0.5,
            lambda value: self._change(lambda: style.__setitem__("body_size", value)),
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        self._separator(parent, pady=10)
        self._group_title(parent, "排版")
        self._combo_field(
            parent,
            "标题对齐",
            [label for label, _ in ALIGN_OPTIONS],
            ALIGN_LABELS.get(style["align"], "左对齐"),
            lambda label: self._change(
                lambda: style.__setitem__("align", dict(ALIGN_OPTIONS)[label])
            ),
        )
        self._combo_field(
            parent,
            "行距",
            [f"{value:.2f}" for value in LINE_SPACINGS],
            f"{style['line_spacing']:.2f}",
            lambda label: self._change(
                lambda: style.__setitem__("line_spacing", float(label))
            ),
        )
        self._combo_field(
            parent,
            "标题装饰",
            [label for label, _ in DECORATION_OPTIONS],
            DECORATION_LABELS.get(style["decoration"], "细下划线"),
            lambda label: self._change(
                lambda: style.__setitem__(
                    "decoration", dict(DECORATION_OPTIONS)[label]
                )
            ),
        )
        gap_box = self._number_field(
            parent,
            "区域前间距（mm）",
            style["gap"],
            0,
            30,
            1,
            lambda value: self._change(lambda: style.__setitem__("gap", value)),
        )
        gap_box.pack(fill="x", pady=(2, 0))

        self._toggle_row(
            parent,
            "区域标题加粗",
            style.get("title_bold", True),
            lambda value: self._change(
                lambda: style.__setitem__("title_bold", value)
            ),
        )
        self._toggle_row(
            parent,
            "显示区域标题",
            style.get("show_heading", True),
            lambda value: self._change(
                lambda: style.__setitem__("show_heading", value)
            ),
        )

        self._separator(parent, pady=12)
        self._soft_button(
            parent,
            "恢复当前区域默认样式",
            lambda: self._reset_section_style(section_type),
            fg=theme.MUTED,
            bg="#F2F4F7",
            padx=14,
            pady=7,
        ).pack(fill="x", pady=(0, 12))

    def _set_style_visible(self, section: dict, visible: bool) -> None:
        section["style"]["visible"] = visible
        self._notify(rebuild_sidebar=True)

    def _reset_section_style(self, section_type: str) -> None:
        section = get_section(self.resume, section_type)
        section["style"] = blank_section(section_type)["style"]
        self._notify(rebuild_sidebar=True)
        self.show(section_type, tab_index=1)

    # -- 页面设置 -----------------------------------------------------
    def _build_page_settings(self, parent) -> None:
        page = self.resume["page"]
        self._info_banner(
            parent,
            "页面设置作用于整份简历。区域可以单独覆盖字体和字号。",
        )
        self._group_title(parent, "纸张")
        paper_var = tk.StringVar(value=page["paper"])
        combo = ttk.Combobox(
            parent,
            textvariable=paper_var,
            values=list(PAPERS),
            state="readonly",
            style="Field.TCombobox",
            font=(theme.UI_FONT, 10),
        )
        combo.pack(fill="x")
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._change(lambda: page.__setitem__("paper", paper_var.get())),
        )

        self._group_title(parent, "页边距（mm）")
        margins = tk.Frame(parent, bg=theme.PANEL_BG)
        margins.pack(fill="x")
        margins.grid_columnconfigure(0, weight=1)
        margins.grid_columnconfigure(1, weight=1)
        for index, (key, label) in enumerate(
            (
                ("margin_top", "上边距"),
                ("margin_right", "右边距"),
                ("margin_bottom", "下边距"),
                ("margin_left", "左边距"),
            )
        ):
            row, column = divmod(index, 2)
            box = self._number_field(
                margins,
                label,
                page[key],
                5,
                40,
                1,
                lambda value, k=key: self._change(lambda: page.__setitem__(k, value)),
            )
            box.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0, 5) if column == 0 else (5, 0),
                pady=(0, 6),
            )

        self._group_title(parent, "快速预设")
        self._hint(
            parent,
            "内容超出一页时，可以先用“紧凑一页”缩小边距和字号，再微调。",
        )
        actions = tk.Frame(parent, bg=theme.PANEL_BG)
        actions.pack(fill="x", pady=(10, 0))
        self._soft_button(
            actions,
            "紧凑一页",
            lambda: self._apply_preset("compact"),
            padx=12,
            pady=7,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._soft_button(
            actions,
            "舒适阅读",
            lambda: self._apply_preset("comfort"),
            fg=theme.MUTED,
            bg="#F2F4F7",
            padx=12,
            pady=7,
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._hint(
            parent,
            "预设只会调整间距、正文字号和行距，不会删除任何内容。",
        )

    def _apply_preset(self, kind: str) -> None:
        page = self.resume["page"]
        if kind == "compact":
            page.update(
                {
                    "margin_top": 12,
                    "margin_right": 12,
                    "margin_bottom": 12,
                    "margin_left": 12,
                }
            )
            body_size = 9.5
            line_spacing = 1.25
            gap = 2.5
            title_size = 12.5
        else:
            page.update(
                {
                    "margin_top": 18,
                    "margin_right": 18,
                    "margin_bottom": 18,
                    "margin_left": 18,
                }
            )
            body_size = 10.5
            line_spacing = 1.45
            gap = 4.5
            title_size = 13.5
        for section in self.resume["sections"]:
            if section["type"] == "basic":
                section["style"]["title_size"] = 24
            else:
                section["style"]["title_size"] = title_size
            section["style"]["body_size"] = body_size
            section["style"]["line_spacing"] = line_spacing
            section["style"]["gap"] = gap
        self._notify(rebuild_sidebar=True)
        self.show("page", tab_index=0)

    # -- 主题 ---------------------------------------------------------
    def _build_theme_settings(self, parent) -> None:
        theme_data = self.resume["theme"]
        self._info_banner(
            parent,
            "主题色用于区域标题、项目符号和强调信息；纸张颜色只影响预览。",
        )
        self._group_title(parent, "快捷主题")
        swatches = tk.Frame(parent, bg=theme.PANEL_BG)
        swatches.pack(fill="x", pady=(2, 2))
        for label, color in THEME_PRESETS:
            button = tk.Button(
                swatches,
                text="",
                bg=color,
                activebackground=color,
                relief="flat",
                bd=0,
                width=3,
                height=1,
                highlightthickness=2,
                highlightbackground=(
                    theme.TEXT
                    if theme_data.get("accent", "").upper() == color.upper()
                    else CARD_BORDER
                ),
                cursor="hand2",
                command=lambda c=color: self._apply_theme_preset(c),
            )
            button.pack(side="left", padx=(0, 5))
        self._hint(parent, "点击色块快速换主题色，也可以在下方精确选择。")

        self._group_title(parent, "页面默认字体")
        font_values = list(self.fonts)
        current = theme_data["font"]
        if current not in font_values:
            font_values.append(current)
        font_var = tk.StringVar(value=current)
        combo = ttk.Combobox(
            parent,
            textvariable=font_var,
            values=font_values,
            state="readonly",
            style="Field.TCombobox",
            font=(theme.UI_FONT, 10),
        )
        combo.pack(fill="x")
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._change(
                lambda: theme_data.__setitem__("font", font_var.get())
            ),
        )

        self._group_title(parent, "颜色")
        self._color_field(
            parent,
            "主题色",
            theme_data["accent"],
            lambda color: self._set_color(theme_data, "accent", color),
        )
        self._color_field(
            parent,
            "正文颜色",
            theme_data["text_color"],
            lambda color: self._set_color(theme_data, "text_color", color),
        )
        self._color_field(
            parent,
            "辅助文字颜色",
            theme_data["muted_color"],
            lambda color: self._set_color(theme_data, "muted_color", color),
        )
        self._color_field(
            parent,
            "分割线颜色",
            theme_data["line_color"],
            lambda color: self._set_color(theme_data, "line_color", color),
        )
        self._color_field(
            parent,
            "预览纸张颜色",
            self.resume["page"]["background"],
            lambda color: self._set_page_color(color),
        )

        self._separator(parent, pady=14)
        self._soft_button(
            parent,
            "恢复默认主题",
            self._reset_theme,
            fg=theme.MUTED,
            bg="#F2F4F7",
            padx=14,
            pady=7,
        ).pack(fill="x", pady=(0, 12))

    def _set_color(self, target: dict, key: str, color: str) -> None:
        target[key] = color
        self._notify()
        self.show("page", tab_index=1)

    def _apply_theme_preset(self, color: str) -> None:
        self.resume["theme"]["accent"] = color.upper()
        self._notify()
        self.show("page", tab_index=1)

    def _set_page_color(self, color: str) -> None:
        self.resume["page"]["background"] = color
        self._notify()
        self.show("page", tab_index=1)

    def _reset_theme(self) -> None:
        self.resume["theme"] = copy.deepcopy(DEFAULT_THEME)
        self._notify()
        self.show("page", tab_index=1)

    # -- 表单辅助 -----------------------------------------------------
    def _number_field(
        self,
        parent,
        label: str,
        value: float,
        low: float,
        high: float,
        step: float,
        callback: Callable[[float], None],
        *,
        bg: str = theme.PANEL_BG,
    ) -> tk.Frame:
        box = tk.Frame(parent, bg=bg)
        self._label(box, label, bg=bg)
        var = tk.StringVar(value=_num_text(value))
        spin = ttk.Spinbox(
            box,
            from_=low,
            to=high,
            increment=step,
            textvariable=var,
            style="Field.TSpinbox",
            font=(theme.UI_FONT, 10),
            command=lambda: commit(),
        )
        spin.pack(fill="x")

        def commit(event=None) -> None:
            try:
                parsed = float(var.get())
            except (TypeError, ValueError):
                parsed = value
            parsed = max(low, min(high, parsed))
            var.set(_num_text(parsed))
            callback(parsed)

        spin.bind("<Return>", commit)
        spin.bind("<FocusOut>", commit)
        return box

    def _combo_field(
        self,
        parent,
        label: str,
        values: list[str],
        current: str,
        callback: Callable[[str], None],
    ) -> None:
        box = tk.Frame(parent, bg=theme.PANEL_BG)
        box.pack(fill="x")
        self._label(box, label)
        var = tk.StringVar(value=current)
        combo = ttk.Combobox(
            box,
            textvariable=var,
            values=values,
            state="readonly",
            style="Field.TCombobox",
            font=(theme.UI_FONT, 10),
        )
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>", lambda _event: callback(var.get()))

    def _toggle_row(
        self,
        parent,
        text: str,
        value: bool,
        command: Callable[[bool], None],
        *,
        bg: str = theme.PANEL_BG,
    ) -> None:
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=(9, 0))
        switch = ToggleSwitch(row, value=value, command=command, bg=bg)
        switch.pack(side="left")
        label = tk.Label(
            row,
            text=text,
            bg=bg,
            fg=theme.TEXT,
            font=(theme.UI_FONT, 9),
            cursor="hand2",
            anchor="w",
        )
        label.pack(side="left", padx=(8, 0))
        label.bind("<Button-1>", lambda _event: switch._toggle())

    def _color_field(
        self, parent, label: str, value: str, callback: Callable[[str], None]
    ) -> None:
        box = tk.Frame(parent, bg=theme.PANEL_BG)
        box.pack(fill="x", pady=4)
        tk.Label(
            box,
            text=label,
            bg=theme.PANEL_BG,
            fg="#475467",
            font=(theme.UI_FONT, 9),
            anchor="w",
        ).pack(side="left")
        value_label = tk.Label(
            box,
            text=value.upper(),
            bg=theme.PANEL_BG,
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
        )
        value_label.pack(side="right", padx=(0, 4))
        swatch = tk.Button(
            box,
            text="",
            bg=value,
            activebackground=value,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER_STRONG,
            width=3,
            height=1,
            cursor="hand2",
        )
        swatch.pack(side="right", padx=(0, 8))

        def pick() -> None:
            _rgb, chosen = colorchooser.askcolor(
                color=value, parent=self.winfo_toplevel(), title=f"选择{label}"
            )
            if not chosen:
                return
            chosen = chosen.upper()
            swatch.configure(bg=chosen, activebackground=chosen)
            value_label.configure(text=chosen)
            callback(chosen)

        swatch.configure(command=pick)

    # -- 数据操作 -----------------------------------------------------
    def _change(self, mutation: Callable[[], None]) -> None:
        mutation()
        self._notify()

    def _notify(self, *, rebuild_sidebar: bool = False) -> None:
        self.on_change(rebuild_sidebar=rebuild_sidebar)

    def _add_item(self, section_type: str) -> None:
        section = get_section(self.resume, section_type)
        section["data"].setdefault("items", []).append(empty_item(section_type))
        self._notify(rebuild_sidebar=True)
        self._scroll_to_bottom = True
        self._focus_new_item = True
        self.show(section_type, tab_index=0)

    def _delete_item(self, section_type: str, index: int) -> None:
        section = get_section(self.resume, section_type)
        items = section["data"].get("items", [])
        if index < 0 or index >= len(items):
            return
        if any(str(value).strip() for value in items[index].values()):
            confirmed = messagebox.askyesno(
                "删除内容",
                "确定删除这条记录吗？该操作在当前雏形中不能撤销。",
                parent=self.winfo_toplevel(),
            )
            if not confirmed:
                return
        items.pop(index)
        self._notify(rebuild_sidebar=True)
        self.show(section_type, tab_index=0)

    def _move_item(self, section_type: str, index: int, direction: int) -> None:
        section = get_section(self.resume, section_type)
        items = section["data"].get("items", [])
        target = index + direction
        if 0 <= index < len(items) and 0 <= target < len(items):
            items[index], items[target] = items[target], items[index]
            self._notify(rebuild_sidebar=True)
            self.show(section_type, tab_index=0)


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------


class ResumeStudio(tk.Tk):
    def __init__(self, library_path: str | Path | None = None) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=theme.APP_BG)
        self.minsize(1180, 740)
        width, height = 1360, 850
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 18)
        self.geometry(f"{width}x{height}+{x}+{y}")

        configure_styles(self)
        self.fonts = theme.available_display_fonts(self)
        self.library_path = (
            Path(library_path) if library_path is not None else default_library_path()
        )
        self._library_load_warning = ""
        entries, active = self._read_library()
        self._library_needs_save = not entries
        if not entries:
            created = sample_resume()
            entries = [make_entry(created, name=person_name(created))]
            active = 0
        self.library_entries: list[dict] = entries
        self.active_index = active
        current = self.library_entries[self.active_index]
        self.resume = current["resume"]
        self.current_path = (
            Path(current["path"]) if current.get("path") else None
        )
        self.selected = "basic"
        self.dirty = False
        self._sidebar_job = None
        self._library_job = None
        self._layout_overflow = False
        self._library_var = tk.IntVar(value=self.active_index)
        self._photo_thumb = None

        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self.reload_document(selected="basic")
        self._update_theme_button()
        self._update_library_switcher()
        initial_saved = True
        if self._library_needs_save:
            initial_saved = self._save_library_now(silent=True)
        if self._library_load_warning:
            self.set_status(self._library_load_warning, "error")
        elif not initial_saved:
            self.set_status("简历库保存失败，请检查用户数据目录权限", "error")
        else:
            message = (
                "已载入示例简历，可直接编辑"
                if self._library_needs_save
                else f"已载入简历库 · {len(self.library_entries)} 份"
            )
            self.set_status(message, "success")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _read_library(self) -> tuple[list[dict], int]:
        try:
            return load_library(self.library_path)
        except Exception as exc:  # noqa: BLE001
            backup = self.library_path.with_name(self.library_path.name + ".broken")
            backup_name = ""
            try:
                if self.library_path.is_file():
                    self.library_path.replace(backup)
                    backup_name = backup.name
            except Exception:
                backup_name = ""
            suffix = f"；原文件已备份为 {backup_name}" if backup_name else ""
            self._library_load_warning = f"简历库读取失败：{exc}{suffix}"
            return [], 0

    # -- UI -----------------------------------------------------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="新建简历", accelerator="Ctrl+N", command=self.new_document)
        file_menu.add_command(label="导入简历…", accelerator="Ctrl+O", command=self.import_document)
        file_menu.add_separator()
        file_menu.add_command(label="保存当前简历 JSON", accelerator="Ctrl+S", command=self.save)
        file_menu.add_command(
            label="另存为…", accelerator="Ctrl+Shift+S", command=lambda: self.save(save_as=True)
        )
        file_menu.add_command(label="导出 Word…", accelerator="Ctrl+E", command=self.export_word)
        file_menu.add_command(label="导出 PDF…", accelerator="Ctrl+Shift+E", command=self.export_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="载入示例", command=self.load_sample)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        resume_menu = tk.Menu(menubar, tearoff=False)
        resume_menu.add_command(label="新建简历", accelerator="Ctrl+N", command=self.new_document)
        resume_menu.add_command(label="复制当前简历", command=self.duplicate_resume)
        resume_menu.add_command(label="重命名当前简历…", command=self.rename_resume)
        resume_menu.add_command(label="删除当前简历", command=self.delete_resume)
        resume_menu.add_separator()
        resume_menu.add_command(label="打开简历库所在文件夹", command=self.open_library_folder)
        menubar.add_cascade(label="简历", menu=resume_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="放大预览", accelerator="Ctrl++", command=lambda: self.preview.step_zoom(1))
        view_menu.add_command(label="缩小预览", accelerator="Ctrl+-", command=lambda: self.preview.step_zoom(-1))
        view_menu.add_command(label="适应宽度", command=lambda: self.preview.fit_width())
        menubar.add_cascade(label="视图", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="使用说明", command=self.show_help)
        help_menu.add_command(label="关于", command=self.show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.configure(menu=menubar)

    def _build_ui(self) -> None:
        self.topbar = tk.Frame(self, bg=theme.PANEL_BG, height=68)
        self.topbar.pack(fill="x")
        self.topbar.pack_propagate(False)
        self._build_brand()
        self._build_library_switcher()
        self._build_top_actions()
        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=theme.APP_BG)
        body.pack(fill="both", expand=True)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(0, minsize=232)
        body.grid_columnconfigure(2, minsize=356)

        self.sidebar = Sidebar(body, on_select=self.select_target)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        center = tk.Frame(body, bg=theme.APP_BG)
        center.grid(row=0, column=1, sticky="nsew")
        self.preview = ResumePreview(
            center,
            on_select=self.select_target,
            on_layout=self._on_layout,
        )
        self.preview.pack(fill="both", expand=True)

        self.inspector = Inspector(
            body,
            resume=self.resume,
            fonts=self.fonts,
            on_change=self.on_model_change,
        )
        self.inspector.grid(row=0, column=2, sticky="nsew")

        self._build_statusbar()

    def _build_brand(self) -> None:
        brand = tk.Frame(self.topbar, bg=theme.PANEL_BG)
        brand.pack(side="left", padx=20, pady=11)
        icon = tk.Canvas(
            brand,
            width=42,
            height=42,
            bg=theme.PANEL_BG,
            highlightthickness=0,
        )
        icon.pack(side="left")
        icon.create_rectangle(0, 0, 42, 42, fill=theme.ACCENT, outline="")
        icon.create_text(
            21,
            21,
            text="简",
            fill="#FFFFFF",
            font=(theme.UI_FONT, 18, "bold"),
        )
        text_box = tk.Frame(brand, bg=theme.PANEL_BG)
        text_box.pack(side="left", padx=(11, 0))
        tk.Label(
            text_box,
            text="简历工坊",
            bg=theme.PANEL_BG,
            fg=theme.TEXT,
            font=(theme.UI_FONT, 14, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            text_box,
            text="结构化简历编辑器 · 雏形",
            bg=theme.PANEL_BG,
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
            anchor="w",
        ).pack(fill="x", pady=(1, 0))

    def _build_library_switcher(self) -> None:
        box = tk.Frame(self.topbar, bg=theme.PANEL_BG)
        box.pack(side="left", padx=(26, 0), pady=(9, 7))
        self.library_caption = tk.Label(
            box,
            text="我的简历",
            bg=theme.PANEL_BG,
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
            anchor="w",
        )
        self.library_caption.pack(fill="x")
        self.library_button = tk.Menubutton(
            box,
            text="1. 林清越  ▾",
            bg=theme.PANEL_BG,
            fg=theme.TEXT,
            activebackground="#F3F5F9",
            activeforeground=theme.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=1,
            font=(theme.UI_FONT, 10, "bold"),
            anchor="w",
            cursor="hand2",
        )
        self.library_button.pack(fill="x")
        self.library_menu = tk.Menu(self.library_button, tearoff=False)
        self.library_button.configure(menu=self.library_menu)
        self._rebuild_library_menu()

    def _truncate(self, text: str, length: int = 20) -> str:
        text = str(text or "").strip()
        return text if len(text) <= length else text[: length - 1] + "…"

    def _rebuild_library_menu(self) -> None:
        menu = self.library_menu
        menu.delete(0, "end")
        for index, entry in enumerate(self.library_entries):
            menu.add_radiobutton(
                label=f"{index + 1}. {self._truncate(entry.get('name', '未命名简历'), 28)}",
                variable=self._library_var,
                value=index,
                command=lambda idx=index: self.switch_resume(idx),
            )
        menu.add_separator()
        menu.add_command(label="新建空白简历", command=self.new_document)
        menu.add_command(label="复制当前简历", command=self.duplicate_resume)
        menu.add_command(label="重命名当前简历…", command=self.rename_resume)
        menu.add_separator()
        menu.add_command(label="删除当前简历", command=self.delete_resume)
        menu.add_separator()
        menu.add_command(label="打开简历库所在文件夹", command=self.open_library_folder)

    def _update_library_switcher(self) -> None:
        if not hasattr(self, "library_button"):
            return
        entry = self.library_entries[self.active_index]
        name = self._truncate(entry.get("name", "未命名简历"), 18)
        self.library_button.configure(text=f"{self.active_index + 1}. {name}  ▾")
        self.library_caption.configure(
            text=f"我的简历 · {len(self.library_entries)} 份"
        )
        self._library_var.set(self.active_index)
        self._rebuild_library_menu()

    def _build_top_actions(self) -> None:
        actions = tk.Frame(self.topbar, bg=theme.PANEL_BG)
        actions.pack(side="right", padx=18, pady=14)
        self.theme_button = self._top_button(
            actions, "主题色", self.choose_accent_color, primary=False
        )
        self.theme_button.pack(side="left", padx=(0, 8))
        self._top_button(actions, "新建", self.new_document, primary=False).pack(
            side="left", padx=(0, 6)
        )
        self._top_button(actions, "导入简历", self.import_document, primary=False).pack(
            side="left", padx=(0, 6)
        )
        self._top_button(actions, "保存", self.save, primary=False).pack(
            side="left", padx=(0, 6)
        )
        self._top_button(actions, "导出 PDF", self.export_pdf, primary=False).pack(
            side="left", padx=(0, 6)
        )
        self._top_button(actions, "导出 Word", self.export_word, primary=True).pack(
            side="left"
        )

    def _top_button(self, parent, text: str, command, *, primary: bool) -> tk.Button:
        if primary:
            bg, fg, hover, active_fg = theme.ACCENT, "#FFFFFF", theme.ACCENT_HOVER, "#FFFFFF"
        else:
            bg, fg, hover, active_fg = "#F3F5F9", "#344054", "#E9EDF3", "#1D2939"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=active_fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=14,
            pady=7,
            font=(theme.UI_FONT, 9),
            cursor="hand2",
        )
        button.bind(
            "<Enter>",
            lambda _event: button.configure(bg=hover),
            add="+",
        )
        button.bind(
            "<Leave>",
            lambda _event: button.configure(bg=bg),
            add="+",
        )
        return button

    def _update_theme_button(self) -> None:
        if not hasattr(self, "theme_button"):
            return
        accent = self.resume.get("theme", {}).get("accent", theme.ACCENT)
        self.theme_button.configure(text="● 主题色", fg=accent)

    def choose_accent_color(self) -> None:
        _rgb, chosen = colorchooser.askcolor(
            color=self.resume["theme"].get("accent", theme.ACCENT),
            parent=self,
            title="选择主题色",
        )
        if not chosen:
            return
        self.resume["theme"]["accent"] = str(chosen).upper()
        self.on_model_change()
        self._update_theme_button()
        if self.inspector.selected == "page":
            self.inspector.show("page", tab_index=self.inspector.current_tab)
        self.set_status("已更换主题色", "success")

    def _build_statusbar(self) -> None:
        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x")
        self.statusbar = tk.Frame(self, bg="#F8FAFC", height=30)
        self.statusbar.pack(fill="x")
        self.statusbar.pack_propagate(False)
        self.status_dot = tk.Canvas(
            self.statusbar,
            width=12,
            height=12,
            bg="#F8FAFC",
            highlightthickness=0,
        )
        self.status_dot.pack(side="left", padx=(16, 0))
        self._dot = self.status_dot.create_oval(2, 2, 10, 10, fill=theme.SUCCESS, outline="")
        self.status_label = tk.Label(
            self.statusbar,
            text="",
            bg="#F8FAFC",
            fg=theme.MUTED,
            font=(theme.UI_FONT, 8),
            anchor="w",
        )
        self.status_label.pack(side="left", padx=(6, 0))
        self.info_label = tk.Label(
            self.statusbar,
            text="",
            bg="#F8FAFC",
            fg=theme.FAINT,
            font=(theme.UI_FONT, 8),
            anchor="e",
        )
        self.info_label.pack(side="right", padx=16)
        self.set_status("已就绪", "ready")

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-n>", lambda _event: self._shortcut(self.new_document))
        self.bind_all("<Control-o>", lambda _event: self._shortcut(self.import_document))
        self.bind_all("<Control-s>", lambda _event: self._shortcut(self.save))
        self.bind_all(
            "<Control-Shift-S>",
            lambda _event: self._shortcut(lambda: self.save(save_as=True)),
        )
        self.bind_all("<Control-e>", lambda _event: self._shortcut(self.export_word))
        self.bind_all(
            "<Control-Shift-E>",
            lambda _event: self._shortcut(self.export_pdf),
        )
        self.bind_all("<Control-plus>", lambda _event: self._shortcut(lambda: self.preview.step_zoom(1)))
        self.bind_all("<Control-equal>", lambda _event: self._shortcut(lambda: self.preview.step_zoom(1)))
        self.bind_all("<Control-minus>", lambda _event: self._shortcut(lambda: self.preview.step_zoom(-1)))

    @staticmethod
    def _shortcut(action) -> str:
        action()
        return "break"

    # -- 状态 ---------------------------------------------------------
    def set_status(self, message: str, tone: str = "ready") -> None:
        colors = {
            "ready": theme.SUCCESS,
            "dirty": theme.WARNING,
            "success": theme.SUCCESS,
            "error": theme.DANGER,
        }
        self.status_label.configure(text=message)
        self.status_dot.itemconfigure(self._dot, fill=colors.get(tone, theme.SUCCESS))

    def _update_title(self) -> None:
        suffix = " *" if self.dirty else ""
        entry = self._current_entry()
        name = entry.get("name") or person_name(self.resume)
        position = (
            f" [{self.active_index + 1}/{len(self.library_entries)}]"
            if len(self.library_entries) > 1
            else ""
        )
        path_text = f" — {self.current_path.name}" if self.current_path else ""
        self.title(f"{name} - {APP_TITLE}{position}{path_text}{suffix}")

    def _update_info(self) -> None:
        page = self.resume["page"]["paper"]
        layout = "内容超页" if self._layout_overflow else "单页"
        self.info_label.configure(
            text=f"{page} · {layout} · {character_count(self.resume):,} 字"
        )

    def _on_layout(self, data: dict) -> None:
        self._layout_overflow = bool(data.get("overflow"))
        self._update_info()

    # -- 选择 ---------------------------------------------------------
    def select_target(self, target: str) -> None:
        if target not in SECTION_TITLES and target != "page":
            return
        self.selected = target
        self.sidebar.set_state(self.resume, target)
        if target == "page":
            self.preview.set_selected("")
            self.inspector.show("page")
        else:
            self.preview.set_selected(target)
            self.inspector.show(target)

    # -- 修改 ---------------------------------------------------------
    def on_model_change(self, *, rebuild_sidebar: bool = False) -> None:
        self.dirty = True
        self._sync_active_entry()
        self._update_theme_button()
        self._update_title()
        self._update_info()
        self.preview.refresh()
        self.set_status("未保存的修改", "dirty")
        if rebuild_sidebar:
            self.sidebar.set_state(self.resume, self.selected)
        else:
            self._schedule_sidebar_refresh()
        self._schedule_library_save()

    def _schedule_sidebar_refresh(self) -> None:
        if self._sidebar_job is not None:
            try:
                self.after_cancel(self._sidebar_job)
            except tk.TclError:
                pass
        self._sidebar_job = self.after(650, self._refresh_sidebar)

    def _refresh_sidebar(self) -> None:
        self._sidebar_job = None
        self.sidebar.set_state(self.resume, self.selected)

    # -- 简历库 -------------------------------------------------------
    def _current_entry(self) -> dict:
        return self.library_entries[self.active_index]

    def _sync_active_entry(self) -> bool:
        if not self.library_entries:
            return False
        entry = self._current_entry()
        entry["resume"] = self.resume
        entry["path"] = str(self.current_path) if self.current_path else ""
        name_changed = False
        if not entry.get("custom_name", False):
            resolved = person_name(self.resume)
            other_names = {
                other.get("name")
                for index, other in enumerate(self.library_entries)
                if index != self.active_index
            }
            if (
                resolved
                and resolved != "未命名简历"
                and resolved not in other_names
                and entry.get("name") != resolved
            ):
                entry["name"] = resolved
                name_changed = True
        if name_changed:
            self._update_library_switcher()
        return name_changed

    def _schedule_library_save(self) -> None:
        if self._library_job is not None:
            try:
                self.after_cancel(self._library_job)
            except tk.TclError:
                pass
        self._library_job = self.after(900, self._autosave_library)

    def _autosave_library(self) -> None:
        self._library_job = None
        if not self._save_library_now(silent=True):
            return
        if self.dirty:
            self.dirty = False
            self._update_title()
            if self.status_label.cget("text") == "未保存的修改":
                self.set_status("已自动保存到简历库", "success")

    def _save_library_now(self, *, silent: bool = False) -> bool:
        if self._library_job is not None:
            try:
                self.after_cancel(self._library_job)
            except tk.TclError:
                pass
            self._library_job = None
        self._sync_active_entry()
        try:
            save_library(self.library_path, self.library_entries, self.active_index)
        except Exception as exc:  # noqa: BLE001
            if not silent:
                messagebox.showerror(
                    "简历库保存失败", str(exc), parent=self.winfo_toplevel()
                )
            self.set_status(f"简历库保存失败：{exc}", "error")
            return False
        return True

    def _unique_entry_name(self, base: str) -> str:
        names = {entry.get("name", "") for entry in self.library_entries}
        base = base.strip() or "未命名简历"
        if base not in names:
            return base
        index = 2
        while f"{base} {index}" in names:
            index += 1
        return f"{base} {index}"

    def _load_entry(self, index: int, message: str = "") -> None:
        entry = self.library_entries[index]
        self.active_index = index
        self.resume = entry["resume"]
        self.current_path = Path(entry["path"]) if entry.get("path") else None
        self.selected = "basic"
        self.dirty = False
        self.reload_document(selected="basic")
        self._update_library_switcher()
        self._update_theme_button()
        if message:
            self.set_status(message, "success")

    def switch_resume(self, index: int) -> None:
        if index < 0 or index >= len(self.library_entries):
            return
        if index == self.active_index:
            return
        self._save_library_now(silent=True)
        self._load_entry(index, f"已切换到「{self.library_entries[index]['name']}」")
        self._save_library_now(silent=True)

    def open_library_folder(self) -> None:
        folder = self.library_path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                messagebox.showinfo("简历库位置", str(folder), parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo(
                "简历库位置",
                f"{folder}\n\n无法打开文件夹：{exc}",
                parent=self,
            )

    def duplicate_resume(self) -> None:
        self._save_library_now(silent=True)
        entry = self._current_entry()
        copied = copy.deepcopy(self.resume)
        name = self._unique_entry_name(f"{entry.get('name', '未命名简历')} 副本")
        new_entry = make_entry(copied, name=name, custom_name=True)
        insert_at = self.active_index + 1
        self.library_entries.insert(insert_at, new_entry)
        self._load_entry(insert_at, f"已复制为「{name}」")
        self._save_library_now(silent=True)

    def rename_resume(self) -> None:
        entry = self._current_entry()
        name = simpledialog.askstring(
            "重命名简历",
            "简历名称：",
            initialvalue=entry.get("name", ""),
            parent=self,
        )
        if name is None:
            return
        name = name.strip()[:60]
        if not name:
            return
        entry["name"] = name
        entry["custom_name"] = True
        self._update_library_switcher()
        self._update_title()
        self._save_library_now(silent=True)
        self.set_status(f"已重命名为「{name}」", "success")

    def delete_resume(self) -> None:
        if len(self.library_entries) <= 1:
            messagebox.showinfo(
                "无法删除",
                "简历库至少需要保留一份简历。",
                parent=self,
            )
            return
        entry = self._current_entry()
        if not messagebox.askyesno(
            "删除简历",
            f"确定从简历库移除「{entry.get('name', '当前简历')}」吗？\n"
            "已经单独保存的 JSON 文件不会被删除。",
            parent=self,
        ):
            return
        old_index = self.active_index
        del self.library_entries[old_index]
        new_index = min(old_index, len(self.library_entries) - 1)
        self._load_entry(new_index, "已从简历库移除")
        self._save_library_now(silent=True)

    # -- 文档生命周期 -------------------------------------------------
    def reload_document(self, *, selected: str = "basic", message: str = "") -> None:
        self.selected = selected
        self.sidebar.set_state(self.resume, selected)
        self.inspector.set_resume(self.resume)
        self.preview.set_resume(self.resume)
        if selected == "page":
            self.preview.set_selected("")
            self.inspector.show("page")
        else:
            self.preview.set_selected(selected)
            self.inspector.show(selected)
        self._update_title()
        self._update_info()
        self._update_theme_button()
        if message:
            self.set_status(message, "success" if not self.dirty else "dirty")

    def _next_untitled_name(self) -> str:
        names = {entry.get("name", "") for entry in self.library_entries}
        index = 1
        while f"未命名简历 {index}" in names:
            index += 1
        return f"未命名简历 {index}"

    def new_document(self) -> None:
        self._save_library_now(silent=True)
        resume = blank_resume()
        name = self._next_untitled_name()
        entry = make_entry(resume, name=name)
        insert_at = self.active_index + 1
        self.library_entries.insert(insert_at, entry)
        self._load_entry(insert_at, "已新建空白简历")
        self._save_library_now(silent=True)
        self.set_status("空白简历 · 从“基本信息”开始填写", "ready")

    def load_sample(self) -> None:
        self._save_library_now(silent=True)
        resume = sample_resume()
        name = self._unique_entry_name(f"{person_name(resume)} · 示例")
        entry = make_entry(resume, name=name, custom_name=True)
        insert_at = self.active_index + 1
        self.library_entries.insert(insert_at, entry)
        self._load_entry(insert_at, "已载入示例简历")
        self._save_library_now(silent=True)
        self.set_status("示例简历 · 可直接修改，或在简历库中复制", "ready")

    def import_document(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="导入简历",
            initialdir=str(Path.cwd()),
            filetypes=[
                ("支持的简历文件", "*.docx *.json *.txt *.md"),
                ("Word 文档", "*.docx"),
                ("文本文件", "*.txt *.md"),
                ("项目 JSON", "*.json"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            result = import_resume(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导入失败", str(exc), parent=self)
            self.set_status("导入失败", "error")
            return

        self._save_library_now(silent=True)
        source = Path(path)
        name = person_name(result.resume)
        if not name or name == "未命名简历":
            name = source.stem
        name = self._unique_entry_name(name)
        entry = make_entry(
            result.resume,
            name=name,
            path=str(source) if source.suffix.lower() == ".json" else None,
        )
        insert_at = self.active_index + 1
        self.library_entries.insert(insert_at, entry)
        self.active_index = insert_at
        self.resume = result.resume
        self.current_path = (
            source if source.suffix.lower() == ".json" else None
        )
        self.dirty = source.suffix.lower() != ".json"
        self.selected = "basic"
        self.reload_document(selected="basic")
        self._update_library_switcher()
        self._update_theme_button()
        self._save_library_now(silent=True)
        self.dirty = False
        self._update_title()
        self.set_status(f"已导入 {source.suffix.lower()} 并加入简历库", "success")

        if result.warnings:
            lines = result.warnings[:7]
            if len(result.warnings) > 7:
                lines.append(f"……另有 {len(result.warnings) - 7} 条提示")
            messagebox.showinfo(
                "导入完成",
                "内容已映射到固定区域，请检查各区域字段。\n\n"
                + "\n".join(f"• {line}" for line in lines),
                parent=self,
            )

    def save(self, save_as: bool = False) -> bool:
        path = self.current_path
        if save_as or path is None:
            chosen = filedialog.asksaveasfilename(
                parent=self,
                title="保存当前简历 JSON",
                initialdir=str(Path.cwd()),
                initialfile=f"{file_stem(self.resume)}.json",
                defaultextension=".json",
                filetypes=[("简历项目", "*.json")],
            )
            if not chosen:
                return False
            path = Path(chosen)
        try:
            saved_path = save_project(self.resume, path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc), parent=self)
            self.set_status("保存失败", "error")
            return False
        self.current_path = saved_path
        self._current_entry()["path"] = str(saved_path)
        self.dirty = False
        self._update_title()
        self._save_library_now(silent=True)
        self.set_status(f"已保存：{saved_path.name}", "success")
        return True

    def export_word(self) -> None:
        chosen = filedialog.asksaveasfilename(
            parent=self,
            title="导出 Word",
            initialdir=str(Path.cwd()),
            initialfile=f"{file_stem(self.resume)}.docx",
            defaultextension=".docx",
            filetypes=[("Word 文档", "*.docx")],
        )
        if not chosen:
            return
        try:
            path = export_docx(self.resume, chosen)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc), parent=self)
            self.set_status("导出失败", "error")
            return
        self.set_status(f"已导出 Word：{path.name}", "success")
        messagebox.showinfo(
            "导出完成",
            f"已生成 Word 文档：\n{path}\n\n"
            "Word 中的字体和间距由预览参数换算生成，复杂排版可能需要在 Word 中再微调。",
            parent=self,
        )

    def export_pdf(self) -> None:
        chosen = filedialog.asksaveasfilename(
            parent=self,
            title="导出 PDF",
            initialdir=str(Path.cwd()),
            initialfile=f"{file_stem(self.resume)}.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF 文档", "*.pdf")],
        )
        if not chosen:
            return
        try:
            path = export_pdf_file(self.resume, chosen)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc), parent=self)
            self.set_status("导出失败", "error")
            return
        self.set_status(f"已导出 PDF：{path.name}", "success")
        messagebox.showinfo(
            "导出完成",
            f"已生成 PDF 文档：\n{path}\n\n"
            "PDF 使用矢量文字，并按页面内容自动分页；如需严格单页，请先在预览中检查超页提示。",
            parent=self,
        )

    def _on_close(self) -> None:
        if not self._save_library_now():
            if not messagebox.askyesno(
                "简历库保存失败",
                "当前修改未能写入简历库，仍要退出吗？",
                parent=self,
            ):
                return
        self.destroy()

    def destroy(self) -> None:
        for job_name in ("_sidebar_job", "_library_job"):
            job = getattr(self, job_name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, job_name, None)
        preview = getattr(self, "preview", None)
        if preview is not None:
            try:
                preview.destroy()
            except tk.TclError:
                pass
        super().destroy()

    # -- 帮助 ---------------------------------------------------------
    def show_help(self) -> None:
        messagebox.showinfo(
            "使用说明",
            "1. 顶部“我的简历”可以新建、切换、复制、重命名或删除多份简历。\n"
            "2. 左侧选择区域，右侧“内容”只显示该区域允许的字段。\n"
            "3. 在“基本信息”顶部的照片卡片可以选择个人图片，显示在简历顶部。\n"
            "4. 在“排版”中单独调整当前区域的字体、字号、对齐、行距和间距。\n"
            "5. 页面设置 → 主题可改主题色，也可以用顶部“主题色”快速换色。\n"
            "6. 导入支持 .docx / .json / .txt / .md；Word 导入是智能识别，复杂排版请检查字段。\n"
            "7. Ctrl+S 保存当前简历 JSON，Ctrl+E 导出 Word，Ctrl+Shift+E 导出 PDF。",
            parent=self,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            "简历工坊 · 结构化简历编辑器（雏形）\n\n"
            "Python 3.11 + Tkinter\n"
            "多简历库、固定区域字段、区域级排版、个人照片、PDF / Word 导出。\n"
            "照片使用 Pillow，PDF 使用 ReportLab。",
            parent=self,
        )


def _enable_windows_dpi_awareness() -> None:
    """避免 Windows 125%/150% 缩放把窗口拉伸成模糊的大图。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def run() -> None:
    _enable_windows_dpi_awareness()
    app = ResumeStudio()
    app.mainloop()
