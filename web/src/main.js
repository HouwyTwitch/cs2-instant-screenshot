// App orchestration: decode an inspect link via the backend, look up the
// weapon model + skin textures in the manifest, and render in the 3D viewer.

import { Viewer } from "./viewer.js?v=b13";

const API = ""; // same origin (served by FastAPI)

const els = {
  link: document.getElementById("link"),
  render: document.getElementById("render-btn"),
  demo: document.getElementById("demo-btn"),
  png: document.getElementById("png-btn"),
  status: document.getElementById("status"),
  info: document.getElementById("info"),
};

// A pre-generated AK-47 "Head Shot" (paintindex 1425) inspect link for demoing
// without a real link. Produced by cs2screenshot.decoder.encode().
const DEMO_LINK =
  "steam://rungame/730/76561202255233023/+csgo_econ_action_preview " +
  "00180720910B30043D0000803E40A403620408001001620408011002620408021003620408031005A9E0DDA6";

// AK-47 | Case Hardened (paintindex 44), seed 661, Minimal Wear — a pattern skin.
const DEMO2_LINK =
  "steam://rungame/730/76561202255233023/+csgo_econ_action_preview " +
  "001807202C30043D9A99193E4095058315C48B";

let viewer;
let manifest;
let lastName = "cs2-screenshot";

function setStatus(msg, isError = false) {
  els.status.textContent = msg;
  els.status.classList.toggle("err", isError);
}

const WEAR_TIERS = [
  [0.07, "Factory New"],
  [0.15, "Minimal Wear"],
  [0.38, "Field-Tested"],
  [0.45, "Well-Worn"],
  [1.01, "Battle-Scarred"],
];
function wearName(f) {
  if (f == null) return "";
  for (const [t, n] of WEAR_TIERS) if (f < t) return n;
  return "Battle-Scarred";
}

function showInfo(decoded, skin) {
  const fv = decoded.paintwear;
  els.info.innerHTML = `
    <div class="name">${skin?.display ?? skin?.name ?? "weapon " + decoded.defindex} ${
    decoded.stattrak ? "★ StatTrak™" : ""
  }</div>
    <div><span class="dim">Float:</span> ${fv != null ? fv.toFixed(8) : "—"} ${
    fv != null ? "(" + wearName(fv) + ")" : ""
  }</div>
    <div><span class="dim">Pattern (seed):</span> ${decoded.paintseed ?? "—"}</div>
    <div><span class="dim">Paint index:</span> ${decoded.paintindex ?? "—"}</div>
    <div><span class="dim">Stickers:</span> ${
      decoded.stickers?.length ? decoded.stickers.length : "—"
    }</div>`;
}

async function ensureManifest() {
  if (!manifest) {
    const r = await fetch(`${API}/assets/manifest.json`, { cache: "no-store" });
    if (!r.ok) throw new Error("manifest.json yüklenemedi (asset extractor çalıştı mı?)");
    manifest = await r.json();
  }
  return manifest;
}

async function decodeLink(link) {
  const r = await fetch(`${API}/api/decode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inspect_link: link }),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail || `decode hatası (${r.status})`);
  }
  return r.json();
}

async function render(link) {
  try {
    els.render.disabled = true;
    setStatus("Link çözülüyor…");
    const decoded = await decodeLink(link);
    if (decoded.needs_gc_lookup) {
      throw new Error("Legacy link: tam veri için Steam bot lookup gerekir (desteklenmiyor).");
    }

    await ensureManifest();
    const weapon = manifest.weapons[String(decoded.defindex)];
    const skin = manifest.skins[String(decoded.paintindex)];
    if (!weapon) throw new Error(`Bu silah (defindex ${decoded.defindex}) henüz çıkarılmadı.`);
    if (!skin) {
      setStatus(`Bu skin (paintindex ${decoded.paintindex}) henüz çıkarılmadı — varsayılan modelle gösteriliyor.`, true);
    }

    setStatus("Model ve doku yükleniyor…");
    await viewer.loadItem({
      modelUrl: weapon.model,
      skin: skin || null,
      paintseed: decoded.paintseed ?? 0,
      paintwear: decoded.paintwear ?? 0,
      stickers: decoded.stickers || [],
      shared: manifest.shared || {},
      composite: weapon.composite || {},
    });

    showInfo(decoded, skin);
    const safe = (skin?.display ?? skin?.name ?? "weapon" + decoded.defindex).replace(/[^a-z0-9]+/gi, "_");
    lastName = `${safe}_${wearName(decoded.paintwear).replace(/\s+/g, "")}`;
    els.png.disabled = false;
    setStatus("Hazır — fareyle döndür, PNG indir.");
  } catch (err) {
    console.error(err);
    setStatus(err.message, true);
  } finally {
    els.render.disabled = false;
  }
}

function init() {
  viewer = new Viewer(document.getElementById("canvas-wrap"));
  window.__viewer = viewer; // debugging
  els.render.addEventListener("click", () => {
    const link = els.link.value.trim();
    if (link) render(link);
    else setStatus("Önce bir inspect linki yapıştır.", true);
  });
  els.demo.addEventListener("click", () => {
    els.link.value = DEMO_LINK;
    render(DEMO_LINK);
  });
  document.getElementById("demo2-btn").addEventListener("click", () => {
    els.link.value = DEMO2_LINK;
    render(DEMO2_LINK);
  });
  els.png.addEventListener("click", () => viewer.exportPNG(`${lastName}.png`));
  setStatus("Hazır — 'Demo' ile başla veya bir inspect linki yapıştır.");
}

init();
