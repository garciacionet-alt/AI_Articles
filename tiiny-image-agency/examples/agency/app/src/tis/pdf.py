"""pdf.py — a document of the agency's images, without an imaging library.

WHAT THIS IS
------------
A PDF: the images, one per page, in the order they were given. The
newsletter case is six images and one file to send.

WHY IT IS WRITTEN BY HAND
-------------------------
Two reasons, and the second is the one that matters.

The first is the dependency. The venv holds pydantic, httpx, fastapi
and uvicorn, and that is the whole list. A PDF writer that is pure
Python can be a hundred lines; a PDF writer that is a package is a
dependency, and the point of this project is that the things it hands
back are the things it was given.

The second is the IMAGES. A PDF page is opaque — every viewer supplies
a white background — so an image that arrives flattened has lost
something the agency promised to keep. And this project already knows
what a round trip through an image library costs: the alpha channel is
the reason the flagship model is worth 62% of the NPU.

HOW THE IMAGES GO IN
---------------------
**A JPEG** is embedded with ``/DCTDecode``, which is exactly what JPEG
is inside a PDF. The bytes go in untouched — no decode, no re-encode.

**An RGB PNG** is embedded with ``/FlateDecode`` and ``/Predictor 15``.
PDF's predictor 15 IS PNG's filtering: each row is prefixed with its
filter type and the rows are then deflated. So the PNG's compressed
scanlines are already the PDF's compressed scanlines, and the IDAT
payload goes in byte for byte.

**An RGBA PNG** keeps its alpha as an ``/SMask``, which is PDF's name
for a separate transparency channel. That one has to be separated from
the colour samples first, and separating them means a decode — a
LOSSLESS one. The pixels come out exactly as they went in; only the
compression is replaced. The alpha values are carried through
unchanged, and the test checks them against the source PNG rather
than against a snapshot.

A PDF has no alpha channel of its own, which is why the alpha travels
as its own image rather than inside the colour one.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from .imaging import PngError, _unfilter, read_info

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

#: PDF 1.7 — the version that has the PNG predictor and the JPEG
#: passthrough this writer uses.
PDF_VERSION = b"1.7"


class PdfError(Exception):
    """Raised when a document cannot be made from what was given."""


@dataclass(frozen=True)
class _Image:
    """One image, and how it will go into the PDF."""

    width: int
    height: int
    stream: bytes
    filter_name: bytes
    colours: int
    decode_parms: bytes
    smask: bytes | None = None


def build_pdf(images: list[bytes], asset_ids: list[str] | None = None,
              title: str = "") -> bytes:
    """A PDF holding these images, one per page.

    The images are embedded as they are: a JPEG as JPEG, an RGB PNG's
    compressed scanlines as they are, and an RGBA PNG's alpha as its
    own transparency channel.
    """
    if not images:
        raise PdfError("a document needs at least one image")

    placed = [_place(image) for image in images]
    return _write(placed, asset_ids or [], title)


def page_count(pdf: bytes) -> int:
    """How many pages this PDF has.

    Read back out of the file rather than remembered from the way it
    was built, so the answer is about the document and not about the
    intention.
    """
    marker = pdf.find(b"/Type /Pages")
    if marker < 0:
        return 0
    count_at = pdf.find(b"/Count ", marker)
    if count_at < 0:
        return 0
    return int(pdf[count_at + 7:count_at + 20].split()[0])


def write_pdf(path: str | Path, images: list[bytes],
              asset_ids: list[str] | None = None,
              title: str = "") -> Path:
    """Write the document to a path, and return where it went."""
    pdf = build_pdf(images, asset_ids=asset_ids, title=title)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf)
    return target


# -- placing an image ----------------------------------------------------


def _place(image: bytes) -> _Image:
    """How this image will go into the PDF."""
    if image.startswith(JPEG_MAGIC):
        return _place_jpeg(image)
    if image.startswith(PNG_MAGIC):
        return _place_png(image)
    raise PdfError(
        "a document holds PNG and JPEG images; this one is neither")


def _place_jpeg(image: bytes) -> _Image:
    """A JPEG as DCTDecode — which is what a JPEG is inside a PDF.

    The dimensions come from the JPEG's own SOF marker, because the
    bytes are not decoded and a PDF must know how big the picture is.
    """
    width, height = _jpeg_size(image)
    return _Image(width=width, height=height, stream=image,
                  filter_name=b"/DCTDecode", colours=3,
                  decode_parms=b"")


def _jpeg_size(image: bytes) -> tuple[int, int]:
    """The width and height of a JPEG, from its frame header.

    Read, not decoded: the bytes are not touched.
    """
    pos = 2
    while pos + 4 <= len(image):
        if image[pos] != 0xFF:
            pos += 1
            continue
        marker = image[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        length = struct.unpack(">H", image[pos + 2:pos + 4])[0]
        # SOF0..SOF15, except the four markers that are not frames.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", image[pos + 5:pos + 9])
            return width, height
        pos += 2 + length
    raise PdfError("this JPEG has no frame header, so its size is unknown")


def _place_png(image: bytes) -> _Image:
    """A PNG into the PDF, with its alpha kept."""
    try:
        info = read_info(image)
    except PngError as exc:
        raise PdfError(f"this PNG could not be read: {exc}") from None
    if info.interlaced:
        raise PdfError(
            "an interlaced PNG cannot be embedded without being decoded")
    if info.bit_depth != 8:
        raise PdfError(
            f"a {info.bit_depth}-bit PNG cannot be embedded without being "
            "decoded")

    idat = _idat(image)
    if info.colour_type == 2:
        # RGB. PDF's predictor 15 IS PNG's filtering, so the compressed
        # scanlines are already what the PDF wants. The bytes go in
        # untouched.
        return _Image(width=info.width, height=info.height, stream=idat,
                      filter_name=b"/FlateDecode", colours=3,
                      decode_parms=_predictor(info.width, 3))
    if info.colour_type == 6:
        # RGBA. The alpha has to become its own image — a PDF image has
        # no alpha channel of its own — and that means separating the
        # samples, which means a decode. A LOSSLESS one: the pixels
        # come out exactly as they went in.
        colour_rows, alpha_rows = _split_rgba(image, info)
        return _Image(width=info.width, height=info.height,
                      stream=colour_rows, filter_name=b"/FlateDecode",
                      colours=3, decode_parms=_predictor(info.width, 3),
                      smask=alpha_rows)
    raise PdfError(
        f"a {info.colour_type_name} PNG cannot be embedded without being "
        "decoded")


def _idat(png: bytes) -> bytes:
    """The compressed scanlines of a PNG, exactly as they are in the
    file."""
    pos = 8
    out = bytearray()
    while pos + 8 <= len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        ctype = png[pos + 4:pos + 8]
        if ctype == b"IDAT":
            out.extend(png[pos + 8:pos + 8 + length])
        elif ctype == b"IEND":
            break
        pos += 12 + length
    return bytes(out)


def _split_rgba(png: bytes, info) -> tuple[bytes, bytes]:
    """The colour samples and the alpha samples, as two deflated
    streams.

    The PNG is decoded once — losslessly — and the two planes are put
    back together with no filtering, which PDF's predictor accepts
    (filter type 0 on every row).
    """
    raw = zlib.decompress(_idat(png))
    pixels = _unfilter(raw, info.width, info.height, 4, 8)
    stride = info.width * 4
    colour = bytearray()
    alpha = bytearray()
    for row in range(info.height):
        start = row * stride
        line = pixels[start:start + stride]
        colour.append(0)  # filter type: None
        for x in range(info.width):
            colour.extend(line[x * 4:x * 4 + 3])
        alpha.append(0)
        for x in range(info.width):
            alpha.append(line[x * 4 + 3])
    return (zlib.compress(bytes(colour), 9),
            zlib.compress(bytes(alpha), 9))


def _predictor(columns: int, colours: int) -> bytes:
    """The decode parameters that tell a PDF reader that the stream is
    PNG-filtered."""
    return (b"<< /Predictor 15 /Colors %d /BitsPerComponent 8 /Columns %d >>"
            % (colours, columns))


# -- writing the file ----------------------------------------------------


def _write(images: list[_Image], asset_ids: list[str], title: str) -> bytes:
    """The PDF itself: objects, a cross-reference table, a trailer.

    Written by hand because the object numbers are simple and the
    bookkeeping is the kind that a library does better — but the
    IMAGES are the point, and those are in the file untouched.
    """
    bodies: dict[int, bytes] = {}
    counter = [1]

    def reserve() -> int:
        number = counter[0]
        counter[0] += 1
        return number

    # The numbers are reserved before the bodies are written, because
    # a body refers to another body and the reference has to know the
    # number it is pointing at.
    info_number = reserve() if (asset_ids or title) else None
    catalog_number = reserve()
    pages_number = reserve()
    image_numbers: list[int] = []
    smask_numbers: list[int | None] = []
    content_numbers: list[int] = []
    page_numbers: list[int] = []
    for image in images:
        image_numbers.append(reserve())
        smask_numbers.append(reserve() if image.smask is not None else None)
        content_numbers.append(reserve())
        page_numbers.append(reserve())

    if info_number is not None:
        bodies[info_number] = (
            b"<< /Title (%s) /Producer (Tiiny Image Agency) /Subject (%s) >>"
            % (_pdf_text(title or "Tiiny Image Agency"),
               _pdf_text(" ".join(asset_ids))))

    info_ref = (b" /Info %d 0 R" % info_number
                if info_number is not None else b"")
    bodies[catalog_number] = (b"<< /Type /Catalog /Pages %d 0 R%s >>"
                              % (pages_number, info_ref))

    bodies[pages_number] = (
        b"<< /Type /Pages /Kids [%s] /Count %d >>"
        % (b" ".join(b"%d 0 R" % number for number in page_numbers),
           len(page_numbers)))

    for index, image in enumerate(images):
        bodies[image_numbers[index]] = _image_object(
            image, smask_numbers[index])
        if smask_numbers[index] is not None:
            bodies[smask_numbers[index]] = _smask_object(image)
        bodies[content_numbers[index]] = _content_object(image)
        bodies[page_numbers[index]] = (
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /XObject << /Im0 %d 0 R >> >> "
            b"/Contents %d 0 R >>"
            % (pages_number, image.width, image.height,
               image_numbers[index], content_numbers[index]))

    out = bytearray()
    offsets: dict[int, int] = {}
    out.extend(b"%PDF-" + PDF_VERSION + b"\n")
    # A binary comment, so a tool that opens it in a text editor knows
    # it is not text.
    out.extend(b"%\xE2\xE3\xCF\xD3\n")
    for number in sorted(bodies):
        offsets[number] = len(out)
        out.extend(b"%d 0 obj\n" % number)
        out.extend(bodies[number])
        out.extend(b"\nendobj\n")

    xref_at = len(out)
    size = counter[0]
    out.extend(b"xref\n0 %d\n" % size)
    out.extend(b"0000000000 65535 f \n")
    for number in range(1, size):
        out.extend(b"%010d 00000 n \n" % offsets.get(number, 0))
    out.extend(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
               % (size, catalog_number, xref_at))
    return bytes(out)


def _image_object(image: _Image, smask_number: int | None) -> bytes:
    """An image XObject, with the image bytes as the stream."""
    parts = [b"<< /Type /XObject /Subtype /Image /Width %d /Height %d"
             % (image.width, image.height),
             b"/ColorSpace /DeviceRGB",
             b"/BitsPerComponent 8",
             b"/Filter %s" % image.filter_name]
    if image.decode_parms:
        parts.append(b"/DecodeParms %s" % image.decode_parms)
    if smask_number is not None:
        parts.append(b"/SMask %d 0 R" % smask_number)
    parts.append(b"/Length %d >>\nstream\n" % len(image.stream))
    return b" ".join(parts) + image.stream + b"\nendstream"


def _smask_object(image: _Image) -> bytes:
    """The alpha channel as its own grayscale image.

    A PDF image has no alpha channel of its own, so transparency
    travels as a separate image — a soft mask — and the colour image
    points at it.
    """
    stream = image.smask or b""
    body = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
            b"/DecodeParms %s /Length %d >>\nstream\n"
            % (image.width, image.height,
               _predictor(image.width, 1), len(stream)))
    return body + stream + b"\nendstream"


def _content_object(image: _Image) -> bytes:
    """The page content stream: one image, drawn to fill the page."""
    content = b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (image.width, image.height)
    return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content)


def _pdf_text(value: str) -> bytes:
    """Text for a PDF string, with the parentheses escaped."""
    escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return escaped.encode("latin-1", "replace")
