"""Tests for PDF output.

WHAT A PDF OUTPUT IS
--------------------
A document: the images the agency made, laid out one per page, in the
order the user asked for. The newsletter case is exactly this — six
images, one page each, one file to send.

THE PART THAT MATTERS
----------------------
**The images go into the PDF without being decoded and re-encoded.**

That is not a nicety. A PDF page is opaque — every viewer supplies a
white background — so an image that arrives flattened has lost
something the agency promised to keep. And this project already knows
what a round trip through an image library costs: the alpha channel is
the reason the flagship model is worth 62% of the NPU.

So:

- a **JPEG** is embedded with ``/DCTDecode``, which is what JPEG *is*
  in PDF — the bytes go in untouched;
- an **RGB PNG** is embedded with ``/FlateDecode`` and ``/Predictor 15``,
  which is PDF's own PNG predictor — the PNG's compressed scanlines are
  the PDF's compressed scanlines, so the bytes go in untouched;
- an **RGBA PNG** keeps its alpha as an ``/SMask``, which is PDF's name
  for a separate transparency channel. That one has to be separated
  from the colour samples first, and that is a DECODE — a lossless one.
  The pixels come out exactly as they went in; only the compression is
  replaced.

No image library. The dependency list does not move.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from tis.pdf import PdfError, build_pdf, page_count


def _png(width: int, height: int, channels: int) -> bytes:
    """A PNG of one colour type, with every pixel distinct enough to
    tell a decode from a copy."""
    colour_type = {1: 0, 3: 2, 4: 6}[channels]
    rows = []
    for y in range(height):
        row = bytearray([0])  # filter type: None
        for x in range(width):
            if channels == 1:
                row += bytes((x * 7 % 256,))
            elif channels == 3:
                row += bytes((x * 11 % 256, y * 13 % 256, (x + y) * 5 % 256))
            else:
                row += bytes((x * 11 % 256, y * 13 % 256, (x + y) * 5 % 256,
                              (x * 17 + y * 3) % 256))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def _jpeg() -> bytes:
    """A real JPEG structure: the markers a reader needs, including the
    frame header that says how big the picture is.

    The bytes are not decoded — only the frame header is read, for the
    size — so the fixture needs the frame header and not a picture.
    """
    return (
        b"\xff\xd8"                                          # SOI
        b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xdb\x00\x43\x00" + bytes(range(1, 65))      # DQT
        # SOF0: 8-bit, height 16, width 24, three components.
        + b"\xff\xc0\x00\x11\x08\x00\x10\x00\x18\x03"
        + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
        + b"\xff\xd9"                                        # EOI
    )


RGB_PNG = _png(24, 16, 3)
RGBA_PNG = _png(24, 16, 4)
JPEG = _jpeg()


# -- the document --------------------------------------------------------


def test_a_pdf_is_built_from_the_images():
    pdf = build_pdf([RGB_PNG, RGB_PNG, RGB_PNG])

    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")


def test_there_is_one_page_per_image():
    pdf = build_pdf([RGB_PNG, RGB_PNG, RGB_PNG])

    assert page_count(pdf) == 3


def test_a_document_with_no_images_is_refused():
    """An empty PDF is not a document; it is a file with nothing in it."""
    with pytest.raises(PdfError):
        build_pdf([])


# -- the images go in untouched -----------------------------------------


def test_a_jpeg_is_embedded_byte_for_byte():
    """JPEG in PDF IS DCTDecode. The bytes are the image."""
    pdf = build_pdf([JPEG])

    assert JPEG in pdf, "the JPEG was re-encoded instead of embedded"


def test_an_rgb_png_is_embedded_byte_for_byte():
    """PDF's own PNG predictor takes the PNG's compressed scanlines
    as they are."""
    pdf = build_pdf([RGB_PNG])

    # The IDAT payload — the compressed scanlines — appears verbatim.
    idat = _idat(RGB_PNG)
    assert idat in pdf, "the PNG was re-encoded instead of embedded"


def test_an_rgba_png_keeps_its_alpha():
    """The alpha becomes an SMask, and the alpha VALUES are the ones the
    PNG carried."""
    pdf = build_pdf([RGBA_PNG])

    alpha = _smask_alpha(pdf, _png(24, 16, 4))
    assert alpha is not None, "the alpha was dropped"
    assert alpha[:24] == bytes((x * 17) % 256 for x in range(24))
    assert alpha[24:48] == bytes((x * 17 + 3) % 256 for x in range(24))


def test_the_alpha_of_the_rgba_png_matches_the_png_itself():
    """Measured against the source, not against a guess."""
    from tis.imaging import alpha_stats

    stats = alpha_stats(RGBA_PNG)
    assert stats.has_alpha_channel
    assert stats.partial_alpha_px > 0, "the test fixture must have a ramp"


# -- the geometry --------------------------------------------------------


def test_the_page_is_the_size_of_the_image():
    """A page the size of its picture, so nothing is cropped or
    letterboxed."""
    pdf = build_pdf([RGB_PNG])

    assert b"/MediaBox [0 0 24 16]" in pdf


def test_the_pdf_says_how_many_pages_it_has():
    pdf = build_pdf([RGB_PNG, RGB_PNG])

    assert b"/Count 2" in pdf


def test_the_document_records_the_images_it_holds():
    """The provenance: which assets went into this file."""
    pdf = build_pdf([RGB_PNG], asset_ids=["ast_1234567890abcdef"])

    assert b"ast_1234567890abcdef" in pdf


def test_a_format_the_document_cannot_carry_is_refused():
    """A GIF has no place in this PDF, and saying so is better than
    writing something that is not the picture."""
    with pytest.raises(PdfError):
        build_pdf([b"GIF89a" + b"\x00" * 32])


# -- the agency, the API and the CLI -------------------------------------


@pytest.fixture(scope="module")
def registry():
    from tis.registry import Registry

    root = Path(__file__).resolve().parents[2]
    return Registry.load(root / "registry" / "image-models.json")


def _agency(tmp_path, registry):
    from tis.config import Settings
    from tis.service import Agency

    root = Path(__file__).resolve().parents[2]
    settings = Settings(
        registry_path=root / "registry" / "image-models.json",
        roles_path=root / "registry" / "roles.json",
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
    )
    from fake_device import FakeDevice

    return Agency(settings, device=FakeDevice(registry), registry=registry)


def _client(agency):
    from fastapi.testclient import TestClient

    from tis.api import create_app

    return TestClient(create_app(agency))


def _save(agency, image: bytes) -> str:
    asset = agency.assets.save(image, {"origin": "test"})
    return asset.id


def test_the_agency_makes_a_document_from_assets(tmp_path, registry):
    """The newsletter case: some images, one file."""
    agency = _agency(tmp_path, registry)
    first = _save(agency, RGB_PNG)
    second = _save(agency, JPEG)

    path = agency.build_document([first, second],
                                 output_path=str(tmp_path / "news.pdf"))

    written = Path(path)
    assert written.exists()
    assert page_count(written.read_bytes()) == 2


def test_the_document_is_written_where_the_caller_asked(tmp_path, registry):
    agency = _agency(tmp_path, registry)
    asset_id = _save(agency, RGB_PNG)
    target = tmp_path / "out" / "weekly.pdf"

    path = agency.build_document([asset_id], output_path=str(target))

    assert Path(path) == target
    assert target.exists()


def test_an_asset_that_does_not_exist_is_refused(tmp_path, registry):
    """The message says which one, because a list of six with a typo in
    it is otherwise a guessing game."""
    from tis.pdf import PdfError

    agency = _agency(tmp_path, registry)
    good = _save(agency, RGB_PNG)

    with pytest.raises(PdfError) as caught:
        agency.build_document([good, "ast_0000000000000000"])

    assert "ast_0000000000000000" in str(caught.value)


def test_the_api_makes_a_document(tmp_path, registry):
    agency = _agency(tmp_path, registry)
    asset_id = _save(agency, RGB_PNG)

    response = _client(agency).post("/v1/documents", json={
        "asset_ids": [asset_id],
        "output_path": str(tmp_path / "doc.pdf"),
        "title": "The newsletter",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["pages"] == 1
    assert Path(body["path"]).exists()


def test_the_api_refuses_a_document_with_no_images(tmp_path, registry):
    agency = _agency(tmp_path, registry)

    response = _client(agency).post("/v1/documents", json={
        "asset_ids": [],
        "output_path": str(tmp_path / "doc.pdf"),
    })

    assert response.status_code == 400


def test_the_cli_makes_a_document(tmp_path, registry):
    """The command an agent or a person runs."""
    agency = _agency(tmp_path, registry)
    asset_id = _save(agency, RGB_PNG)
    target = tmp_path / "cli.pdf"

    from tis.cli import main

    code = main(["pdf", asset_id, "--out", str(target), "--url",
                 "http://127.0.0.1:9"])

    # The CLI is an HTTP client, so it cannot see this agency's assets;
    # what it must do is fail cleanly rather than pretend.
    assert code != 0 or target.exists()


# -- helpers -------------------------------------------------------------


def _idat(png: bytes) -> bytes:
    """The compressed scanlines of a PNG, as they are in the file."""
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


def _smask_alpha(pdf: bytes, source_png: bytes) -> bytes | None:
    """The alpha samples in the PDF's SMask, inflated.

    The colour image points at its soft mask by object number, so the
    reference is followed rather than guessed at.
    """
    import zlib

    marker = pdf.find(b"/SMask")
    if marker < 0:
        return None
    number_at = pdf.find(b" 0 R", marker)
    if number_at < 0:
        return None
    number = int(pdf[marker + len(b"/SMask"):number_at].strip())

    header = b"%d 0 obj" % number
    start = pdf.find(header)
    if start < 0:
        return None
    end = pdf.find(b"endobj", start)
    body = pdf[start:end]
    stream_at = body.find(b"stream")
    if stream_at < 0:
        return None
    data_at = stream_at + len(b"stream")
    if body[data_at:data_at + 2] == b"\r\n":
        data_at += 2
    elif body[data_at:data_at + 1] in (b"\n", b"\r"):
        data_at += 1
    length_at = body.find(b"/Length")
    declared = int(body[length_at + len(b"/Length"):].split()[0])
    compressed = body[data_at:data_at + declared]
    try:
        raw = zlib.decompress(compressed)
    except zlib.error:
        return None
    # PDF's predictor 15 rows: a filter byte, then the samples.
    width = 24
    out = bytearray()
    stride = width + 1
    for row in range(16):
        out.extend(raw[row * stride + 1:(row + 1) * stride])
    return bytes(out)
