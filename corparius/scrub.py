"""Metadata out of a file, with the standard library. Rank 4, bytes in and bytes out.

A screenshot dropped into a company's documents folder carries where it was taken, on what, and
often at what coordinates. A logo exported from a design tool carries the licence holder's name. None
of that is the picture, all of it travels with the picture, and a company that publishes the file or
sends it to a model publishes the rest of it too.

So: strip what is not the image. No new dependency, which is not a slogan here but the constraint
that makes this installable in two wheels, and the formats are containers rather than mysteries. A
PNG is a chunk stream and a JPEG is a segment stream, and in both cases the metadata is a handful of
named blocks sitting beside the pixels.

## What comes out

  * **EXIF**, which is where the camera, the timestamp and the GPS coordinates live;
  * **XMP**, Adobe's packet, which carries the author, the tool and often a history of edits;
  * **C2PA**, the signed provenance manifest, which rides in the same containers;
  * PNG's textual chunks, which are where a generator writes its own name and its prompt.

## What deliberately does not

The pixels, the colour profile and the resolution. An `iCCP` chunk is why a red is the red the
designer chose, and dropping it to be thorough would change what the image looks like: this removes
what is *about* the file, never what the file is.

And nothing here re-encodes. A JPEG that goes through a decode and an encode loses quality for no
reason and gains the fingerprint of whatever library did it, which is the opposite of the intent. The
bytes that are kept are the original bytes.
"""

from __future__ import annotations

import logging
import struct

log = logging.getLogger("corparius.scrub")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# PNG chunks that carry something *about* the image rather than the image. `caBX` is where a C2PA
# manifest sits; `eXIf` is EXIF; the three text chunks are where a generator writes its own name.
PNG_STRIP = {b"eXIf", b"iTXt", b"tEXt", b"zTXt", b"caBX", b"tIME", b"dSIG"}

# JPEG application segments. APP1 is EXIF and XMP, APP11 is JUMBF which is how C2PA travels, APP13
# is Photoshop's IRB (IPTC). APP0 is JFIF and stays: it carries the density a viewer needs.
JPEG_STRIP = {0xE1, 0xE2, 0xEB, 0xED, 0xEE, 0xEF, 0xFE}


def _png(data: bytes) -> bytes | None:
    """Rebuild a PNG from the chunks worth keeping, or `None` if the walk did not finish.

    Chunk by chunk rather than by pattern: a length-prefixed stream can be walked exactly, and
    searching for a marker inside compressed pixel data is how a stripper corrupts an image.
    """
    out = bytearray(PNG_MAGIC)
    at = len(PNG_MAGIC)
    while at + 8 <= len(data):
        (size,) = struct.unpack(">I", data[at : at + 4])
        kind = data[at + 4 : at + 8]
        end = at + 12 + size
        if end > len(data):
            log.info(
                "scrub: PNG ends inside a %s chunk; left the file alone",
                kind.decode("ascii", "replace"),
            )
            return None
        if kind not in PNG_STRIP:
            out += data[at:end]
        at = end
        if kind == b"IEND":
            return bytes(out)
    return None  # ran off the end without an IEND


def _jpeg(data: bytes) -> bytes | None:
    """Rebuild a JPEG from the segments worth keeping, or `None` if the walk did not reach the scan.

    Stops copying at the start of scan: everything after `SOS` is entropy-coded pixel data with no
    segment structure, so it is passed through whole. Walking into it looking for markers is how a
    stripper produces a grey rectangle.
    """
    out = bytearray(data[:2])  # SOI
    at = 2
    while at + 4 <= len(data):
        if data[at] != 0xFF:
            # Not a marker where one belongs: padding, or two files concatenated. Reading a length
            # out of whatever this is would cut the file at an arbitrary offset.
            log.info("scrub: JPEG stopped being a segment stream; left the file alone")
            return None
        marker = data[at + 1]
        if marker == 0xDA:  # start of scan: the rest is the image
            out += data[at:]
            return bytes(out)
        (size,) = struct.unpack(">H", data[at + 2 : at + 4])
        end = at + 2 + size
        if end > len(data):
            log.info("scrub: JPEG ends inside a segment; left the file alone")
            return None
        if marker not in JPEG_STRIP:
            out += data[at:end]
        at = end
    return None  # ran off the end without a scan


def image(data: bytes) -> tuple[bytes, int]:
    """Strip metadata from an image. Returns (bytes, how many bytes went).

    The count is the report: "nothing was removed" and "this is not an image I know" look the same
    from the outside otherwise, and an operator deserves to know which one happened. A format this
    does not understand is returned untouched, because a stripper that mangles what it cannot read
    is worse than one that declines.

    **The rule is that a file is rewritten only if it was walked to the end.** An earlier version
    tried to salvage — keep the chunks that were whole and drop the truncated tail — and a test of
    a PNG whose first chunk declared a false length caught what that means in the bad case: the
    salvage was the eight magic bytes and nothing else, written over the upload by `documents.save`.
    A file that cannot be walked is already broken for whoever sent it, and the original at least
    still holds everything a repair tool could use. The cost is stated rather than hidden: metadata
    stays in a file corparius could not parse, so this is hygiene on a company's own files and not a
    boundary that holds against someone crafting one.
    """
    if not data:
        return data, 0
    try:
        if data.startswith(PNG_MAGIC):
            out = _png(data)
        elif data.startswith(b"\xff\xd8\xff"):
            out = _jpeg(data)
        else:
            return data, 0
    except (struct.error, IndexError):
        # Malformed beyond walking. The original is returned: this runs on a file an operator just
        # dropped in, and losing it to a strict parser would be corparius eating their upload.
        log.info("scrub: could not walk this file; left it alone")
        return data, 0
    if out is None:
        return data, 0
    return out, max(0, len(data) - len(out))
