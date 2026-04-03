"""Best-effort name resolution for CS2 ids.

Uses public metadata endpoints when available and falls back gracefully when
network access is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
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
    _state_loaded = False
    _last_failed_at: float = 0.0
    _FAIL_RETRY_SECONDS = 60 * 60 * 6
    _STATE_PATH = Path.home() / ".cache" / "cs2screenshot" / "name_resolver_state.json"

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
    def _load_state(cls) -> None:
        if cls._state_loaded:
            return
        cls._state_loaded = True
        try:
            if cls._STATE_PATH.exists():
                data = json.loads(cls._STATE_PATH.read_text(encoding="utf-8"))
                cls._last_failed_at = float(data.get("last_failed_at", 0.0))
                skin_by_pair = data.get("skin_by_pair", {})
                if isinstance(skin_by_pair, dict):
                    parsed: dict[tuple[int, int], tuple[str | None, str | None]] = {}
                    for k, v in skin_by_pair.items():
                        try:
                            d, p = k.split(":")
                            defindex = int(d)
                            paintindex = int(p)
                        except Exception:
                            continue
                        if isinstance(v, list) and len(v) == 2:
                            item_name = v[0] if isinstance(v[0], str) else None
                            paint_name = v[1] if isinstance(v[1], str) else None
                            parsed[(defindex, paintindex)] = (item_name, paint_name)
                    cls._skin_by_pair.update(parsed)

                sticker_names = data.get("sticker_names", {})
                if isinstance(sticker_names, dict):
                    for k, v in sticker_names.items():
                        try:
                            sid = int(k)
                        except Exception:
                            continue
                        if isinstance(v, str):
                            cls._sticker_names[sid] = v

                keychain_names = data.get("keychain_names", {})
                if isinstance(keychain_names, dict):
                    for k, v in keychain_names.items():
                        try:
                            kid = int(k)
                        except Exception:
                            continue
                        if isinstance(v, str):
                            cls._keychain_names[kid] = v
        except Exception:
            cls._last_failed_at = 0.0

    @classmethod
    def _save_state(cls) -> None:
        try:
            skin_by_pair = {
                f"{d}:{p}": [item_name, paint_name]
                for (d, p), (item_name, paint_name) in cls._skin_by_pair.items()
            }
            sticker_names = {str(k): v for k, v in cls._sticker_names.items()}
            keychain_names = {str(k): v for k, v in cls._keychain_names.items()}
            cls._STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            cls._STATE_PATH.write_text(
                json.dumps(
                    {
                        "last_failed_at": cls._last_failed_at,
                        "skin_by_pair": skin_by_pair,
                        "sticker_names": sticker_names,
                        "keychain_names": keychain_names,
                    }
                ),
                encoding="utf-8",
            )
        except Exception:
            return

    @classmethod
    def _can_attempt_network(cls, *, has_cached_data: bool) -> bool:
        cls._load_state()
        # If we still have no cached data for this dataset, allow a retry so
        # names can start resolving as soon as network becomes available.
        if not has_cached_data:
            return True
        if not cls._last_failed_at:
            return True
        return (time.time() - cls._last_failed_at) >= cls._FAIL_RETRY_SECONDS

    @classmethod
    def _load_skins(cls) -> None:
        if cls._skins_loaded:
            return
        cls._load_state()
        cls._skins_loaded = True
        if not cls._can_attempt_network(has_cached_data=bool(cls._skin_by_pair)):
            return
        try:
            with httpx.Client(timeout=0.5) as client:
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
                if cls._skin_by_pair:
                    cls._save_state()
        except Exception:
            cls._last_failed_at = time.time()
            cls._save_state()
            return

    @classmethod
    def _load_stickers(cls) -> None:
        if cls._stickers_loaded:
            return
        cls._load_state()
        cls._stickers_loaded = True
        if not cls._can_attempt_network(has_cached_data=bool(cls._sticker_names)):
            return
        try:
            with httpx.Client(timeout=0.5) as client:
                stickers = cls._fetch_json(client, cls._STICKERS_URL)
                for row in stickers:
                    sid = cls._to_int(row.get("def_index"))
                    name = row.get("name")
                    if isinstance(sid, int) and isinstance(name, str):
                        cls._sticker_names[sid] = name
                if cls._sticker_names:
                    cls._save_state()
        except Exception:
            cls._last_failed_at = time.time()
            cls._save_state()
            return

    @classmethod
    def _load_keychains(cls) -> None:
        if cls._keychains_loaded:
            return
        cls._load_state()
        cls._keychains_loaded = True
        if not cls._can_attempt_network(has_cached_data=bool(cls._keychain_names)):
            return
        try:
            with httpx.Client(timeout=0.5) as client:
                keychains = cls._fetch_json(client, cls._KEYCHAINS_URL)
                for row in keychains:
                    kid = cls._to_int(row.get("def_index"))
                    name = row.get("name")
                    if isinstance(kid, int) and isinstance(name, str):
                        cls._keychain_names[kid] = name
                if cls._keychain_names:
                    cls._save_state()
        except Exception:
            cls._last_failed_at = time.time()
            cls._save_state()
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
