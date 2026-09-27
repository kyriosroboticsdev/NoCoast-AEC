// Ground reference for the editor viewer. Replaces the fixed GridHelper(60, 60)
// and the 200 m ground quad: one camera-following plane, grid lines in world
// space, so the spacing stays on the origin while the surface has no edge.
import * as THREE from "three";

/** Metres between lines — GridHelper(60, 60) was 60 / 60. */
export const GRID_SPACING = 1;
const AXIS = new THREE.Color(0x333844);
const LINE = new THREE.Color(0x22252d);
const GROUND = new THREE.Color(0x0b0d12);
// Ground-floor slab top is storey elevation 0. Sharing that plane avoids a gap that
// still z-fights once the camera is far enough for 2 cm to fall inside one depth step.
const GROUND_Y = 0;
const GROUND_OPACITY = 0.75;

/**
 * Quad half-size and where the lines fade, both in metres, for a perspective `far`.
 * Lines stay solid well past the old 30 m half-size, then fade inside the far clip.
 * The quad is larger than that clip, so the ground plane never draws its own edge.
 */
export function gridCover(far: number): { extent: number; fadeStart: number; fadeEnd: number } {
  const safeFar = Number.isFinite(far) && far > 1 ? far : 2000;
  const fadeEnd = safeFar * 0.92;
  const fadeStart = Math.min(120, fadeEnd * 0.5);
  return { extent: safeFar * 1.5, fadeStart, fadeEnd };
}

const vertexShader = /* glsl */`
#include <common>
#include <clipping_planes_pars_vertex>
uniform float uExtent;
varying vec2 vLocal;
void main() {
  vec3 pos = position.xzy * uExtent;
  vLocal = pos.xz;
  pos.xz += cameraPosition.xz;
  pos.y = ${GROUND_Y.toFixed(2)};
  vec4 mvPosition = viewMatrix * vec4(pos, 1.0);
  gl_Position = projectionMatrix * mvPosition;
  #include <clipping_planes_vertex>
}
`;

const fragmentShader = /* glsl */`
#include <common>
#include <clipping_planes_pars_fragment>
uniform vec3 uGround;
uniform vec3 uLineColor;
uniform vec3 uAxisColor;
uniform float uSpacing;
uniform float uFadeStart;
uniform float uFadeEnd;
uniform float uOpacity;
varying vec2 vLocal;
void main() {
  #include <clipping_planes_fragment>
  vec2 fw = max(fwidth(vLocal), vec2(1e-4));
  vec2 phase = vLocal / uSpacing + mod(cameraPosition.xz, uSpacing);
  vec2 g = abs(fract(phase - 0.5) - 0.5) / max(fwidth(phase), vec2(1e-4));
  float minor = 1.0 - min(min(g.x, g.y), 1.0);
  vec2 world = vLocal + cameraPosition.xz;
  float axis = max(
    1.0 - min(abs(world.x) / fw.x, 1.0),
    1.0 - min(abs(world.y) / fw.y, 1.0)
  );
  float density = 1.0 - smoothstep(uSpacing * 0.45, uSpacing * 1.15, max(fw.x, fw.y));
  float cover = 1.0 - smoothstep(uFadeStart, uFadeEnd, length(vLocal));
  float line = max(minor, axis) * density * cover;
  vec3 color = mix(uGround, mix(uLineColor, uAxisColor, axis), line);
  float alpha = mix(uOpacity, 1.0, line);
  if (alpha < 0.001) discard;
  gl_FragColor = vec4(color, alpha);
  // Lines toward the camera, fill away from it. Window z is smaller when closer.
  // The floor slab then loses to the lines and wins the gaps, at every zoom.
  float gridSlope = max(abs(dFdx(gl_FragCoord.z)), abs(dFdy(gl_FragCoord.z)));
  float gridBias = gridSlope * 2.0 + 16.0 / 16777216.0;
  gl_FragDepth = clamp(gl_FragCoord.z + (line >= 0.5 ? -gridBias : gridBias), 0.0, 1.0);
  #include <colorspace_fragment>
}
`;

/** Infinite ground grid. The mesh transform must stay identity: the shader places it. */
export function createBaseGrid(clipPlane: THREE.Plane): THREE.Mesh {
  const cover = gridCover(2000);
  const uniforms = {
    uExtent: { value: cover.extent },
    uGround: { value: GROUND },
    uLineColor: { value: LINE },
    uAxisColor: { value: AXIS },
    uSpacing: { value: GRID_SPACING },
    uFadeStart: { value: cover.fadeStart },
    uFadeEnd: { value: cover.fadeEnd },
    uOpacity: { value: GROUND_OPACITY },
  };
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader,
    fragmentShader,
    transparent: true,
    depthTest: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    clipping: true,
    clippingPlanes: [clipPlane],
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  mesh.name = "base-grid";
  mesh.frustumCulled = false;
  // After opaque floors, so the depth bias can keep lines and reject the fill.
  // Drawn earlier, the slab would paint over the lines.
  mesh.renderOrder = 1;
  mesh.matrixAutoUpdate = false;
  mesh.onBeforeRender = (_renderer, _scene, camera) => {
    const next = gridCover((camera as THREE.PerspectiveCamera).far);
    uniforms.uExtent.value = next.extent;
    uniforms.uFadeStart.value = next.fadeStart;
    uniforms.uFadeEnd.value = next.fadeEnd;
  };
  return mesh;
}
