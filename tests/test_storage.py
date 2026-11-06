import json
import tempfile
import unittest
from pathlib import Path

from resume_editor.model import blank_resume, get_section, sample_resume
from resume_editor.storage import import_resume, load_project, save_project


class StorageTests(unittest.TestCase):
    def test_project_roundtrip(self):
        resume = sample_resume()
        with tempfile.TemporaryDirectory() as temp:
            path = save_project(resume, Path(temp) / "项目")
            self.assertEqual(path.suffix, ".json")
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["sections"][0]["data"]["name"], "林清越")
            loaded = load_project(path).resume
        self.assertEqual(get_section(loaded, "basic")["data"]["name"], "林清越")
        self.assertEqual(
            len(get_section(loaded, "work")["data"]["items"]),
            1,
        )

    def test_import_json_through_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            path = save_project(blank_resume(), Path(temp) / "blank.json")
            result = import_resume(path)
            self.assertEqual(len(result.resume["sections"]), 7)

    def test_unknown_extension_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resume.pdf"
            path.write_bytes(b"%PDF-1.4")
            with self.assertRaises(ValueError):
                import_resume(path)

    def test_invalid_json_raises_friendly_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError) as context:
                load_project(path)
            self.assertIn("JSON", str(context.exception))


if __name__ == "__main__":
    unittest.main()
