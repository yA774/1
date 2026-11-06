import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from resume_editor import photo
from resume_editor.model import normalize_resume, sample_resume
from resume_editor.pdf_io import HAS_REPORTLAB, export_pdf


@unittest.skipUnless(HAS_REPORTLAB, "PDF 测试需要 ReportLab")
class PdfTests(unittest.TestCase):
    def test_export_pdf_with_photo(self):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (300, 400), "#DCE7F5")
        draw = ImageDraw.Draw(image)
        draw.ellipse((95, 60, 205, 190), fill="#F1D0BB")
        draw.ellipse((50, 225, 250, 430), fill="#2F5E8F")
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=90)
        data = photo.encode_photo_bytes(buffer.getvalue())

        resume = normalize_resume(sample_resume())
        resume["sections"][0]["data"][photo.PHOTO_KEY] = data
        with tempfile.TemporaryDirectory() as temp:
            path = export_pdf(resume, Path(temp) / "resume.pdf")
            payload = path.read_bytes()
        self.assertTrue(payload.startswith(b"%PDF"))
        self.assertTrue(payload.rstrip().endswith(b"%%EOF"))
        self.assertGreater(len(payload), 50000)
        self.assertIn(b"/Subtype /Image", payload)

    def test_export_pdf_without_photo(self):
        with tempfile.TemporaryDirectory() as temp:
            path = export_pdf(normalize_resume(sample_resume()), Path(temp) / "a.pdf")
            payload = path.read_bytes()
        self.assertTrue(payload.startswith(b"%PDF"))
        self.assertNotIn(b"/Subtype /Image", payload)


if __name__ == "__main__":
    unittest.main()
