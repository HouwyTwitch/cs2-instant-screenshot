"""Asset extraction pipeline for the CS2 screenshot tool (Faz 0).

Drives the ValveResourceFormat ``Source2Viewer-CLI`` to pull the assets we need
out of the local CS2 install and into ``assets/``:

  * a weapon model (``.vmdl_c``)  → glTF/GLB (mesh + UV + composite-input textures)
  * paint pattern + wear textures (``.vtex_c``) → PNG
  * ``scripts/items/items_game.txt`` → parsed into ``assets/paintkits.json``

This script only *locates* things and shells out to the CLI; it does not parse
Source 2 binaries itself.  Run ``list`` first to discover exact in-VPK paths,
then ``vertical-slice`` for the AK-47 end-to-end pull.

Examples::

    python tools/extract/extract.py info
    python tools/extract/extract.py list ak47
    python tools/extract/extract.py items-game
    python tools/extract/extract.py vertical-slice
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VRF_EXE = REPO_ROOT / "tools" / "vrf" / "Source2Viewer-CLI.exe"
ASSETS_DIR = REPO_ROOT / "assets"

# Default CS2 install (overridable via --cs2). pak01_dir.vpk indexes all paks.
DEFAULT_CS2 = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive"
)


def cs2_vpk(cs2_root: Path) -> Path:
    vpk = cs2_root / "game" / "csgo" / "pak01_dir.vpk"
    if not vpk.exists():
        raise SystemExit(f"pak01_dir.vpk not found under {cs2_root}")
    return vpk


def _run(args: list[str]) -> int:
    if not VRF_EXE.exists():
        raise SystemExit(
            f"Source2Viewer-CLI not found at {VRF_EXE}.\n"
            "Download cli-windows-x64.zip from "
            "https://github.com/ValveResourceFormat/ValveResourceFormat/releases "
            "and extract it into tools/vrf/."
        )
    cmd = [str(VRF_EXE), *args]
    print("›", " ".join(cmd))
    return subprocess.call(cmd)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
def cmd_info(cs2_root: Path) -> int:
    print("VRF exe   :", VRF_EXE, "(exists)" if VRF_EXE.exists() else "(MISSING)")
    print("CS2 root  :", cs2_root)
    print("VPK index :", cs2_vpk(cs2_root))
    print("Assets out:", ASSETS_DIR)
    return 0


def cmd_list(cs2_root: Path, needle: str) -> int:
    """List VPK entries (pipe through grep for the needle)."""
    # -l / --vpk_list dumps the file index; we filter in Python for portability.
    vpk = cs2_vpk(cs2_root)
    proc = subprocess.run(
        [str(VRF_EXE), "-i", str(vpk), "--vpk_list"],
        capture_output=True, text=True,
    )
    lines = [ln for ln in proc.stdout.splitlines() if needle.lower() in ln.lower()]
    print("\n".join(lines) if lines else f"(no entries matching {needle!r})")
    return proc.returncode


def cmd_items_game(cs2_root: Path) -> int:
    """Extract items_game.txt and parse → assets/paintkits.json."""
    vpk = cs2_vpk(cs2_root)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    rc = _run([
        "-i", str(vpk),
        "--vpk_filepath", "scripts/items/items_game.txt",
        "-o", str(ASSETS_DIR / "_raw"),
    ])
    if rc != 0:
        return rc
    # Locate the extracted file and parse it.
    candidates = list((ASSETS_DIR / "_raw").rglob("items_game.txt"))
    if not candidates:
        print("items_game.txt not found after extraction", file=sys.stderr)
        return 1
    from parse_items_game import extract_paintkits  # type: ignore
    import json
    kits = extract_paintkits(candidates[0])
    out = ASSETS_DIR / "paintkits.json"
    out.write_text(json.dumps(kits, indent=0), encoding="utf-8")
    print(f"Wrote {len(kits)} paint kits → {out}")
    return 0


def cmd_model(cs2_root: Path, vpk_path: str, fmt: str) -> int:
    """Decompile a single .vmdl_c to glTF/GLB with materials + textures."""
    vpk = cs2_vpk(cs2_root)
    out = ASSETS_DIR / "models"
    out.mkdir(parents=True, exist_ok=True)
    return _run([
        "-i", str(vpk),
        "--vpk_filepath", vpk_path,
        "-o", str(out),
        "-d",                              # decompile
        "--gltf_export_format", fmt,       # glb | gltf
        "--gltf_export_materials",
        "--gltf_export_textures",
    ])


def cmd_texture(cs2_root: Path, vpk_path: str) -> int:
    """Decompile a single .vtex_c to PNG."""
    vpk = cs2_vpk(cs2_root)
    out = ASSETS_DIR / "textures"
    out.mkdir(parents=True, exist_ok=True)
    return _run([
        "-i", str(vpk),
        "--vpk_filepath", vpk_path,
        "-o", str(out),
        "-d",
    ])


# Confirmed in-VPK paths for the AK-47 vertical slice (CS2 build 2025).
AK47_MODEL = "weapons/models/ak47/weapon_rif_ak47.vmdl_c"
# AK-47 | Head Shot (paintindex 1425, ak47_crane_flight): pre-baked PBR set.
CRANE_FLIGHT_TEX = "items/assets/paintkits/community/community_37/ak47_crane_flight"


def cmd_vertical_slice(cs2_root: Path, fmt: str) -> int:
    """Reproduce the full AK-47 + Head Shot vertical-slice asset set.

    Pulls: items_game → paintkits.json, the AK-47 model (GLB + composite inputs
    + sticker masks), the Head Shot skin textures, then builds manifest.json.
    """
    if (rc := cmd_items_game(cs2_root)) != 0:
        return rc
    if (rc := cmd_model(cs2_root, AK47_MODEL, fmt)) != 0:
        return rc
    if (rc := cmd_texture(cs2_root, CRANE_FLIGHT_TEX)) != 0:
        return rc

    # Build the manifest the frontend reads.
    from build_manifest import main as build_manifest  # type: ignore

    build_manifest()
    print("\nVertical slice ready. Start the server: "
          "python -m cs2screenshot.cli serve")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="CS2 asset extraction (Faz 0)")
    ap.add_argument("--cs2", type=Path, default=DEFAULT_CS2, help="CS2 install root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Show resolved paths")
    p_list = sub.add_parser("list", help="List VPK entries matching a needle")
    p_list.add_argument("needle")
    sub.add_parser("items-game", help="Extract+parse items_game.txt → paintkits.json")
    p_model = sub.add_parser("model", help="Decompile a .vmdl_c to glTF/GLB")
    p_model.add_argument("vpk_path")
    p_model.add_argument("--format", default="glb", choices=["glb", "gltf"])
    p_tex = sub.add_parser("texture", help="Decompile a .vtex_c to PNG")
    p_tex.add_argument("vpk_path")
    p_vs = sub.add_parser("vertical-slice", help="AK-47 end-to-end pull")
    p_vs.add_argument("--format", default="glb", choices=["glb", "gltf"])

    args = ap.parse_args()
    cs2 = args.cs2

    if args.cmd == "info":
        sys.exit(cmd_info(cs2))
    elif args.cmd == "list":
        sys.exit(cmd_list(cs2, args.needle))
    elif args.cmd == "items-game":
        sys.exit(cmd_items_game(cs2))
    elif args.cmd == "model":
        sys.exit(cmd_model(cs2, args.vpk_path, args.format))
    elif args.cmd == "texture":
        sys.exit(cmd_texture(cs2, args.vpk_path))
    elif args.cmd == "vertical-slice":
        sys.exit(cmd_vertical_slice(cs2, args.format))


if __name__ == "__main__":
    main()
