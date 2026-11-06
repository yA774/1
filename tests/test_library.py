import json
import tempfile
import unittest
from pathlib import Path

from resume_editor.library import (
    LIBRARY_SCHEMA,
    load_library,
    make_entry,
    save_library,
)
from resume_editor.model import blank_resume, sample_resume


class LibraryTests(unittest.TestCase):
    def test_save_and_load_multiple_entries(self):
        first = make_entry(sample_resume(), name="产品版", custom_name=True)
        second = make_entry(blank_resume(), name="技术版", custom_name=True)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.json"
            save_library(path, [first, second], 1)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema"], LIBRARY_SCHEMA)
            self.assertEqual(raw["active"], 1)
            loaded, active = load_library(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(active, 1)
        self.assertEqual(loaded[0]["name"], "产品版")
        self.assertEqual(
            loaded[0]["resume"]["sections"][0]["data"]["name"], "林清越"
        )
        self.assertEqual(loaded[1]["name"], "技术版")

    def test_missing_library_returns_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            entries, active = load_library(Path(temp) / "nothing.json")
        self.assertEqual(entries, [])
        self.assertEqual(active, 0)

    def test_single_resume_json_is_accepted_as_legacy_library(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "single.json"
            path.write_text(
                json.dumps(sample_resume(), ensure_ascii=False), encoding="utf-8"
            )
            entries, active = load_library(path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(active, 0)
        self.assertEqual(entries[0]["name"], "林清越")

    def test_broken_library_raises_value_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_library(path)


if __name__ == "__main__":
    unittest.main()
