// Builds a Three.js material for a CS2 skin.
//
// Targets "fully authored" finishes (style 9) whose paint kit ships a complete
// PBR set (color / normal / rough / metal / ao) mapped onto the weapon UVs.
//
// Wear (float) is composited the way CS2's `customweapon` shader does, using the
// real shared wear + grunge masks: paint scratches off following the paint_wear
// pattern (edges first), exposing scuffed metal, with grunge grime layered in.
// As the float rises the worn area grows and roughens.

import * as THREE from "three";

const texLoader = new THREE.TextureLoader();

function loadTexture(url, { srgb = false } = {}) {
  if (!url) return Promise.resolve(null);
  return new Promise((resolve) => {
    texLoader.load(
      url,
      (tex) => {
        tex.flipY = false; // glTF authoring convention
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

// Remap raw paintwear (0..1) through the kit's wear window, like the game does.
export function effectiveWear(paintwear, kit) {
  const lo = kit?.wear_remap_min ?? 0.0;
  const hi = kit?.wear_remap_max ?? 1.0;
  return Math.min(1, Math.max(0, lo + (hi - lo) * (paintwear ?? 0)));
}

export async function buildSkinMaterial(skin, paintwear, shared = {}) {
  const t = skin.textures || {};
  const [color, normal, rough, metal, ao, wearTex, grungeTex] = await Promise.all([
    loadTexture(t.color, { srgb: true }),
    loadTexture(t.normal),
    loadTexture(t.rough),
    loadTexture(t.metal),
    loadTexture(t.ao),
    loadTexture(shared.paint_wear),
    loadTexture(shared.grunge),
  ]);

  const mat = new THREE.MeshStandardMaterial({
    map: color,
    normalMap: normal,
    roughnessMap: rough,
    metalnessMap: metal,
    aoMap: ao,
    // Crane Flight reads bright because its metalness MAP keeps the paint areas
    // dielectric (lit by the front key). Custom paints ship no metal map, so
    // default to dielectric paint — fully metallic would make them dark.
    metalness: metal ? 1.0 : 0.0,
    roughness: 1.0,
    envMapIntensity: 1.0,
  });

  const wear = effectiveWear(paintwear, skin);
  mat.userData.wear = wear;

  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uWear = { value: wear };
    shader.uniforms.tWear = { value: wearTex };
    shader.uniforms.tGrunge = { value: grungeTex };
    shader.uniforms.uHasWear = { value: wearTex ? 1 : 0 };

    // Pass the base UV through for sampling the wear/grunge masks.
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        "#include <common>\nvarying vec2 vWearUv;",
      )
      .replace(
        "#include <uv_vertex>",
        "#include <uv_vertex>\nvWearUv = uv;",
      );

    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
         uniform float uWear;
         uniform float uHasWear;
         uniform sampler2D tWear;
         uniform sampler2D tGrunge;
         varying vec2 vWearUv;`,
      )
      .replace(
        "#include <map_fragment>",
        `#include <map_fragment>
         if (uHasWear > 0.5) {
           float pw = texture2D(tWear, vWearUv).r;      // wear resistance (edges low)
           float gr = texture2D(tGrunge, vWearUv).r;    // grime noise
           // Worn region grows with float, following the wear pattern.
           float worn = smoothstep(pw - 0.10, pw + 0.10, uWear * 1.15);
           // Exposed, scuffed metal: desaturated + darkened + grimed.
           float luma = dot(diffuseColor.rgb, vec3(0.299, 0.587, 0.114));
           vec3 metalColor = vec3(luma) * 0.32 * mix(0.65, 1.0, gr);
           diffuseColor.rgb = mix(diffuseColor.rgb, metalColor, worn);
           // Subtle overall grime as wear rises.
           diffuseColor.rgb *= mix(1.0, mix(0.82, 1.0, gr), uWear * 0.45);
           wornFactor = worn;
         }`,
      )
      .replace(
        "#include <roughnessmap_fragment>",
        `#include <roughnessmap_fragment>
         roughnessFactor = clamp(roughnessFactor + wornFactor * 0.5, 0.0, 1.0);`,
      );

    // `wornFactor` is shared between map and roughness chunks.
    shader.fragmentShader = shader.fragmentShader.replace(
      "void main() {",
      "void main() {\n\tfloat wornFactor = 0.0;",
    );

    mat.userData.shader = shader;
  };

  return mat;
}
