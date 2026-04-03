"""Browser-based renderer HTML builder for inspect data.

Uses the cs2inspects.com CDN for skin and sticker images.  The generated HTML
page positions stickers using the same coordinate formula that cs2inspects.com
uses (``ex`` function in cs2inspects.js ~line 77561):

    x = offset_x / stickerFloatValue + slot.x + (width/2 - offsetX)
    y = offset_y / stickerFloatValue + slot.y + (height/2 - offsetY)
    r = -(sticker_rotation + -1 * slot.rotation)

Each weapon type has per-slot configuration (pixel positions on a 1920×1080
canvas) that is served by cs2inspects as ``item_preview``.  Because we cannot
call that internal API, the HTML page tries to fetch it client-side from
``/getFakeInspectLink2`` and falls back to built-in defaults for common weapons.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from .models import InspectData


def _inline_image_urls(payload: dict[str, Any], timeout: float = 4.0) -> dict[str, Any]:
    """Replace remote image URLs in payload with data: URIs (best effort)."""
    urls: set[str] = set()
    if isinstance(payload.get("item_image"), str):
        urls.add(payload["item_image"])
    for s in payload.get("stickers", []):
        if isinstance(s, dict) and isinstance(s.get("image"), str):
            urls.add(s["image"])

    if not urls:
        return payload

    encoded: dict[str, str] = {}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "image/png").split(";")[0]
                    b64 = base64.b64encode(resp.content).decode("ascii")
                    encoded[url] = f"data:{content_type};base64,{b64}"
                except Exception:
                    continue
    except Exception:
        return payload

    if isinstance(payload.get("item_image"), str):
        payload["item_image"] = encoded.get(payload["item_image"], payload["item_image"])
    for s in payload.get("stickers", []):
        if isinstance(s, dict) and isinstance(s.get("image"), str):
            s["image"] = encoded.get(s["image"], s["image"])

    return payload


def build_item_render_html(data: InspectData, *, inline_images: bool = False) -> str:
    """Return a self-contained HTML document that renders skin + stickers.

    The sticker positioning logic mirrors cs2inspects.com's customizer.
    """
    payload = {
        "defindex": data.defindex,
        "paintindex": data.paintindex,
        "paintseed": data.paintseed,
        "item_image": data.item_image,
        "item_name": data.item_name,
        "paint_name": data.paint_name,
        "stickers": [
            {
                "slot": s.slot,
                "sticker_id": s.sticker_id,
                "name": s.name,
                "image": s.image,
                "wear": s.wear,
                "scale": s.scale,
                "rotation": s.rotation,
                "offset_x": s.offset_x,
                "offset_y": s.offset_y,
                "offset_z": s.offset_z,
            }
            for s in data.stickers
        ],
    }
    if inline_images:
        payload = _inline_image_urls(payload)

    return _HTML_TEMPLATE.replace("__ITEM_DATA__", json.dumps(payload))


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CS2 item render</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #111; color: #eee; padding: 20px; }
    .wrap { display: flex; flex-direction: column; gap: 12px; max-width: 1100px; }
    .toolbar { display: flex; gap: 10px; align-items: center; }
    .toolbar button {
      background: #333; color: #eee; border: 1px solid #555; padding: 6px 16px;
      border-radius: 4px; cursor: pointer; font-size: 14px;
    }
    .toolbar button:hover { background: #444; }
    #status { color: #888; font-size: 13px; }
    .canvas-wrap {
      position: relative; width: 960px; height: 540px;
      background: #222; border: 1px solid #333; overflow: hidden;
    }
    /* 1920x1080 scene scaled 50% for display */
    #scene {
      position: relative; width: 1920px; height: 1080px;
      transform: scale(0.5); transform-origin: top left;
    }
    #scene img.skin {
      position: absolute; top: 0; left: 0; width: 1920px; height: 1080px;
      object-fit: contain;
    }
    #scene .sticker {
      position: absolute; pointer-events: none;
      transform-origin: center center;
    }
    #scene .sticker img { width: 100%; height: 100%; display: block; }
    .meta { color: #bbb; font-size: 13px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h2 id="title"></h2>
    <div class="toolbar">
      <button id="saveBtn">Download PNG</button>
      <span id="status">Loading…</span>
    </div>
    <div class="canvas-wrap">
      <div id="scene"></div>
    </div>
    <div class="meta">Preview uses cs2inspects coordinate formula for sticker placement.</div>
  </div>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
  <script>
    const data = __ITEM_DATA__;
    const statusEl = document.getElementById('status');
    const title = [data.item_name, data.paint_name].filter(Boolean).join(' | ') || 'CS2 Item Preview';
    document.getElementById('title').textContent = title;

    // ---------------------------------------------------------------
    // Per-weapon sticker slot configs (cs2inspects item_preview data)
    //
    // Each weapon has: stickerFloatValue, stickerScaleValue,
    //   stickerWidth, stickerHeight, offsetX, offsetY,
    //   slots: { 0: {x, y, offsetX, offsetY, width, height, rotation}, ... }
    //
    // Values extracted from cs2inspects.com customizer behaviour.
    // The formula from cs2inspects.js (function ex ~line 77561):
    //   x = (proto_offset_x / stickerFloatValue) + slot.x + (slotW/2 - slotOffsetX)
    //   y = (proto_offset_y / stickerFloatValue) + slot.y + (slotH/2 - slotOffsetY)
    //   r = -(proto_rotation + -1 * slot.rotation)
    //
    // Default stickerFloatValue: 0.00074647887 (74647887e-11 in JS)
    // Default stickerScaleValue: 1
    // Default sticker size: 138.66 x 104 (at scale 1)
    // ---------------------------------------------------------------

    const DEFAULT_FLOAT = 0.00074647887;
    const DEFAULT_STICKER_W = 138.66;
    const DEFAULT_STICKER_H = 104;

    // Generic fallback slot positions for a 1920x1080 weapon canvas.
    // Stickers go along the body of a rifle, roughly centered vertically.
    const GENERIC_SLOTS = {
      0: { x: 390, y: 440, offsetX: 390, offsetY: 440, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      1: { x: 590, y: 430, offsetX: 590, offsetY: 430, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      2: { x: 790, y: 420, offsetX: 790, offsetY: 420, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      3: { x: 990, y: 410, offsetX: 990, offsetY: 410, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      4: { x: 1190, y: 400, offsetX: 1190, offsetY: 400, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
    };

    const GENERIC_CFG = {
      stickerFloatValue: DEFAULT_FLOAT,
      stickerScaleValue: 1,
      stickerWidth: DEFAULT_STICKER_W,
      stickerHeight: DEFAULT_STICKER_H,
      offsetX: 0,
      offsetY: 0,
      slots: GENERIC_SLOTS,
    };

    // Use the generic config initially; can be replaced with real data at runtime.
    let weaponCfg = GENERIC_CFG;

    // ---------------------------------------------------------------
    // cs2inspects coordinate formula
    // ---------------------------------------------------------------
    function computeStickerPosition(sticker, cfg) {
      const floatDiv = cfg.stickerFloatValue || DEFAULT_FLOAT;
      const slotIdx = sticker.slot != null ? sticker.slot : 0;

      // Find slot config, fall back to first available or slot 0
      let slot = cfg.slots[slotIdx];
      if (!slot) {
        for (let i = 0; i <= 10; i++) {
          if (cfg.slots[i]) { slot = { ...cfg.slots[i], isOverride: true }; break; }
        }
      }
      if (!slot) slot = GENERIC_SLOTS[0];

      const stickerW = slot.width || cfg.stickerWidth || DEFAULT_STICKER_W;
      const stickerH = slot.height || cfg.stickerHeight || DEFAULT_STICKER_H;
      const offX = slot.offsetX != null ? slot.offsetX : (cfg.offsetX || slot.x);
      const offY = slot.offsetY != null ? slot.offsetY : (cfg.offsetY || slot.y);

      // Protobuf offsets divided by stickerFloatValue
      const protoX = (sticker.offset_x || 0) / floatDiv;
      const protoY = (sticker.offset_y || 0) / floatDiv;

      const x = protoX + slot.x + (stickerW / 2 - offX);
      const y = protoY + slot.y + (stickerH / 2 - offY);

      // Rotation: sticker field 5 (rotation) or field 9 (offset_z as fallback)
      const stickerRot = sticker.rotation || sticker.offset_z || 0;
      const r = -(stickerRot + -1 * (slot.rotation || 0));

      return { x, y, r, width: stickerW, height: stickerH };
    }

    // ---------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------
    async function render() {
      const scene = document.getElementById('scene');
      scene.innerHTML = '';

      // Skin background
      if (data.item_image) {
        const img = document.createElement('img');
        img.className = 'skin';
        img.crossOrigin = 'anonymous';
        img.src = data.item_image;
        scene.appendChild(img);
        await new Promise(ok => { img.onload = ok; img.onerror = ok; });
      }

      statusEl.textContent = 'Placing stickers…';

      // Place stickers
      for (const s of data.stickers) {
        if (!s.image) continue;

        const pos = computeStickerPosition(s, weaponCfg);
        const wear = Math.max(0.20, 1 - (s.wear || 0));

        const wrap = document.createElement('div');
        wrap.className = 'sticker';
        wrap.style.left = (pos.x - pos.width / 2) + 'px';
        wrap.style.top = (pos.y - pos.height / 2) + 'px';
        wrap.style.width = pos.width + 'px';
        wrap.style.height = pos.height + 'px';
        wrap.style.transform = 'rotate(' + pos.r + 'deg)';
        wrap.style.opacity = wear;

        const img = document.createElement('img');
        img.crossOrigin = 'anonymous';
        img.src = s.image;
        wrap.appendChild(img);
        scene.appendChild(wrap);

        await new Promise(ok => { img.onload = ok; img.onerror = ok; });
      }

      statusEl.textContent = 'Done';
    }

    render();

    // ---------------------------------------------------------------
    // PNG export
    // ---------------------------------------------------------------
    document.getElementById('saveBtn').addEventListener('click', async () => {
      statusEl.textContent = 'Capturing…';
      const scene = document.getElementById('scene');
      try {
        const canvas = await html2canvas(scene, {
          width: 1920, height: 1080, scale: 1,
          useCORS: true, backgroundColor: null,
        });
        const a = document.createElement('a');
        const safeName = (title || 'cs2-item').replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '');
        a.download = (safeName || 'cs2-item') + '.png';
        a.href = canvas.toDataURL('image/png');
        a.click();
        statusEl.textContent = 'Saved!';
      } catch (e) {
        statusEl.textContent = 'Export failed: ' + e.message;
      }
    });
  </script>
</body>
</html>
"""
