"""Deterministic PNG writer for NIGHT-03 Patch 2B R1A-R5.

The deflate stream is produced by THIS module's own fixed-Huffman
LZ77 encoder: every output byte is a pure function of the pixel data,
with no dependence on zlib's version, strategy or tuning tables.
zlib is used only for the fully specified adler32/crc32 checksums.

This makes committed deliverables bit-reproducible in any environment:
fresh exact checkout -> delete output -> single freeze entry ->
committed files == rebuilt files, byte for byte.
"""
from __future__ import annotations

import struct
from pathlib import Path
from zlib import adler32, crc32

import numpy as np

# ---------------------------------------------------------------- bit IO


class _BitWriter:
    __slots__ = ('acc', 'n', 'out')

    def __init__(self):
        self.acc = 0
        self.n = 0
        self.out = bytearray()

    def put(self, value, nbits):
        # value packed LSB-first (deflate "other fields" order)
        self.acc |= value << self.n
        self.n += nbits
        while self.n >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.n -= 8

    def align(self):
        if self.n:
            self.out.append(self.acc & 0xFF)
            self.acc = 0
            self.n = 0


def _rev(code, nbits):
    r = 0
    for _ in range(nbits):
        r = (r << 1) | (code & 1)
        code >>= 1
    return r


def _fixed_lit(sym):
    if sym <= 143:
        return _rev(0x30 + sym, 8), 8
    if sym <= 255:
        return _rev(0x190 + sym - 144, 9), 9
    if sym <= 279:
        return _rev(sym - 256, 7), 7
    return _rev(0xC0 + sym - 280, 8), 8


_LIT = [_fixed_lit(s) for s in range(288)]

# (symbol, base, extra) for lengths 3..258 and distances 1..32768
_LEN_SPEC = [
    (257, 3, 0), (258, 4, 0), (259, 5, 0), (260, 6, 0), (261, 7, 0),
    (262, 8, 0), (263, 9, 0), (264, 10, 0), (265, 11, 1), (266, 13, 1),
    (267, 15, 1), (268, 17, 1), (269, 19, 2), (270, 23, 2), (271, 27, 2),
    (272, 31, 2), (273, 35, 3), (274, 43, 3), (275, 51, 3), (276, 59, 3),
    (277, 67, 4), (278, 83, 4), (279, 99, 4), (280, 115, 4), (281, 131, 5),
    (282, 163, 5), (283, 195, 5), (284, 227, 5), (285, 258, 0),
]
_DIST_SPEC = [
    (0, 1, 0), (1, 2, 0), (2, 3, 0), (3, 4, 0), (4, 5, 1), (5, 7, 1),
    (6, 9, 2), (7, 13, 2), (8, 17, 3), (9, 25, 3), (10, 33, 4),
    (11, 49, 4), (12, 65, 5), (13, 97, 5), (14, 129, 6), (15, 193, 6),
    (16, 257, 7), (17, 385, 7), (18, 513, 8), (19, 769, 8), (20, 1025, 9),
    (21, 1537, 9), (22, 2049, 10), (23, 3073, 10), (24, 4097, 11),
    (25, 6145, 11), (26, 8193, 12), (27, 12289, 12), (28, 16385, 13),
    (29, 24577, 13),
]
_DIST = [(_rev(s, 0), 0) for s in range(30)]  # placeholder, fixed below
# distance codes are 5-bit fixed codes: symbol s -> code s (MSB-first)
_DIST = [(_rev(s, 5), 5) for s in range(30)]


def _len_lookup(length):
    for sym, base, extra in _LEN_SPEC:
        if length < base + (1 << extra):
            return sym, base, extra
    return 285, 258, 0


def _dist_lookup(dist):
    for sym, base, extra in _DIST_SPEC:
        if dist < base + (1 << extra):
            return sym, base, extra
    return 29, 24577, 13


def deflate_fixed(data: bytes) -> bytes:
    """Single fixed-Huffman deflate block with greedy LZ77 (32 KiB window)."""
    bw = _BitWriter()
    bw.put(1, 1)   # BFINAL
    bw.put(1, 2)   # BTYPE=01 fixed Huffman
    n = len(data)
    i = 0
    prev = np.full(n, -1, np.int32)
    head = {}
    put = bw.put
    lit = _LIT
    while i < n:
        best = 0
        best_pos = 0
        h = -1
        if i + 3 <= n:
            h = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
            p = head.get(h, -1)
            lim = n - i
            if lim > 258:
                lim = 258
            tries = 32
            while p >= 0 and tries > 0 and i - p <= 32768:
                if best == 0 or data[p + best] == data[i + best]:
                    l = 0
                    while l < lim and data[p + l] == data[i + l]:
                        l += 1
                    if l > best:
                        best = l
                        best_pos = p
                        if l >= lim:
                            break
                p = int(prev[p])
                tries -= 1
        if best >= 3:
            sym, base, extra = _len_lookup(best)
            put(*lit[sym])
            if extra:
                put(best - base, extra)
            dsym, dbase, dextra = _dist_lookup(i - best_pos)
            put(*_DIST[dsym])
            if dextra:
                put(i - best_pos - dbase, dextra)
            end = i + best
            while i < end:
                if i + 3 <= n:
                    h2 = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
                    prev[i] = head.get(h2, -1)
                    head[h2] = i
                i += 1
        else:
            put(*lit[data[i]])
            if h >= 0:
                prev[i] = head.get(h, -1)
                head[h] = i
            i += 1
    put(*lit[256])
    bw.align()
    return bytes(bw.out)


# ---------------------------------------------------------------- PNG

_SIG = b'\x89PNG\r\n\x1a\n'


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack('>I', len(payload)) + tag + payload
            + struct.pack('>I', crc32(tag + payload) & 0xFFFFFFFF))


def _zlib_stream(raw: bytes) -> bytes:
    return (b'\x78\x01' + deflate_fixed(raw)
            + struct.pack('>I', adler32(raw) & 0xFFFFFFFF))


def _scanlines(flat: np.ndarray) -> bytes:
    h, w = flat.shape
    buf = np.zeros((h, w + 1), np.uint8)
    buf[:, 1:] = flat
    return buf.tobytes()


def write_png_gray(path, arr: np.ndarray) -> None:
    ihdr = struct.pack('>IIBBBBB', arr.shape[1], arr.shape[0], 8, 0, 0, 0, 0)
    raw = _scanlines(arr)
    blob = (_SIG + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', _zlib_stream(raw)) + _chunk(b'IEND', b''))
    Path(path).write_bytes(blob)


def write_png_rgb(path, arr: np.ndarray) -> None:
    ihdr = struct.pack('>IIBBBBB', arr.shape[1], arr.shape[0], 8, 2, 0, 0, 0)
    raw = _scanlines(arr.reshape(arr.shape[0], arr.shape[1] * 3))
    blob = (_SIG + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', _zlib_stream(raw)) + _chunk(b'IEND', b''))
    Path(path).write_bytes(blob)


def write_png_palette(path, arr: np.ndarray, palette, transparency=None):
    ihdr = struct.pack('>IIBBBBB', arr.shape[1], arr.shape[0], 8, 3, 0, 0, 0)
    plte = bytes(v for rgb in palette for v in rgb)
    blob = (_SIG + _chunk(b'IHDR', ihdr) + _chunk(b'PLTE', plte))
    if transparency is not None:
        blob += _chunk(b'tRNS', bytes(transparency))
    blob += (_chunk(b'IDAT', _zlib_stream(_scanlines(arr)))
             + _chunk(b'IEND', b''))
    Path(path).write_bytes(blob)
