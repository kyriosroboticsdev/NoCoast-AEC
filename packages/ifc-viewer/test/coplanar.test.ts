import { describe, expect, it } from "vitest";
import { biasGridFragment, preferGridOverFloor } from "../src/core/coplanar";

function material(line = false) {
  return {
    polygonOffset: false,
    polygonOffsetFactor: 0,
    polygonOffsetUnits: 0,
    depthTest: false,
    depthWrite: true,
    isLineBasicMaterial: line,
    onBeforeCompile(_shader: { fragmentShader: string }, _renderer: unknown) {},
  };
}

const LINE_SHADER = "void main() {\n\t#include <dithering_fragment>\n}\n";

describe("coplanar grid and floor", () => {
  it("pulls a filled grid toward the camera so lines beat the floor", () => {
    const grid = material();
    preferGridOverFloor(grid);
    expect(grid.polygonOffset).toBe(true);
    expect(grid.polygonOffsetFactor).toBeLessThan(0);
    expect(grid.polygonOffsetUnits).toBeLessThan(0);
    expect(grid.depthTest).toBe(true);
    const shader = { fragmentShader: LINE_SHADER };
    grid.onBeforeCompile(shader, undefined);
    expect(shader.fragmentShader).toBe(LINE_SHADER);
  });

  it("biases line grids in the shader because WebGL does not offset lines", () => {
    const grid = material(true);
    preferGridOverFloor(grid);
    const shader = { fragmentShader: LINE_SHADER };
    grid.onBeforeCompile(shader, undefined);
    expect(shader.fragmentShader).toContain("gl_FragCoord.z - gridSlope * 2.0");
    expect(shader.fragmentShader).toContain("gl_FragDepth");
    grid.onBeforeCompile(shader, undefined);
    expect(shader.fragmentShader.match(/float gridSlope/g)).toHaveLength(1);
  });

  it("leaves a custom grid shader untouched when it has no three.js fragment hook", () => {
    const source = "void main() { gl_FragColor = vec4(1.0); }";
    expect(biasGridFragment(source)).toBe(source);
  });

  it("applies the same precedence to every material on the grid", () => {
    const a = material();
    const b = material();
    preferGridOverFloor([a, b]);
    expect(a.polygonOffsetFactor).toBeLessThan(0);
    expect(b.polygonOffsetFactor).toBeLessThan(0);
  });
});
