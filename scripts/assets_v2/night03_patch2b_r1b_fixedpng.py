"""R1B PNG extensions on top of the FROZEN R1A fixed-Huffman encoder.

The frozen module night03_patch2b_r1a_r6_fixedpng.py stays byte-identical;
this wrapper re-uses its deterministic deflate and chunk writer to add
the RGBA (colour type 6) writer needed for full-canvas candidates.
Every output byte remains a pure function of the pixel data.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

import night03_patch2b_r1a_r6_fixedpng as _frozen

_SIG = _frozen._SIG
_chunk = _frozen._chunk
_zlib_stream = _frozen._zlib_stream
_scanlines = _frozen._scanlines


def write_png_rgba(path, arr: np.ndarray) -> None:
    assert arr.ndim == 3 and arr.shape[2] == 4
    ihdr = struct.pack('>IIBBBBB', arr.shape[1], arr.shape[0], 8, 6, 0, 0, 0)
    raw = _scanlines(arr.reshape(arr.shape[0], arr.shape[1] * 4))
    blob = (_SIG + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', _zlib_stream(raw)) + _chunk(b'IEND', b''))
    Path(path).write_bytes(blob)

# re-exports from the frozen module (same deterministic byte paths)
write_png_gray = _frozen.write_png_gray
write_png_rgb = _frozen.write_png_rgb
write_png_palette = _frozen.write_png_palette
deflate_fixed = _frozen.deflate_fixed
