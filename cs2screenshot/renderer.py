"""Browser-based renderer HTML builder for inspect data."""
from __future__ import annotations

import json

from .models import InspectData


def build_item_render_html(data: InspectData) -> str:
    """Return an HTML document that renders skin + sticker overlays via Canvas.

    Notes:
    - This is an approximate renderer intended for quick previews.
    - Sticker offsets/rotation/scale are applied when available.
    """
    payload = {
        "item_image": data.item_image,
        "item_name": data.item_name,
        "paint_name": data.paint_name,
        "stickers": [
            {
                "slot": s.slot,
                "name": s.name,
                "image": s.image,
                "wear": s.wear,
                "scale": s.scale,
                "rotation": s.rotation,
                "offset_x": s.offset_x,
                "offset_y": s.offset_y,
            }
            for s in data.stickers
        ],
    }

    # Default fallback positions for stickers with no explicit offsets
    slot_positions = {
        0: [0.22, 0.70],
        1: [0.38, 0.62],
        2: [0.53, 0.54],
        3: [0.67, 0.46],
        4: [0.80, 0.38],
    }

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>CS2 item render</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#111; color:#eee; margin: 20px; }}
    .wrap {{ display:grid; gap:12px; max-width:1100px; }}
    canvas {{ background:#222; border:1px solid #333; width:1024px; height:768px; }}
    .meta {{ color:#bbb; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h2 id=\"title\"></h2>
    <canvas id=\"c\" width=\"1024\" height=\"768\"></canvas>
    <div class=\"meta\">Approximate preview based on inspect metadata.</div>
  </div>
  <script>
    const data = {json.dumps(payload)};
    const slotPos = {json.dumps(slot_positions)};

    const title = [data.item_name, data.paint_name].filter(Boolean).join(' | ') || 'CS2 Item Preview';
    document.getElementById('title').textContent = title;

    const canvas = document.getElementById('c');
    const ctx = canvas.getContext('2d');

    function loadImage(src) {{
      return new Promise((resolve, reject) => {{
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = src;
      }});
    }}

    async function render() {{
      ctx.clearRect(0,0,canvas.width,canvas.height);

      if (data.item_image) {{
        try {{
          const skin = await loadImage(data.item_image);
          ctx.drawImage(skin, 0, 0, canvas.width, canvas.height);
        }} catch (e) {{
          ctx.fillStyle = '#333';
          ctx.fillRect(0,0,canvas.width,canvas.height);
          ctx.fillStyle = '#f66';
          ctx.fillText('Failed to load skin image', 20, 30);
        }}
      }} else {{
        ctx.fillStyle = '#333';
        ctx.fillRect(0,0,canvas.width,canvas.height);
      }}

      for (const s of data.stickers) {{
        if (!s.image) continue;
        try {{
          const img = await loadImage(s.image);
          const hasOffset = Math.abs(s.offset_x || 0) > 1e-6 || Math.abs(s.offset_y || 0) > 1e-6;
          const fallback = slotPos[s.slot] || [0.5, 0.5];
          const nx = hasOffset ? (0.5 + (s.offset_x || 0) * 0.25) : fallback[0];
          const ny = hasOffset ? (0.5 - (s.offset_y || 0) * 0.25) : fallback[1];

          const x = nx * canvas.width;
          const y = ny * canvas.height;

          const baseScale = 0.22;
          const customScale = s.scale && s.scale > 0 ? s.scale : 1.0;
          const w = img.width * baseScale * customScale;
          const h = img.height * baseScale * customScale;

          const rotDeg = s.rotation || 0;
          const rot = rotDeg * Math.PI / 180;
          const alpha = Math.max(0.20, 1 - (s.wear || 0));

          ctx.save();
          ctx.translate(x, y);
          ctx.rotate(rot);
          ctx.globalAlpha = alpha;
          ctx.drawImage(img, -w/2, -h/2, w, h);
          ctx.restore();
        }} catch (e) {{}}
      }}
    }}

    render();
  </script>
</body>
</html>
"""
