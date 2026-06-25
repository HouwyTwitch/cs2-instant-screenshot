# cs2-instant-screenshot

Paste a CS2 inspect link → get an accurate, in-game-style screenshot in the
browser. Decodes the link offline (float, paint seed, stickers, …) and renders
the real weapon model + skin in 3D — no Steam bot or game client needed.

This is the approach used by tools like cs2inspect / cs2x.ai: a browser WebGL
(Three.js) renderer fed by assets extracted from a local CS2 install.

## Status

**Vertical slice working end-to-end** for the AK-47:
inspect link → decode → real 3D model → skin texture → float/wear → stickers →
PNG export (1920×1080). See `web/` + `cs2screenshot/api.py`.

- ✅ Inspect-link decode/encode (`cs2screenshot/decoder.py`)
- ✅ Asset extraction from local CS2 via ValveResourceFormat (`tools/extract/`)
- ✅ 3D viewer with PBR skin material + approximate wear (`web/src/`)
- ⏳ Next: full `customweapon` finish parity (pattern-seed skins: Case Hardened,
  Fade, Doppler…), precise per-slot sticker placement, full weapon catalog.

## Architecture

```
inspect link ──/api/decode──> {defindex, paintindex, paintseed, paintwear, stickers}
                                          │
   assets/manifest.json (weapon model + skin textures + paint-kit params)
                                          │
                Three.js viewer: GLB + skin PBR material + wear + sticker decals
                                          │
                                   PNG screenshot
```

- **Backend** (`cs2screenshot/api.py`, FastAPI): decode API, paint-kit lookup,
  static asset + frontend serving, same-origin image proxy for sticker CDNs.
- **Frontend** (`web/`, Three.js via CDN importmap — no build step / no npm).
- **Assets** (`assets/`, git-ignored): extracted by `tools/extract/`.

## Setup

```bash
pip install -e .

# 1) Extract assets from your local CS2 install (Windows; CS2 must be installed).
#    Downloads ValveResourceFormat CLI into tools/vrf/ on first use.
python tools/extract/extract.py vertical-slice

# 2) Run the server (serves API + web frontend + assets on http://127.0.0.1:8000)
python -m cs2screenshot.cli serve
```

Open http://127.0.0.1:8000 and click **Demo (AK Head Shot)**, or paste any
modern AK-47 inspect link.

## Asset pipeline notes

- Weapon **models** live in `csgo/pak01_dir.vpk` under `weapons/models/<gun>/`.
- Skin **textures** live under `items/assets/paintkits/...` (per collection).
- `items_game.txt` defines paint kits across **many** `paint_kits` blocks; the
  parser in `tools/extract/parse_items_game.py` merges them all.
- Modern paint kits reference a `composite_material_path` (`.vcompmat`); the
  AK Head Shot (paintindex 1425, style 9) ships a full PBR set (color / normal /
  rough / metal / ao) that maps straight onto the model UVs.

## CLI

```bash
cs2screenshot decode "<inspect link>"     # print decoded item JSON (or --table)
cs2screenshot serve                       # run the FastAPI backend
```
