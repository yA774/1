import json
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from resume_editor.ui import ResumeStudio, _enable_windows_dpi_awareness


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


class UISmokeTests(unittest.TestCase):
    def setUp(self):
        _enable_windows_dpi_awareness()
        self.tempdir = tempfile.TemporaryDirectory()
        self.library_path = Path(self.tempdir.name) / "library.json"
        try:
            self.app = ResumeStudio(library_path=self.library_path)
        except tk.TclError as exc:
            self.tempdir.cleanup()
            self.skipTest(f"当前环境没有可用的图形界面：{exc}")
        self.app.withdraw()
        self.app.update_idletasks()
        self.app.update()

    def tearDown(self):
        if getattr(self, "app", None) is not None:
            try:
                self.app.destroy()
            except tk.TclError:
                pass
        self.tempdir.cleanup()

    def test_window_builds_with_preview(self):
        self.app.deiconify()
        self.app.geometry("1200x760+30+30")
        self.app.update()
        self.assertEqual(len(self.app.resume["sections"]), 7)
        self.app.preview.refresh(immediate=True)
        deadline = time.time() + 1.5
        while time.time() < deadline:
            self.app.update()
            time.sleep(0.02)
        self.assertGreater(len(self.app.preview.canvas.find_all()), 20)
        self.assertEqual(self.app.preview.selected, "basic")

    def test_content_edit_updates_model(self):
        self.app.select_target("work")
        self.app.inspector.show("work", tab_index=0)
        self.app.update()
        texts = [
            widget
            for widget in _walk(self.app.inspector.body)
            if isinstance(widget, tk.Text)
        ]
        self.assertTrue(texts)
        text = texts[0]
        text.insert("end", "\n测试新增的一条工作内容")
        text.edit_modified(True)
        text.event_generate("<<Modified>>")
        self.app.update()
        details = (
            self.app.resume["sections"][2]["data"]["items"][0]["details"]
        )
        self.assertTrue(details.endswith("测试新增的一条工作内容"))
        self.assertTrue(self.app.dirty)

    def test_pages_and_section_switch(self):
        self.app.select_target("page")
        self.app.update()
        self.assertEqual(self.app.inspector.selected, "page")
        self.app.select_target("skills")
        self.app.update()
        self.assertEqual(self.app.inspector.selected, "skills")
        self.assertEqual(
            self.app.inspector.title_label.cget("text"), "专业技能"
        )

    def test_multiple_resumes_switch_and_save_library(self):
        first_name = self.app.resume["sections"][0]["data"]["name"]
        self.app.new_document()
        self.app.update()
        self.assertEqual(len(self.app.library_entries), 2)
        self.app.resume["sections"][0]["data"]["name"] = "第二版简历"
        self.app.on_model_change(rebuild_sidebar=True)
        self.app.update()
        self.assertEqual(self.app.library_entries[1]["name"], "第二版简历")
        self.app.switch_resume(0)
        self.app.update()
        self.assertEqual(self.app.resume["sections"][0]["data"]["name"], first_name)
        self.app.switch_resume(1)
        self.app.update()
        self.assertEqual(self.app.resume["sections"][0]["data"]["name"], "第二版简历")
        self.app._save_library_now()
        payload = json.loads(self.library_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["resumes"]), 2)
        self.assertEqual(payload["active"], 1)

    def test_theme_preset_updates_theme_and_button(self):
        self.app.select_target("page")
        self.app.inspector.show("page", tab_index=1)
        self.app.update()
        self.app.inspector._apply_theme_preset("#0F766E")
        self.app.update()
        self.assertEqual(self.app.resume["theme"]["accent"], "#0F766E")
        self.assertEqual(str(self.app.theme_button.cget("fg")), "#0F766E")

    def test_add_empty_item_shows_preview_placeholder(self):
        self.app.deiconify()
        self.app.geometry("1200x760+30+30")
        self.app.update()
        self.app.new_document()
        self.app.select_target("education")
        self.app.inspector._add_item("education")
        deadline = time.time() + 1.2
        while time.time() < deadline:
            self.app.update()
            time.sleep(0.02)
        canvas = self.app.preview.canvas
        texts = [
            str(canvas.itemcget(item, "text"))
            for item in canvas.find_all()
            if canvas.type(item) == "text"
        ]
        self.assertTrue(any("新增条目待填写" in text for text in texts), texts)
        self.assertGreater(len(canvas.find_all()), 5)

    def test_multiple_education_entries_render(self):
        self.app.deiconify()
        self.app.geometry("1200x760+30+30")
        self.app.update()
        education = self.app.resume["sections"][1]
        education["data"]["items"].append(
            {
                "school": "第二大学",
                "major": "软件工程",
                "degree": "硕士",
                "start": "2020.09",
                "end": "2023.06",
                "details": "研究方向：数据系统\n发表论文两篇",
            }
        )
        self.app.on_model_change(rebuild_sidebar=True)
        deadline = time.time() + 1.2
        while time.time() < deadline:
            self.app.update()
            time.sleep(0.02)
        canvas = self.app.preview.canvas
        texts = [
            str(canvas.itemcget(item, "text"))
            for item in canvas.find_all()
            if canvas.type(item) == "text"
        ]
        self.assertIn("第二大学", texts)
        self.assertGreater(len(canvas.find_all()), 20)


if __name__ == "__main__":
    unittest.main()
