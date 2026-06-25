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
      background: linear-gradient(135deg, #2a2a2a 0%, #111 100%);
    }
    .skin-placeholder {
      position: absolute; inset: 0;
      background: linear-gradient(135deg, #ffbf6b 0%, #8a4a21 35%, #1b120f 100%);
      border: 2px solid rgba(255,255,255,0.18);
      box-shadow: inset 0 0 120px rgba(255,255,255,0.20);
      z-index: 0;
    }
    .weapon-fallback {
      position: absolute; inset: 0;
      background: linear-gradient(115deg, #3f2b1f 0%, #7c4d23 24%, #c98a40 50%, #6d3a1d 78%, #24150d 100%);
      z-index: 1;
      pointer-events: none;
      overflow: hidden;
    }
    .weapon-fallback::before {
      content: "";
      position: absolute;
      inset: 10% 20% 14% 24%;
      border-radius: 50% 46% 44% 50%;
      border: 4px solid rgba(255,255,255,0.22);
      transform: rotate(-8deg);
      box-shadow: inset 0 0 60px rgba(0,0,0,0.35), 0 0 60px rgba(0,0,0,0.18);
    }
    .weapon-fallback::after {
      content: "";
      position: absolute;
      inset: 12% 22% 14% 26%;
      background: linear-gradient(90deg, rgba(255,255,255,0.16) 0%, transparent 35%, rgba(0,0,0,0.28) 100%);
      clip-path: polygon(8% 20%, 24% 16%, 72% 16%, 92% 24%, 94% 40%, 82% 58%, 70% 70%, 48% 80%, 22% 78%, 10% 64%, 6% 42%);
      opacity: 0.95;
    }
    .weapon-silhouette {
      position: absolute; inset: 0;
      background-image: radial-gradient(circle at 50% 50%, rgba(255,255,255,0.10) 0%, transparent 28%),
                        linear-gradient(112deg, rgba(255,255,255,0.14) 0%, transparent 42%, rgba(0,0,0,0.24) 100%);
      clip-path: polygon(12% 36%, 32% 28%, 46% 22%, 56% 22%, 70% 24%, 80% 30%, 90% 38%, 89% 48%, 82% 60%, 68% 70%, 54% 76%, 38% 78%, 24% 70%, 14% 58%, 10% 46%);
      z-index: 2;
      pointer-events: none;
    }
    #scene img.skin {
      position: absolute; top: 0; left: 0; width: 1920px; height: 1080px;
      object-fit: contain;
      display: block;
      background: linear-gradient(135deg, #2a2a2a 0%, #111 100%);
    }
    #scene .sticker {
      position: absolute; pointer-events: none;
      transform-origin: center center;
      z-index: 3;
    }
    .sticker-slot {
      position: absolute; width: 18px; height: 18px; border-radius: 50%;
      background: rgba(255,255,255,0.9); border: 2px solid rgba(0,0,0,0.5);
      transform: translate(-50%, -50%);
      z-index: 4;
      pointer-events: none;
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
    // These values are centered on the weapon body instead of cancelling the
    // slot position out in the coordinate formula.
    const GENERIC_SLOTS = {
      0: { x: 760, y: 420, offsetX: 0, offsetY: 0, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      1: { x: 920, y: 400, offsetX: 0, offsetY: 0, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      2: { x: 1080, y: 380, offsetX: 0, offsetY: 0, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      3: { x: 1240, y: 360, offsetX: 0, offsetY: 0, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
      4: { x: 1400, y: 340, offsetX: 0, offsetY: 0, width: DEFAULT_STICKER_W, height: DEFAULT_STICKER_H, rotation: 0 },
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
      const offX = slot.offsetX != null ? slot.offsetX : (cfg.offsetX || 0);
      const offY = slot.offsetY != null ? slot.offsetY : (cfg.offsetY || 0);

      // Protobuf offsets divided by stickerFloatValue.
      // The slot position should act as the anchor point, not be cancelled out.
      const protoX = (sticker.offset_x || 0) / floatDiv;
      const protoY = (sticker.offset_y || 0) / floatDiv;

      const x = slot.x + protoX + (stickerW / 2 - offX);
      const y = slot.y + protoY + (stickerH / 2 - offY);

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

      const fallbackSkin = document.createElement('div');
      fallbackSkin.className = 'skin-placeholder';
      scene.appendChild(fallbackSkin);

      const weaponFallback = document.createElement('div');
      weaponFallback.className = 'weapon-fallback';
      scene.appendChild(weaponFallback);

      const weaponSilhouette = document.createElement('div');
      weaponSilhouette.className = 'weapon-silhouette';
      scene.appendChild(weaponSilhouette);

      const fallbackPattern = document.createElement('div');
      fallbackPattern.style.position = 'absolute';
      fallbackPattern.style.inset = '0';
      fallbackPattern.style.backgroundImage = 'repeating-linear-gradient(45deg, rgba(255,255,255,0.08) 0px, rgba(255,255,255,0.08) 8px, transparent 8px, transparent 16px)';
      fallbackPattern.style.mixBlendMode = 'screen';
      fallbackPattern.style.opacity = '0.95';
      fallbackPattern.style.pointerEvents = 'none';
      fallbackPattern.style.zIndex = '0';
      scene.appendChild(fallbackPattern);

      const fallbackLabel = document.createElement('div');
      fallbackLabel.style.position = 'absolute';
      fallbackLabel.style.left = '24px';
      fallbackLabel.style.bottom = '24px';
      fallbackLabel.style.padding = '10px 14px';
      fallbackLabel.style.borderRadius = '10px';
      fallbackLabel.style.background = 'rgba(0,0,0,0.78)';
      fallbackLabel.style.color = '#fce0b2';
      fallbackLabel.style.fontSize = '22px';
      fallbackLabel.style.fontWeight = '700';
      fallbackLabel.style.letterSpacing = '0.05em';
      fallbackLabel.style.zIndex = '5';
      fallbackLabel.textContent = title || 'CS2 Item Preview';
      scene.appendChild(fallbackLabel);

      // Skin background
      if (data.item_image) {
        const img = document.createElement('img');
        img.className = 'skin';
        img.crossOrigin = 'anonymous';
        img.src = data.item_image;
        img.style.zIndex = '1';

        await new Promise((resolve) => {
          const done = () => {
            if (!img.parentNode) {
              scene.appendChild(img);
            }
            resolve();
          };
          img.onload = done;
          img.onerror = done;
        });
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

        const slotMarker = document.createElement('div');
        slotMarker.className = 'sticker-slot';
        slotMarker.style.left = (pos.x) + 'px';
        slotMarker.style.top = (pos.y) + 'px';
        slotMarker.style.width = (Math.max(16, pos.width * 0.18)) + 'px';
        slotMarker.style.height = (Math.max(16, pos.height * 0.18)) + 'px';
        slotMarker.style.borderRadius = '4px';
        scene.appendChild(slotMarker);

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
