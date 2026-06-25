// Builds a material for "pattern" finishes (Case Hardened, Fade, …) — the CS2
// `csgo_customweapon` style where a pattern texture is positioned by the paint
// seed and composited onto the weapon's composite inputs (base color + paint
// mask), then worn.
//
// b1 scope: the pattern is placed by a seed-derived rotation/offset/scale so
// different seeds visibly change the look, sampled in the model UV and masked to
// the painted regions. Exact Valve seed parity + the weapon-space position map
// (`_pos`) + cavity edge wear are b2.

import * as THREE from "three";
import { effectiveWear } from "./paintMaterial.js?v=b13";

const texLoader = new THREE.TextureLoader();

function loadTexture(url, { srgb = false } = {}) {
  if (!url) return Promise.resolve(null);
  return new Promise((resolve) => {
    texLoader.load(
      url,
      (tex) => {
        tex.flipY = false;
        tex.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        tex.anisotropy = 8;
        tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
        resolve(tex);
      },
      undefined,
      () => resolve(null),
    );
  });
}

// Deterministic pseudo-random transform from the paint seed (b1 approximation).
function seedTransform(seed) {
  const rnd = (n) => {
    const x = Math.sin((seed + 1) * 12.9898 + n * 78.233) * 43758.5453;
    return x - Math.floor(x);
  };
  return {
    rot: rnd(1) * Math.PI * 2,
    offset: new THREE.Vector2(rnd(2), rnd(3)),
    scale: 0.85 + rnd(4) * 0.5,
  };
}

// Custom paint overlay: instead of building a material from scratch (which would
// need the base color + paint mask on the right UV — they're HD-only, but most
// skins render on the legacy body), we keep each body mesh's OWN material (its
// correct base color on the correct UV) and overlay the pattern on top. The
// pattern is authored for that same UV, and its alpha encodes paint coverage —
// so the base (wood furniture / bare metal) shows where the skin isn't painted.
export async function applyCustomPaint(meshes, skin, paintwear, shared = {}) {
  const [pattern, wearTex, grungeTex] = await Promise.all([
    loadTexture(skin.pattern, { srgb: true }),
    loadTexture(shared.paint_wear),
    loadTexture(shared.grunge),
  ]);
  if (!pattern) return;
  const wear = effectiveWear(paintwear, skin);
  const brightness = skin.color_brightness ?? 1.0;

  for (const node of meshes) {
    const mat = node.material;
    mat.userData.wear = wear;
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uWear = { value: wear };
      shader.uniforms.uBrightness = { value: brightness };
      shader.uniforms.tPattern = { value: pattern };
      shader.uniforms.tWear = { value: wearTex };
      shader.uniforms.tGrunge = { value: grungeTex };

      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", "#include <common>\nvarying vec2 vSkinUv;")
        .replace("#include <uv_vertex>", "#include <uv_vertex>\nvSkinUv = uv;");

      shader.fragmentShader = shader.fragmentShader
        .replace(
          "#include <common>",
          `#include <common>
           uniform float uWear, uBrightness;
           uniform sampler2D tPattern, tWear, tGrunge;
           varying vec2 vSkinUv;`,
        )
        .replace(
          "#include <map_fragment>",
          `#include <map_fragment>
           {
             // diffuseColor is now the mesh's own base (wood + metal, right UV).
             vec4 pat = texture2D(tPattern, vSkinUv);
             // Alpha encodes paint coverage; base shows where there's no paint.
             float cover = smoothstep(0.72, 0.96, pat.a);
             vec3 paintCol = pat.rgb * uBrightness;
             // Wear: paint scratches off (following the wear pattern) toward metal.
             float pw = texture2D(tWear, vSkinUv).r;
             float gr = texture2D(tGrunge, vSkinUv).r;
             float worn = smoothstep(pw - 0.10, pw + 0.10, uWear * 1.15) * cover;
             float luma = dot(paintCol, vec3(0.299, 0.587, 0.114));
             vec3 metalCol = vec3(luma) * 0.32 * mix(0.6, 1.0, gr);
             paintCol = mix(paintCol, metalCol, worn);
             diffuseColor.rgb = mix(diffuseColor.rgb, paintCol, cover);
           }`,
        );
      mat.userData.shader = shader;
    };
    mat.needsUpdate = true;
  }
}

export async function buildPatternMaterial(skin, paintseed, paintwear, composite, shared = {}) {
  const c = composite || {};
  const [base, masks, ao, normal, rough, pattern, wearTex, grungeTex] = await Promise.all([
    loadTexture(c.base_color, { srgb: true }),
    loadTexture(c.masks),
    loadTexture(c.ao),
    loadTexture(c.normal),
    loadTexture(c.rough),
    loadTexture(skin.pattern, { srgb: true }),
    loadTexture(shared.paint_wear),
    loadTexture(shared.grunge),
  ]);

  // map = the weapon's base (wood furniture + metal). The pattern is composited
  // over it via the paint mask; metalness/roughness are driven per-region in the
  // shader. We deliberately skip the AK normal/rough/ao maps here because they
  // are HD-UV and most pattern skins render on the legacy body (wrong UV).
  const mat = new THREE.MeshStandardMaterial({
    map: base,
    metalness: 1.0,
    roughness: 0.5,
    envMapIntensity: 1.6,
  });

  const wear = effectiveWear(paintwear, skin);
  const tf = seedTransform(paintseed ?? 0);
  mat.userData.wear = wear;
  mat.userData.seedTransform = tf;

  // Custom-paint finishes (Asiimov, Anubis, …) map the pattern 1:1 onto the UV;
  // only anodized/antiqued finishes (Case Hardened, Fade, Doppler) randomize the
  // pattern by the paint seed.
  const seeded = skin.seeded ? 1 : 0;

  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uWear = { value: wear };
    shader.uniforms.uBrightness = { value: skin.color_brightness ?? 1.0 };
    shader.uniforms.uSeeded = { value: seeded };
    shader.uniforms.uSeedRot = { value: tf.rot };
    shader.uniforms.uSeedOffset = { value: tf.offset };
    shader.uniforms.uSeedScale = { value: tf.scale };
    shader.uniforms.tPattern = { value: pattern };
    shader.uniforms.tMasks = { value: masks };
    shader.uniforms.tWear = { value: wearTex };
    shader.uniforms.tGrunge = { value: grungeTex };
    shader.uniforms.uHasPattern = { value: pattern ? 1 : 0 };

    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec2 vSkinUv;")
      .replace("#include <uv_vertex>", "#include <uv_vertex>\nvSkinUv = uv;");

    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
         uniform float uWear, uBrightness, uSeedRot, uSeedScale, uHasPattern, uSeeded;
         uniform vec2 uSeedOffset;
         uniform sampler2D tPattern, tMasks, tWear, tGrunge;
         varying vec2 vSkinUv;`,
      )
      .replace(
        "#include <map_fragment>",
        `#include <map_fragment>
         if (uHasPattern > 0.5) {
           // Paint mask: where the finish applies (metal); 0 leaves the base
           // (wood furniture / bare metal) showing through.
           float pm = texture2D(tMasks, vSkinUv).r;
           // Custom paint maps 1:1 to UV; anodized/antiqued randomizes by seed.
           vec2 patUv = vSkinUv;
           if (uSeeded > 0.5) {
             vec2 p = vSkinUv - 0.5;
             float cs = cos(uSeedRot), sn = sin(uSeedRot);
             p = mat2(cs, -sn, sn, cs) * p;
             patUv = p * uSeedScale + 0.5 + uSeedOffset;
           }
           vec3 patternColor = texture2D(tPattern, patUv).rgb * uBrightness;
           // Wear: paint scratches off following the wear pattern, exposing metal.
           float pw = texture2D(tWear, vSkinUv).r;
           float gr = texture2D(tGrunge, vSkinUv).r;
           float worn = smoothstep(pw - 0.10, pw + 0.10, uWear * 1.15);
           float luma = dot(patternColor, vec3(0.299, 0.587, 0.114));
           vec3 metalColor = vec3(luma) * 0.30 * mix(0.65, 1.0, gr);
           vec3 painted = mix(patternColor, metalColor, worn);
           // Composite the finish over the base where the mask says it is painted.
           diffuseColor.rgb = mix(diffuseColor.rgb, painted, pm);
           vPaintMask = pm;
           wornFactor = worn * pm;
         }`,
      )
      .replace(
        "#include <metalnessmap_fragment>",
        `#include <metalnessmap_fragment>
         if (uHasPattern > 0.5) {
           // Painted metal is metallic; unpainted base (wood) is dielectric.
           metalnessFactor = max(vPaintMask, wornFactor);
         }`,
      )
      .replace(
        "#include <roughnessmap_fragment>",
        `#include <roughnessmap_fragment>
         if (uHasPattern > 0.5) {
           // Semi-gloss paint (~0.38), matte base, rougher where worn.
           roughnessFactor = clamp(mix(0.78, 0.38, vPaintMask) + wornFactor * 0.45, 0.05, 1.0);
         }`,
      )
      .replace(
        "void main() {",
        "void main() {\n\tfloat wornFactor = 0.0;\n\tfloat vPaintMask = 0.0;",
      );

    mat.userData.shader = shader;
  };

  return mat;
}
