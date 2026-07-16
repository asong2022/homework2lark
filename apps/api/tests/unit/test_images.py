from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image
from tests.conftest import image_bytes

from mistake_notebook_api.application.images import (
    NormalizedBoundingBox,
    crop_image,
    inspect_image,
    to_pixel_bbox,
)
from mistake_notebook_api.domain.errors import AppError
from mistake_notebook_api.domain.geometry import BoundingBox


def test_bbox_accepts_origin_and_rounds_outward() -> None:
    result = to_pixel_bbox(
        NormalizedBoundingBox(x=0, y=0, width=0.501, height=0.501),
        source_width=100,
        source_height=80,
        min_region_pixels=2,
    )
    assert result == BoundingBox(x=0, y=0, width=51, height=41)


@pytest.mark.parametrize(
    "bbox",
    [
        NormalizedBoundingBox(float("nan"), 0, 0.5, 0.5),
        NormalizedBoundingBox(0, 0, 0, 0.5),
        NormalizedBoundingBox(0.8, 0, 0.3, 0.5),
        NormalizedBoundingBox(0, 0, 0.001, 0.001),
    ],
)
def test_bbox_rejects_invalid_values(bbox: NormalizedBoundingBox) -> None:
    with pytest.raises(AppError, match="框选"):
        to_pixel_bbox(
            bbox,
            source_width=100,
            source_height=100,
            min_region_pixels=2,
        )


def test_exif_orientation_controls_metadata_and_crop() -> None:
    source = BytesIO()
    image = Image.new("RGB", (20, 10), color="white")
    exif = image.getexif()
    exif[274] = 6
    image.save(source, format="JPEG", exif=exif)
    data = source.getvalue()

    metadata = inspect_image(data, max_pixels=10_000)
    assert (metadata.width, metadata.height) == (10, 20)

    cropped = crop_image(
        data,
        BoundingBox(0, 0, 10, 10),
        expected_width=10,
        expected_height=20,
    )
    with Image.open(BytesIO(cropped)) as result:
        assert result.size == (10, 10)


def test_animated_png_is_rejected() -> None:
    output = BytesIO()
    frames = [Image.new("RGB", (8, 8), color=color) for color in ("red", "blue")]
    frames[0].save(output, format="PNG", save_all=True, append_images=frames[1:])
    with pytest.raises(AppError) as raised:
        inspect_image(output.getvalue(), max_pixels=10_000)
    assert raised.value.code == "unsupported_image"


def test_pixel_limit_is_enforced_before_transpose_or_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_decode(_: Image.Image) -> Image.Image:
        raise AssertionError("oversized image reached EXIF transpose")

    monkeypatch.setattr(
        "mistake_notebook_api.application.images.ImageOps.exif_transpose", unexpected_decode
    )
    with pytest.raises(AppError) as raised:
        inspect_image(image_bytes(size=(20, 20)), max_pixels=399)
    assert raised.value.code == "invalid_image"
