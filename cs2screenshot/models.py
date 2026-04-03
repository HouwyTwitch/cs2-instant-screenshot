"""Data models for cs2screenshot."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


WEAR_TIERS = [
    (0.07, "FN"),
    (0.15, "MW"),
    (0.38, "FT"),
    (0.45, "WW"),
    (1.01, "BS"),
]

WEAR_TIER_NAMES = {
    "FN": "Factory New",
    "MW": "Minimal Wear",
    "FT": "Field-Tested",
    "WW": "Well-Worn",
    "BS": "Battle-Scarred",
}


def wear_tier(float_val: float) -> str:
    """Map a float value to its wear tier abbreviation."""
    for threshold, name in WEAR_TIERS:
        if float_val < threshold:
            return name
    return "BS"


@dataclass
class StickerData:
    slot: int
    sticker_id: int
    wear: float = 0.0
    pattern: int = 0
    scale: float = 0.0
    rotation: float = 0.0
    tint_id: int = 0
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_z: float = 0.0
    name: Optional[str] = None

    def __repr__(self) -> str:
        wear_str = f", wear={self.wear:.4f}" if self.wear else ""
        return f"StickerData(slot={self.slot}, sticker_id={self.sticker_id}{wear_str})"


@dataclass
class KeychainData:
    slot: int
    keychain_id: int
    pattern: int = 0
    name: Optional[str] = None

    def __repr__(self) -> str:
        return f"KeychainData(slot={self.slot}, keychain_id={self.keychain_id})"


@dataclass
class InspectData:
    """Decoded item parameters from a CS2 inspect link."""

    # Core item parameters
    defindex: Optional[int]      # weapon type ID
    paintindex: Optional[int]    # skin ID
    paintseed: Optional[int]     # pattern seed 0–999
    paintwear: Optional[float]   # float value 0.0–1.0

    # Item attributes
    stattrak: Optional[bool]
    stattrak_count: Optional[int]
    souvenir: Optional[bool]
    rarity: Optional[int]
    quality: Optional[int]
    item_name: Optional[str] = None
    paint_name: Optional[str] = None

    # Decorations
    stickers: list[StickerData] = field(default_factory=list)
    keychains: list[KeychainData] = field(default_factory=list)

    # Link parameters
    asset_id: int = 0
    owner_steamid: int = 0
    market_id: int = 0
    d_param: str = ""
    inspect_link: str = ""

    # Whether this item needs Game Coordinator lookup to resolve full data
    needs_gc_lookup: bool = False

    @property
    def wear_tier(self) -> Optional[str]:
        """Returns wear tier abbreviation (FN/MW/FT/WW/BS) or None."""
        if self.paintwear is None or self.paintwear <= 0:
            return None
        return wear_tier(self.paintwear)

    @property
    def wear_tier_name(self) -> Optional[str]:
        """Returns the full wear tier name or None."""
        t = self.wear_tier
        return WEAR_TIER_NAMES.get(t) if t else None

    def to_dict(self) -> dict:
        return {
            "defindex": self.defindex,
            "paintindex": self.paintindex,
            "paintseed": self.paintseed,
            "paintwear": self.paintwear,
            "wear_tier": self.wear_tier,
            "wear_tier_name": self.wear_tier_name,
            "stattrak": self.stattrak,
            "stattrak_count": self.stattrak_count,
            "souvenir": self.souvenir,
            "rarity": self.rarity,
            "quality": self.quality,
            "stickers": [
                {
                    "slot": s.slot,
                    "sticker_id": s.sticker_id,
                    "wear": s.wear,
                    "pattern": s.pattern,
                    "scale": s.scale,
                    "rotation": s.rotation,
                    "tint_id": s.tint_id,
                    "offset_x": s.offset_x,
                    "offset_y": s.offset_y,
                    "offset_z": s.offset_z,
                    "name": s.name,
                }
                for s in self.stickers
            ],
            "keychains": [
                {
                    "slot": k.slot,
                    "keychain_id": k.keychain_id,
                    "pattern": k.pattern,
                    "name": k.name,
                }
                for k in self.keychains
            ],
            "item_name": self.item_name,
            "paint_name": self.paint_name,
            "asset_id": self.asset_id,
            "owner_steamid": self.owner_steamid,
            "market_id": self.market_id,
            "inspect_link": self.inspect_link,
            "needs_gc_lookup": self.needs_gc_lookup,
        }
