"""个人照片的读取、裁剪、编码与预览辅助。

照片会统一裁剪为 25mm × 32mm 的竖向比例（存储为 500 × 640 JPEG），
以 base64 data URI 的形式保存在 basic 区域，方便项目 JSON 单文件携带。

编辑器和 Word 导出不强制依赖 Pillow；只有“选择照片 / 生成缩略图 / 从
Word 提取照片”这些操作需要 Pillow。未安装时会给出明确提示。
"""

from __future__ import annotations

import base64
import binascii
import re
from io import BytesIO
from pathlib import Path

PHOTO_KEY = "photo"
PHOTO_WIDTH_MM = 25.0
PHOTO_HEIGHT_MM = 32.0
PHOTO_GAP_MM = 4.0
PHOTO_STORE_SIZE = (500, 640)
MAX_PHOTO_FILE_BYTES = 20 * 1024 * 1024

try:
    from PIL import Image, ImageOps

    try:
        from PIL import ImageTk

        HAS_TK_PHOTO = True
    except Exception:
        ImageTk = None
        HAS_TK_PHOTO = False
    HAS_PIL = True
except Exception:
    Image = None
    ImageOps = None
    ImageTk = None
    HAS_PIL = False
    HAS_TK_PHOTO = False

_DATA_URI_RE = re.compile(
    r"^data:(image/(?:jpeg|jpg|png|webp));base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_data_uri(value: str) -> tuple[str, bytes] | None:
    if not isinstance(value, str):
        return None
    match = _DATA_URI_RE.match(value.strip())
    if not match:
        return None
    mime = match.group(1).lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    payload = re.sub(r"\s+", "", match.group(2))
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not raw or len(raw) > MAX_PHOTO_FILE_BYTES:
        return None
    return mime, raw


def _data_uri(raw: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _is_canonical(raw: bytes) -> bool:
    """已经是本程序生成的 500×640 JPEG 时不再二次压缩。"""
    if not HAS_PIL:
        return False
    try:
        with Image.open(BytesIO(raw)) as image:
            return (
                image.format == "JPEG"
                and image.size == PHOTO_STORE_SIZE
                and image.mode == "RGB"
            )
    except Exception:
        return False


def encode_photo_bytes(raw: bytes) -> str:
    """把任意常见图片转成 25:32 裁剪的 JPEG data URI。"""
    if not raw:
        raise ValueError("图片内容为空。")
    if len(raw) > MAX_PHOTO_FILE_BYTES:
        raise ValueError("图片文件太大，请选择 20 MB 以内的图片。")
    if not HAS_PIL:
        raise RuntimeError(
            "添加照片需要 Pillow。请先运行：python -m pip install Pillow"
        )
    if _is_canonical(raw):
        return _data_uri(raw)
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 40_000_000:
                raise ValueError("图片像素过大，请先压缩后再选择。")
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "#FFFFFF")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image = ImageOps.fit(
                image,
                PHOTO_STORE_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.42),
            )
            buffer = BytesIO()
            image.save(buffer, "JPEG", quality=88, optimize=True)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError("无法读取这张图片，请换一张 JPG / PNG 图片。") from exc
    return _data_uri(buffer.getvalue())


def normalize_photo(value: object) -> str:
    """读取 JSON 时校验照片；损坏或格式不支持的数据会被丢弃。"""
    if not isinstance(value, str) or not value.strip():
        return ""
    parsed = parse_data_uri(value)
    if parsed is None:
        return ""
    if not HAS_PIL:
        # 没有 Pillow 的机器仍可打开已有项目，只是不能在编辑器里预览。
        mime, _raw = parsed
        if mime in {"image/jpeg", "image/png"}:
            return value.strip()
        return ""
    try:
        return encode_photo_bytes(parsed[1])
    except Exception:
        return ""


def load_photo_file(path: str | Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise ValueError("找不到这张图片。")
    if path.stat().st_size > MAX_PHOTO_FILE_BYTES:
        raise ValueError("图片文件太大，请选择 20 MB 以内的图片。")
    return encode_photo_bytes(path.read_bytes())


def image_dimensions(raw: bytes) -> tuple[int, int] | None:
    if not HAS_PIL or not raw:
        return None
    try:
        with Image.open(BytesIO(raw)) as image:
            return image.size
    except Exception:
        return None


def make_thumbnail(value: str, width: int, height: int):
    """给编辑器生成缩略图，返回 Pillow 的 ImageTk.PhotoImage。"""
    if not HAS_TK_PHOTO:
        return None
    parsed = parse_data_uri(value)
    if parsed is None:
        return None
    try:
        with Image.open(BytesIO(parsed[1])) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image = ImageOps.fit(
                image,
                (max(1, width), max(1, height)),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.42),
            )
            return ImageTk.PhotoImage(image)
    except Exception:
        return None


def make_preview_image(value: str, width: int, height: int):
    """给 A4 预览生成指定像素尺寸的照片。"""
    if not HAS_TK_PHOTO:
        return None
    parsed = parse_data_uri(value)
    if parsed is None:
        return None
    try:
        with Image.open(BytesIO(parsed[1])) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image = ImageOps.fit(
                image,
                (max(1, width), max(1, height)),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.42),
            )
            return ImageTk.PhotoImage(image)
    except Exception:
        return None


def docx_payload(value: str) -> tuple[bytes, str, str] | None:
    """返回 Word 嵌入所需的 (bytes, 扩展名, MIME)。"""
    parsed = parse_data_uri(value)
    if parsed is None:
        return None
    mime, raw = parsed
    if mime == "image/png":
        return raw, "png", "image/png"
    if mime == "image/webp":
        return raw, "webp", "image/webp"
    return raw, "jpg", "image/jpeg"
