"""界面配色与字体常量。"""

from __future__ import annotations

import tkinter.font as tkfont

APP_BG = "#F3F5F9"
PANEL_BG = "#FFFFFF"
SIDEBAR_BG = "#F8FAFC"
PREVIEW_BG = "#E9EEF5"
BORDER = "#E2E8F0"
BORDER_STRONG = "#CBD5E1"
TEXT = "#172033"
MUTED = "#667085"
FAINT = "#98A2B3"
ACCENT = "#1D4ED8"
ACCENT_HOVER = "#1E40AF"
ACCENT_SOFT = "#EEF4FF"
ACCENT_LINE = "#BFD3FF"
SUCCESS = "#15803D"
WARNING = "#B45309"
DANGER = "#B42318"
INPUT_BG = "#F8FAFC"
HOVER_BG = "#F1F5F9"
CHIP_BG = "#F1F5F9"

UI_FONT = "Microsoft YaHei UI"
UI_FONT_SIZE = 10
SMALL_FONT_SIZE = 9

DISPLAY_FONT_CANDIDATES = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "SimSun",
    "宋体",
    "SimHei",
    "黑体",
    "DengXian",
    "等线",
    "KaiTi",
    "楷体",
    "Arial",
    "Calibri",
    "Georgia",
    "Times New Roman",
]


def available_display_fonts(root) -> list[str]:
    try:
        installed = set(tkfont.families(root))
    except Exception:
        installed = set()
    fonts = [font for font in DISPLAY_FONT_CANDIDATES if font in installed]
    if UI_FONT in installed and UI_FONT not in fonts:
        fonts.insert(0, UI_FONT)
    if not fonts:
        fonts = [UI_FONT, "Arial"]
    return fonts
