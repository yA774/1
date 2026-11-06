import copy
import unittest

from resume_editor.model import (
    BASIC_FIELDS,
    ITEM_FIELDS,
    SECTION_ORDER,
    SECTION_TITLES,
    blank_resume,
    character_count,
    empty_item,
    normalize_resume,
    sample_resume,
    section_has_content,
    section_summary,
)


class ModelTests(unittest.TestCase):
    def test_blank_resume_has_all_fixed_sections(self):
        resume = blank_resume()
        self.assertEqual([s["type"] for s in resume["sections"]], SECTION_ORDER)
        self.assertEqual(
            [s["title"] for s in resume["sections"]],
            [SECTION_TITLES[t] for t in SECTION_ORDER],
        )

    def test_import_rejects_unknown_fields(self):
        raw = blank_resume()
        basic = raw["sections"][0]
        basic["data"]["name"] = "张三"
        basic["data"]["secret"] = "不应出现"
        work = raw["sections"][2]
        work["data"]["items"] = [
            {
                "company": "示例公司",
                "position": "产品经理",
                "details": "负责一个项目",
                "salary": "不应出现",
            }
        ]
        warnings = []
        resume = normalize_resume(raw, warnings)
        self.assertNotIn("secret", resume["sections"][0]["data"])
        self.assertNotIn("salary", resume["sections"][2]["data"]["items"][0])
        self.assertTrue(any("非白名单" in warning for warning in warnings))

    def test_unknown_section_is_ignored(self):
        raw = blank_resume()
        raw["sections"].append(
            {
                "type": "hack_section",
                "title": "任意区域",
                "data": {"items": [{"anything": "x"}]},
            }
        )
        warnings = []
        resume = normalize_resume(raw, warnings)
        self.assertEqual(len(resume["sections"]), len(SECTION_ORDER))
        self.assertNotIn("hack_section", [s["type"] for s in resume["sections"]])
        self.assertTrue(any("未知区域" in warning for warning in warnings))

    def test_style_values_are_clamped(self):
        raw = blank_resume()
        raw["page"]["margin_left"] = 999
        raw["page"]["paper"] = "A4"
        style = raw["sections"][1]["style"]
        style["body_size"] = 999
        style["align"] = "diagonal"
        style["line_spacing"] = 0.1
        resume = normalize_resume(raw)
        self.assertEqual(resume["page"]["margin_left"], 40)
        self.assertEqual(resume["sections"][1]["style"]["body_size"], 20)
        self.assertEqual(resume["sections"][1]["style"]["align"], "left")
        self.assertEqual(resume["sections"][1]["style"]["line_spacing"], 1.0)

    def test_sample_roundtrip_has_content(self):
        resume = normalize_resume(sample_resume())
        self.assertGreater(character_count(resume), 100)
        for section in resume["sections"]:
            self.assertTrue(section_has_content(section), section["type"])
        self.assertEqual(section_summary(resume["sections"][4]), "3 条内容")

    def test_each_item_type_has_its_own_whitelist(self):
        for section_type, fields in ITEM_FIELDS.items():
            item = empty_item(section_type)
            self.assertEqual(set(item), {key for key, _ in fields})
        self.assertEqual(
            [key for key, _ in BASIC_FIELDS],
            ["name", "job", "phone", "email", "city", "website"],
        )

    def test_normalize_does_not_mutate_input(self):
        raw = sample_resume()
        snapshot = copy.deepcopy(raw)
        normalize_resume(raw)
        self.assertEqual(raw, snapshot)


if __name__ == "__main__":
    unittest.main()
