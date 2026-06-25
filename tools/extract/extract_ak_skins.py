"""Batch-extract every AK-47 skin from the local CS2 files.

For each AK-47 paint kit we decompile its ``csgo_customweapon`` material
(``materials/.../paints/vmats/<kit>.vmat``); VRF exports the referenced pattern
texture, which we downscale to a web-friendly WebP. The kit's finish style
decides whether the pattern is seed-randomized (anodized/antiqued) or mapped 1:1
to the UV (custom paint).

Output: ``assets/skins/<paintindex>/pattern.webp`` + ``assets/ak_skins.json``
(consumed by build_manifest.py).

Usage::

    python tools/extract/extract_ak_skins.py            # all AK-47 skins
    python tools/extract/extract_ak_skins.py 801 44     # only these paintindexes
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
VRF_EXE = REPO_ROOT / "tools" / "vrf" / "Source2Viewer-CLI.exe"
ASSETS = REPO_ROOT / "assets"
PAINTKITS = ASSETS / "paintkits.json"
SKINS_OUT = ASSETS / "skins"
META_OUT = ASSETS / "ak_skins.json"

CS2 = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive")
VPK = CS2 / "game" / "csgo" / "pak01_dir.vpk"
VMAT_DIR = "materials/models/weapons/customization/paints/vmats"

SKINS_API = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json"
SKINS_CACHE = ASSETS / "_raw" / "skins_api.json"

# Shared/non-pattern textures a vmat also pulls in — never the skin's pattern.
_SHARED_TEX = ("gun_grunge", "paint_wear", "squares_glitter", "default_", "_metal", "_mask")

# Finish styles whose pattern is positioned by the paint seed (vs 1:1 on UV).
_SEEDED_STYLES = {2, 5, 8}  # hydrographic, anodized-multi, antiqued

MAX_TEX = 2048  # downscale patterns to this max dimension for the web


def ak_skins() -> list[dict]:
    """Return [{paintindex, kit_name, display, style}] for every AK-47 skin."""
    if SKINS_CACHE.exists():
        data = json.loads(SKINS_CACHE.read_text(encoding="utf-8"))
    else:
        data = httpx.get(SKINS_API, timeout=30).json()
        SKINS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SKINS_CACHE.write_text(json.dumps(data), encoding="utf-8")

    kits = json.loads(PAINTKITS.read_text(encoding="utf-8"))
    out = []
    for s in data:
        if not isinstance(s, dict) or s.get("weapon", {}).get("id") != "weapon_ak47":
            continue
        pi = s.get("paint_index")
        if pi is None:
            continue
        kit = kits.get(str(pi), {})
        name = kit.get("name")
        if not name:
            continue
        out.append({
            "paintindex": int(pi),
            "kit_name": name,
            "display": s.get("name", name),
            "style": int(kit.get("style", 0) or 0),
            "brightness": 1.0,
        })
    return out


def _decompile_vmat(kit_name: str, out_dir: Path) -> Path | None:
    vmat = f"{VMAT_DIR}/{kit_name}.vmat"
    subprocess.run(
        [str(VRF_EXE), "-i", str(VPK), "--vpk_filepath", vmat, "-o", str(out_dir), "-d"],
        capture_output=True, text=True,
    )
    hits = list(out_dir.rglob("*.vmat"))
    return hits[0] if hits else None


def _pattern_png(out_dir: Path) -> Path | None:
    """Pick the skin's pattern PNG (largest non-shared one VRF exported)."""
    pngs = [
        p for p in out_dir.rglob("*.png")
        if not any(s in p.name.lower() for s in _SHARED_TEX)
    ]
    if not pngs:
        return None
    return max(pngs, key=lambda p: p.stat().st_size)


def _vmat_params(vmat_path: Path) -> dict:
    text = vmat_path.read_text(encoding="utf-8", errors="replace")
    def num(key: str, default: float) -> float:
        m = re.search(rf'"{key}"\s+"([0-9.\-]+)"', text)
        return float(m.group(1)) if m else default
    return {"brightness": num("g_flColorBrightness", 1.0)}


def _save_webp(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGBA")
    if max(im.size) > MAX_TEX:
        scale = MAX_TEX / max(im.size)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    im.save(dst, "WEBP", quality=90, method=4)


def main() -> None:
    if not VRF_EXE.exists():
        raise SystemExit(f"VRF CLI missing at {VRF_EXE}")

    wanted = {int(a) for a in sys.argv[1:]} or None
    skins = [s for s in ak_skins() if wanted is None or s["paintindex"] in wanted]
    print(f"Extracting {len(skins)} AK-47 skin(s)…")

    meta: dict[str, dict] = {}
    ok = fail = 0
    for s in skins:
        pi = s["paintindex"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            vmat = _decompile_vmat(s["kit_name"], tmp_dir)
            pattern = _pattern_png(tmp_dir) if vmat else None
            if not pattern:
                print(f"  ! {pi} {s['kit_name']}: no vmat/pattern (skipped)")
                fail += 1
                continue
            dst = SKINS_OUT / str(pi) / "pattern.webp"
            _save_webp(pattern, dst)
            params = _vmat_params(vmat) if vmat else {}
            meta[str(pi)] = {
                "display": s["display"],
                "kit_name": s["kit_name"],
                "style": s["style"],
                "seeded": s["style"] in _SEEDED_STYLES,
                "brightness": params.get("brightness", 1.0),
                "pattern": f"/assets/{dst.relative_to(ASSETS).as_posix()}",
            }
            print(f"  ok {pi} {s['display']} (style {s['style']}, "
                  f"{'seeded' if meta[str(pi)]['seeded'] else 'uv'})")
            ok += 1

    META_OUT.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"\nDone: {ok} ok, {fail} skipped -> {META_OUT}")


if __name__ == "__main__":
    main()
