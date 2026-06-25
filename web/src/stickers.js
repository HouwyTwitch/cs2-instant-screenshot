// Projects sticker images onto the weapon as decals.
//
// NOTE: precise per-slot placement requires the weapon's sticker-slot UV data
// (from the model's sticker mask / attachments), which we have not mapped to
// world space yet.  For the vertical slice we place decals at approximate
// positions along the receiver on the side facing the camera.  This proves the
// decal + proxy pipeline; exact placement is a follow-up.

import * as THREE from "three";
import { DecalGeometry } from "three/addons/geometries/DecalGeometry.js";

const texLoader = new THREE.TextureLoader();

// Route remote sticker images through our same-origin proxy so the WebGL canvas
// stays untainted (otherwise toDataURL / PNG export throws).
function proxied(url) {
  if (!url) return null;
  if (url.startsWith("/")) return url;
  return `/api/proxy?url=${encodeURIComponent(url)}`;
}

function loadTexture(url) {
  return new Promise((resolve) => {
    texLoader.load(
      url,
      (t) => {
        t.colorSpace = THREE.SRGBColorSpace;
        resolve(t);
      },
      undefined,
      () => resolve(null),
    );
  });
}

// Pick the largest mesh as the decal receiver (the weapon body).
function pickReceiver(root) {
  let best = null;
  let bestVol = -1;
  root.traverse((n) => {
    if (!n.isMesh || !n.visible) return;
    const b = new THREE.Box3().setFromObject(n);
    const s = b.getSize(new THREE.Vector3());
    const vol = s.x * s.y * s.z;
    if (vol > bestVol) {
      bestVol = vol;
      best = n;
    }
  });
  return best;
}

// `parent` is the world-space container the decals are added to (the scene),
// while `root` is the (transformed) model used to find the receiver mesh.
export async function applyStickers(parent, root, stickers) {
  const list = (stickers || []).filter((s) => s.image);
  if (!list.length) return [];

  root.updateMatrixWorld(true);
  const receiver = pickReceiver(root);
  if (!receiver) return [];

  const box = new THREE.Box3().setFromObject(receiver);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());

  // Lay slots along the weapon length (X). Slot 0 nearest the magazine/grip.
  // Stickers occupy the central receiver band, evenly spaced and discrete.
  const span = size.x * 0.62;
  const decals = [];
  const dim = size.y * 0.34; // discrete sticker size (not a full-body wrap)

  for (const s of list) {
    const tex = await loadTexture(proxied(s.image));
    if (!tex) continue;

    const slot = s.slot ?? 0;
    const t = list.length > 1 ? slot / (list.length - 1) : 0.5; // 0..1 along body
    const px = center.x - span / 2 + span * t;
    const position = new THREE.Vector3(px, center.y + size.y * 0.1, center.z + size.z / 2);

    // Project straight onto the camera-facing side; shallow depth so the decal
    // only wraps the near face rather than the whole receiver thickness.
    const orientation = new THREE.Euler(0, 0, 0);
    const decalSize = new THREE.Vector3(dim, dim, size.z * 0.9);

    const geo = new DecalGeometry(receiver, position, orientation, decalSize);
    const mat = new THREE.MeshStandardMaterial({
      map: tex,
      transparent: true,
      side: THREE.DoubleSide,
      depthTest: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -8,
      polygonOffsetUnits: -8,
      roughness: 0.6,
      opacity: Math.max(0.25, 1 - (s.wear || 0)),
    });
    const mesh = new THREE.Mesh(geo, mat);
    parent.add(mesh);
    decals.push(mesh);
  }
  return decals;
}
