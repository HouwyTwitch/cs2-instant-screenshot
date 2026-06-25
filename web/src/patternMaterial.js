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
import { effectiveWear } from "./paintMaterial.js?v=b11";

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

  const mat = new THREE.MeshStandardMaterial({
    map: base,
    normalMap: normal,
    roughnessMap: rough,
    aoMap: ao,
    metalness: 0.85,
    roughness: 0.9,
    envMapIntensity: 1.0,
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
           // Custom paint covers the whole weapon (the pattern IS the albedo);
           // anodized/antiqued paints only the masked (metal) regions.
           float paintMask = mix(1.0, texture2D(tMasks, vSkinUv).r, uSeeded);
           // Custom paint maps 1:1 to UV; anodized/antiqued randomizes by seed.
           vec2 patUv = vSkinUv;
           if (uSeeded > 0.5) {
             vec2 p = vSkinUv - 0.5;
             float cs = cos(uSeedRot), sn = sin(uSeedRot);
             p = mat2(cs, -sn, sn, cs) * p;
             patUv = p * uSeedScale + 0.5 + uSeedOffset;
           }
           vec3 patternColor = texture2D(tPattern, patUv).rgb * uBrightness;
           // Composite the finish onto the painted regions.
           vec3 painted = patternColor;
           // Wear within painted regions, following the wear pattern.
           float pw = texture2D(tWear, vSkinUv).r;
           float gr = texture2D(tGrunge, vSkinUv).r;
           float worn = smoothstep(pw - 0.10, pw + 0.10, uWear * 1.15);
           float luma = dot(painted, vec3(0.299, 0.587, 0.114));
           vec3 metalColor = vec3(luma) * 0.30 * mix(0.65, 1.0, gr);
           painted = mix(painted, metalColor, worn);
           diffuseColor.rgb = mix(diffuseColor.rgb, painted, paintMask);
           wornFactor = worn * paintMask;
         }`,
      )
      .replace(
        "#include <roughnessmap_fragment>",
        `#include <roughnessmap_fragment>
         roughnessFactor = clamp(roughnessFactor - 0.35 + wornFactor * 0.7, 0.05, 1.0);`,
      )
      .replace(
        "void main() {",
        "void main() {\n\tfloat wornFactor = 0.0;",
      );

    mat.userData.shader = shader;
  };

  return mat;
}
