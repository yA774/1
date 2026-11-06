"""项目文件与导入入口。"""

from __future__ import annotations

import json
from pathlib import Path

from .docx_io import ImportResult, import_docx, import_txt
from .model import normalize_resume

SUPPORTED_IMPORT_EXTENSIONS = {".json", ".docx", ".txt", ".md"}


def save_project(resume: dict, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.write_text(
        json.dumps(resume, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_project(path: str | Path) -> ImportResult:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行，{exc.msg}") from exc
    warnings: list[str] = []
    resume = normalize_resume(raw, warnings)
    return ImportResult(resume=resume, warnings=warnings)


def import_resume(path: str | Path) -> ImportResult:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_project(path)
    if suffix == ".docx":
        return import_docx(path)
    if suffix in {".txt", ".md"}:
        return import_txt(path)
    if suffix == ".doc":
        raise ValueError("暂不支持旧版 .doc，请在 Word/WPS 中另存为 .docx 后再导入。")
    raise ValueError("暂不支持该文件类型，请选择 .docx、.json、.txt 或 .md 文件。")
