"""多份简历的本地简历库。

简历库保存在用户数据目录中，与单份简历的 JSON 导出互不冲突：
- 库里可以有多份简历，切换时自动保存；
- “保存项目”仍然把当前简历导出为一份独立 JSON；
- 关闭程序不会丢失库里的修改。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from .model import normalize_resume, person_name

LIBRARY_SCHEMA = "resume-editor/library"
LIBRARY_VERSION = 1
MAX_ENTRIES = 100


def default_library_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        base = Path(appdata) / "ResumeStudio"
    else:
        base = Path.home() / ".resume_studio"
    return base / "library.json"


def make_entry(
    resume: dict,
    *,
    name: str | None = None,
    custom_name: bool = False,
    path: str | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": entry_id or uuid.uuid4().hex,
        "name": (name or person_name(resume) or "未命名简历")[:60],
        "custom_name": bool(custom_name),
        "path": str(path) if path else "",
        "resume": resume,
    }


def load_library(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """读取简历库；文件不存在时返回空库。

    为了兼容早期版本，如果文件本身是一份单简历 JSON，会自动包成一条记录。
    """
    library_path = Path(path)
    if not library_path.is_file():
        return [], 0
    try:
        raw = json.loads(library_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"简历库 JSON 格式错误：第 {exc.lineno} 行，{exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ValueError("简历库格式不正确：顶层应为对象。")

    if raw.get("schema") != LIBRARY_SCHEMA:
        if "sections" not in raw:
            raise ValueError("简历库格式不正确：缺少 resumes 列表。")
        resume = normalize_resume(raw)
        return [make_entry(resume)], 0

    raw_entries = raw.get("resumes")
    if not isinstance(raw_entries, list):
        raise ValueError("简历库格式不正确：resumes 应为列表。")

    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_entries[:MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue
        raw_resume = item.get("resume")
        if not isinstance(raw_resume, dict):
            continue
        try:
            resume = normalize_resume(raw_resume)
        except Exception:
            continue
        entry_id = str(item.get("id") or uuid.uuid4().hex)
        if entry_id in seen_ids:
            entry_id = uuid.uuid4().hex
        seen_ids.add(entry_id)
        entry = make_entry(
            resume,
            name=str(item.get("name") or "") or person_name(resume),
            custom_name=bool(item.get("custom_name", False)),
            path=str(item.get("path") or "") or None,
            entry_id=entry_id,
        )
        entries.append(entry)

    try:
        active = int(raw.get("active", 0))
    except (TypeError, ValueError):
        active = 0
    if entries:
        active = max(0, min(active, len(entries) - 1))
    else:
        active = 0
    return entries, active


def save_library(
    path: str | Path,
    entries: list[dict[str, Any]],
    active: int,
) -> Path:
    library_path = Path(path)
    library_path.parent.mkdir(parents=True, exist_ok=True)
    if entries:
        active = max(0, min(int(active), len(entries) - 1))
    else:
        active = 0
    payload = {
        "schema": LIBRARY_SCHEMA,
        "version": LIBRARY_VERSION,
        "active": active,
        "resumes": entries,
    }
    temp = library_path.with_name(library_path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, library_path)
    return library_path
