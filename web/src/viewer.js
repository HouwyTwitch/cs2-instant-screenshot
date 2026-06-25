// Three.js viewport: loads the weapon GLB, applies the skin material, frames
// the weapon in an inspect-style pose, and exports PNG screenshots.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { buildSkinMaterial } from "./paintMaterial.js?v=b11";
import { buildPatternMaterial } from "./patternMaterial.js?v=b11";
import { applyStickers } from "./stickers.js?v=b11";

export class Viewer {
  constructor(container) {
    this.container = container;

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true, // required for canvas.toDataURL screenshots
      alpha: true,
    });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.35;
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();

    // CS2 weapon finishes are largely metallic, so their brightness comes from
    // environment reflections. A bright neutral studio gradient (rather than the
    // dim RoomEnvironment) keeps metallic skins from rendering dark.
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromEquirectangular(this._studioEnvTexture()).texture;

    this.camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
    this.camera.position.set(0.0, 0.12, 0.6);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;

    // Studio-style lighting tuned so dark finishes (Fire Serpent, etc.) read well.
    // Hemisphere gives even ambient fill; a strong front key + soft fill + rim.
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x666a72, 1.6));

    const key = new THREE.DirectionalLight(0xffffff, 3.2); // front-top-right
    key.position.set(0.6, 1.2, 1.6);
    this.scene.add(key);

    const fill = new THREE.DirectionalLight(0xffffff, 1.6); // front-left, soft
    fill.position.set(-1.5, 0.2, 1.0);
    this.scene.add(fill);

    const rim = new THREE.DirectionalLight(0xffffff, 2.0); // behind, edge highlight
    rim.position.set(-0.5, 0.9, -1.6);
    this.scene.add(rim);

    const under = new THREE.DirectionalLight(0xffffff, 0.5); // gentle bounce from below
    under.position.set(0.2, -1.0, 0.6);
    this.scene.add(under);

    this.loader = new GLTFLoader();
    this.current = null;

    this._resize = this._resize.bind(this);
    window.addEventListener("resize", this._resize);
    this._resize();
    this._animate();
  }

  // A bright neutral studio gradient used as the reflection environment.
  _studioEnvTexture() {
    const c = document.createElement("canvas");
    c.width = 32;
    c.height = 128;
    const ctx = c.getContext("2d");
    const g = ctx.createLinearGradient(0, 0, 0, 128);
    g.addColorStop(0.0, "#ffffff"); // bright sky
    g.addColorStop(0.45, "#e7ecf2");
    g.addColorStop(0.55, "#cdd4dc"); // horizon
    g.addColorStop(1.0, "#8b9098"); // floor
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 32, 128);
    const tex = new THREE.CanvasTexture(c);
    tex.mapping = THREE.EquirectangularReflectionMapping;
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  _resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / Math.max(1, h);
    this.camera.updateProjectionMatrix();
  }

  _animate() {
    requestAnimationFrame(() => this._animate());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  // Orient the weapon so its longest axis is horizontal (along world X).
  // CS2 view models come in with varying up-axes; this normalizes the pose.
  _orient(object) {
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3());
    const longest = Math.max(size.x, size.y, size.z);
    if (longest === size.y) {
      object.rotation.z = -Math.PI / 2; // Y (up) -> X
    } else if (longest === size.z) {
      object.rotation.y = Math.PI / 2; // Z (depth) -> X
    }
    object.updateMatrixWorld(true);
  }

  // Frame the weapon: recenter to origin and fit the camera to its bounds.
  _frame(object) {
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    object.position.sub(center); // recenter at origin

    // Fit the longest on-screen extent accounting for aspect ratio.
    const maxDim = Math.max(size.x, size.y, size.z);
    const fov = (this.camera.fov * Math.PI) / 180;
    const fitH = maxDim / (2 * Math.tan(fov / 2));
    const fitW = fitH / Math.min(1, this.camera.aspect);
    const dist = Math.max(fitH, fitW) * 0.62; // fill most of the frame

    // 3/4 inspect view: slightly above, slightly to the side.
    this.camera.position.set(dist * 0.25, dist * 0.45, dist * 0.95);
    this.camera.near = maxDim / 100;
    this.camera.far = maxDim * 100;
    this.camera.updateProjectionMatrix();
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  async loadItem({ modelUrl, skin, paintseed, paintwear, stickers, shared, composite }) {
    if (this.current) {
      this.scene.remove(this.current);
      this.current = null;
    }
    for (const d of this.decals || []) this.scene.remove(d);
    this.decals = [];

    const gltf = await this.loader.loadAsync(modelUrl);
    const root = gltf.scene;

    let material = null;
    if (skin && skin.kind === "pattern" && skin.seeded) {
      // Anodized/antiqued (Case Hardened, Fade, …): pattern is composited onto
      // the masked metal regions and positioned by the paint seed.
      material = await buildPatternMaterial(skin, paintseed, paintwear, composite, shared);
    } else if (skin && skin.kind === "pattern") {
      // Custom paint (Asiimov, Fire Serpent, …): the pattern IS the full albedo.
      // It's authored for whichever body the finish targets (legacy vs HD), so we
      // only feed the pattern as the color map — the HD composite normal/ao would
      // be on the wrong UV for legacy skins. Constant semi-gloss (g_flPaintRoughness).
      const bakedSkin = { ...skin, textures: { color: skin.pattern } };
      material = await buildSkinMaterial(bakedSkin, paintwear, shared);
    } else if (skin) {
      material = await buildSkinMaterial(skin, paintwear, shared);
    }

    // CS2 weapon GLBs ship BOTH a "legacy" (CS:GO-era UV) and an "hd" body that
    // overlap. A finish targets exactly one — picked by the kit's use_legacy_model
    // flag. Rendering both, or mapping an HD-authored finish onto legacy UVs,
    // produces a scrambled skin, so we keep only the matching body.
    // Respect each finish's target body: most older skins are authored for the
    // legacy body (use_legacy_model=1); newer ones (Crane Flight) for HD.
    const useLegacy = !!(skin && skin.legacy);
    root.traverse((node) => {
      if (!node.isMesh) return;
      const name = (node.name || "").toLowerCase();
      const isLegacy = name.includes("legacy");
      const isHd = name.includes("_hd");
      // If the mesh is tagged legacy/hd, keep only the matching variant.
      if ((isLegacy || isHd) && isLegacy !== useLegacy) {
        node.visible = false;
        return;
      }
      // Ensure aoMap has a UV set (glTF aoMap reads uv2 / channel 1).
      const geo = node.geometry;
      if (geo && geo.attributes.uv && !geo.attributes.uv2) {
        geo.setAttribute("uv2", geo.attributes.uv);
      }
      if (material) node.material = material;
    });

    this.scene.add(root);
    this._orient(root);
    this._frame(root);
    this.current = root;

    if (stickers && stickers.length) {
      this.decals = await applyStickers(this.scene, root, stickers);
    }
    return root;
  }

  // Render at a fixed high resolution (independent of the viewport) and download.
  exportPNG(filename = "cs2-screenshot.png", width = 1920, height = 1080) {
    const oldSize = this.renderer.getSize(new THREE.Vector2());
    const oldRatio = this.renderer.getPixelRatio();
    const oldAspect = this.camera.aspect;

    this.renderer.setPixelRatio(1);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();

    this.renderer.render(this.scene, this.camera);
    const url = this.renderer.domElement.toDataURL("image/png");

    // Restore the interactive viewport.
    this.renderer.setPixelRatio(oldRatio);
    this.renderer.setSize(oldSize.x, oldSize.y, false);
    this.camera.aspect = oldAspect;
    this.camera.updateProjectionMatrix();

    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  }
}
