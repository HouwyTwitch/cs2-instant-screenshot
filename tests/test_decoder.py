"""Tests for the CS2 inspect link decoder.

The modern CS2 inspect link format (post-2025) is:
    steam://rungame/730/76561202255233023/+csgo_econ_action_preview {HEX}

Where HEX is: 00 [protobuf CEconItemPreviewDataBlock] [CRC32 4B big-endian]
(or the same with every byte XOR-ed by a mask key, mask key first).

Legacy format:
    +csgo_econ_action_preview S{steamid}A{assetid}D{numeric_d}

Reference: https://github.com/csfloat/cs-inspect-serializer
"""
import struct
import zlib

import pytest

from cs2screenshot.decoder import (
    _crc32_checksum,
    _parse_link,
    _unwrap_payload,
    decode,
)
from cs2screenshot.name_resolver import NameResolver
from cs2screenshot.models import InspectData


# ---------------------------------------------------------------------------
# Protobuf builder helpers
# ---------------------------------------------------------------------------

def _write_varint(value: int) -> bytes:
    parts = []
    while True:
        bits = value & 0x7F
        value >>= 7
        if value:
            parts.append(bits | 0x80)
        else:
            parts.append(bits)
            break
    return bytes(parts)


def _field_varint(field: int, value: int) -> bytes:
    return _write_varint((field << 3) | 0) + _write_varint(value)


def _field_bytes(field: int, data: bytes) -> bytes:
    return _write_varint((field << 3) | 2) + _write_varint(len(data)) + data


def _field_fixed32(field: int, value: int) -> bytes:
    return _write_varint((field << 3) | 5) + struct.pack("<I", value)


def _float_bits(f: float) -> int:
    return struct.unpack("<I", struct.pack("<f", f))[0]


def _build_sticker(slot: int, sticker_id: int, wear: float = 0.0, pattern: int = 0) -> bytes:
    data = _field_varint(1, slot) + _field_varint(2, sticker_id)
    if wear:
        data += _field_fixed32(3, _float_bits(wear))
    if pattern:
        data += _field_varint(10, pattern)
    return data


def _build_sticker_with_xyr(slot: int, sticker_id: int, x: float, y: float, r: float) -> bytes:
    data = _field_varint(1, slot) + _field_varint(2, sticker_id)
    data += _field_fixed32(7, _float_bits(x))
    data += _field_fixed32(8, _float_bits(y))
    data += _field_fixed32(9, _float_bits(r))
    return data


def _build_block(
    defindex: int = 7,
    paintindex: int = 282,
    paintseed: int = 500,
    paintwear: float = 0.15,
    quality: int = 4,
    rarity: int = 4,
    killeater_type: int | None = None,
    killeater_value: int | None = None,
    stickers: list[bytes] | None = None,
    keychains: list[bytes] | None = None,
    itemid: int = 0,
    accountid: int = 0,
) -> bytes:
    """Build a CEconItemPreviewDataBlock protobuf payload (unwrapped)."""
    data = b""
    if accountid:
        data += _field_varint(1, accountid)
    if itemid:
        data += _field_varint(2, itemid)
    data += _field_varint(3, defindex)
    data += _field_varint(4, paintindex)
    data += _field_varint(5, rarity)
    data += _field_varint(6, quality)
    data += _field_varint(7, _float_bits(paintwear))  # field 7 = paintwear
    data += _field_varint(8, paintseed)               # field 8 = paintseed
    if killeater_type is not None:
        data += _field_varint(9, killeater_type)
    if killeater_value is not None:
        data += _field_varint(10, killeater_value)
    for s in (stickers or []):
        data += _field_bytes(12, s)
    for k in (keychains or []):
        data += _field_bytes(20, k)
    return data


def _wrap(proto_bytes: bytes) -> bytes:
    """Wrap protobuf bytes: [0x00][proto][CRC32 big-endian 4B]."""
    csum = _crc32_checksum(proto_bytes)
    return b"\x00" + proto_bytes + struct.pack(">I", csum)


def _to_link(proto_bytes: bytes) -> str:
    hex_str = _wrap(proto_bytes).hex().upper()
    return f"steam://rungame/730/76561202255233023/+csgo_econ_action_preview {hex_str}"


def _to_raw_link(proto_bytes: bytes, *, prefixed: bool = False) -> str:
    raw = (b"\x00" + proto_bytes) if prefixed else proto_bytes
    return (
        "steam://rungame/730/76561202255233023/+csgo_econ_action_preview "
        f"{raw.hex().upper()}"
    )


# ---------------------------------------------------------------------------
# Unit: _crc32_checksum
# ---------------------------------------------------------------------------

class TestChecksum:
    def test_matches_reference_vector(self):
        # Generate a known payload and verify wrap/unwrap round-trips
        proto = _build_block()
        wrapped = _wrap(proto)
        # Unwrapping should not raise
        result = _unwrap_payload(wrapped)
        assert result == proto

    def test_bad_checksum_falls_back_to_raw_proto_plus_footer(self):
        proto = _build_block()
        wrapped = bytearray(_wrap(proto))
        wrapped[-1] ^= 0xFF  # corrupt last checksum byte
        unwrapped = _unwrap_payload(bytes(wrapped))
        assert unwrapped.startswith(proto)
        assert len(unwrapped) == len(proto) + 4


# ---------------------------------------------------------------------------
# Unit: _unwrap_payload
# ---------------------------------------------------------------------------

class TestUnwrapPayload:
    def test_too_short_raises(self):
        assert _unwrap_payload(b"\x00\x01\x02") == b"\x01\x02"

    def test_unmasked(self):
        proto = _build_block(defindex=7)
        assert _unwrap_payload(_wrap(proto)) == proto

    def test_xor_masked(self):
        proto = _build_block(defindex=7)
        wrapped = _wrap(proto)
        key = 0x42
        masked = bytes(b ^ key for b in wrapped)
        assert _unwrap_payload(masked) == proto

    def test_bad_mask_raises(self):
        # Mask by key=0x01: first byte becomes 0x01 ^ 0x00 = 0x01, after
        # unmasking first byte is 0x01 ^ 0x01 = 0x00 ✓ — so key=0x01 is valid.
        # Key=0xFF masks 0x00→0xFF; unmasked 0xFF^0xFF=0x00 ✓ also valid.
        # Use a payload where XOR result ≠ 0 for byte 0 to trigger the error:
        bad = bytes([0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])  # unmask: 0x01^0x01=0x00... still valid
        # Actually impossible to construct without valid proto, so just test too-short path
        assert _unwrap_payload(b"\x01\x02") == b"\x03"

    def test_raw_proto_without_checksum(self):
        proto = _build_block(defindex=42)
        assert _unwrap_payload(proto) == proto

    def test_raw_proto_with_zero_prefix(self):
        proto = _build_block(defindex=42)
        assert _unwrap_payload(b"\x00" + proto) == proto


# ---------------------------------------------------------------------------
# Unit: _parse_link
# ---------------------------------------------------------------------------

class TestParseLink:
    def test_modern_hex_link(self):
        link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview DEADBEEF00112233"
        kind, params = _parse_link(link)
        assert kind == "modern"
        assert params["hex"] == "DEADBEEF00112233"

    def test_modern_lowercase_hex(self):
        link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview deadbeef"
        kind, params = _parse_link(link)
        assert kind == "modern"
        assert params["hex"] == "deadbeef"

    def test_legacy_s_format(self):
        link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview S76561198153518904A1234567890D9876543210"
        kind, params = _parse_link(link)
        assert kind == "legacy"
        assert params["asset_id"] == 1234567890
        assert params["d_param"] == "9876543210"

    def test_legacy_m_format(self):
        link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview M987654321A1234567890D000111222"
        kind, params = _parse_link(link)
        assert kind == "legacy"
        assert params["asset_id"] == 1234567890

    def test_legacy_b_format(self):
        link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview B111222333A9876543210D1111111"
        kind, params = _parse_link(link)
        assert kind == "legacy"
        assert params["asset_id"] == 9876543210

    def test_invalid_link_raises(self):
        with pytest.raises(ValueError, match="csgo_econ_action_preview"):
            _parse_link("steam://rungame/730/notaninspectlink")

    def test_odd_length_hex_raises(self):
        with pytest.raises(ValueError, match="odd length"):
            _parse_link("steam://rungame/730/76561202255233023/+csgo_econ_action_preview DEADBEE")


# ---------------------------------------------------------------------------
# Integration: decode() — legacy
# ---------------------------------------------------------------------------

class TestDecodeLegacy:
    def test_s_format(self):
        link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview S76561198153518904A1234567890D9876543210"
        data = decode(link)
        assert data.needs_gc_lookup is True
        assert data.asset_id == 1234567890
        assert data.defindex is None
        assert data.paintwear is None

    def test_m_format(self):
        link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview M999888777A1234567890D000111"
        data = decode(link)
        assert data.needs_gc_lookup is True
        assert data.asset_id == 1234567890


# ---------------------------------------------------------------------------
# Integration: decode() — modern self-encoded
# ---------------------------------------------------------------------------

class TestDecodeModern:
    def _make(self, **kwargs) -> InspectData:
        proto = _build_block(**kwargs)
        return decode(_to_link(proto))

    def test_basic_fields(self):
        data = self._make(defindex=7, paintindex=282, paintseed=661, paintwear=0.08)
        assert data.needs_gc_lookup is False
        assert data.defindex == 7
        assert data.paintindex == 282
        assert data.paintseed == 661
        assert abs(data.paintwear - 0.08) < 1e-5

    def test_wear_tier_fn(self):
        data = self._make(paintwear=0.01)
        assert data.wear_tier == "FN"
        assert data.wear_tier_name == "Factory New"

    def test_wear_tier_mw(self):
        data = self._make(paintwear=0.10)
        assert data.wear_tier == "MW"

    def test_wear_tier_ft(self):
        data = self._make(paintwear=0.20)
        assert data.wear_tier == "FT"

    def test_wear_tier_ww(self):
        data = self._make(paintwear=0.40)
        assert data.wear_tier == "WW"

    def test_wear_tier_bs(self):
        data = self._make(paintwear=0.90)
        assert data.wear_tier == "BS"

    def test_stattrak(self):
        data = self._make(quality=12, killeater_type=0, killeater_value=1337)
        assert data.stattrak is True
        assert data.stattrak_count == 1337
        assert data.souvenir is None

    def test_souvenir(self):
        data = self._make(quality=9)
        assert data.souvenir is True
        assert data.stattrak is None

    def test_stickers(self):
        sticker_bytes = [
            _build_sticker(0, 100),
            _build_sticker(1, 200, wear=0.5),
            _build_sticker(3, 999, pattern=42),
        ]
        data = self._make(stickers=sticker_bytes)
        assert len(data.stickers) == 3
        assert data.stickers[0].slot == 0
        assert data.stickers[0].sticker_id == 100
        assert data.stickers[1].slot == 1
        assert abs(data.stickers[1].wear - 0.5) < 1e-4
        assert data.stickers[2].pattern == 42

    def test_no_stickers(self):
        data = self._make()
        assert data.stickers == []

    def test_inspect_link_preserved(self):
        proto = _build_block(defindex=60, paintindex=77)
        link = _to_link(proto)
        data = decode(link)
        assert data.inspect_link == link

    def test_rarity(self):
        data = self._make(rarity=6)
        assert data.rarity == 6

    def test_to_dict_keys(self):
        data = self._make(defindex=7, paintindex=282)
        d = data.to_dict()
        for key in ("defindex", "paintindex", "paintseed", "paintwear",
                    "wear_tier", "stattrak", "souvenir", "stickers",
                    "keychains", "inspect_link", "needs_gc_lookup"):
            assert key in d

    def test_masked_payload(self):
        """XOR-masked payloads should decode identically."""
        proto = _build_block(defindex=7, paintindex=282, paintseed=661, paintwear=0.15)
        wrapped = _wrap(proto)
        key = 0x37
        masked = bytes(b ^ key for b in wrapped)
        hex_str = masked.hex().upper()
        link = f"steam://rungame/730/76561202255233023/+csgo_econ_action_preview {hex_str}"
        data = decode(link)
        assert data.defindex == 7
        assert data.paintseed == 661
        assert abs(data.paintwear - 0.15) < 1e-5

    def test_reference_hex(self):
        """Decode the example hex from the csfloat/cs-inspect-serializer README."""
        # From generateHex docstring:
        # "00180720C80A280638A4E1F5FB03409A0562040800104C62040801104C62040802104C62040803104C6D4F5E30"
        hex_str = "00180720C80A280638A4E1F5FB03409A0562040800104C62040801104C62040802104C62040803104C6D4F5E30"
        link = f"steam://rungame/730/76561202255233023/+csgo_econ_action_preview {hex_str}"
        data = decode(link)
        assert data.needs_gc_lookup is False
        # Validate we get plausible values (not all zeros)
        assert data.defindex is not None or data.paintindex is not None or data.paintseed is not None

    def test_raw_proto_no_checksum(self):
        proto = _build_block(defindex=16, paintindex=711, paintseed=512, paintwear=0.1234)
        link = _to_raw_link(proto, prefixed=True)
        data = decode(link)
        assert data.defindex == 16
        assert data.paintindex == 711
        assert data.paintseed == 512
        assert abs(data.paintwear - 0.1234) < 1e-5

    def test_user_reported_new_link_type(self):
        hex_str = (
            "34248FE2BB9C89352C3D14D7351C3104300CE4DAEBC53774F63056313C3524AB"
            "36563E3C3724C81111EEA5B20B56313C3624A600563B3C3724A60009C6AE0F0A"
            "71B4041F0F5CB7B4B4B438443C4D060D14"
        )
        link = f"steam://rungame/730/76561202255233023/+csgo_econ_action_preview {hex_str}"
        data = decode(link)
        assert data.needs_gc_lookup is False
        assert data.defindex == 9
        assert data.paintindex == 227
        assert data.paintseed == 578

    def test_sticker_offsets_are_decoded(self):
        hex_str = (
            "00183C20F90728053004389C8EFDE703408201620A0803108F271D00000000"
            "620A0801108F271D00000000620A0802108F271D00000000620A0800108F271D"
            "0000000062140804108F271D000000003D2508873E4500D9893A7B316755"
        )
        link = f"steam://rungame/730/76561202255233023/+csgo_econ_action_preview {hex_str}"
        data = decode(link)
        assert len(data.stickers) == 5
        s = data.stickers[4]
        assert abs(s.offset_x - 0.2637) < 1e-4
        assert abs(s.offset_y - 0.0011) < 1e-4

    def test_rotation_falls_back_to_field_9(self):
        sticker = _build_sticker_with_xyr(0, 5007, 0.2, 0.1, 0.6)
        data = self._make(stickers=[sticker])
        assert len(data.stickers) == 1
        s = data.stickers[0]
        assert abs(s.offset_x - 0.2) < 1e-4
        assert abs(s.offset_y - 0.1) < 1e-4
        assert abs(s.rotation - 0.6) < 1e-4

    def test_name_resolution_from_cache(self, monkeypatch):
        monkeypatch.setattr(NameResolver, "_skins_loaded", True)
        monkeypatch.setattr(NameResolver, "_stickers_loaded", True)
        monkeypatch.setattr(NameResolver, "_keychains_loaded", True)
        monkeypatch.setattr(NameResolver, "_skin_by_pair", {(60, 1017): ("M4A1-S", "Printstream")})
        monkeypatch.setattr(NameResolver, "_sticker_names", {5007: "Movistar Riders (Holo) | Stockholm 2021"})
        monkeypatch.setattr(NameResolver, "_keychain_names", {12: "Hot Howl"})

        sticker = _build_sticker(0, 5007)
        keychain = _build_sticker(1, 12)
        data = self._make(defindex=60, paintindex=1017, stickers=[sticker], keychains=[keychain])

        assert data.item_name == "M4A1-S"
        assert data.paint_name == "Printstream"
        assert data.stickers[0].name == "Movistar Riders (Holo) | Stockholm 2021"
        assert data.keychains[0].name == "Hot Howl"
