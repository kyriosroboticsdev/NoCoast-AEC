/**
 * Depth precedence for a floor and a grid that share one plane.
 *
 * Grid lines must stay readable on top; the floor shows in the gaps. A world-space
 * gap big enough to survive the depth buffer reads as the grid floating, and a gap
 * small enough to hide still swaps which surface wins as the camera moves.
 *
 * Filled line-only grids use polygonOffset, which WebGL applies to triangles: the
 * turn-card grid discards the gaps, so the whole drawn surface is the lines.
 * A grid that also paints the floor fill in the same shader cannot use one
 * offset for both, so that shader writes gl_FragDepth per pixel instead.
 * Line primitives ignore polygonOffset, so those emulate the same bias here:
 * two pixels of depth slope, plus a few depth-buffer steps toward the camera.
 * Window z is smaller when closer (three.js default depth).
 */

const GRID_LINE_DEPTH_BIAS = `
#ifndef USE_LOGARITHMIC_DEPTH_BUFFER
	float gridSlope = max(abs(dFdx(gl_FragCoord.z)), abs(dFdy(gl_FragCoord.z)));
	gl_FragDepth = clamp(gl_FragCoord.z - gridSlope * 2.0 - 16.0 / 16777216.0, 0.0, 1.0);
#endif
`;

type CoplanarMaterial = {
  polygonOffset: boolean;
  polygonOffsetFactor: number;
  polygonOffsetUnits: number;
  depthTest: boolean;
  depthWrite?: boolean;
  isLineBasicMaterial?: boolean;
  isLineMaterial?: boolean;
  onBeforeCompile: (shader: { fragmentShader: string }, renderer: unknown) => void;
};

function asMaterial(material: object): CoplanarMaterial {
  return material as CoplanarMaterial;
}

/** Insert the line-grid depth bias once. Shaders without three's fragment hook are left alone. */
export function biasGridFragment(fragmentShader: string): string {
  if (fragmentShader.includes("gridSlope")) return fragmentShader;
  const hook = "#include <dithering_fragment>";
  if (!fragmentShader.includes(hook)) return fragmentShader;
  return fragmentShader.replace(hook, `${hook}\n${GRID_LINE_DEPTH_BIAS}`);
}

/** Grid wins the depth test against a coplanar floor. Gaps are whatever was drawn under the lines. */
export function preferGridOverFloor(material: object | object[]): void {
  for (const entry of Array.isArray(material) ? material : [material]) {
    const mat = asMaterial(entry);
    mat.polygonOffset = true;
    mat.polygonOffsetFactor = -2;
    mat.polygonOffsetUnits = -4;
    mat.depthTest = true;
    if (mat.isLineBasicMaterial !== true && mat.isLineMaterial !== true) continue;
    const previous = mat.onBeforeCompile;
    mat.onBeforeCompile = (shader, renderer) => {
      previous(shader, renderer);
      shader.fragmentShader = biasGridFragment(shader.fragmentShader);
    };
  }
}
