"""Decoder for CS2 inspect links.

CS2 inspect links come in two forms:

1. **Modern (self-encoded, post-2025)** — the payload is a hex-encoded binary blob:

   ``steam://rungame/730/76561202255233023/+csgo_econ_action_preview {HEX}``

   The hex blob is structured as::

       [0x00][protobuf CEconItemPreviewDataBlock][CRC32 4 bytes big-endian]

   If the first byte is not ``0x00`` it is an XOR mask key: every byte (including
   the first) is XOR-ed with that key first, which produces the above layout.

   All item parameters (defindex, float, paintseed, stickers, …) are encoded
   directly in the protobuf — no Steam bot or Game Coordinator needed.

2. **Legacy** — the payload encodes owner/market/asset IDs and an auth token:

   ``+csgo_econ_action_preview S{steamid}A{assetid}D{d}``
   ``+csgo_econ_action_preview M{market_id}A{assetid}D{d}``

   Full item data requires a Game Coordinator lookup via a Steam bot session.
   The decoder returns what it can (asset_id, owner_steamid) and sets
   ``needs_gc_lookup=True``.

Reference implementation: https://github.com/csfloat/cs-inspect-serializer
"""
from __future__ import annotations

import re
import struct
import zlib
from typing import Optional
from urllib.parse import unquote

from .models import InspectData, KeychainData, StickerData

# ---------------------------------------------------------------------------
# CEconItemPreviewDataBlock field numbers
# (from csfloat/cs-inspect-serializer)
# ---------------------------------------------------------------------------
#  1  accountid         uint32
#  2  itemid            uint64
#  3  defindex          uint32
#  4  paintindex        uint32
#  5  rarity            uint32
#  6  quality           uint32   (6=normal, 9=souvenir, 12=stattrak/unusual)
#  7  paintwear         uint32   raw IEEE-754 float32 bits
#  8  paintseed         uint32
#  9  killeaterscoretype uint32  (0 = kills)
# 10  killeatervalue    uint32   (kill count)
# 11  customname        string   (length-delimited)
# 12  stickers          repeated Sticker (length-delimited each)
# 13  inventory         uint32
# 14  origin            uint32
# 20  keychains         repeated Sticker (length-delimited each)
# 22  variations        repeated Sticker (length-delimited each)
#
# CEconItemPreviewDataBlock.Sticker field numbers:
#  1  slot              uint32
#  2  sticker_id        uint32
#  3  wear              float32  (wire type 5)
#  4  scale             float32  (wire type 5)
#  5  rotation          float32  (wire type 5)
#  6  tint_id           uint32
#  7  offset_x          float32
#  8  offset_y          float32
#  9  offset_z          float32
# 10  pattern           uint32

# ---------------------------------------------------------------------------
# Minimal self-contained protobuf binary decoder
# ---------------------------------------------------------------------------


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Read a varint at *pos*. Returns ``(value, new_pos)``."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("Truncated varint in protobuf data")


def _decode_proto(data: bytes) -> dict[int, object]:
    """Decode a flat protobuf message into ``{field_number: value}``."""
    result: dict[int, object] = {}
    pos = 0
    n = len(data)

    while pos < n:
        tag, pos = _read_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if wire_type == 0:
            value: object
            value, pos = _read_varint(data, pos)
        elif wire_type == 1:
            if pos + 8 > n:
                raise ValueError("Truncated 64-bit field in protobuf data")
            value = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
        elif wire_type == 2:
            length, pos = _read_varint(data, pos)
            if pos + length > n:
                raise ValueError("Truncated length-delimited field in protobuf data")
            value = data[pos : pos + length]
            pos += length
        elif wire_type == 5:
            if pos + 4 > n:
                raise ValueError("Truncated 32-bit field in protobuf data")
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        else:
            raise ValueError(f"Unknown protobuf wire type {wire_type} at byte {pos}")

        if field_number in result:
            existing = result[field_number]
            if isinstance(existing, list):
                existing.append(value)  # type: ignore[arg-type]
            else:
                result[field_number] = [existing, value]
        else:
            result[field_number] = value

    return result


def _as_list(val: object) -> list:
    if val is None:
        return []
    return val if isinstance(val, list) else [val]

def _uint32_to_float(v: int) -> float:
    return struct.unpack("<f", struct.pack("<I", v))[0]


# ---------------------------------------------------------------------------
# Checksum (matches csfloat/cs-inspect-serializer getChecksum)
# ---------------------------------------------------------------------------

def _crc32_checksum(payload: bytes) -> int:
    """Compute the inspect payload checksum.

    Algorithm: CRC32 of [0x00 || payload], then fold:
        x_crc = (crc & 0xFFFF) ^ (len(payload) * crc)
        result = x_crc & 0xFFFFFFFF
    """
    buf = b"\x00" + payload
    crc = zlib.crc32(buf) & 0xFFFFFFFF
    # zlib.crc32 returns the same polynomial as the JS CRC32.buf
    x_crc = (crc & 0xFFFF) ^ ((len(payload) * crc) & 0xFFFFFFFF)
    return x_crc & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Payload unwrapping
# ---------------------------------------------------------------------------

def _xor_mask(data: bytes, key: int) -> bytes:
    return bytes(b ^ key for b in data)


def _unwrap_payload(raw: bytes) -> bytes:
    """Unwrap modern inspect hex and return protobuf bytes.

    Supported modern encodings:
    * Wrapped (legacy-modern): [0x00][proto...][checksum 4B big-endian]
    * Wrapped XOR:             [key] XOR(key, 0x00 || proto... || checksum)
    * Raw proto:               [proto...]
    * Raw proto + 0x00 prefix: [0x00][proto...]
    * Raw proto XOR:           [key] XOR(key, 0x00 || proto...)  (new links)
    """
    if len(raw) < 2:
        raise ValueError("Inspect hex payload is too short")

    # If first byte doesn't look like a protobuf tag start, treat it as XOR key.
    # Common first-byte values for unmasked payloads are 0x00, 0x08, 0x10, 0x18, 0x20.
    if raw[0] not in (0x00, 0x08, 0x10, 0x18, 0x20):
        raw = _xor_mask(raw, raw[0])

    if raw[0] == 0x00:
        # First try wrapped payload with checksum.
        if len(raw) >= 5:
            wrapped_proto = raw[1:-4]
            expected_csum = struct.unpack_from(">I", raw, len(raw) - 4)[0]
            actual_csum = _crc32_checksum(wrapped_proto)
            if expected_csum == actual_csum:
                return wrapped_proto
            # Some newer links are protobuf + trailing 4-byte footer that does not
            # match historical checksum. Keep both candidates for parser fallback.
            return raw[1:]
        return raw[1:]

    return raw


# ---------------------------------------------------------------------------
# Sticker / keychain decoding
# ---------------------------------------------------------------------------

def _decode_sticker(raw: bytes) -> StickerData:
    f = _decode_proto(raw)
    wear_raw = f.get(3, 0)
    scale_raw = f.get(4, 0)
    rot_raw = f.get(5, 0)
    off_x_raw = f.get(7, 0)
    off_y_raw = f.get(8, 0)
    off_z_raw = f.get(9, 0)
    rotation = _uint32_to_float(rot_raw) if rot_raw else 0.0
    offset_z = _uint32_to_float(off_z_raw) if off_z_raw else 0.0
    if not rotation and offset_z:
        rotation = offset_z

    return StickerData(
        slot=int(f.get(1, 0)),
        sticker_id=int(f.get(2, 0)),
        wear=_uint32_to_float(wear_raw) if wear_raw else 0.0,
        scale=_uint32_to_float(scale_raw) if scale_raw else 0.0,
        rotation=rotation,
        tint_id=int(f.get(6, 0)),
        offset_x=_uint32_to_float(off_x_raw) if off_x_raw else 0.0,
        offset_y=_uint32_to_float(off_y_raw) if off_y_raw else 0.0,
        offset_z=offset_z,
        pattern=int(f.get(10, 0)),
    )


def _decode_keychain(raw: bytes) -> KeychainData:
    f = _decode_proto(raw)
    return KeychainData(
        slot=int(f.get(1, 0)),
        keychain_id=int(f.get(2, 0)),
        pattern=int(f.get(10, 0)),
    )


# ---------------------------------------------------------------------------
# Inspect link parsing
# ---------------------------------------------------------------------------

_PREVIEW_MARKER = "csgo_econ_action_preview"

# Modern: hex blob after the marker
_HEX_RE = re.compile(
    r"\+?" + _PREVIEW_MARKER + r"\s+([0-9A-Fa-f]+)\s*$",
    re.IGNORECASE,
)

# Legacy: S/M/B + A + D numeric params
_LEGACY_RE = re.compile(
    r"\+?" + _PREVIEW_MARKER + r"\s+(?:[SMBsmb](\d+))?A(\d+)D(\S+)\s*$",
    re.IGNORECASE,
)


def _parse_link(link: str) -> tuple[str, dict]:
    """Parse an inspect link.

    Returns ``('modern', {'hex': str})`` or ``('legacy', {params})``.
    Raises ``ValueError`` if the link cannot be parsed.
    """
    normalized = unquote(link).strip()

    if _PREVIEW_MARKER.lower() not in normalized.lower():
        raise ValueError(
            "Not a valid CS2 inspect link: missing csgo_econ_action_preview"
        )

    # Check legacy format first — its leading letter (S/M/B) distinguishes it
    # from the modern all-hex format even though hex digits include A–F.
    m = _LEGACY_RE.search(normalized)
    if m:
        owner_or_market, asset_id_str, d_str = m.group(1), m.group(2), m.group(3)
        return "legacy", {
            "owner_or_market": int(owner_or_market) if owner_or_market else None,
            "asset_id": int(asset_id_str),
            "d_param": d_str,
        }

    m = _HEX_RE.search(normalized)
    if m:
        hex_str = m.group(1)
        if len(hex_str) % 2 != 0:
            raise ValueError(f"Inspect hex has odd length: {hex_str!r}")
        return "modern", {"hex": hex_str}

    raise ValueError(f"Cannot parse inspect link parameters from: {normalized!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decode(inspect_link: str) -> InspectData:
    """Decode a CS2 inspect link and return item parameters.

    **Modern links** (post-2025 CS2) contain a hex-encoded self-describing
    payload.  All item data is extracted directly — no Steam bot needed.

    **Legacy links** encode ``S``/``M``/``B``, ``A``, and ``D`` numeric
    parameters.  Full item data requires querying the Steam Game Coordinator.
    The returned :class:`InspectData` has ``needs_gc_lookup=True`` and item
    fields set to ``None``.

    Args:
        inspect_link: A CS2 inspect link.

    Returns:
        :class:`InspectData` with decoded parameters.

    Raises:
        ValueError: If the link cannot be parsed or the payload is invalid.
    """
    kind, params = _parse_link(inspect_link)

    if kind == "legacy":
        return InspectData(
            defindex=None,
            paintindex=None,
            paintseed=None,
            paintwear=None,
            stattrak=None,
            stattrak_count=None,
            souvenir=None,
            rarity=None,
            quality=None,
            stickers=[],
            keychains=[],
            asset_id=params["asset_id"],
            owner_steamid=0,
            market_id=0,
            d_param=params["d_param"],
            inspect_link=inspect_link,
            needs_gc_lookup=True,
        )

    # Modern hex payload
    raw = bytes.fromhex(params["hex"])
    proto_bytes = _unwrap_payload(raw)
    parse_error: Optional[Exception] = None
    f: dict[int, object] = {}
    for candidate in (proto_bytes, proto_bytes[:-4] if len(proto_bytes) > 4 else b""):
        if not candidate:
            continue
        try:
            f = _decode_proto(candidate)
            parse_error = None
            break
        except Exception as exc:
            parse_error = exc
            continue
    if parse_error is not None:
        raise ValueError(f"Invalid inspect protobuf payload: {parse_error}") from parse_error

    defindex = int(f[3]) if 3 in f else None
    paintindex = int(f[4]) if 4 in f else None
    rarity = int(f[5]) if 5 in f else None
    quality = int(f[6]) if 6 in f else 4

    paintwear: Optional[float] = None
    if 7 in f:
        paintwear = _uint32_to_float(int(f[7]))

    paintseed = int(f[8]) if 8 in f else None
    killeater_value = int(f[10]) if 10 in f else None

    # StatTrak: quality 12 = unusual/stattrak in CS2
    is_stattrak = quality == 12
    stattrak_count = killeater_value if is_stattrak else None
    is_souvenir = quality == 9

    # Stickers (field 12) — each entry is bytes for a Sticker sub-message
    stickers: list[StickerData] = [
        _decode_sticker(s)
        for s in _as_list(f.get(12))
        if isinstance(s, bytes)
    ]

    # Keychains (field 20)
    keychains: list[KeychainData] = [
        _decode_keychain(k)
        for k in _as_list(f.get(20))
        if isinstance(k, bytes)
    ]

    return InspectData(
        defindex=defindex,
        paintindex=paintindex,
        paintseed=paintseed,
        paintwear=paintwear,
        stattrak=is_stattrak if is_stattrak else None,
        stattrak_count=stattrak_count,
        souvenir=is_souvenir if is_souvenir else None,
        rarity=rarity,
        quality=quality,
        stickers=stickers,
        keychains=keychains,
        asset_id=int(f.get(2, 0)),
        owner_steamid=int(f.get(1, 0)),
        market_id=0,
        d_param="",
        inspect_link=inspect_link,
        needs_gc_lookup=False,
    )
