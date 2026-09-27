"""A 5x7 bitmap font for labelling screenshots: each glyph is seven rows of five bits, as hex pairs."""

from __future__ import annotations

import numpy as np

GLYPHS = {
    "A": "0E11111F111111", "B": "1E11111E11111E", "C": "0E11101010110E", "D": "1E11111111111E",
    "E": "1F10101E10101F", "F": "1F10101E101010", "G": "0E11101711110F", "H": "1111111F111111",
    "I": "0E04040404040E", "J": "0702020202120C", "K": "11121418141211", "L": "1010101010101F",
    "M": "111B1515111111", "N": "11191513111111", "O": "0E11111111110E", "P": "1E11111E101010",
    "Q": "0E11111115120D", "R": "1E11111E141211", "S": "0F10100E01011E", "T": "1F040404040404",
    "U": "1111111111110E", "V": "11111111110A04", "W": "1111111515150A", "X": "11110A040A1111",
    "Y": "11110A04040404", "Z": "1F01020408101F",
    "0": "0E11131519110E", "1": "040C040404040E", "2": "0E11010204081F", "3": "1F02040201110E",
    "4": "02060A121F0202", "5": "1F101E0101110E", "6": "0608101E11110E", "7": "1F010204080808",
    "8": "0E11110E11110E", "9": "0E11110F01020C",
    "-": "0000001F000000", "_": "0000000000001F", ".": "00000000000C0C", " ": "00000000000000",
    "+": "0004041F040400", "/": "01010204081010", ":": "000C0C000C0C00",
}
W, H = 5, 7


def _bitmap(code: str) -> np.ndarray:
    rows = [int(code[i:i + 2], 16) for i in range(0, 14, 2)]
    return np.array([[(r >> (4 - c)) & 1 for c in range(W)] for r in rows], bool)


BITMAPS = {ch: _bitmap(code) for ch, code in GLYPHS.items()}


def text_mask(text: str, scale: int = 1) -> np.ndarray:
    """A boolean mask of `text` (upper-cased; unknown characters become spaces), one blank column between glyphs."""
    glyphs = [BITMAPS.get(ch, BITMAPS[" "]) for ch in text.upper()]
    if not glyphs:
        return np.zeros((H * scale, 0), bool)
    gap = np.zeros((H, 1), bool)
    row = np.hstack([part for g in glyphs for part in (g, gap)][:-1])
    return row.repeat(scale, 0).repeat(scale, 1)
