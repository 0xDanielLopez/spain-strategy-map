"""Minimal stdlib readers for ESRI shapefiles (.shp polygons) and dBASE tables (.dbf).

Both take a binary file object, so they work straight on zipfile members (sequential
reads only). Only what the INE census-section boundaries need: polygon shapes
(type 5) with their parts, and character/numeric dBASE fields.
"""

from __future__ import annotations

import struct
from typing import BinaryIO, Iterator

POLYGON = 5


def read_dbf(f: BinaryIO, encoding: str = "utf-8") -> list[dict[str, str]]:
    """All records of a .dbf as {field name: stripped text} (deleted records are skipped but keep their position
    in the .shp, so use read_dbf_all() when positions matter)."""
    return [r for r in read_dbf_all(f, encoding) if r is not None]


def read_dbf_all(f: BinaryIO, encoding: str = "utf-8") -> list[dict[str, str] | None]:
    """Records in file order; a deleted record is None (so index i matches shape i)."""
    head = f.read(32)
    if len(head) < 32:
        raise ValueError("dbf: truncated header")
    n_records, header_len, record_len = struct.unpack("<IHH", head[4:12])
    fields: list[tuple[str, int]] = []
    desc = f.read(header_len - 32)
    for i in range(0, len(desc), 32):
        if desc[i] == 0x0D:
            break
        name = desc[i : i + 11].split(b"\0", 1)[0].decode("ascii", "replace")
        fields.append((name, desc[i + 16]))
    out: list[dict[str, str] | None] = []
    for _ in range(n_records):
        rec = f.read(record_len)
        if len(rec) < record_len:
            raise ValueError("dbf: truncated records")
        if rec[0] == 0x2A:  # deleted
            out.append(None)
            continue
        pos, row = 1, {}
        for name, length in fields:
            row[name] = rec[pos : pos + length].decode(encoding, "replace").strip()
            pos += length
        out.append(row)
    return out


def iter_polygons(f: BinaryIO, wanted=None) -> Iterator[tuple[int, list[list[tuple[float, float]]]]]:
    """Yield (record index from 0, rings) for each polygon record, in file order.

    rings = every part of the shape as [(x, y), ...] (outer rings and holes, as stored).
    `wanted` is an optional container of record indexes; the others are skipped without decoding.
    A null shape yields no rings.
    """
    head = f.read(100)
    if len(head) < 100 or struct.unpack(">i", head[:4])[0] != 9994:
        raise ValueError("shp: bad file header")
    index = 0
    while True:
        rh = f.read(8)
        if len(rh) < 8:
            return
        words = struct.unpack(">ii", rh)[1]
        body = f.read(words * 2)
        if wanted is None or index in wanted:
            yield index, _decode_polygon(body)
        index += 1


def _decode_polygon(body: bytes) -> list[list[tuple[float, float]]]:
    stype = struct.unpack("<i", body[:4])[0]
    if stype == 0:
        return []
    if stype not in (POLYGON, 15, 25):
        raise ValueError(f"shp: unsupported shape type {stype}")
    n_parts, n_points = struct.unpack("<ii", body[36:44])
    parts = list(struct.unpack(f"<{n_parts}i", body[44 : 44 + 4 * n_parts]))
    base = 44 + 4 * n_parts
    flat = struct.unpack(f"<{2 * n_points}d", body[base : base + 16 * n_points])
    pts = list(zip(flat[0::2], flat[1::2]))
    parts.append(n_points)
    return [pts[parts[i] : parts[i + 1]] for i in range(n_parts)]
