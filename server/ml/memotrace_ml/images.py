"""Display-oriented JPEG decoding and deterministic, edge-preserving regions."""

import io
import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from PIL import Image, ImageOps

from memotrace_ml.common import JSON, fingerprint
from memotrace_ml.numbers import ExactDecimal, coordinate

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_DIMENSION = 16_384
PREPROCESSING_VERSION = "exif-rgb-letterbox-bilinear-224-pad127-exact-box-v2"
_PREPROCESSING_VERSIONS: Mapping[int, str] = MappingProxyType(
    {
        224: PREPROCESSING_VERSION,
        384: "exif-rgb-letterbox-bilinear-384-pad127-exact-box-v2",
    }
)
Box = tuple[ExactDecimal, ExactDecimal, ExactDecimal, ExactDecimal]
PixelBox = tuple[int, int, int, int]
Mode = Literal["full", "overlap"]


def dimensions(width: int, height: int) -> None:
    if min(width, height) < 1 or max(width, height) > MAX_DIMENSION:
        raise ValueError("image dimensions exceed limit")
    if width * height > MAX_PIXELS:
        raise ValueError("image pixels exceed limit")


def decode_jpeg(data: bytes) -> Image.Image:
    if not 0 < len(data) <= MAX_IMAGE_BYTES:
        raise ValueError("image bytes exceed limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data), formats=["JPEG"]) as source:
            dimensions(*source.size)
            source.load()  # Pillow's default rejects truncated JPEGs.
            # The original bytes are unchanged; boxes and dimensions use the display frame.
            return ImageOps.exif_transpose(source).convert("RGB")


def preprocessing_version(side: int) -> str:
    if isinstance(side, bool) or not isinstance(side, int):
        raise ValueError("unsupported input resolution")
    try:
        return _PREPROCESSING_VERSIONS[side]
    except KeyError:
        raise ValueError("unsupported input resolution") from None


def letterbox(image: Image.Image, side: int = 224) -> Image.Image:
    preprocessing_version(side)
    width, height = image.size
    longest = max(width, height)
    resized = (
        max(1, (width * side + longest // 2) // longest),
        max(1, (height * side + longest // 2) // longest),
    )
    result = Image.new("RGB", (side, side), (127, 127, 127))
    result.paste(
        image.resize(resized, Image.Resampling.BILINEAR),
        ((side - resized[0]) // 2, (side - resized[1]) // 2),
    )
    return result


def validate_box(value: JSON) -> Box:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("invalid box")
    coordinates: list[ExactDecimal] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float | Decimal | ExactDecimal):
            raise ValueError("invalid box")
        number = coordinate(item)
        if not number.in_unit_interval():
            raise ValueError("invalid box")
        coordinates.append(number)
    x0, y0, x1, y1 = coordinates
    if not (x0.less_than(x1) and y0.less_than(y1)):
        raise ValueError("invalid box")
    return x0, y0, x1, y1


def query_crop(image: Image.Image, box: Box) -> Image.Image:
    width, height = image.size
    x0, y0, x1, y1 = box
    return image.crop(
        (
            x0.pixel(width, ceil=False),
            y0.pixel(height, ceil=False),
            x1.pixel(width, ceil=True),
            y1.pixel(height, ceil=True),
        )
    )


def positions(length: int, side: int, step: int) -> list[int]:
    edge = length - side
    values = list(range(0, edge + 1, step))
    if values[-1] != edge:
        values.append(edge)
    return values


@dataclass(frozen=True)
class Region:
    kind: Literal["full", "crop"]
    pixels: PixelBox

    def box(self, width: int, height: int) -> list[JSON]:
        x0, y0, x1, y1 = self.pixels
        return [x0 / width, y0 / height, x1 / width, y1 / height]


@dataclass(frozen=True)
class Policy:
    min_side_fraction: float = 0.75
    overlap: float = 0.25
    max_regions: int = 64

    def __post_init__(self) -> None:
        if not 0 < self.min_side_fraction <= 1 or not 0 <= self.overlap < 1:
            raise ValueError("invalid crop policy")
        if not 1 <= self.max_regions <= 64:
            raise ValueError("invalid region limit")

    def specification(self, mode: Mode) -> dict[str, JSON]:
        if mode == "full":
            return {"version": "full-v1", "include_full": True}
        return {
            "version": "overlap-v1",
            "include_full": True,
            "min_side_fraction": self.min_side_fraction,
            "overlap": self.overlap,
            "max_regions": self.max_regions,
            "side_rounding": "ceil",
            "step_rounding": "max(1,floor(side*(1-overlap)))",
            "edges": "append-final-anchor",
            "ordering": "full-then-y-major-x-minor-deduplicated",
            "overflow": "reject",
        }

    def fingerprint(self, mode: Mode) -> str:
        return fingerprint(self.specification(mode))

    def regions(self, width: int, height: int, mode: Mode) -> list[Region]:
        dimensions(width, height)
        full = Region("full", (0, 0, width, height))
        if mode == "full":
            return [full]
        side = math.ceil(self.min_side_fraction * min(width, height))
        step = max(1, math.floor(side * (1 - self.overlap)))
        xs, ys = positions(width, side, step), positions(height, side, step)
        duplicate_full = int(width == height == side)
        if 1 + len(xs) * len(ys) - duplicate_full > self.max_regions:
            raise ValueError("region budget exceeded")
        result = [full]
        for y in ys:
            for x in xs:
                pixels = (x, y, x + side, y + side)
                if pixels != full.pixels:
                    result.append(Region("crop", pixels))
        return result
