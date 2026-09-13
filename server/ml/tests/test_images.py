"""Synthetic-only spatial regression fixtures; no retrieval quality claims."""

import io
import math
import time

import pytest
from PIL import Image, ImageDraw

from memotrace_ml.common import JSON, parse_json
from memotrace_ml.images import (
    Policy,
    decode_jpeg,
    dimensions,
    letterbox,
    preprocessing_version,
    query_crop,
    validate_box,
)


def jpeg(width: int = 160, height: int = 90, orientation: int = 1) -> bytes:
    image = Image.new("RGB", (width, height), "red")
    draw = ImageDraw.Draw(image)
    draw.rectangle((width // 2, 0, width, height // 2), fill=(0, 255, 0))
    draw.rectangle((0, height // 2, width // 2, height), fill=(255, 255, 0))
    draw.rectangle((width // 2, height // 2, width, height), fill=(0, 0, 255))
    exif = Image.Exif()
    exif[274] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=100, subsampling=0, exif=exif)
    return buffer.getvalue()


@pytest.mark.parametrize("width,height", [(160, 90), (90, 160), (7, 7), (1, 1), (1, 12), (2, 3)])
def test_tiles_cover_every_pixel_without_duplicate_windows(width: int, height: int) -> None:
    regions = Policy().regions(width, height, "overlap")
    assert regions[0].kind == "full"
    assert len({region.pixels for region in regions}) == len(regions) <= 64
    tiles = regions[1:] or regions
    for y in range(height):
        for x in range(width):
            assert any(
                x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in (r.pixels for r in tiles)
            )
    assert all(validate_box(r.box(width, height)) for r in regions)
    assert any(r.pixels[0] == 0 for r in tiles)
    assert any(r.pixels[2] == width for r in tiles)
    assert any(r.pixels[1] == 0 for r in tiles)
    assert any(r.pixels[3] == height for r in tiles)


def test_default_landscape_edges_and_boundary_object() -> None:
    regions = Policy().regions(1600, 900, "overlap")
    assert len(regions) == 7
    assert regions[1].pixels == (0, 0, 675, 675)
    assert regions[-1].pixels == (925, 225, 1600, 900)
    # Object straddles x=675, the first tile's edge; the adjacent overlap retains it.
    assert any(
        x0 <= 660 and 700 <= x1 and y0 <= 300 and 340 <= y1
        for x0, y0, x1, y1 in (r.pixels for r in regions[1:])
    )


def test_full_mode_and_generation_policy_identity() -> None:
    assert len(Policy().regions(1600, 900, "full")) == 1
    assert Policy().fingerprint("full") != Policy().fingerprint("overlap")
    assert Policy().fingerprint("overlap") != Policy(0.5).fingerprint("overlap")
    assert Policy().fingerprint("full") == Policy(0.5).fingerprint("full")
    assert len(Policy(1.0).regions(5, 5, "overlap")) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_side_fraction": 0.0},
        {"min_side_fraction": math.nan},
        {"overlap": 1.0},
        {"overlap": math.inf},
        {"max_regions": 65},
    ],
)
def test_invalid_policies(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Policy(**kwargs)  # type: ignore[arg-type]


def test_excessive_regions_reject_instead_of_dropping_edges() -> None:
    with pytest.raises(ValueError, match="budget"):
        Policy().regions(16384, 1, "overlap")
    assert len(Policy().regions(16384, 1, "full")) == 1


@pytest.mark.parametrize("width,height", [(0, 1), (1, 16385), (7000, 7000)])
def test_size_limits(width: int, height: int) -> None:
    with pytest.raises(ValueError):
        dimensions(width, height)


def test_decode_limits_and_corruption() -> None:
    with pytest.raises(ValueError):
        decode_jpeg(jpeg(16385, 1))
    with pytest.raises(OSError):
        decode_jpeg(jpeg()[:100])
    with pytest.raises(OSError):
        decode_jpeg(b"not an image")
    with pytest.raises(ValueError):
        decode_jpeg(b"x" * (16 * 1024 * 1024 + 1))


@pytest.mark.parametrize(
    "orientation,color",
    [
        (1, (255, 0, 0)),
        (2, (0, 255, 0)),
        (3, (0, 0, 255)),
        (4, (255, 255, 0)),
        (5, (255, 0, 0)),
        (6, (255, 255, 0)),
        (7, (0, 0, 255)),
        (8, (0, 255, 0)),
    ],
)
def test_exif_display_coordinates(orientation: int, color: tuple[int, int, int]) -> None:
    image = decode_jpeg(jpeg(160, 90, orientation))
    assert image.size == ((90, 160) if orientation >= 5 else (160, 90))
    crop = query_crop(image, validate_box([0, 0, 0.25, 0.25]))
    sample = crop.getpixel((crop.width // 2, crop.height // 2))
    assert isinstance(sample, tuple)
    assert all(abs(actual - expected) <= 2 for actual, expected in zip(sample, color, strict=True))


def test_letterbox_keeps_all_edges_and_deterministic_padding() -> None:
    image = Image.new("RGB", (224, 112), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 4, 111), fill="red")
    draw.rectangle((219, 0, 223, 111), fill="blue")
    boxed = letterbox(image)
    assert boxed.size == (224, 224)
    assert boxed.getpixel((0, 56)) == (255, 0, 0)
    assert boxed.getpixel((223, 167)) == (0, 0, 255)
    assert boxed.getpixel((0, 55)) == (127, 127, 127)
    assert boxed.getpixel((0, 168)) == (127, 127, 127)
    assert letterbox(boxed).tobytes() == boxed.tobytes()


def test_letterbox_384_keeps_edges_and_uses_distinct_version() -> None:
    image = Image.new("RGB", (384, 192), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 0, 0, 191), fill="red")
    draw.line((383, 0, 383, 191), fill="blue")
    boxed = letterbox(image, 384)
    assert boxed.size == (384, 384)
    assert boxed.getpixel((0, 96)) == (255, 0, 0)
    assert boxed.getpixel((383, 287)) == (0, 0, 255)
    assert boxed.getpixel((0, 95)) == (127, 127, 127)
    assert preprocessing_version(384) != preprocessing_version(224)


@pytest.mark.parametrize("side", [256, True])
def test_letterbox_rejects_unsupported_resolution(side: int) -> None:
    with pytest.raises(ValueError, match="unsupported input resolution"):
        letterbox(Image.new("RGB", (10, 10)), side)


@pytest.mark.parametrize("box", [[0, 0, 0, 1], [False, 0, 1, 1], [0, 0, math.nan, 1], [0, 0, 2, 1]])
def test_invalid_query_boxes(box: list[float]) -> None:
    with pytest.raises(ValueError):
        validate_box([*box])


def test_exact_region_limit_64_and_65() -> None:
    assert len(Policy().regions(63, 1, "overlap")) == 64
    with pytest.raises(ValueError, match="budget"):
        Policy().regions(64, 1, "overlap")


@pytest.mark.parametrize("box", [None, {}, [], [0, 1], [0, 0, "1", 1], [0, 0, 1, 1, 1]])
def test_malformed_box_shapes(box: JSON) -> None:
    with pytest.raises(ValueError):
        validate_box(box)


@pytest.mark.parametrize(
    "raw,width,expected",
    [
        (b"[0,0,1e-400,1]", 80, (1, 20)),
        (b"[0.5,0,0.50000000000000001,1]", 80, (1, 20)),
        (b"[0.49999999999999999,0,0.5,1]", 80, (1, 20)),
        (b"[0.49999999999999999,0,0.50000000000000001,1]", 80, (2, 20)),
        (b"[0.2,0,0.3,1]", 10, (1, 20)),
        (b"[1e-999999999999999999999999999999,0,2e-999999999999999999999999999999,1]", 80, (1, 20)),
        (b"[0,0,1e-100000000000000000,1]", 80, (1, 20)),
    ],
)
def test_exact_decimal_rasterization(raw: bytes, width: int, expected: tuple[int, int]) -> None:
    box = validate_box(parse_json(raw, exact_numbers=True))
    image = Image.new("RGB", (width, 20), "red")
    assert query_crop(image, box).size == expected


@pytest.mark.parametrize(
    "raw",
    [
        b"[1e-400,0,1.0e-400,1]",
        b"[2e-400,0,1e-400,1]",
        b"[0,0,1e9999999999999999999999999,1]",
        b"[2e-9999999999999999999999,0,1e-9999999999999999999999,1]",
    ],
)
def test_exact_decimal_zero_area_and_out_of_range(raw: bytes) -> None:
    with pytest.raises(ValueError):
        validate_box(parse_json(raw, exact_numbers=True))


def test_extreme_written_exponent_is_bounded() -> None:
    started = time.monotonic()
    raw = b"[0,0,1e-" + b"9" * 10000 + b",1]"
    crop = query_crop(
        Image.new("RGB", (16384, 1)), validate_box(parse_json(raw, exact_numbers=True))
    )
    assert crop.size == (1, 1)
    assert time.monotonic() - started < 2


def test_letterbox_round_half_up_and_odd_padding() -> None:
    # 224 * 3 / 64 = 10.5 -> 11, leaving 213 padding pixels: 106 above, 107 below.
    boxed = letterbox(Image.new("RGB", (64, 3), "white"))
    assert boxed.getpixel((100, 105)) == (127, 127, 127)
    assert boxed.getpixel((100, 106)) == (255, 255, 255)
    assert boxed.getpixel((100, 116)) == (255, 255, 255)
    assert boxed.getpixel((100, 117)) == (127, 127, 127)


def test_near_request_limit_significand_keeps_exact_boundary_pixels() -> None:
    raw = b"[0.5,0,0.5" + b"0" * 1_000_000 + b"1,1]"
    assert len(raw) < 1024 * 1024
    image = Image.new("RGB", (4, 3), "red")
    ImageDraw.Draw(image).line((2, 0, 2, 2), fill="blue")
    cropped = query_crop(image, validate_box(parse_json(raw, exact_numbers=True)))
    assert cropped.size == (1, 3)
    assert list(cropped.getdata()) == [(0, 0, 255)] * 3
