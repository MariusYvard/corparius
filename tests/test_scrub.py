"""What is in a file that is not the file.

A screenshot dropped into a company's documents folder carries where it was taken, on what, and
often at what coordinates. An export from a design tool carries the licence holder's name. None of it
is the picture, all of it travels with the picture, and that folder is read into prompts and sent to
models that are not on this machine.

Stripped on the way **in** rather than on the way out, because there is no single way out: the same
file reaches a prompt, a published page and a backup zip, and a strip per exit is three chances to
miss one.

**The line this module holds** is between what a file is *about* and what a file *is*. EXIF, XMP, the
C2PA manifest and PNG's text chunks come out. The pixels stay, the resolution stays, and the colour
profile stays because `iCCP` is why a red is the red somebody chose: dropping it to be thorough would
change what the image looks like. Nothing is re-encoded either, so a JPEG loses no quality and gains
no library's fingerprint.
"""

import struct
import zlib

import pytest

from corparius import scrub


def _png(chunks) -> bytes:
    out = bytearray(scrub.PNG_MAGIC)
    for kind, body in chunks:
        out += struct.pack(">I", len(body)) + kind + body
        out += struct.pack(">I", zlib.crc32(kind + body))
    return bytes(out)


IHDR = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)


def _jpeg(segments, scan=b"entropy-coded-pixels") -> bytes:
    out = bytearray(b"\xff\xd8")
    for marker, body in segments:
        out += bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body
    out += b"\xff\xda" + struct.pack(">H", 2) + scan
    return bytes(out)


# --- what comes out ---------------------------------------------------------------


def test_a_png_loses_its_location_and_keeps_its_pixels():
    """The whole point, in one assertion: the coordinates go and the image does not."""
    before = _png(
        [
            (b"IHDR", IHDR),
            (b"eXIf", b"GPS 48.8566,2.3522"),
            (b"iTXt", b"parameters\x00a photo of a cat"),
            (b"iCCP", b"sRGB IEC61966-2.1"),
            (b"IDAT", b"the actual pixels"),
            (b"IEND", b""),
        ]
    )
    after, dropped = scrub.image(before)

    assert b"48.8566" not in after and b"a photo of a cat" not in after
    assert b"the actual pixels" in after, "it took the image with the metadata"
    assert b"sRGB IEC61966-2.1" in after, "the colour profile is what the image looks like"
    assert after.startswith(scrub.PNG_MAGIC) and after.endswith(
        b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    )
    assert dropped == len(before) - len(after) > 0


def test_a_c2pa_manifest_comes_out_of_both_containers():
    """It rides in a PNG chunk and in a JPEG APP11 segment, which is why this is two code paths and
    one test: a stripper that handled one container would be silent about the other."""
    png = _png(
        [(b"IHDR", IHDR), (b"caBX", b"c2pa signed manifest"), (b"IDAT", b"px"), (b"IEND", b"")]
    )
    assert b"c2pa" not in scrub.image(png)[0]

    jpeg = _jpeg([(0xE0, b"JFIF\x00"), (0xEB, b"JUMBF c2pa signed manifest")])
    assert b"JUMBF" not in scrub.image(jpeg)[0]


def test_a_jpeg_keeps_its_scan_and_its_jfif_header():
    """APP0 carries the density a viewer needs, and everything after the start of scan is the image.
    Walking into that looking for markers is how a stripper produces a grey rectangle."""
    before = _jpeg([(0xE0, b"JFIF\x00density"), (0xE1, b"Exif\x00\x00camera and GPS")])
    after, dropped = scrub.image(before)

    assert b"Exif" not in after and b"camera and GPS" not in after
    assert b"JFIF\x00density" in after
    assert after.endswith(b"entropy-coded-pixels"), "the image data was truncated"
    assert dropped > 0


# --- what it refuses to do --------------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"GIF89a not something this reads", b"%PDF-1.4", b"\x89PNG"])
def test_a_format_it_cannot_walk_is_returned_untouched(data):
    """A stripper that mangles what it cannot read is worse than one that declines, and the count
    is what tells the two apart: zero removed from a file it understood and zero removed from a file
    it did not look the same otherwise."""
    out, dropped = scrub.image(data)
    assert out == data and dropped == 0


def test_a_truncated_file_comes_back_exactly_as_it_arrived():
    """This runs on a file an operator just dropped on the console. Losing it to a strict parser
    would be corparius eating their upload, so nothing raises — and nothing is rewritten either."""
    whole = _png([(b"IHDR", IHDR), (b"IDAT", b"pixels"), (b"IEND", b"")])
    cut = whole[:-6]
    out, dropped = scrub.image(cut)
    assert out == cut and dropped == 0


def test_a_clean_image_is_returned_byte_for_byte():
    """Nothing is re-encoded: the bytes that are kept are the original bytes. An image that carried
    no metadata must come back identical, or every upload is a silent recompression."""
    clean = _png([(b"IHDR", IHDR), (b"IDAT", b"pixels"), (b"IEND", b"")])
    out, dropped = scrub.image(clean)
    assert out == clean and dropped == 0


# --- where it runs ----------------------------------------------------------------


def test_it_runs_when_a_file_arrives(tmp_path, monkeypatch):
    """Through `documents.save`, which is the door every uploaded file comes through. A module
    nothing calls is the shape this codebase keeps finding in its own product."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    from corparius import documents
    from corparius.config import cfg

    cfg.invalidate()
    dirty = _png(
        [(b"IHDR", IHDR), (b"eXIf", b"GPS 48.8566,2.3522"), (b"IDAT", b"px"), (b"IEND", b"")]
    )
    path, _replaced = documents.save("acme", "shot.png", dirty)
    stored = path.read_bytes()

    assert b"48.8566" not in stored, "the coordinates were written to disk"
    assert b"px" in stored and len(stored) < len(dirty)


# --- the promise not to eat an upload ---------------------------------------------
#
# One rule, asserted at each way a walk can fail: a file is rewritten only if it was walked to the
# end. The last of these three found the defect that made it the rule.


def test_a_jpeg_truncated_inside_a_segment_is_left_alone():
    """The JPEG half of the truncation promise, which was true in the PNG container and untried
    here. Cut in the middle of the EXIF segment, so the walker is asked to keep a segment whose
    declared length runs past the file."""
    whole = _jpeg([(0xE0, b"JFIF\x00header"), (0xE1, b"Exif\x00\x00GPS 48.8566,2.3522")])
    cut = whole[: whole.index(b"Exif") + 6]
    out, dropped = scrub.image(cut)
    assert out == cut and dropped == 0


def test_a_jpeg_that_stops_being_a_segment_stream_is_left_alone():
    """A byte that is not `0xFF` where a marker belongs. Real files do this: some encoders pad, and
    some files are two files concatenated. Reading a length out of whatever that is would cut the
    file at an arbitrary offset, so the walk gives up rather than guessing."""
    whole = _jpeg([(0xE0, b"JFIF\x00header"), (0xE1, b"Exif\x00\x00secret")])
    odd = whole[: whole.index(b"\xff\xda")] + b"\x00\x00padding"
    out, dropped = scrub.image(odd)
    assert out == odd and dropped == 0


def test_a_png_that_lies_about_a_chunk_length_is_returned_whole():
    """The test that changed the rule, and the reason the rule is worth its cost.

    Under the earlier "keep what was whole" behaviour this file came back as the eight magic bytes:
    the very first chunk was the one that lied, so there was nothing whole to keep, and
    `documents.save` would have written those eight bytes over the operator's image. A salvage that
    can produce nothing is a deletion with a reassuring name.
    """
    lying = bytearray(_png([(b"IHDR", IHDR), (b"IDAT", b"pixels"), (b"IEND", b"")]))
    lying[8:12] = b"\xff\xff\xff\xff"  # IHDR now claims four gigabytes

    out, dropped = scrub.image(bytes(lying))
    assert out == bytes(lying) and dropped == 0
    assert len(out) > len(scrub.PNG_MAGIC), "the file was reduced to a bare header"


def test_a_broken_upload_reaches_the_disk_unharmed(tmp_path, monkeypatch):
    """The rule where it is actually load-bearing. `documents.save` writes whatever `scrub.image`
    hands back, so a stripper that returns a fragment does not return a fragment, it destroys a
    file. Asserted through the real door rather than on the function alone."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    from corparius import documents
    from corparius.config import cfg

    cfg.invalidate()
    lying = bytearray(_png([(b"IHDR", IHDR), (b"IDAT", b"pixels"), (b"IEND", b"")]))
    lying[8:12] = b"\xff\xff\xff\xff"
    path, _replaced = documents.save("acme", "broken.png", bytes(lying))
    assert path.read_bytes() == bytes(lying)
