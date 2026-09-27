"""RGB image → PNG bytes with the standard library only (zlib + struct)."""

from __future__ import annotations

import struct
import zlib

import numpy as np


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(rgb: np.ndarray) -> bytes:
    """`rgb` is (height, width, 3) uint8."""
    h, w, _ = rgb.shape
    rows = np.hstack([np.zeros((h, 1), np.uint8), rgb.reshape(h, w * 3)])  # filter byte 0 (none) per row
    header = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + _chunk(b"IEND", b"")


def png_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a PNG's header."""
    return struct.unpack(">II", data[16:24])
