from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from mistake_notebook_api.domain.errors import AppError
from mistake_notebook_api.domain.geometry import BoundingBox

_MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png"}


@dataclass(frozen=True, slots=True)
class ImageMetadata:
    media_type: str
    width: int
    height: int
    extension: str


@dataclass(frozen=True, slots=True)
class NormalizedBoundingBox:
    x: float
    y: float
    width: float
    height: float


def inspect_image(data: bytes, *, max_pixels: int) -> ImageMetadata:
    if not data:
        raise AppError("invalid_image", "图片内容为空，请重新选择文件。")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image_format = image.format
                if image_format not in _MEDIA_TYPES:
                    raise AppError("unsupported_image", "当前只支持 JPG、JPEG 或 PNG 图片。")
                if getattr(image, "n_frames", 1) != 1:
                    raise AppError("unsupported_image", "当前不支持动图，请上传单帧图片。")
                raw_width, raw_height = image.size
                if raw_width <= 0 or raw_height <= 0 or raw_width * raw_height > max_pixels:
                    raise AppError("invalid_image", "图片像素尺寸超出允许范围。")
                oriented = ImageOps.exif_transpose(image)
                oriented.load()
                width, height = oriented.size
    except AppError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise AppError("invalid_image", "图片像素尺寸过大，请缩小后重试。") from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise AppError("invalid_image", "图片无法解码，请重新导出后上传。") from None

    extension = "jpg" if image_format == "JPEG" else "png"
    return ImageMetadata(_MEDIA_TYPES[image_format], width, height, extension)


def to_pixel_bbox(
    normalized: NormalizedBoundingBox,
    *,
    source_width: int,
    source_height: int,
    min_region_pixels: int,
) -> BoundingBox:
    values = (normalized.x, normalized.y, normalized.width, normalized.height)
    if not all(math.isfinite(value) for value in values):
        raise AppError("invalid_region", "框选坐标无效，请重新框选。")
    if normalized.x < 0 or normalized.y < 0 or normalized.width <= 0 or normalized.height <= 0:
        raise AppError("invalid_region", "框选区域必须是有效矩形。")
    if normalized.x + normalized.width > 1 or normalized.y + normalized.height > 1:
        raise AppError("invalid_region", "框选区域超出原图范围，请重新框选。")

    left = math.floor(normalized.x * source_width)
    top = math.floor(normalized.y * source_height)
    right = min(source_width, math.ceil((normalized.x + normalized.width) * source_width))
    bottom = min(source_height, math.ceil((normalized.y + normalized.height) * source_height))
    width = right - left
    height = bottom - top

    if width < min_region_pixels or height < min_region_pixels:
        raise AppError("invalid_region", "框选区域太小，请扩大后重试。")
    return BoundingBox(left, top, width, height)


def crop_image(
    data: bytes, bbox: BoundingBox, *, expected_width: int, expected_height: int
) -> bytes:
    return crop_images(
        data,
        [bbox],
        expected_width=expected_width,
        expected_height=expected_height,
    )[0]


def crop_images(
    data: bytes,
    bboxes: list[BoundingBox],
    *,
    expected_width: int,
    expected_height: int,
) -> list[bytes]:
    try:
        with Image.open(BytesIO(data)) as image:
            oriented = ImageOps.exif_transpose(image)
            oriented.load()
            if oriented.size != (expected_width, expected_height):
                raise AppError("invalid_image", "原图尺寸与保存记录不一致。")
            results: list[bytes] = []
            for bbox in bboxes:
                right = bbox.x + bbox.width
                bottom = bbox.y + bbox.height
                if bbox.x < 0 or bbox.y < 0 or right > expected_width or bottom > expected_height:
                    raise AppError("invalid_region", "框选区域超出原图范围，请重新框选。")
                cropped = oriented.crop((bbox.x, bbox.y, right, bottom))
                output = BytesIO()
                cropped.save(output, format="PNG", optimize=True)
                results.append(output.getvalue())
            return results
    except AppError:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise AppError("invalid_image", "原始图片无法读取，请重新上传。") from None
