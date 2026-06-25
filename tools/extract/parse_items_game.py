"""Parse CS2 ``items_game.txt`` → ``assets/paintkits.json``.

``items_game.txt`` is a Valve KeyValues (VDF) document.  The ``paint_kits`` block
maps each *paintindex* to a paint kit definition whose fields drive the in-game
``customweapon`` finish (pattern texture, wear remap, finish ``style``, color
tints, etc.).

We dump **all** fields of each paint kit verbatim (rather than cherry-picking
field names that vary between game updates) so the renderer can pick what it
needs.  We also keep ``paint_kits_rarity`` for convenience.

Usage::

    python tools/extract/parse_items_game.py <path/to/items_game.txt> [-o assets/paintkits.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "assets" / "paintkits.json"


# ---------------------------------------------------------------------------
# Minimal VDF / KeyValues parser
# ---------------------------------------------------------------------------
def parse_vdf(text: str) -> dict[str, Any]:
    """Parse Valve KeyValues text into nested dicts.

    Handles quoted/unquoted tokens, nested ``{ }`` blocks, ``//`` line comments,
    and duplicate keys (later values win for scalars; blocks merge shallowly).
    Conditional tags like ``[$WIN32]`` are ignored.
    """
    tokens = _tokenize(text)
    pos = 0

    def parse_block() -> dict[str, Any]:
        nonlocal pos
        block: dict[str, Any] = {}
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "}":
                pos += 1
                break
            key = tok
            pos += 1
            if pos >= len(tokens):
                break
            # Skip platform conditional tags e.g. [$WIN32]
            if tokens[pos].startswith("[") and tokens[pos].endswith("]"):
                pos += 1
                if pos >= len(tokens):
                    break
            nxt = tokens[pos]
            if nxt == "{":
                pos += 1
                value: Any = parse_block()
            else:
                value = nxt
                pos += 1
                # consume trailing conditional tag after a value
                if pos < len(tokens) and tokens[pos].startswith("[") and tokens[pos].endswith("]"):
                    pos += 1
            if key in block and isinstance(block[key], dict) and isinstance(value, dict):
                block[key].update(value)
            else:
                block[key] = value
        return block

    # Top level may have a single root key ("items_game") wrapping everything.
    return parse_block()


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in "{}":
            tokens.append(c)
            i += 1
            continue
        if c == '"':
            i += 1
            start = i
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                buf.append(text[i])
                i += 1
            i += 1  # closing quote
            tokens.append("".join(buf))
            continue
        # unquoted token
        start = i
        while i < n and text[i] not in ' \t\r\n{}"':
            i += 1
        tokens.append(text[start:i])
    return tokens


# ---------------------------------------------------------------------------
# Block-targeted extraction
#
# items_game.txt (as dumped by VRF) contains *many* separate ``paint_kits``
# blocks scattered through 200k+ lines (Valve splits them via ``#base`` includes
# that VRF inlines).  Parsing the whole 8 MB file in one pass is fragile, so we
# instead locate every ``"paint_kits" { ... }`` block by brace matching and
# parse each one independently, then merge.
# ---------------------------------------------------------------------------
def _find_blocks(text: str, key: str) -> list[str]:
    """Return the ``{...}`` body text of every top-level ``"key" { ... }``."""
    needle = '"' + key + '"'
    blocks: list[str] = []
    idx = 0
    n = len(text)
    while True:
        i = text.find(needle, idx)
        if i < 0:
            break
        b = text.find("{", i + len(needle))
        if b < 0:
            break
        # Brace-match from b, respecting quoted strings.
        depth = 0
        j = b
        in_str = False
        while j < n:
            c = text[j]
            if c == '"' and text[j - 1] != "\\":
                in_str = not in_str
            elif not in_str:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        # Inner body without the wrapping braces, so parse_vdf reads key/value
        # pairs directly.
        blocks.append(text[b + 1 : j])
        idx = j + 1
    return blocks


def extract_paintkits(items_game_path: Path) -> dict[str, Any]:
    text = items_game_path.read_text(encoding="utf-8", errors="replace")

    # Merge every paint_kits block into a single index → fields map.
    kits: dict[str, Any] = {}
    for body in _find_blocks(text, "paint_kits"):
        parsed = parse_vdf(body)  # body is "{ "0" {..} "1" {..} }"
        for paintindex, kit in parsed.items():
            if isinstance(kit, dict):
                kits[str(paintindex)] = dict(kit)

    if not kits:
        raise SystemExit("No paint_kits found in items_game.txt")

    # Attach rarity from paint_kits_rarity blocks where available.
    rarity: dict[str, Any] = {}
    for body in _find_blocks(text, "paint_kits_rarity"):
        parsed = parse_vdf(body)
        for k, v in parsed.items():
            if isinstance(v, (str, int)):
                rarity[str(k)] = v
    for k, v in rarity.items():
        if k in kits:
            kits[k]["_rarity"] = v

    return kits


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse items_game.txt → paintkits.json")
    ap.add_argument("items_game", type=Path, help="Path to extracted items_game.txt")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help="Output JSON path")
    args = ap.parse_args()

    kits = extract_paintkits(args.items_game)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(kits, indent=0), encoding="utf-8")
    print(f"Wrote {len(kits)} paint kits -> {args.out}")


if __name__ == "__main__":
    main()
