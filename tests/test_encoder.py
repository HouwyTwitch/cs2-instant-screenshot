"""Round-trip tests for the inspect-link encoder (cs2screenshot.decoder.encode)."""
from __future__ import annotations

import math

from cs2screenshot.decoder import decode, encode
from cs2screenshot.models import StickerData


def test_encode_decode_basic_roundtrip() -> None:
    link = encode(defindex=7, paintindex=1425, paintseed=420, paintwear=0.25)
    d = decode(link)
    assert d.defindex == 7
    assert d.paintindex == 1425
    assert d.paintseed == 420
    assert math.isclose(d.paintwear, 0.25, rel_tol=1e-6)
    assert not d.needs_gc_lookup


def test_encode_decode_with_stickers() -> None:
    stickers = [StickerData(slot=i, sticker_id=sid) for i, sid in enumerate([1, 2, 3, 5])]
    link = encode(defindex=7, paintindex=1425, paintseed=1, paintwear=0.01, stickers=stickers)
    d = decode(link)
    assert [(s.slot, s.sticker_id) for s in d.stickers] == [(0, 1), (1, 2), (2, 3), (3, 5)]


def test_encode_produces_modern_link() -> None:
    link = encode(defindex=1, paintindex=0)
    assert "csgo_econ_action_preview" in link
    # Modern (hex) link — decodes without a GC lookup.
    assert decode(link).needs_gc_lookup is False
