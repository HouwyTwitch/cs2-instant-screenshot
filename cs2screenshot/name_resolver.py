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
    _skins_loaded = False
    _stickers_loaded = False
    _keychains_loaded = False
    _skin_by_pair: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    _sticker_names: dict[int, str] = {}
    _keychain_names: dict[int, str] = {}

    _SKINS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json"
    _STICKERS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/stickers.json"
    _KEYCHAINS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/keychains.json"

    @staticmethod
    def _to_int(value: object) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _fetch_json(cls, client: httpx.Client, url: str) -> list[dict]:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    @classmethod
    def _load_skins(cls) -> None:
        if cls._skins_loaded:
            return
        cls._skins_loaded = True
        try:
            with httpx.Client(timeout=1.5) as client:
                skins = cls._fetch_json(client, cls._SKINS_URL)
                for row in skins:
                    weapon = row.get("weapon") if isinstance(row.get("weapon"), dict) else {}
                    pattern = row.get("pattern") if isinstance(row.get("pattern"), dict) else {}

                    defindex = cls._to_int(weapon.get("weapon_id") or row.get("weapon_id") or row.get("def_index"))
                    paintindex = cls._to_int(row.get("paint_index") or row.get("paintindex"))
                    if defindex is None or paintindex is None:
                        continue

                    item_name = weapon.get("name") if isinstance(weapon.get("name"), str) else None
                    paint_name = pattern.get("name") if isinstance(pattern.get("name"), str) else None
                    cls._skin_by_pair[(defindex, paintindex)] = (item_name, paint_name)
        except Exception:
            return

    @classmethod
    def _load_stickers(cls) -> None:
        if cls._stickers_loaded:
            return
        cls._stickers_loaded = True
        try:
            with httpx.Client(timeout=1.5) as client:
                stickers = cls._fetch_json(client, cls._STICKERS_URL)
                for row in stickers:
                    sid = cls._to_int(row.get("def_index"))
                    name = row.get("name")
                    if isinstance(sid, int) and isinstance(name, str):
                        cls._sticker_names[sid] = name
        except Exception:
            return

    @classmethod
    def _load_keychains(cls) -> None:
        if cls._keychains_loaded:
            return
        cls._keychains_loaded = True
        try:
            with httpx.Client(timeout=1.5) as client:
                keychains = cls._fetch_json(client, cls._KEYCHAINS_URL)
                for row in keychains:
                    kid = cls._to_int(row.get("def_index"))
                    name = row.get("name")
                    if isinstance(kid, int) and isinstance(name, str):
                        cls._keychain_names[kid] = name
        except Exception:
            return

    @classmethod
    def resolve_skin(cls, defindex: Optional[int], paintindex: Optional[int]) -> ResolvedNames:
        if defindex is None or paintindex is None:
            return ResolvedNames(item_name=None, paint_name=None)
        item_name, paint_name = cls._skin_by_pair.get((defindex, paintindex), (None, None))
        if item_name is None and paint_name is None:
            cls._load_skins()
            item_name, paint_name = cls._skin_by_pair.get((defindex, paintindex), (None, None))
        return ResolvedNames(item_name=item_name, paint_name=paint_name)

    @classmethod
    def resolve_sticker_name(cls, sticker_id: int) -> Optional[str]:
        name = cls._sticker_names.get(sticker_id)
        if name is None:
            cls._load_stickers()
            name = cls._sticker_names.get(sticker_id)
        return name

    @classmethod
    def resolve_keychain_name(cls, keychain_id: int) -> Optional[str]:
        name = cls._keychain_names.get(keychain_id)
        if name is None:
            cls._load_keychains()
            name = cls._keychain_names.get(keychain_id)
        return name
