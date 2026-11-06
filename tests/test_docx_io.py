import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from resume_editor import photo
from resume_editor.docx_io import export_docx, import_docx, import_txt
from resume_editor.model import get_section, sample_resume


class DocxTests(unittest.TestCase):
    def test_export_and_reimport_sample(self):
        source = sample_resume()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resume.docx"
            export_docx(source, path)
            self.assertTrue(path.exists())
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                self.assertIn("word/document.xml", names)
                self.assertIn("word/styles.xml", names)
                self.assertIn("[Content_Types].xml", names)

            result = import_docx(path)
            self.assertEqual(result.warnings, [])
            b = get_section(result.resume, "basic")["data"]
            self.assertEqual(b["name"], "林清越")
            self.assertEqual(b["phone"], "138 0013 8000")
            self.assertEqual(b["email"], "lin.qingyue@example.com")

            education = get_section(result.resume, "education")["data"]["items"]
            self.assertEqual(len(education), 1)
            self.assertEqual(education[0]["school"], "复旦大学")
            self.assertEqual(education[0]["start"], "2016.09")
            self.assertIn("主修课程", education[0]["details"])

            work = get_section(result.resume, "work")["data"]["items"]
            self.assertEqual(work[0]["company"], "云舟科技")
            self.assertEqual(work[0]["position"], "产品经理")
            self.assertIn("日活用户", work[0]["details"])

            projects = get_section(result.resume, "projects")["data"]["items"]
            self.assertEqual(projects[0]["role"], "项目负责人")

            self.assertEqual(
                len(get_section(result.resume, "skills")["data"]["items"]), 3
            )
            self.assertEqual(
                get_section(result.resume, "awards")["data"]["items"][0]["issuer"],
                "云舟科技",
            )

    @unittest.skipUnless(photo.HAS_PIL, "照片往返测试需要 Pillow")
    def test_photo_roundtrip_through_docx(self):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (300, 400), "#DCE7F5")
        draw = ImageDraw.Draw(image)
        draw.ellipse((95, 60, 205, 190), fill="#F1D0BB")
        draw.ellipse((50, 225, 250, 430), fill="#2F5E8F")
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=90)
        photo_data = photo.encode_photo_bytes(buffer.getvalue())

        source = sample_resume()
        get_section(source, "basic")["data"][photo.PHOTO_KEY] = photo_data
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "photo.docx"
            export_docx(source, path)
            with zipfile.ZipFile(path) as archive:
                self.assertIn("word/media/photo.jpg", archive.namelist())
                media = archive.read("word/media/photo.jpg")
            self.assertGreater(len(media), 1000)
            result = import_docx(path)
            self.assertEqual(result.warnings, [])
            restored = get_section(result.resume, "basic")["data"][photo.PHOTO_KEY]
            self.assertTrue(restored.startswith("data:image/jpeg;base64,"))
            parsed = photo.parse_data_uri(restored)
            self.assertIsNotNone(parsed)
            self.assertEqual(photo.image_dimensions(parsed[1]), (500, 640))

    def test_plain_text_import_maps_headings(self):
        text = """王小明
求职意向：Java 后端工程师
电话：139 1234 5678 ｜ 邮箱：wang@example.com ｜ 城市：杭州 ｜ github.com/wangxm

教育经历
北京大学 | 计算机科学与技术 | 本科
2018.09 - 2022.06
主修课程：数据结构、操作系统
GPA 3.7/4.0

工作经历
字节跳动 | 后端开发工程师
2022.07 - 至今
负责推荐服务接口设计与性能优化
QPS 提升 40%

项目经历
内容推荐系统 | 项目负责人
2023.01 - 2023.08
设计召回与排序链路，日请求量 2000 万

专业技能
Java：Spring Boot、JVM 调优
数据库：MySQL、Redis

获奖情况
优秀毕业生
2022.06 北京大学

自我评价
热爱后端技术，关注系统性能与工程质量。
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resume.txt"
            path.write_text(text, encoding="utf-8")
            result = import_txt(path)
        basic = get_section(result.resume, "basic")["data"]
        self.assertEqual(basic["name"], "王小明")
        self.assertEqual(basic["job"], "Java 后端工程师")
        self.assertEqual(basic["city"], "杭州")
        self.assertEqual(basic["website"], "github.com/wangxm")

        education = get_section(result.resume, "education")["data"]["items"][0]
        self.assertEqual(education["school"], "北京大学")
        self.assertEqual(education["major"], "计算机科学与技术")
        self.assertEqual(education["degree"], "本科")

        work = get_section(result.resume, "work")["data"]["items"][0]
        self.assertEqual(work["company"], "字节跳动")
        self.assertEqual(work["position"], "后端开发工程师")
        self.assertIn("QPS 提升 40%", work["details"])

        project = get_section(result.resume, "projects")["data"]["items"][0]
        self.assertEqual(project["role"], "项目负责人")
        self.assertIn("2000 万", project["details"])

        award = get_section(result.resume, "awards")["data"]["items"][0]
        self.assertEqual(award["title"], "优秀毕业生")
        self.assertEqual(award["date"], "2022.06")
        self.assertEqual(award["issuer"], "北京大学")

        self.assertIn(
            "热爱后端技术",
            get_section(result.resume, "self_eval")["data"]["content"],
        )


if __name__ == "__main__":
    unittest.main()
