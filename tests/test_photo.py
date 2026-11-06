import unittest
from io import BytesIO

from resume_editor import photo
from resume_editor.model import blank_resume, character_count, normalize_resume


def _test_photo() -> str:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (300, 400), "#DCE7F5")
    draw = ImageDraw.Draw(image)
    draw.ellipse((95, 60, 205, 190), fill="#F1D0BB")
    draw.ellipse((50, 225, 250, 430), fill="#2F5E8F")
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return photo.encode_photo_bytes(buffer.getvalue())


@unittest.skipUnless(photo.HAS_PIL, "照片测试需要 Pillow")
class PhotoTests(unittest.TestCase):
    def test_encode_crops_to_portrait_ratio(self):
        data = _test_photo()
        self.assertTrue(data.startswith("data:image/jpeg;base64,"))
        parsed = photo.parse_data_uri(data)
        self.assertIsNotNone(parsed)
        self.assertEqual(photo.image_dimensions(parsed[1]), (500, 640))

    def test_normalize_rejects_broken_data(self):
        self.assertEqual(photo.normalize_photo(""), "")
        self.assertEqual(photo.normalize_photo("not-an-image"), "")
        self.assertEqual(photo.normalize_photo("data:image/png;base64,!!!!"), "")

    def test_photo_is_whitelisted_but_not_counted_as_text(self):
        resume = blank_resume()
        before = character_count(resume)
        resume["sections"][0]["data"]["photo"] = _test_photo()
        normalized = normalize_resume(resume)
        self.assertTrue(normalized["sections"][0]["data"]["photo"])
        self.assertEqual(character_count(normalized), before)

    def test_unknown_photo_variant_is_ignored(self):
        resume = blank_resume()
        resume["sections"][0]["data"]["photo"] = "https://example.com/a.jpg"
        warnings = []
        normalized = normalize_resume(resume, warnings)
        self.assertEqual(normalized["sections"][0]["data"]["photo"], "")
        self.assertTrue(any("照片" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
