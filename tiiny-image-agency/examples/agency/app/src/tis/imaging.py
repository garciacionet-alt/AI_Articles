"""imaging.py — read a PNG without an imaging library.

Pillow is not installed and is not worth installing: the appliance
returns PNGs, the only thing the Agency needs to know about them is
their geometry and how much of them is transparent, and both are in the
file itself.

The alpha histogram matters because "does this model render a
transparent background" is the single most consequential fact about an
image model, and it is the one thing a vision model cannot answer: a
transparent image composited onto a viewer's background looks opaque.

Only what is needed is supported: 8- and 16-bit, greyscale, RGB,
greyscale+alpha and RGBA, non-interlaced. An interlaced or palette
image is reported as unreadable rather than misread.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

#: The colour types, and how many samples each pixel has.
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngError(Exception):
    """Raised when a file is not a PNG this reader can read."""


@dataclass
class PngInfo:
    """What can be known about a PNG without decoding it."""

    width: int = 0
    height: int = 0
    bit_depth: int = 0
    colour_type: int = 0
    has_alpha_channel: bool = False
    colour_type_name: str = ""
    interlaced: bool = False
    bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "bit_depth": self.bit_depth,
            "colour_type": self.colour_type,
            "colour_type_name": self.colour_type_name,
            "has_alpha_channel": self.has_alpha_channel,
            "interlaced": self.interlaced,
            "bytes": self.bytes,
        }


@dataclass
class AlphaStats:
    """How transparent the image is.

    ``transparent_pct`` counts the pixels that are fully transparent.
    ``partial_pct`` counts the ones that are partly transparent, which
    is what a soft edge looks like, and is what separates a real alpha
    channel from a hard cut-out.
    """

    total_px: int = 0
    fully_transparent_px: int = 0
    fully_opaque_px: int = 0
    partial_alpha_px: int = 0
    alpha_min: int = 255
    alpha_max: int = 0
    has_alpha_channel: bool = False
    unreadable: str = ""

    @property
    def transparent_pct(self) -> float:
        if not self.total_px:
            return 0.0
        return round(100.0 * self.fully_transparent_px / self.total_px, 2)

    @property
    def partial_pct(self) -> float:
        if not self.total_px:
            return 0.0
        return round(100.0 * self.partial_alpha_px / self.total_px, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_px": self.total_px,
            "fully_transparent_px": self.fully_transparent_px,
            "fully_opaque_px": self.fully_opaque_px,
            "partial_alpha_px": self.partial_alpha_px,
            "transparent_pct": self.transparent_pct,
            "partial_pct": self.partial_pct,
            "alpha_min": self.alpha_min,
            "alpha_max": self.alpha_max,
            "has_alpha_channel": self.has_alpha_channel,
            "unreadable": self.unreadable,
        }


def read_info(data: bytes) -> PngInfo:
    """The geometry and format of a PNG, from its chunks."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PngError("not a PNG")
    info = PngInfo(bytes=len(data))
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            (info.width, info.height, info.bit_depth, info.colour_type,
             _compression, _filter, interlaced) = struct.unpack(
                ">IIBBBBB", chunk)
            info.interlaced = bool(interlaced)
            info.has_alpha_channel = info.colour_type in (4, 6)
            info.colour_type_name = {
                0: "greyscale", 2: "RGB", 3: "palette", 4: "greyscale+alpha",
                6: "RGBA",
            }.get(info.colour_type, str(info.colour_type))
        elif ctype == b"IEND":
            break
        pos += 12 + length
    return info


def _unfilter(raw: bytes, width: int, height: int, channels: int,
              depth: int) -> bytes:
    """Undo the PNG's per-scanline filters."""
    stride = width * channels * (depth // 8)
    out = bytearray()
    previous = bytearray(stride)
    pos = 0
    for _ in range(height):
        if pos >= len(raw):
            break
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if filter_type == 1:  # Sub
            for i in range(channels, len(line)):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(len(line)):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(len(line)):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(len(line)):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                upleft = previous[i - channels] if i >= channels else 0
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                if pa <= pb and pa <= pc:
                    pred = left
                elif pb <= pc:
                    pred = up
                else:
                    pred = upleft
                line[i] = (line[i] + pred) & 0xFF
        out.extend(line)
        previous = line
    return bytes(out)


def alpha_stats(data: bytes) -> AlphaStats:
    """The transparency of a PNG, measured from its pixels."""
    try:
        info = read_info(data)
    except PngError as exc:
        return AlphaStats(unreadable=str(exc))

    stats = AlphaStats(has_alpha_channel=info.has_alpha_channel)
    if info.interlaced:
        stats.unreadable = "interlaced"
        return stats
    if info.colour_type == 3:
        stats.unreadable = "palette"
        return stats
    if not info.has_alpha_channel:
        # No alpha channel at all: every pixel is opaque, and saying so
        # is the answer, not a failure.
        stats.total_px = info.width * info.height
        stats.fully_opaque_px = stats.total_px
        stats.alpha_min = stats.alpha_max = 255
        return stats
    if info.bit_depth not in (8, 16):
        stats.unreadable = f"bit depth {info.bit_depth}"
        return stats

    # Collect the IDAT chunks and inflate them.
    pos = 8
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        if ctype == b"IDAT":
            idat.extend(data[pos + 8:pos + 8 + length])
        elif ctype == b"IEND":
            break
        pos += 12 + length
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        stats.unreadable = f"could not inflate: {exc}"
        return stats

    channels = CHANNELS.get(info.colour_type, 0)
    depth = info.bit_depth
    pixels = _unfilter(raw, info.width, info.height, channels, depth)
    step = depth // 8
    alpha_index = channels - 1  # alpha is the last sample of the pixel

    histogram = [0] * 256
    total = info.width * info.height
    per_pixel = channels * step
    for pixel in range(total):
        offset = pixel * per_pixel + alpha_index * step
        if offset >= len(pixels):
            break
        value = pixels[offset]
        histogram[value] += 1

    stats.total_px = total
    stats.fully_transparent_px = histogram[0]
    stats.fully_opaque_px = histogram[255]
    stats.partial_alpha_px = total - histogram[0] - histogram[255]
    seen = [i for i, count in enumerate(histogram) if count]
    if seen:
        stats.alpha_min = seen[0]
        stats.alpha_max = seen[-1]
    return stats
