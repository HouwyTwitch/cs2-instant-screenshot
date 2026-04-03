"""Best-effort name resolution for CS2 ids.

Uses public metadata endpoints when available and falls back gracefully when
network access is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class ResolvedNames:
    item_name: Optional[str]
    paint_name: Optional[str]


class NameResolver:
    _loaded = False
    _skin_by_pair: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    _sticker_names: dict[int, str] = {}
    _keychain_names: dict[int, str] = {}

    _SKINS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins_not_grouped.json"
    _STICKERS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/stickers.json"
    _KEYCHAINS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/charms.json"

    @classmethod
    def _fetch_json(cls, client: httpx.Client, url: str) -> list[dict]:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True

        try:
            with httpx.Client(timeout=1.5) as client:
                skins = cls._fetch_json(client, cls._SKINS_URL)
                for row in skins:
                    weapon = row.get("weapon") if isinstance(row.get("weapon"), dict) else {}
                    pattern = row.get("pattern") if isinstance(row.get("pattern"), dict) else {}

                    defindex = weapon.get("id") or row.get("defindex") or row.get("weapon_id")
                    paintindex = pattern.get("id") or row.get("paintindex") or row.get("paint_index")
                    if not isinstance(defindex, int) or not isinstance(paintindex, int):
                        continue

                    item_name = weapon.get("name") if isinstance(weapon.get("name"), str) else None
                    paint_name = row.get("name") if isinstance(row.get("name"), str) else None
                    cls._skin_by_pair[(defindex, paintindex)] = (item_name, paint_name)

                stickers = cls._fetch_json(client, cls._STICKERS_URL)
                for row in stickers:
                    sid = row.get("id")
                    name = row.get("name")
                    if isinstance(sid, int) and isinstance(name, str):
                        cls._sticker_names[sid] = name

                keychains = cls._fetch_json(client, cls._KEYCHAINS_URL)
                for row in keychains:
                    kid = row.get("id")
                    name = row.get("name")
                    if isinstance(kid, int) and isinstance(name, str):
                        cls._keychain_names[kid] = name
        except Exception:
            # Best-effort only; decoding should still work with numeric ids.
            return

    @classmethod
    def resolve_skin(cls, defindex: Optional[int], paintindex: Optional[int]) -> ResolvedNames:
        cls._load()
        if defindex is None or paintindex is None:
            return ResolvedNames(item_name=None, paint_name=None)
        item_name, paint_name = cls._skin_by_pair.get((defindex, paintindex), (None, None))
        return ResolvedNames(item_name=item_name, paint_name=paint_name)

    @classmethod
    def resolve_sticker_name(cls, sticker_id: int) -> Optional[str]:
        cls._load()
        return cls._sticker_names.get(sticker_id)

    @classmethod
    def resolve_keychain_name(cls, keychain_id: int) -> Optional[str]:
        cls._load()
        return cls._keychain_names.get(keychain_id)
