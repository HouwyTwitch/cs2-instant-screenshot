"""Build ``assets/manifest.json`` from the extracted asset tree.

The frontend reads this manifest to map a decoded item (defindex + paintindex)
to concrete asset URLs (model GLB, skin PBR textures, sticker mask) plus the
paint-kit parameters needed for wear rendering.

For the vertical slice this registers a single weapon (AK-47, defindex 7) and a
single skin (paintindex 1425, ``ak47_crane_flight``).  The globbing is generic
so adding more skins later is just a matter of extending ``SKINS``.

Usage::

    python tools/extract/build_manifest.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / "assets"
PAINTKITS = ASSETS / "paintkits.json"

# Served base: api.py mounts assets/ at /assets/.
BASE = "/assets"


# defindex → model + per-weapon composite inputs (used by pattern-finish skins).
WEAPONS = {
    7: {  # AK-47
        "name": "AK-47",
        "model": "models/**/weapon_rif_ak47.glb",
        "sticker_mask": "models/**/weapon_rif_ak47_sticker_mask_hd_*.png",
        # Composite inputs the csgo_customweapon finish reads (see *.vmat).
        "composite": {
            "base_color": "models/**/ak47_default_color_*.png",
            "masks": "models/**/composite_inputs/weapon_rif_ak47_masks_*.png",
            "cavity": "models/**/composite_inputs/weapon_rif_ak47_cavity_*.png",
            "ao": "models/**/ak47_default_ao_*.png",
            "normal": "models/**/ak47_default_normal_*.png",
            "rough": "models/**/ak47_default_rough_*.png",
        },
    },
}

# "Baked" skins ship a complete PBR set (style 9). paintindex → (prefix, display).
SKINS = {
    1425: ("ak47_crane_flight", "AK-47 | Crane Flight"),
}

# "Pattern" skins (Case Hardened, Asiimov, Fade, …) are read from ak_skins.json,
# produced by extract_ak_skins.py (pattern texture + style + seeded flag).
AK_SKINS_META = ASSETS / "ak_skins.json"

# Shared wear/grunge textures used by CS2's customweapon finish (global).
SHARED = {
    "paint_wear": "textures/**/paint_wear_psd_*.png",
    "grunge": "textures/**/gun_grunge_psd_*.png",
}


def _one(glob: str) -> str | None:
    hits = sorted(ASSETS.glob(glob))
    if not hits:
        return None
    rel = hits[0].relative_to(ASSETS).as_posix()
    return f"{BASE}/{rel}"


def _skin_map(prefix: str) -> str | None:
    """Find an extracted skin texture by channel keyword."""
    def find(*keys: str) -> str | None:
        for key in keys:
            url = _one(f"textures/**/{prefix}_{key}_*.png")
            if url:
                return url
        return None

    color = find("color", "albedo_texture", "albedo")
    if not color:
        return None
    return {
        "color": color,
        "normal": find("normal", "normal_map_texture"),
        "rough": find("rough", "roughness_texture", "roughness"),
        "metal": find("metal", "metalness"),
        "ao": find("ambient_occlusion", "ao"),
    }


def main() -> None:
    paintkits = json.loads(PAINTKITS.read_text(encoding="utf-8")) if PAINTKITS.exists() else {}

    weapons: dict[str, dict] = {}
    for defindex, cfg in WEAPONS.items():
        model = _one(cfg["model"])
        if not model:
            print(f"! weapon {defindex}: model not found ({cfg['model']})")
            continue
        composite = {k: _one(g) for k, g in cfg.get("composite", {}).items()}
        weapons[str(defindex)] = {
            "name": cfg["name"],
            "model": model,
            "sticker_mask": _one(cfg["sticker_mask"]),
            "composite": composite,
        }

    skins: dict[str, dict] = {}

    def _kit_common(paintindex: int) -> dict:
        kit = paintkits.get(str(paintindex), {})
        return {
            "style": int(kit.get("style", 0) or 0),
            # Which weapon body the finish targets: legacy (CS:GO-era UV) or HD.
            "legacy": str(kit.get("use_legacy_model", "0")) == "1",
            "wear_remap_min": float(kit.get("wear_remap_min", 0.0) or 0.0),
            "wear_remap_max": float(kit.get("wear_remap_max", 1.0) or 1.0),
        }

    # Baked (pre-rendered PBR) skins.
    for paintindex, (prefix, display) in SKINS.items():
        tex = _skin_map(prefix)
        if not tex:
            print(f"! skin {paintindex}: textures not found (prefix {prefix})")
            continue
        skins[str(paintindex)] = {
            "kind": "baked",
            "name": prefix,
            "display": display,
            "textures": tex,
            **_kit_common(paintindex),
        }

    # Pattern skins from extract_ak_skins.py (Case Hardened, Asiimov, …).
    if AK_SKINS_META.exists():
        ak_meta = json.loads(AK_SKINS_META.read_text(encoding="utf-8"))
        for paintindex, m in ak_meta.items():
            if str(paintindex) in skins:  # a baked entry takes precedence
                continue
            skins[str(paintindex)] = {
                "kind": "pattern",
                "display": m.get("display"),
                "pattern": m["pattern"],
                "color_brightness": m.get("brightness", 1.0),
                "seeded": bool(m.get("seeded", False)),
                **_kit_common(int(paintindex)),
            }

    shared = {k: _one(g) for k, g in SHARED.items()}
    manifest = {"weapons": weapons, "skins": skins, "shared": shared}
    out = ASSETS / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest: {len(weapons)} weapon(s), {len(skins)} skin(s) -> {out}")


if __name__ == "__main__":
    main()
